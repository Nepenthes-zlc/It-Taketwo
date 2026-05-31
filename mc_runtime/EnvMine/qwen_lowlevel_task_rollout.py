#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import json
import math
import random
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from envmine.config import load_instance_config
from envmine.runner import InstanceRunner
from qwen_constructscene_task_test import extract_first_json_object, game_cmd


ROOT = Path(__file__).resolve().parent
WORKSPACE = ROOT.parents[1]
DEFAULT_TASKS = WORKSPACE / "ConstructScene" / "generated" / "generated_tasks.json"
DEFAULT_PACK_SRC = WORKSPACE / "ConstructScene" / "generated" / "datapacks" / "multiagent_scene_pack"
DEFAULT_PACK_DST = Path(
    ROOT / "envs" / "qwen-batch-1" / "run" / "saves" / "New World" / "datapacks" / "multiagent_scene_pack"
)
DEFAULT_CONFIG = ROOT / "configs" / "single_tickgate.json"
DEFAULT_LOG_DIR = ROOT / "logs"

ACTION_TO_PUPPET = {
    "wait": "stop",
    "forward": "w 0.12",
    "backward": "s 0.12",
    "strafe_left": "a 0.12",
    "strafe_right": "d 0.12",
    "jump": "jump 0.2",
    "turn_left": "turn -20 0 0.1",
    "turn_right": "turn 20 0 0.1",
    "look_up": "turn 0 -15 0.1",
    "look_down": "turn 0 15 0.1",
}
ALLOWED_ACTIONS = list(ACTION_TO_PUPPET)
DEFAULT_POV_EYE_HEIGHT = 1.35
DEFAULT_POV_FORWARD_OFFSET = 0.0
PLAYER_HALF_WIDTH = 0.3
SECOND_ROOM_ENTRY_DEPTH = 1.0


def data_url(png_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def second_room_entry_goal(task: dict[str, Any]) -> dict[str, Any]:
    region = task["players"]["player_b"]["goal"]["target_region"]
    start_pos = task["players"]["player_b"]["start_pos"]
    center_x = (float(region[0]) + float(region[3])) / 2.0 + 0.5
    center_z = (float(region[2]) + float(region[5])) / 2.0 + 0.5
    if int(region[2]) == int(region[5]):
        axis = "z"
        door_coord = float(region[2])
        direction = 1.0 if float(start_pos[2]) <= door_coord else -1.0
        center_z = door_coord + 0.5 + direction * SECOND_ROOM_ENTRY_DEPTH
    elif int(region[0]) == int(region[3]):
        axis = "x"
        door_coord = float(region[0])
        direction = 1.0 if float(start_pos[0]) <= door_coord else -1.0
        center_x = door_coord + 0.5 + direction * SECOND_ROOM_ENTRY_DEPTH
    else:
        axis = "unknown"
        door_coord = 0.0
        direction = 0.0
    return {
        "axis": axis,
        "door_coord": door_coord,
        "direction": direction,
        "target_center": [center_x, float(region[1]), center_z],
    }


def agent_fully_inside_second_room(task: dict[str, Any], pose: dict[str, Any]) -> bool:
    pos = pose.get("pos") if isinstance(pose, dict) else None
    if not isinstance(pos, list) or len(pos) < 3:
        return False
    goal = second_room_entry_goal(task)
    axis = goal["axis"]
    direction = float(goal["direction"])
    if axis not in {"x", "z"} or direction == 0.0:
        return False
    coord_index = 0 if axis == "x" else 2
    coord = float(pos[coord_index])
    door_coord = float(goal["door_coord"])
    interior_boundary = door_coord + 1.0 if direction > 0 else door_coord
    if direction > 0:
        return coord - PLAYER_HALF_WIDTH >= interior_boundary
    return coord + PLAYER_HALF_WIDTH <= interior_boundary


def randomized_reset_pose(base_pos: list[float], rng: random.Random, args: argparse.Namespace) -> tuple[list[float], float, float]:
    x_jitter = rng.uniform(-args.start_position_jitter, args.start_position_jitter)
    z_jitter = rng.uniform(-args.start_position_jitter, args.start_position_jitter)
    yaw = rng.uniform(-args.start_yaw_jitter, args.start_yaw_jitter)
    return [float(base_pos[0]) + x_jitter, float(base_pos[1]), float(base_pos[2]) + z_jitter], yaw, 0.0


def query_agent_pose(runner: InstanceRunner, agent: str) -> dict[str, Any]:
    if runner.puppet is None:
        raise RuntimeError("Puppet is not connected")
    def parse_entity_line(raw_text: str) -> dict[str, Any] | None:
        for line in raw_text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 8 and parts[0] == "ENTITY" and parts[1].lower() == agent.lower():
                return {
                    "agent": agent,
                    "type": parts[2],
                    "pos": [float(parts[3]), float(parts[4]), float(parts[5])],
                    "yaw": float(parts[6]),
                    "pitch": float(parts[7]),
                    "raw": line.strip(),
                }
        return None

    runner.puppet.sock.settimeout(1.0)
    runner.puppet.sock.sendall((f"query_entity {agent}\n").encode("utf-8"))
    if runner.tickgate is not None:
        runner.tickgate.cmd("advance_wait 3 1", timeout=30.0)
    chunks: list[str] = []
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            data = runner.puppet.sock.recv(4096)
        except TimeoutError:
            if runner.tickgate is not None:
                runner.tickgate.cmd("advance_wait 3 1", timeout=30.0)
            continue
        if not data:
            break
        chunks.append(data.decode("utf-8", "ignore"))
        parsed = parse_entity_line("".join(chunks))
        if parsed is not None:
            return parsed
    raw = "".join(chunks).strip()
    return {"agent": agent, "error": raw}


def write_video(frames_dir: Path, output: Path, fps: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            str(frames_dir / "rollout_frame_%03d.png"),
            "-vf",
            "format=yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def camera_look_at(camera_pos: list[float], target_pos: list[float]) -> tuple[float, float]:
    delta_x = float(target_pos[0]) - float(camera_pos[0])
    delta_y = float(target_pos[1]) - float(camera_pos[1])
    delta_z = float(target_pos[2]) - float(camera_pos[2])
    horizontal = max(math.hypot(delta_x, delta_z), 0.001)
    yaw = math.degrees(math.atan2(-delta_x, delta_z))
    pitch = math.degrees(math.atan2(-delta_y, horizontal))
    return yaw, pitch


def observer_camera_pose(task: dict[str, Any], poses: dict[str, Any]) -> tuple[list[float], float, float]:
    points: list[list[float]] = []
    for pose in poses.values():
        pos = pose.get("pos") if isinstance(pose, dict) else None
        if isinstance(pos, list) and len(pos) >= 3:
            points.append([float(pos[0]), float(pos[1]), float(pos[2])])
    for player_key in ("player_a", "player_b"):
        player = task["players"][player_key]
        points.append([float(v) for v in player["start_pos"]])
        goal = player.get("goal", {})
        if "target_pos" in goal:
            points.append([float(v) for v in goal["target_pos"]])
    if not points:
        return [6.5, -56.2, 1.7], 0.0, 12.0

    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    zs = [p[2] for p in points]
    center = [(min(xs) + max(xs)) / 2.0, max(ys) + 0.9, (min(zs) + max(zs)) / 2.0]
    goal = second_room_entry_goal(task)
    camera_backoff = 2.5
    camera = [center[0], max(ys) + 3.0, center[2]]
    if goal["axis"] == "z":
        camera[2] = min(zs) - camera_backoff if float(goal["direction"]) > 0 else max(zs) + camera_backoff
    elif goal["axis"] == "x":
        camera[0] = min(xs) - camera_backoff if float(goal["direction"]) > 0 else max(xs) + camera_backoff
    else:
        camera[2] = min(zs) - camera_backoff
    yaw, pitch = camera_look_at(camera, center)
    return camera, yaw, pitch


def capture_observer_view(
    runner: InstanceRunner,
    commands: list[str],
    task: dict[str, Any],
    poses: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    if runner.puppet is not None:
        runner.puppet.send("pov self", wait=False)
        runner.puppet.send("camera first_person", wait=False)
    if runner.tickgate is not None:
        runner.tickgate.cmd("advance_wait 2 1", timeout=30.0)
    camera_pos, yaw, pitch = observer_camera_pose(task, poses)
    game_cmd(runner, commands, "spectate", 2)
    game_cmd(
        runner,
        commands,
        f"tp Dev {camera_pos[0]:.3f} {camera_pos[1]:.3f} {camera_pos[2]:.3f} {yaw:.3f} {pitch:.3f}",
        args.camera_settle_ticks,
    )
    if runner.tickgate is not None:
        runner.tickgate.cmd(f"observe_ready {args.camera_settle_render_frames}", timeout=30.0)
    return runner.capture_image(ticks=args.capture_ticks, render_frames=args.capture_render_frames, timeout=args.capture_timeout)


def capture_agent_pov(
    runner: InstanceRunner,
    commands: list[str],
    agent: str,
    pose: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    pos = pose.get("pos") if isinstance(pose, dict) else None
    if not isinstance(pos, list) or len(pos) < 3:
        raise RuntimeError(f"cannot capture {agent} POV without a valid pose: {pose!r}")
    if runner.puppet is not None:
        runner.puppet.send(f"pov {agent}", wait=False)
        runner.puppet.send("camera first_person", wait=False)
    if runner.tickgate is not None:
        runner.tickgate.cmd(f"advance_wait {args.pov_camera_settle_ticks + args.pov_extra_settle_ticks} {args.pov_settle_render_frames}", timeout=30.0)
    image = runner.capture_image(ticks=args.capture_ticks, render_frames=args.capture_render_frames, timeout=args.capture_timeout)
    image["camera_entity"] = agent
    return image


def choose_actions(
    client: OpenAI,
    model: str,
    task: dict[str, Any],
    step_index: int,
    agent_images: dict[str, bytes],
    poses: dict[str, Any],
) -> tuple[dict[str, str], str]:
    prompt = f"""
You control two Minecraft fake players from their own first-person screenshots.
This is a LOW-LEVEL ACTION rollout. You may only choose actions from the allowed list.
No teleport action is allowed. The executor will apply your actions to AgentA and AgentB.

Task: Player A must hold the pressure plate so Player B can pass through the elevator door.
AgentA should reach and stay on the pressure plate. AgentB should pass fully through the open doorway into the second room.
AgentA must visually search for a small stone pressure plate on the floor near the elevator door.
If the pressure plate is not clearly visible under AgentA's feet or centered in view, AgentA should not wait; it should rotate or move to search.

Allowed actions for each agent: {json.dumps(ALLOWED_ACTIONS)}
Action meanings: forward/backward/strafe_left/strafe_right move relative to the agent's own current view. turn_left/turn_right rotate the view. look_up/look_down adjust the view. wait stops movement for this step.
Use only the task text and the two first-person screenshots to decide what each agent should do.
Do not assume any hidden coordinates, navigation deltas, block-state sensors, or success markers.
AgentA should wait only if the visual evidence suggests it is actually standing on and holding the pressure plate.
Step index: {step_index}
The first image is AgentA first-person view. The second image is AgentB first-person view.

Return ONLY compact JSON: {{"agent_a":"action", "agent_b":"action", "reason":"short reason"}}
"""
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url(agent_images["AgentA"])}},
                    {"type": "image_url", "image_url": {"url": data_url(agent_images["AgentB"])}},
                ],
            }
        ],
        temperature=0,
        max_tokens=256,
    )
    text = response.choices[0].message.content or ""
    parsed = extract_first_json_object(text)
    agent_a = str(parsed.get("agent_a", "wait"))
    agent_b = str(parsed.get("agent_b", "wait"))
    if agent_a not in ACTION_TO_PUPPET:
        agent_a = "wait"
    if agent_b not in ACTION_TO_PUPPET:
        agent_b = "wait"
    return {"agent_a": agent_a, "agent_b": agent_b, "reason": str(parsed.get("reason", ""))}, text


def choose_non_qwen_actions(args: argparse.Namespace, rng: random.Random) -> tuple[dict[str, str], str]:
    if args.policy == "fixed":
        agent_a = args.fixed_agent_a_action
        agent_b = args.fixed_agent_b_action
        reason = "fixed policy"
    elif args.policy == "random":
        agent_a = rng.choice(ALLOWED_ACTIONS)
        agent_b = rng.choice(ALLOWED_ACTIONS)
        reason = "random policy"
    else:
        raise ValueError(f"unsupported non-Qwen policy: {args.policy}")
    if agent_a not in ACTION_TO_PUPPET:
        agent_a = "wait"
    if agent_b not in ACTION_TO_PUPPET:
        agent_b = "wait"
    actions = {"agent_a": agent_a, "agent_b": agent_b, "reason": reason}
    return actions, json.dumps(actions, ensure_ascii=False)


def choose_rollout_actions(
    args: argparse.Namespace,
    client: OpenAI | None,
    task: dict[str, Any],
    step_index: int,
    agent_images: dict[str, bytes],
    poses: dict[str, Any],
    rng: random.Random,
) -> tuple[dict[str, str], str]:
    if args.policy == "qwen":
        if client is None:
            raise RuntimeError("Qwen policy selected but OpenAI client is not initialized")
        return choose_actions(client, args.model, task, step_index, agent_images, poses)
    return choose_non_qwen_actions(args, rng)


def send_agent_action(runner: InstanceRunner, agent: str, action: str) -> None:
    if runner.puppet is None:
        raise RuntimeError("Puppet is not connected")
    runner.puppet.send(f"{agent} {ACTION_TO_PUPPET[action]}", wait=False)


def query_success_markers(runner: InstanceRunner, commands: list[str], task: dict[str, Any], stamp: str) -> tuple[dict[str, bool], str]:
    player_a = task["players"]["player_a"]
    plate = player_a["goal"]["target_pos"]
    region = task["players"]["player_b"]["goal"]["target_region"]
    marker_plate = f"LOWLEVEL_TASK{task['id']}_PLATE_OK_{stamp}"
    marker_done = f"LOWLEVEL_TASK{task['id']}_DONE_{stamp}"
    game_cmd(
        runner,
        commands,
        f"execute if block {int(plate[0])} {int(plate[1])} {int(plate[2])} minecraft:stone_pressure_plate[powered=true] run say {marker_plate}",
        5,
    )
    game_cmd(runner, commands, f"execute if block {region[0]} {region[1]} {region[2]} minecraft:air run say {marker_done}", 5)
    agent_b_pose = query_agent_pose(runner, "AgentB")
    time.sleep(0.2)
    log_text = Path(runner.log_path).read_text(encoding="utf-8", errors="ignore") if runner.log_path else ""
    return {
        "pressure_plate_powered": marker_plate in log_text,
        "agent_b_fully_in_second_room": agent_fully_inside_second_room(task, agent_b_pose),
        "door_block_air": marker_done in log_text,
    }, log_text


def run(args: argparse.Namespace) -> dict[str, Any]:
    if getattr(args, "refresh_pack", False) and args.pack_dst.exists():
        shutil.rmtree(args.pack_dst)
    if not args.pack_dst.exists():
        shutil.copytree(args.pack_src, args.pack_dst)
    task_data = json.loads(args.tasks.read_text(encoding="utf-8"))
    task = task_data["tasks"][args.task_index]
    player_a = task["players"]["player_a"]
    player_b = task["players"]["player_b"]

    args.frames_dir.mkdir(parents=True, exist_ok=True)
    for frame in args.frames_dir.glob("rollout_frame_*.png"):
        frame.unlink()
    args.qwen_frames_dir.mkdir(parents=True, exist_ok=True)
    for frame in args.qwen_frames_dir.glob("rollout_step_*_agent_*.png"):
        frame.unlink()

    client = None
    if args.policy == "qwen":
        client = OpenAI(base_url=args.api_base_url, api_key=args.api_key or "EMPTY")
    instance_config = getattr(args, "instance_config", None)
    if instance_config is None:
        instance_config = load_instance_config(str(args.config))
    runner = InstanceRunner(instance_config, Path(args.log_dir))
    commands: list[str] = []
    records: list[dict[str, Any]] = []
    reset_state: dict[str, Any] = {}
    markers = {"pressure_plate_powered": False, "agent_b_fully_in_second_room": False, "door_block_air": False}
    policy_rng = random.Random(args.random_seed)
    try:
        runner.start()
        game_cmd(runner, commands, "reload", 40)
        game_cmd(runner, commands, "gamerule commandBlockOutput false", 5)
        game_cmd(runner, commands, "gamerule sendCommandFeedback false", 5)
        game_cmd(runner, commands, "gamerule logAdminCommands false", 5)
        game_cmd(runner, commands, f"function {task['scene_clear_function']}", 20)
        game_cmd(runner, commands, f"function {task['scene_setup_function']}", 40)
        game_cmd(runner, commands, "gamemode spectator Dev", 5)
        game_cmd(runner, commands, "effect give Dev minecraft:night_vision 999 0 true", 5)
        setup_camera_pos, setup_yaw, setup_pitch = observer_camera_pose(task, {})
        game_cmd(
            runner,
            commands,
            f"tp Dev {setup_camera_pos[0]:.3f} {setup_camera_pos[1]:.3f} {setup_camera_pos[2]:.3f} {setup_yaw:.3f} {setup_pitch:.3f}",
            20,
        )
        if runner.puppet is not None:
            runner.puppet.send("camera first_person", wait=False)
            if runner.tickgate is not None:
                runner.tickgate.cmd("advance_wait 5 5", timeout=30.0)
        if args.hide_hud and runner.puppet is not None:
            runner.puppet.send("f1", wait=False)
            if runner.tickgate is not None:
                runner.tickgate.cmd("advance_wait 5 1", timeout=30.0)

        # Reset-only placement: the task rollout below never uses positional teleport.
        game_cmd(runner, commands, "player AgentA spawn", 40)
        game_cmd(runner, commands, "player AgentB spawn", 40)
        game_cmd(runner, commands, "gamemode creative AgentA", 5)
        game_cmd(runner, commands, "gamemode creative AgentB", 5)
        game_cmd(runner, commands, "effect give AgentA minecraft:glowing 999 0 true", 5)
        game_cmd(runner, commands, "effect give AgentB minecraft:glowing 999 0 true", 5)
        a_start = [float(v) for v in player_a["start_pos"]]
        b_start = [float(v) for v in player_b["start_pos"]]
        a_yaw = 0.0
        b_yaw = 0.0
        if args.randomize_starts:
            rng = random.Random(args.random_seed)
            a_start, a_yaw, _ = randomized_reset_pose(a_start, rng, args)
            b_start, b_yaw, _ = randomized_reset_pose(b_start, rng, args)
        reset_state = {
            "randomize_starts": args.randomize_starts,
            "random_seed": args.random_seed,
            "AgentA": {"pos": a_start, "yaw": a_yaw, "pitch": 0.0},
            "AgentB": {"pos": b_start, "yaw": b_yaw, "pitch": 0.0},
        }
        game_cmd(runner, commands, f"tp AgentA {a_start[0]:.3f} {a_start[1]:.3f} {a_start[2]:.3f} {a_yaw:.3f} 0.0", 20)
        game_cmd(runner, commands, f"tp AgentB {b_start[0]:.3f} {b_start[1]:.3f} {b_start[2]:.3f} {b_yaw:.3f} 0.0", 20)

        for step_index in range(args.max_steps):
            poses = {
                "AgentA": query_agent_pose(runner, "AgentA"),
                "AgentB": query_agent_pose(runner, "AgentB"),
            }
            image = capture_observer_view(runner, commands, task, poses, args)
            frame_path = args.frames_dir / f"rollout_frame_{step_index:03d}.png"
            frame_path.write_bytes(image["image_bytes"])
            pov_a = capture_agent_pov(runner, commands, "AgentA", poses["AgentA"], args)
            pov_b = capture_agent_pov(runner, commands, "AgentB", poses["AgentB"], args)
            pov_a_path = args.qwen_frames_dir / f"rollout_step_{step_index:03d}_agent_a.png"
            pov_b_path = args.qwen_frames_dir / f"rollout_step_{step_index:03d}_agent_b.png"
            pov_a_path.write_bytes(pov_a["image_bytes"])
            pov_b_path.write_bytes(pov_b["image_bytes"])
            actions, qwen_text = choose_rollout_actions(
                args,
                client,
                task,
                step_index,
                {"AgentA": pov_a["image_bytes"], "AgentB": pov_b["image_bytes"]},
                poses,
                policy_rng,
            )
            send_agent_action(runner, "AgentA", actions["agent_a"])
            send_agent_action(runner, "AgentB", actions["agent_b"])
            if runner.tickgate is not None:
                runner.tickgate.cmd(f"advance_wait {args.action_ticks} 1", timeout=90.0)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            markers, _ = query_success_markers(runner, commands, task, stamp)
            done = all(markers.values())
            records.append(
                {
                    "step": step_index,
                    "policy": args.policy,
                    "frame": str(frame_path),
                    "qwen_input_frames": {"AgentA": str(pov_a_path), "AgentB": str(pov_b_path)},
                    "actions": actions,
                    "qwen_response": qwen_text,
                    "poses": poses,
                    "markers": markers,
                    "reward": 1.0 if done else 0.0,
                    "done": done,
                    "serverTick": image.get("serverTick"),
                    "renderFrame": image.get("renderFrame"),
                }
            )
            if done:
                break
    finally:
        runner.close()

    video_written = False
    video_error = None
    if args.write_video and records:
        try:
            write_video(args.frames_dir, args.video_output, args.fps)
            video_written = True
        except Exception as exc:
            video_error = repr(exc)
            if args.fail_on_video_error:
                raise
    result = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "policy": args.policy,
        "model": args.model if args.policy == "qwen" else None,
        "task_id": task["id"],
        "scene_id": task["scene_id"],
        "description": task["task_description"],
        "success": all(markers.values()),
        "episode_reward": 1.0 if all(markers.values()) else 0.0,
        "markers": markers,
        "action_space": ALLOWED_ACTIONS,
        "note": "Only reset/setup teleports AgentA/AgentB. During rollout, Qwen actions are low-level movement/look commands only; Dev camera teleports are used only to capture observer and synthetic first-person POV images.",
        "reset_state": reset_state,
        "frames_dir": str(args.frames_dir),
        "qwen_frames_dir": str(args.qwen_frames_dir),
        "video_output": str(args.video_output) if args.write_video else None,
        "video_written": video_written,
        "video_error": video_error,
        "step_count": len(records),
        "records": records,
        "commands": commands,
        "log": str(runner.log_path),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Qwen low-level action rollout for the elevator task.")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--task-index", type=int, default=0)
    parser.add_argument("--pack-src", type=Path, default=DEFAULT_PACK_SRC)
    parser.add_argument("--pack-dst", type=Path, default=DEFAULT_PACK_DST)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:3888/v1/")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--model", default="qwen2.5-vl-7b")
    parser.add_argument("--policy", choices=["qwen", "fixed", "random"], default="qwen")
    parser.add_argument("--fixed-agent-a-action", choices=ALLOWED_ACTIONS, default="wait")
    parser.add_argument("--fixed-agent-b-action", choices=ALLOWED_ACTIONS, default="forward")
    parser.add_argument("--frames-dir", type=Path, default=ROOT / "test_results" / "qwen_lowlevel_frames")
    parser.add_argument("--qwen-frames-dir", type=Path, default=ROOT / "test_results" / "qwen_lowlevel_qwen_pov_frames")
    parser.add_argument("--video-output", type=Path, default=ROOT / "test_results" / "qwen_lowlevel_rollout.mp4")
    parser.add_argument("--output", type=Path, default=ROOT / "test_results" / "qwen_lowlevel_rollout_result.json")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--action-ticks", type=int, default=4)
    parser.add_argument("--capture-ticks", type=int, default=2)
    parser.add_argument("--capture-render-frames", type=int, default=2)
    parser.add_argument("--camera-settle-ticks", type=int, default=10)
    parser.add_argument("--camera-settle-render-frames", type=int, default=6)
    parser.add_argument("--pov-eye-height", type=float, default=DEFAULT_POV_EYE_HEIGHT)
    parser.add_argument("--pov-forward-offset", type=float, default=DEFAULT_POV_FORWARD_OFFSET)
    parser.add_argument("--pov-camera-settle-ticks", type=int, default=16)
    parser.add_argument("--pov-extra-settle-ticks", type=int, default=8)
    parser.add_argument("--pov-settle-render-frames", type=int, default=10)
    parser.add_argument("--capture-timeout", type=float, default=90.0)
    parser.add_argument("--fps", type=int, default=2)
    parser.add_argument("--write-video", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--fail-on-video-error", action="store_true")
    parser.add_argument("--hide-hud", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--refresh-pack", action="store_true")
    parser.add_argument("--randomize-starts", action="store_true")
    parser.add_argument("--random-seed", type=int, default=None)
    parser.add_argument("--start-position-jitter", type=float, default=0.6)
    parser.add_argument("--start-yaw-jitter", type=float, default=35.0)
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

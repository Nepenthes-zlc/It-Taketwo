from __future__ import annotations

import argparse
import concurrent.futures
import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from action_space import ALLOWED_ACTIONS
from agent_driver import build_agent_drivers, choose_agent_actions, driver_metadata
from completion import query_success_markers
from game_functions import (
    capture_rollout_agent_pov,
    capture_rollout_observer_view,
    capture_three_agent_pov,
    capture_three_observer,
    choose_task_indices,
    datapack_dst,
    ensure_datapack,
    game_cmd,
    load_task_list,
    observer_camera_pose,
    parse_index_list,
    query_agent_pose,
    randomized_reset_pose,
    send_agent_action,
    sync_datapack,
    tp,
    validate_png_views,
    write_video,
    write_view,
)
from launch import (
    DEFAULT_LOG_DIR,
    DEFAULT_OUTPUT_DIR,
    BatchConfig,
    InstanceConfig,
    InstanceRunner,
    instance_config_from_cli,
    load_batch_config,
    load_instance_config,
)


@dataclass(frozen=True)
class EpisodeSpec:
    episode_id: int
    task_index: int
    repeat_index: int
    random_seed: int | None


def run_rollout(args: argparse.Namespace) -> dict[str, Any]:
    if args.entry == "three_views":
        return run_three_views(args)
    if args.entry == "lowlevel_episode":
        return run_lowlevel_episode(args)
    if args.entry == "lowlevel_batch":
        return run_lowlevel_batch(args)
    raise ValueError(f"unknown rollout entry: {args.entry}")


# -----------------------------------------------------------------------------
# Three-view smoke rollout
# -----------------------------------------------------------------------------


def setup_three_view_scene(runner: InstanceRunner, task: dict[str, Any]) -> None:
    player_a = task["players"]["player_a"]
    player_b = task["players"]["player_b"]
    plate = player_a["goal"]["target_pos"]
    b_target = player_b["goal"]["target_pos"]
    a_start_rot = player_a.get("start_rotation", [0.0, 0.0])
    b_start_rot = player_b.get("start_rotation", [0.0, 0.0])

    game_cmd(runner, "gamemode creative Dev", 5)
    game_cmd(runner, "kill @e[type=player,name=AgentA]", 5)
    game_cmd(runner, "kill @e[type=player,name=AgentB]", 5)
    game_cmd(runner, f"function {task['scene_clear_function']}", 20)
    game_cmd(runner, f"function {task['scene_setup_function']}", 40)
    game_cmd(runner, "player AgentA spawn", 40)
    game_cmd(runner, "gamemode creative AgentA", 5)
    game_cmd(runner, "player AgentB spawn", 40)
    game_cmd(runner, "gamemode creative AgentB", 5)
    tp(runner, "AgentA", [plate[0] + 0.5, plate[1], plate[2] + 0.5], a_start_rot[0], a_start_rot[1], 30)
    tp(runner, "AgentB", [b_target[0], b_target[1], b_target[2]], b_start_rot[0], b_start_rot[1], 30)
    if runner.tickgate is not None:
        runner.tickgate.cmd("advance_wait 20 1", timeout=90.0)


def capture_three_view_task(runner: InstanceRunner, task: dict[str, Any], out_dir: Path, args: argparse.Namespace) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    setup_three_view_scene(runner, task)

    pose_a = query_agent_pose(runner, "AgentA")
    pose_b = query_agent_pose(runner, "AgentB")
    views = [
        write_view(out_dir, "player_a_AgentA", pose_a, capture_three_agent_pov(runner, "AgentA", pose_a, args)),
        write_view(out_dir, "player_b_AgentB", pose_b, capture_three_agent_pov(runner, "AgentB", pose_b, args)),
    ]
    image_observer, pose_observer = capture_three_observer(runner, pose_a, pose_b, args)
    views.append(write_view(out_dir, "observer", pose_observer, image_observer))

    result = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "task_id": task["id"],
        "scene_id": task["scene_id"],
        "description": task["task_description"],
        "output_dir": str(out_dir),
        "views": views,
        "log": str(runner.log_path) if runner.log_path else None,
    }
    (out_dir / "views.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    validate_png_views(result)
    return result


def run_three_views(args: argparse.Namespace) -> dict[str, Any]:
    tasks = load_task_list(args.tasks)
    indices = choose_task_indices(len(tasks), task_index=args.task_index, task_indices=args.task_indices)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    batch_dir = args.output_dir / f"three_views_batch_{stamp}"
    config = instance_config_from_cli(args)

    if args.dry_run:
        return {
            "dry_run": True,
            "root": str(DEFAULT_OUTPUT_DIR.parent),
            "env_root": str(config.root),
            "tickgate_port": config.tickgate_port,
            "tasks": str(args.tasks),
            "pack_src": str(args.pack_src),
            "task_indices": indices,
            "action_space": ALLOWED_ACTIONS,
        }

    sync_datapack(config.root, args.pack_src, args.refresh_pack)
    runner = InstanceRunner(config, DEFAULT_LOG_DIR)
    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        runner.start()
        game_cmd(runner, "reload", 40)
        game_cmd(runner, "gamerule commandBlockOutput false", 5)
        for index in indices:
            task = tasks[index]
            out_dir = batch_dir / f"task{index:02d}_{task['scene_id']}"
            print(f"[three-views] task {index} ({task['scene_id']}) ...", flush=True)
            try:
                results.append(capture_three_view_task(runner, task, out_dir, args))
            except Exception as exc:
                errors.append({"task_index": index, "error": repr(exc)})
                if args.fail_fast:
                    raise
            time.sleep(0.3)
    finally:
        runner.close()

    batch_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "ok": not errors,
        "batch_dir": str(batch_dir),
        "task_indices": indices,
        "ok_count": len(results),
        "error_count": len(errors),
        "errors": errors,
        "results": [
            {
                "task_id": item["task_id"],
                "scene_id": item["scene_id"],
                "output_dir": item["output_dir"],
                "views": [
                    {"view": view["view"], "yaw": view["yaw"], "pitch": view["pitch"], "pose_error": view["pose_error"]}
                    for view in item["views"]
                ],
            }
            for item in results
        ],
    }
    (batch_dir / "batch_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if errors:
        raise RuntimeError(f"three-view rollout had {len(errors)} errors; see {batch_dir / 'batch_summary.json'}")
    return summary


# -----------------------------------------------------------------------------
# Low-level action rollout
# -----------------------------------------------------------------------------


def setup_rollout_world(runner: InstanceRunner, commands: list[str], task: dict[str, Any], args: argparse.Namespace) -> None:
    game_cmd(runner, "reload", 40, commands=commands)
    game_cmd(runner, "gamerule commandBlockOutput false", 5, commands=commands)
    game_cmd(runner, "gamerule sendCommandFeedback false", 5, commands=commands)
    game_cmd(runner, "gamerule logAdminCommands false", 5, commands=commands)
    game_cmd(runner, f"function {task['scene_clear_function']}", 20, commands=commands)
    game_cmd(runner, f"function {task['scene_setup_function']}", 40, commands=commands)
    game_cmd(runner, "gamemode spectator Dev", 5, commands=commands)
    game_cmd(runner, "effect give Dev minecraft:night_vision 999 0 true", 5, commands=commands)
    setup_camera_pos, setup_yaw, setup_pitch = observer_camera_pose(task, {})
    tp(runner, "Dev", setup_camera_pos, setup_yaw, setup_pitch, 20, commands=commands)
    if runner.puppet is not None:
        runner.puppet.send("camera first_person", wait=False)
        if runner.tickgate is not None:
            runner.tickgate.cmd("advance_wait 5 5", timeout=30.0)
    if args.hide_hud and runner.puppet is not None:
        runner.puppet.send("f1", wait=False)
        if runner.tickgate is not None:
            runner.tickgate.cmd("advance_wait 5 1", timeout=30.0)


def spawn_agents(runner: InstanceRunner, commands: list[str], active_agents: tuple[str, ...] | list[str] | None = None) -> None:
    active = tuple(active_agents or ("AgentA", "AgentB"))
    for agent in ("AgentA", "AgentB"):
        game_cmd(runner, f"kill @e[type=player,name={agent}]", 5, commands=commands)
    for agent in active:
        game_cmd(runner, f"player {agent} spawn", 40, commands=commands)
        game_cmd(runner, f"gamemode creative {agent}", 5, commands=commands)
        game_cmd(runner, f"effect give {agent} minecraft:glowing 999 0 true", 5, commands=commands)


def reset_agents(runner: InstanceRunner, commands: list[str], task: dict[str, Any], args: argparse.Namespace, active_agents: tuple[str, ...] | list[str] | None = None) -> dict[str, Any]:
    player_a = task["players"]["player_a"]
    player_b = task["players"]["player_b"]
    a_start = [float(v) for v in player_a["start_pos"]]
    b_start = [float(v) for v in player_b["start_pos"]]
    a_rotation = [float(v) for v in player_a.get("start_rotation", [0.0, 0.0])]
    b_rotation = [float(v) for v in player_b.get("start_rotation", [0.0, 0.0])]
    a_yaw = a_rotation[0] if len(a_rotation) > 0 else 0.0
    a_pitch = a_rotation[1] if len(a_rotation) > 1 else 0.0
    b_yaw = b_rotation[0] if len(b_rotation) > 0 else 0.0
    b_pitch = b_rotation[1] if len(b_rotation) > 1 else 0.0
    if args.randomize_starts:
        rng = random.Random(args.random_seed)
        a_start, a_yaw, a_pitch = randomized_reset_pose(
            a_start,
            rng,
            args.start_position_jitter,
            args.start_yaw_jitter,
            args.start_pitch_min,
            args.start_pitch_max,
        )
        b_start, b_yaw, b_pitch = randomized_reset_pose(
            b_start,
            rng,
            args.start_position_jitter,
            args.start_yaw_jitter,
            args.start_pitch_min,
            args.start_pitch_max,
        )
    active = tuple(active_agents or ("AgentA", "AgentB"))
    all_reset_state = {
        "AgentA": {"pos": a_start, "yaw": a_yaw, "pitch": a_pitch},
        "AgentB": {"pos": b_start, "yaw": b_yaw, "pitch": b_pitch},
    }
    reset_state = {
        "randomize_starts": args.randomize_starts,
        "random_seed": args.random_seed,
        "active_agents": list(active),
    }
    for agent in active:
        reset_state[agent] = all_reset_state[agent]
        pose = all_reset_state[agent]
        tp(runner, agent, pose["pos"], pose["yaw"], pose["pitch"], 20, commands=commands)
    return reset_state


def prepare_frame_dir(path: Path, pattern: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for frame in path.glob(pattern):
        frame.unlink()


def run_rollout_step(
    runner: InstanceRunner,
    commands: list[str],
    task: dict[str, Any],
    args: argparse.Namespace,
    step_index: int,
    drivers: dict[str, Any],
    policy_rng: random.Random,
) -> tuple[dict[str, Any], dict[str, bool]]:
    poses = {"AgentA": query_agent_pose(runner, "AgentA"), "AgentB": query_agent_pose(runner, "AgentB")}
    image = capture_rollout_observer_view(runner, commands, task, poses, args)
    frame_path = args.frames_dir / f"rollout_frame_{step_index:03d}.png"
    frame_path.write_bytes(image["image_bytes"])

    pov_a = capture_rollout_agent_pov(runner, commands, "AgentA", poses["AgentA"], args)
    pov_b = capture_rollout_agent_pov(runner, commands, "AgentB", poses["AgentB"], args)
    pov_a_path = args.qwen_frames_dir / f"rollout_step_{step_index:03d}_agent_a.png"
    pov_b_path = args.qwen_frames_dir / f"rollout_step_{step_index:03d}_agent_b.png"
    pov_a_path.write_bytes(pov_a["image_bytes"])
    pov_b_path.write_bytes(pov_b["image_bytes"])

    actions, driver_responses = choose_agent_actions(
        drivers,
        task=task,
        step_index=step_index,
        agent_images={"AgentA": pov_a["image_bytes"], "AgentB": pov_b["image_bytes"]},
        poses=poses,
        rng=policy_rng,
    )
    send_agent_action(runner, "AgentA", actions["agent_a"])
    send_agent_action(runner, "AgentB", actions["agent_b"])
    if runner.tickgate is not None:
        runner.tickgate.cmd(f"advance_wait {args.action_ticks} 1", timeout=90.0)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    markers, _ = query_success_markers(runner, commands, task, stamp)
    done = all(markers.values())
    record = {
        "step": step_index,
        "policy": args.policy,
        "frame": str(frame_path),
        "qwen_input_frames": {"AgentA": str(pov_a_path), "AgentB": str(pov_b_path)},
        "frame_normalization": {"observer": image.get("split_frame_crop"), "AgentA": pov_a.get("split_frame_crop"), "AgentB": pov_b.get("split_frame_crop")},
        "camera_pose": {"observer": image.get("camera_pose"), "AgentA": pov_a.get("camera_pose"), "AgentB": pov_b.get("camera_pose")},
        "actions": actions,
        "agent_driver_responses": driver_responses,
        "qwen_response": json.dumps(driver_responses, ensure_ascii=False),
        "poses": poses,
        "markers": markers,
        "reward": 1.0 if done else 0.0,
        "done": done,
        "serverTick": image.get("serverTick"),
        "renderFrame": image.get("renderFrame"),
    }
    return record, markers


def maybe_write_video(args: argparse.Namespace, records: list[dict[str, Any]]) -> tuple[bool, str | None]:
    if not args.write_video or not records:
        return False, None
    try:
        write_video(args.frames_dir, args.video_output, args.fps)
        return True, None
    except Exception as exc:
        if args.fail_on_video_error:
            raise
        return False, repr(exc)


def run_lowlevel_episode(args: argparse.Namespace) -> dict[str, Any]:
    instance_config = getattr(args, "instance_config", None)
    if instance_config is None:
        instance_config = load_instance_config(args.config)
    pack_dst = args.pack_dst or datapack_dst(instance_config.root)
    ensure_datapack(args.pack_src, pack_dst, refresh=getattr(args, "refresh_pack", False))
    task = load_task_list(args.tasks)[args.task_index]

    prepare_frame_dir(args.frames_dir, "rollout_frame_*.png")
    prepare_frame_dir(args.qwen_frames_dir, "rollout_step_*_agent_*.png")

    drivers = build_agent_drivers(args)
    runner = InstanceRunner(instance_config, Path(args.log_dir))
    commands: list[str] = []
    records: list[dict[str, Any]] = []
    reset_state: dict[str, Any] = {}
    markers = {"pressure_plate_powered": False, "agent_b_fully_in_second_room": False, "door_block_air": False}
    policy_rng = random.Random(args.random_seed)
    try:
        runner.start()
        setup_rollout_world(runner, commands, task, args)
        spawn_agents(runner, commands)
        reset_state = reset_agents(runner, commands, task, args)
        for step_index in range(args.max_steps):
            record, markers = run_rollout_step(runner, commands, task, args, step_index, drivers, policy_rng)
            records.append(record)
            if record["done"]:
                break
    finally:
        runner.close()

    video_written, video_error = maybe_write_video(args, records)
    result = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "policy": args.policy,
        "model": args.model if args.policy == "qwen" else None,
        "agent_drivers": driver_metadata(drivers),
        "task_id": task["id"],
        "scene_id": task["scene_id"],
        "description": task["task_description"],
        "success": all(markers.values()),
        "episode_reward": 1.0 if all(markers.values()) else 0.0,
        "markers": markers,
        "action_space": ALLOWED_ACTIONS,
        "note": "Only reset/setup teleports AgentA/AgentB. During rollout, actions are low-level movement/look commands only; Dev camera teleports are used only for observer and synthetic POV capture.",
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


# -----------------------------------------------------------------------------
# Batched / parallel rollout
# -----------------------------------------------------------------------------


def build_episode_specs(task_indices: list[int], episodes_per_task: int, seed: int | None) -> list[EpisodeSpec]:
    specs: list[EpisodeSpec] = []
    episode_id = 0
    for task_index in task_indices:
        for repeat_index in range(episodes_per_task):
            episode_seed = None if seed is None else seed + episode_id
            specs.append(EpisodeSpec(episode_id=episode_id, task_index=task_index, repeat_index=repeat_index, random_seed=episode_seed))
            episode_id += 1
    return specs


def assign_specs(instances: list[InstanceConfig], specs: list[EpisodeSpec]) -> dict[str, list[EpisodeSpec]]:
    assignments = {instance.name: [] for instance in instances}
    for index, spec in enumerate(specs):
        instance = instances[index % len(instances)]
        assignments[instance.name].append(spec)
    return assignments


def episode_output_dir(base_dir: Path, instance: InstanceConfig, spec: EpisodeSpec) -> Path:
    seed_label = "none" if spec.random_seed is None else str(spec.random_seed)
    return base_dir / instance.name / f"episode_{spec.episode_id:04d}_task_{spec.task_index}_seed_{seed_label}"


def make_episode_args(base_args: argparse.Namespace, instance: InstanceConfig, spec: EpisodeSpec, output_dir: Path) -> argparse.Namespace:
    values = vars(base_args).copy()
    values.update(
        {
            "entry": "lowlevel_episode",
            "task_index": spec.task_index,
            "pack_dst": datapack_dst(instance.root),
            "instance_config": instance,
            "frames_dir": output_dir / "observer_frames",
            "qwen_frames_dir": output_dir / "agent_pov_frames",
            "video_output": output_dir / "rollout.mp4",
            "output": output_dir / "result.json",
            "random_seed": spec.random_seed,
        }
    )
    return argparse.Namespace(**values)


def compact_episode_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "task_id": result.get("task_id"),
        "scene_id": result.get("scene_id"),
        "success": result.get("success"),
        "episode_reward": result.get("episode_reward"),
        "step_count": result.get("step_count"),
        "markers": result.get("markers"),
        "agent_drivers": result.get("agent_drivers"),
        "log": result.get("log"),
    }


def run_worker(instance: InstanceConfig, specs: list[EpisodeSpec], args: argparse.Namespace) -> dict[str, Any]:
    worker_started = time.time()
    records: list[dict[str, Any]] = []
    for spec in specs:
        out_dir = episode_output_dir(args.output_dir, instance, spec)
        out_dir.mkdir(parents=True, exist_ok=True)
        episode_args = make_episode_args(args, instance, spec, out_dir)
        started = time.time()
        try:
            result = run_lowlevel_episode(episode_args)
            record = compact_episode_result(result)
            record.update(
                {
                    "env": instance.name,
                    "episode_id": spec.episode_id,
                    "task_index": spec.task_index,
                    "repeat_index": spec.repeat_index,
                    "random_seed": spec.random_seed,
                    "elapsed_sec": round(time.time() - started, 3),
                    "output": str(episode_args.output),
                }
            )
        except Exception as exc:
            record = {
                "ok": False,
                "env": instance.name,
                "episode_id": spec.episode_id,
                "task_index": spec.task_index,
                "repeat_index": spec.repeat_index,
                "random_seed": spec.random_seed,
                "elapsed_sec": round(time.time() - started, 3),
                "output": str(episode_args.output),
                "error": repr(exc),
            }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    return {"env": instance.name, "ok": all(record.get("ok") for record in records), "episodes": len(records), "elapsed_sec": round(time.time() - worker_started, 3), "records": records}


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_lowlevel_batch(args: argparse.Namespace) -> dict[str, Any]:
    batch = load_batch_config(args.config)
    if args.parallel is not None:
        batch = BatchConfig(instances=batch.instances, parallel=max(1, args.parallel))
    task_indices = parse_index_list(args.task_indices or "0")
    specs = build_episode_specs(task_indices, args.episodes_per_task, args.random_seed)
    assignments = assign_specs(batch.instances, specs)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    active_instances = [instance for instance in batch.instances if assignments[instance.name]]
    if not active_instances:
        raise ValueError("no active instances; check --task-indices and --episodes-per-task")
    if args.dry_run:
        planned = []
        for instance in active_instances:
            for spec in assignments[instance.name]:
                planned.append(
                    {
                        "env": instance.name,
                        "root": str(instance.root),
                        "tickgate_port": instance.tickgate_port,
                        "episode_id": spec.episode_id,
                        "task_index": spec.task_index,
                        "repeat_index": spec.repeat_index,
                        "random_seed": spec.random_seed,
                        "output_dir": str(episode_output_dir(args.output_dir, instance, spec)),
                    }
                )
        return {"time_utc": datetime.now(timezone.utc).isoformat(), "ok": True, "dry_run": True, "policy": args.policy, "config": str(args.config), "parallel": batch.parallel, "total_episodes": len(planned), "planned": planned}

    worker_results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(batch.parallel, len(active_instances))) as executor:
        future_map = {executor.submit(run_worker, instance, assignments[instance.name], args): instance for instance in active_instances}
        for future in concurrent.futures.as_completed(future_map):
            instance = future_map[future]
            try:
                worker_results.append(future.result())
            except Exception as exc:
                worker_results.append({"env": instance.name, "ok": False, "episodes": 0, "records": [], "error": repr(exc)})

    episode_records = [record for worker in worker_results for record in worker.get("records", [])]
    ok_records = [record for record in episode_records if record.get("ok")]
    success_records = [record for record in ok_records if record.get("success")]
    summary = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "ok": len(ok_records) == len(episode_records),
        "policy": args.policy,
        "model": args.model if args.policy == "qwen" else None,
        "config": str(args.config),
        "tasks": str(args.tasks),
        "task_indices": task_indices,
        "episodes_per_task": args.episodes_per_task,
        "total_episodes": len(episode_records),
        "completed_episodes": len(ok_records),
        "successful_episodes": len(success_records),
        "success_rate": (len(success_records) / len(ok_records)) if ok_records else 0.0,
        "output_dir": str(args.output_dir),
        "workers": [{k: v for k, v in worker.items() if k != "records"} for worker in worker_results],
        "episodes": episode_records,
    }
    write_jsonl(args.output_dir / "episodes.jsonl", episode_records)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary

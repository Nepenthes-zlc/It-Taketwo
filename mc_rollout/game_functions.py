from __future__ import annotations

import base64
import io
import json
import math
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from action_space import ACTION_TO_PUPPET

PLAYER_HALF_WIDTH = 0.3
SECOND_ROOM_ENTRY_DEPTH = 1.0


def datapack_dst(env_root: Path) -> Path:
    return env_root / "run" / "saves" / "New World" / "datapacks" / "multiagent_scene_pack"


def load_task_list(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(f"task file has no tasks list: {path}")
    return tasks


def parse_index_list(value: str) -> list[int]:
    if not value.strip():
        return [0]
    indices: list[int] = []
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if ":" in part:
            pieces = [int(piece) for piece in part.split(":")]
            if len(pieces) == 2:
                start, stop = pieces
                step = 1
            elif len(pieces) == 3:
                start, stop, step = pieces
            else:
                raise ValueError(f"bad task index range: {part!r}")
            indices.extend(range(start, stop, step))
        else:
            indices.append(int(part))
    if not indices:
        raise ValueError("empty task index list")
    return indices


def choose_task_indices(task_count: int, task_index: int = 0, task_indices: str | None = None) -> list[int]:
    indices = parse_index_list(task_indices) if task_indices else [task_index]
    for index in indices:
        if index < 0 or index >= task_count:
            raise IndexError(f"task index {index} out of range for {task_count} tasks")
    return indices


def ensure_datapack(pack_src: Path, pack_dst: Path, refresh: bool = False) -> Path:
    if refresh and pack_dst.exists():
        shutil.rmtree(pack_dst)
    if not pack_dst.exists():
        pack_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(pack_src, pack_dst)
    return pack_dst


def sync_datapack(env_root: Path, pack_src: Path, refresh: bool = False) -> Path:
    return ensure_datapack(pack_src, datapack_dst(env_root), refresh=refresh)


def game_cmd(
    runner: Any,
    command: str,
    ticks: int = 20,
    commands: list[str] | None = None,
    timeout: float = 90.0,
) -> dict[str, Any]:
    if runner.tickgate is None or runner.puppet is None:
        raise RuntimeError("runner is not connected")
    if commands is not None:
        commands.append(command)
    runner.puppet.send("cmd " + command, wait=False)
    return runner.tickgate.cmd(f"advance_wait {ticks} 1", timeout=timeout)


def tp(runner: Any, entity: str, pos: list[float], yaw: float, pitch: float, ticks: int = 20, commands: list[str] | None = None) -> dict[str, Any]:
    return game_cmd(runner, f"tp {entity} {pos[0]:.3f} {pos[1]:.3f} {pos[2]:.3f} {yaw:.3f} {pitch:.3f}", ticks, commands=commands)


def query_agent_pose(runner: Any, agent: str) -> dict[str, Any]:
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
    return {"agent": agent, "error": "".join(chunks).strip()}


def send_agent_action(runner: Any, agent: str, action: str) -> None:
    if runner.puppet is None:
        raise RuntimeError("Puppet is not connected")
    runner.puppet.send(f"{agent} {ACTION_TO_PUPPET[action]}", wait=False)


def camera_look_at(camera_pos: list[float], target_pos: list[float]) -> tuple[float, float]:
    delta_x = float(target_pos[0]) - float(camera_pos[0])
    delta_y = float(target_pos[1]) - float(camera_pos[1])
    delta_z = float(target_pos[2]) - float(camera_pos[2])
    horizontal = max(math.hypot(delta_x, delta_z), 0.001)
    yaw = math.degrees(math.atan2(-delta_x, delta_z))
    pitch = math.degrees(math.atan2(-delta_y, horizontal))
    return yaw, pitch


def observer_pose_from_two_agents(pose_a: dict[str, Any], pose_b: dict[str, Any]) -> tuple[list[float], float, float]:
    pos_a = pose_a.get("pos") or [0.0, 0.0, 0.0]
    pos_b = pose_b.get("pos") or [0.0, 0.0, 0.0]
    mid = [(pos_a[0] + pos_b[0]) / 2.0, (pos_a[1] + pos_b[1]) / 2.0, (pos_a[2] + pos_b[2]) / 2.0]
    span = max(2.0, abs(pos_a[0] - pos_b[0]), abs(pos_a[2] - pos_b[2]))
    camera = [mid[0], mid[1] + 3.0, mid[2] - (span + 4.0)]
    dx = mid[0] - camera[0]
    dy = (mid[1] + 0.9) - (camera[1] + 1.62)
    dz = mid[2] - camera[2]
    yaw = math.degrees(math.atan2(-dx, dz))
    pitch = math.degrees(-math.atan2(dy, math.hypot(dx, dz)))
    return camera, yaw, pitch


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
    return {"axis": axis, "door_coord": door_coord, "direction": direction, "target_center": [center_x, float(region[1]), center_z]}


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


def agent_pov_camera_pose(pose: dict[str, Any], eye_height: float, forward_offset: float) -> tuple[list[float], float, float]:
    pos = pose.get("pos") if isinstance(pose, dict) else None
    if not isinstance(pos, list) or len(pos) < 3:
        raise RuntimeError(f"cannot capture agent POV without a valid pose: {pose!r}")
    yaw = float(pose.get("yaw", 0.0))
    pitch = float(pose.get("pitch", 0.0))
    yaw_rad = math.radians(yaw)
    forward_x = -math.sin(yaw_rad)
    forward_z = math.cos(yaw_rad)
    camera = [float(pos[0]) + forward_x * float(forward_offset), float(pos[1]) + float(eye_height), float(pos[2]) + forward_z * float(forward_offset)]
    return camera, yaw, pitch


def capture_fresh_camera_image(runner: Any, args: Any) -> dict[str, Any]:
    """Drop the first image after a camera move; TickGate can return the previous rendered view."""
    runner.capture_image(ticks=args.capture_ticks, render_frames=args.capture_render_frames, timeout=args.capture_timeout)
    return runner.capture_image(ticks=args.capture_ticks, render_frames=args.capture_render_frames, timeout=args.capture_timeout)


def randomized_reset_pose(
    base_pos: list[float],
    rng: Any,
    position_jitter: float,
    yaw_jitter: float,
    pitch_min: float = 20.0,
    pitch_max: float = 40.0,
) -> tuple[list[float], float, float]:
    x_jitter = rng.uniform(-position_jitter, position_jitter)
    z_jitter = rng.uniform(-position_jitter, position_jitter)
    yaw = rng.uniform(-yaw_jitter, yaw_jitter)
    low = min(float(pitch_min), float(pitch_max))
    high = max(float(pitch_min), float(pitch_max))
    pitch = rng.uniform(low, high)
    return [float(base_pos[0]) + x_jitter, float(base_pos[1]), float(base_pos[2]) + z_jitter], yaw, pitch


def capture_three_agent_pov(runner: Any, agent: str, pose: dict[str, Any], args: Any) -> dict[str, Any]:
    pos = pose.get("pos") if isinstance(pose, dict) else None
    if not isinstance(pos, list) or len(pos) < 3:
        raise RuntimeError(f"cannot capture {agent} POV without a valid pose: {pose!r}")
    if runner.puppet is not None:
        runner.puppet.send(f"pov {agent}", wait=False)
        runner.puppet.send("camera first_person", wait=False)
    if runner.tickgate is not None:
        ticks = args.pov_camera_settle_ticks + args.pov_extra_settle_ticks
        runner.tickgate.cmd(f"advance_wait {ticks} {args.pov_settle_render_frames}", timeout=30.0)
    image = runner.capture_image(ticks=args.capture_ticks, render_frames=args.capture_render_frames, timeout=args.capture_timeout)
    image["camera_entity"] = agent
    return image


def capture_three_observer(runner: Any, pose_a: dict[str, Any], pose_b: dict[str, Any], args: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    camera, yaw, pitch = observer_pose_from_two_agents(pose_a, pose_b)
    if runner.puppet is not None:
        runner.puppet.send("pov self", wait=False)
        runner.puppet.send("camera first_person", wait=False)
    game_cmd(runner, "gamemode spectator Dev", 5)
    tp(runner, "Dev", camera, yaw, pitch, args.pov_camera_settle_ticks)
    if runner.tickgate is not None:
        runner.tickgate.cmd(f"advance_wait {args.pov_extra_settle_ticks} {args.pov_settle_render_frames}", timeout=30.0)
    image = runner.capture_image(ticks=args.capture_ticks, render_frames=args.capture_render_frames, timeout=args.capture_timeout)
    image["camera_entity"] = "observer"
    return image, {"pos": camera, "yaw": yaw, "pitch": pitch, "type": "observer_camera"}


def capture_rollout_observer_view(runner: Any, commands: list[str], task: dict[str, Any], poses: dict[str, Any], args: Any) -> dict[str, Any]:
    if runner.puppet is not None:
        runner.puppet.send("pov self", wait=False)
        runner.puppet.send("camera first_person", wait=False)
    if runner.tickgate is not None:
        runner.tickgate.cmd("advance_wait 2 1", timeout=30.0)
    camera_pos, yaw, pitch = observer_camera_pose(task, poses)
    game_cmd(runner, "spectate", 2, commands=commands)
    tp(runner, "Dev", camera_pos, yaw, pitch, args.camera_settle_ticks, commands=commands)
    if runner.tickgate is not None:
        runner.tickgate.cmd(f"observe_ready {args.camera_settle_render_frames}", timeout=30.0)
    image = capture_fresh_camera_image(runner, args)
    image["camera_entity"] = "observer"
    image["camera_pose"] = {"pos": camera_pos, "yaw": yaw, "pitch": pitch}
    return normalize_split_capture(image)


def capture_rollout_agent_pov(runner: Any, commands: list[str], agent: str, pose: dict[str, Any], args: Any) -> dict[str, Any]:
    camera_pos, yaw, pitch = agent_pov_camera_pose(pose, args.pov_eye_height, args.pov_forward_offset)
    if runner.puppet is not None:
        runner.puppet.send("pov self", wait=False)
        runner.puppet.send("camera first_person", wait=False)
    tp(runner, "Dev", camera_pos, yaw, pitch, args.pov_camera_settle_ticks, commands=commands)
    if runner.tickgate is not None:
        runner.tickgate.cmd(f"observe_ready {args.pov_settle_render_frames}", timeout=30.0)
        if args.pov_extra_settle_ticks:
            runner.tickgate.cmd(f"advance_wait {args.pov_extra_settle_ticks} 1", timeout=30.0)
    image = capture_fresh_camera_image(runner, args)
    image = normalize_split_capture(image)
    image["camera_entity"] = agent
    image["camera_pose"] = {"pos": camera_pos, "yaw": yaw, "pitch": pitch}
    return image


def write_view(out_dir: Path, label: str, pose: dict[str, Any], image: dict[str, Any]) -> dict[str, Any]:
    png_path = out_dir / f"{label}.png"
    png_path.write_bytes(image["image_bytes"])
    return {
        "view": label,
        "yaw": pose.get("yaw"),
        "pitch": pose.get("pitch"),
        "pos": pose.get("pos"),
        "entity_type": pose.get("type"),
        "pose_raw": pose.get("raw"),
        "pose_error": pose.get("error"),
        "screenshot": str(png_path),
        "width": image.get("width"),
        "height": image.get("height"),
        "bytes": png_path.stat().st_size,
        "serverTick": image.get("serverTick"),
    }


def validate_png_views(result: dict[str, Any]) -> None:
    labels = {view["view"] for view in result.get("views", [])}
    expected = {"player_a_AgentA", "player_b_AgentB", "observer"}
    if labels != expected:
        raise RuntimeError(f"bad views for task {result.get('task_id')}: {sorted(labels)}")
    for view in result["views"]:
        if view.get("pose_error"):
            raise RuntimeError(f"{view['view']} pose error: {view['pose_error']}")
        path = Path(view["screenshot"])
        data = path.read_bytes()
        if len(data) < 100 or not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError(f"{view['view']} did not write a valid PNG: {path}")


def data_url(png_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")


def _average_rgb(image: Any) -> tuple[float, float, float]:
    sample = image.resize((64, 36))
    pixels = list(sample.getdata())
    total = len(pixels)
    return tuple(sum(pixel[index] for pixel in pixels) / total for index in range(3))


def normalize_split_capture(image: dict[str, Any], enabled: bool = False) -> dict[str, Any]:
    if not enabled:
        return image
    raw = image.get("image_bytes")
    if not isinstance(raw, bytes):
        return image
    try:
        from PIL import Image
        rendered = Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        return image
    width, height = rendered.size
    if width < 400 or height < 100:
        return image

    midpoint = width // 2
    left = rendered.crop((0, 0, midpoint, height))
    right = rendered.crop((midpoint, 0, width, height))
    left_avg = _average_rgb(left)
    right_avg = _average_rgb(right)
    color_gap = sum(abs(left_avg[index] - right_avg[index]) for index in range(3)) / 3.0
    right_is_sky_grass = right_avg[1] - left_avg[1] > 25.0 and right_avg[2] - left_avg[2] > 35.0
    if color_gap < 35.0 or not right_is_sky_grass:
        return image

    fixed = Image.new("RGB", (width, height), (12, 12, 12))
    fixed.paste(left, ((width - midpoint) // 2, 0))
    out = io.BytesIO()
    fixed.save(out, format="PNG")
    image = dict(image)
    image["image_bytes"] = out.getvalue()
    image["split_frame_crop"] = {
        "source": "left_half",
        "left_avg_rgb": [round(value, 2) for value in left_avg],
        "right_avg_rgb": [round(value, 2) for value in right_avg],
    }
    return image


def write_video(frames_dir: Path, output: Path, fps: int) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-framerate", str(fps), "-i", str(frames_dir / "rollout_frame_%03d.png"), "-vf", "format=yuv420p", "-movflags", "+faststart", str(output)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return
    except FileNotFoundError:
        pass

    import cv2

    frames = sorted(frames_dir.glob("rollout_frame_*.png"))
    if not frames:
        raise FileNotFoundError(f"no rollout frames found in {frames_dir}")
    first = cv2.imread(str(frames[0]))
    if first is None:
        raise RuntimeError(f"failed to read video frame: {frames[0]}")
    height, width = first.shape[:2]
    writer = cv2.VideoWriter(str(output), cv2.VideoWriter_fourcc(*"mp4v"), float(fps), (width, height))
    if not writer.isOpened():
        raise RuntimeError(f"failed to open video writer: {output}")
    try:
        for frame_path in frames:
            frame = cv2.imread(str(frame_path))
            if frame is None:
                raise RuntimeError(f"failed to read video frame: {frame_path}")
            if frame.shape[:2] != (height, width):
                frame = cv2.resize(frame, (width, height))
            writer.write(frame)
    finally:
        writer.release()

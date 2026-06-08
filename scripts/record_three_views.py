#!/usr/bin/env python3
"""Run one ConstructScene task (no Qwen) and record the view (yaw/pitch + screenshot)
of player A (Dev), player B (AgentB), and the observer/camera.

A's view is captured by attaching the render camera to Dev (`pov Dev`).
B's view is captured by attaching the render camera to AgentB (`pov AgentB`).
The observer view is the local render camera looking at the scene (`pov self`).
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "mc_runtime" / "EnvMine"))
sys.path.insert(0, str(WORKSPACE / "adapter"))

from envmine.config import load_batch_config, load_instance_config  # noqa: E402
from envmine.runner import InstanceRunner  # noqa: E402
from envmine_verl.env_episode import (  # noqa: E402
    capture_agent_pov,
    query_agent_pose,
)

DEFAULT_TASKS = WORKSPACE / "ConstructScene" / "generated" / "generated_tasks.json"
DEFAULT_PACK_SRC = WORKSPACE / "ConstructScene" / "generated" / "datapacks" / "multiagent_scene_pack"
DEFAULT_CONFIG = WORKSPACE / "mc_runtime" / "EnvMine" / "configs" / "qwen_batch_lowlevel.json"
DEFAULT_OUTPUT_DIR = WORKSPACE / "runs"


def game_cmd(runner: InstanceRunner, command: str, ticks: int = 20) -> None:
    if runner.tickgate is None or runner.puppet is None:
        raise RuntimeError("runner is not connected")
    runner.puppet.send("cmd " + command, wait=False)
    runner.tickgate.cmd(f"advance_wait {ticks} 1", timeout=90.0)


def _observer_pose(pose_a: dict[str, Any], pose_b: dict[str, Any]) -> tuple[list[float], float, float]:
    """Overhead, backed-off camera looking at the midpoint of A and B."""
    pa = pose_a.get("pos") or [0.0, 0.0, 0.0]
    pb = pose_b.get("pos") or [0.0, 0.0, 0.0]
    mid = [(pa[0] + pb[0]) / 2.0, (pa[1] + pb[1]) / 2.0, (pa[2] + pb[2]) / 2.0]
    span = max(2.0, abs(pa[0] - pb[0]), abs(pa[2] - pb[2]))
    back = span + 4.0
    camera = [mid[0], mid[1] + 3.0, mid[2] - back]
    dx = mid[0] - camera[0]
    dy = (mid[1] + 0.9) - (camera[1] + 1.62)
    dz = mid[2] - camera[2]
    horiz = math.hypot(dx, dz)
    yaw = math.degrees(math.atan2(-dx, dz))
    pitch = math.degrees(-math.atan2(dy, horiz))
    return camera, yaw, pitch


def capture_observer(
    runner: InstanceRunner, pose_a: dict[str, Any], pose_b: dict[str, Any], args: SimpleNamespace
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Observer: Dev as a spectator free-camera at an overhead pose framing both dummies."""
    camera, yaw, pitch = _observer_pose(pose_a, pose_b)
    if runner.puppet is not None:
        runner.puppet.send("pov self", wait=False)
        runner.puppet.send("camera first_person", wait=False)
    game_cmd(runner, "gamemode spectator Dev", 5)
    game_cmd(runner, f"tp Dev {camera[0]:.3f} {camera[1]:.3f} {camera[2]:.3f} {yaw:.3f} {pitch:.3f}", args.pov_camera_settle_ticks)
    if runner.tickgate is not None:
        runner.tickgate.cmd(f"advance_wait {args.pov_extra_settle_ticks} {args.pov_settle_render_frames}", timeout=30.0)
    image = runner.capture_image(
        ticks=args.capture_ticks,
        render_frames=args.capture_render_frames,
        timeout=args.capture_timeout,
    )
    image["camera_entity"] = "observer"
    obs_pose = {"pos": camera, "yaw": yaw, "pitch": pitch, "type": "observer_camera"}
    return image, obs_pose


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


def run(args: argparse.Namespace) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = args.output_dir / f"three_views_task{args.task_index}_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)

    config_data = json.loads(args.config.read_text(encoding="utf-8"))
    if "instances" in config_data:
        config = load_batch_config(str(args.config)).instances[0]
    else:
        config = load_instance_config(str(args.config))
    pack_dst = config.root / "run" / "saves" / "New World" / "datapacks" / "multiagent_scene_pack"
    if not pack_dst.exists():
        pack_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(args.pack_src, pack_dst)

    task_data = json.loads(args.tasks.read_text(encoding="utf-8"))
    task = task_data["tasks"][args.task_index]
    player_a = task["players"]["player_a"]
    player_b = task["players"]["player_b"]
    plate = player_a["goal"]["target_pos"]
    b_target = player_b["goal"]["target_pos"]
    a_start_rot = player_a.get("start_rotation", [0.0, 0.0])
    b_start_rot = player_b.get("start_rotation", [0.0, 0.0])
    scene_setup = task["scene_setup_function"]
    scene_clear = task["scene_clear_function"]

    pov_args = SimpleNamespace(
        capture_ticks=args.capture_ticks,
        capture_render_frames=args.capture_render_frames,
        capture_timeout=args.capture_timeout,
        pov_camera_settle_ticks=args.pov_camera_settle_ticks,
        pov_extra_settle_ticks=args.pov_extra_settle_ticks,
        pov_settle_render_frames=args.pov_settle_render_frames,
    )

    runner = InstanceRunner(config, WORKSPACE / "scripts" / "logs")
    views: list[dict[str, Any]] = []
    try:
        runner.start()
        game_cmd(runner, "reload", 40)
        game_cmd(runner, "gamerule commandBlockOutput false", 5)

        # Setup scene; A and B are symmetric Carpet dummies.
        game_cmd(runner, f"function {scene_clear}", 20)
        game_cmd(runner, f"function {scene_setup}", 40)
        game_cmd(runner, "player AgentA spawn", 40)
        game_cmd(runner, "gamemode creative AgentA", 5)
        game_cmd(runner, "player AgentB spawn", 40)
        game_cmd(runner, "gamemode creative AgentB", 5)

        game_cmd(
            runner,
            f"tp AgentA {plate[0] + 0.5:.3f} {plate[1]:.3f} {plate[2] + 0.5:.3f} {a_start_rot[0]:.3f} {a_start_rot[1]:.3f}",
            30,
        )
        game_cmd(
            runner,
            f"tp AgentB {b_target[0]:.3f} {b_target[1]:.3f} {b_target[2]:.3f} {b_start_rot[0]:.3f} {b_start_rot[1]:.3f}",
            30,
        )
        runner.tickgate.cmd("advance_wait 20 1", timeout=90.0)

        # Read poses (yaw/pitch) for A and B.
        pose_a = query_agent_pose(runner, "AgentA")
        pose_b = query_agent_pose(runner, "AgentB")

        # View A: first-person from AgentA.
        image_a = capture_agent_pov(runner, "AgentA", pose_a, pov_args)
        views.append(write_view(out_dir, "player_a_AgentA", pose_a, image_a))

        # View B: first-person from AgentB.
        image_b = capture_agent_pov(runner, "AgentB", pose_b, pov_args)
        views.append(write_view(out_dir, "player_b_AgentB", pose_b, image_b))

        # Observer: Dev spectator free-cam framing both.
        image_obs, pose_obs = capture_observer(runner, pose_a, pose_b, pov_args)
        views.append(write_view(out_dir, "observer", pose_obs, image_obs))

        time.sleep(0.5)
        log_path = str(runner.log_path) if runner.log_path else None
    finally:
        runner.close()

    result = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "task_id": task["id"],
        "scene_id": task["scene_id"],
        "description": task["task_description"],
        "output_dir": str(out_dir),
        "views": views,
        "log": log_path,
    }
    (out_dir / "views.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record A/B/observer views for one ConstructScene task.")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--task-index", type=int, default=0)
    parser.add_argument("--pack-src", type=Path, default=DEFAULT_PACK_SRC)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--capture-ticks", type=int, default=2)
    parser.add_argument("--capture-render-frames", type=int, default=2)
    parser.add_argument("--capture-timeout", type=float, default=90.0)
    parser.add_argument("--pov-camera-settle-ticks", type=int, default=16)
    parser.add_argument("--pov-extra-settle-ticks", type=int, default=8)
    parser.add_argument("--pov-settle-render-frames", type=int, default=10)
    return parser.parse_args()


def main() -> int:
    result = run(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

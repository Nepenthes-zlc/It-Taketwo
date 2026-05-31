#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openai import OpenAI

from envmine.config import load_instance_config
from envmine.runner import InstanceRunner


ROOT = Path(__file__).resolve().parent
DEFAULT_TASKS = Path("/home/zlc/Multiagent/ConstructScene/generated/generated_tasks.json")
DEFAULT_PACK_SRC = Path("/home/zlc/Multiagent/ConstructScene/generated/datapacks/multiagent_scene_pack")
DEFAULT_PACK_DST = Path(
    "/home/zlc/Multiagent/EnvMine/envs/tickgate-1/run/saves/New World/datapacks/multiagent_scene_pack"
)
DEFAULT_CONFIG = ROOT / "configs" / "single_tickgate.json"
DEFAULT_OUTPUT = ROOT / "test_results" / "constructscene_task_qwen_planned_completion.json"


def extract_first_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise ValueError(f"Qwen did not return a JSON object: {text!r}")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : index + 1])
    raise ValueError(f"Unclosed JSON object in Qwen response: {text!r}")


def normalize_plan(raw_plan: dict[str, Any]) -> list[str]:
    expected = ["setup_scene", "spawn_agent_b", "move_player_a_to_goal", "move_player_b_to_goal", "verify_success"]
    if "plan" not in raw_plan:
        keyed_plan = [step for step in expected if step in raw_plan]
        if keyed_plan:
            return keyed_plan
    normalized = []
    for item in raw_plan.get("plan", []):
        if isinstance(item, str):
            name = item
        elif isinstance(item, dict):
            name = str(item.get("function") or item.get("step") or item.get("action") or "")
        else:
            name = ""
        if name.startswith("multiagent_scene:") or name.endswith("/setup"):
            name = "setup_scene"
        normalized.append(name)
    return normalized


def game_cmd(runner: InstanceRunner, commands: list[str], command: str, ticks: int = 20) -> dict[str, Any]:
    if runner.tickgate is None or runner.puppet is None:
        raise RuntimeError("runner is not connected")
    commands.append(command)
    runner.puppet.send("cmd " + command, wait=False)
    return runner.tickgate.cmd(f"advance_wait {ticks} 1", timeout=90.0)


def run(args: argparse.Namespace) -> dict[str, Any]:
    if not args.pack_dst.exists():
        shutil.copytree(args.pack_src, args.pack_dst)

    task_data = json.loads(args.tasks.read_text(encoding="utf-8"))
    task = task_data["tasks"][args.task_index]
    client = OpenAI(base_url=args.api_base_url, api_key=args.api_key or "EMPTY")
    prompt = f"""
You are controlling a Minecraft multi-agent test through a high-level executor.
Read the task JSON and return exactly this compact JSON shape, with no markdown and no nested objects:
{{"plan":["setup_scene","spawn_agent_b","move_player_a_to_goal","move_player_b_to_goal","verify_success"],"reason":"short reason"}}
Task JSON:
{json.dumps(task, ensure_ascii=False)}
"""
    response = client.chat.completions.create(
        model=args.model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
        max_tokens=1024,
    )
    qwen_text = response.choices[0].message.content or ""
    qwen_plan_raw = extract_first_json_object(qwen_text)
    qwen_plan = normalize_plan(qwen_plan_raw)
    expected_plan = ["setup_scene", "spawn_agent_b", "move_player_a_to_goal", "move_player_b_to_goal", "verify_success"]
    if qwen_plan != expected_plan:
        raise RuntimeError(f"Unexpected Qwen plan: normalized={qwen_plan!r} raw={qwen_plan_raw!r}")

    player_a = task["players"]["player_a"]
    player_b = task["players"]["player_b"]
    plate = player_a["goal"]["target_pos"]
    b_target = player_b["goal"]["target_pos"]
    region = player_b["goal"]["target_region"]
    scene_setup = task["scene_setup_function"]
    scene_clear = task["scene_clear_function"]

    runner = InstanceRunner(load_instance_config(str(args.config)), ROOT / "logs")
    commands: list[str] = []
    status: dict[str, Any] | None = None
    capture: dict[str, Any] | None = None
    try:
        runner.start()
        game_cmd(runner, commands, "reload", 40)
        game_cmd(runner, commands, "gamerule commandBlockOutput false", 5)
        for step in qwen_plan:
            if step == "setup_scene":
                game_cmd(runner, commands, f"function {scene_clear}", 20)
                game_cmd(runner, commands, f"function {scene_setup}", 40)
                game_cmd(runner, commands, "gamemode creative Dev", 5)
            elif step == "spawn_agent_b":
                game_cmd(runner, commands, "player AgentB spawn", 40)
                game_cmd(runner, commands, "gamemode creative AgentB", 5)
            elif step == "move_player_a_to_goal":
                game_cmd(runner, commands, f"tp Dev {plate[0] + 0.5:.3f} {plate[1]:.3f} {plate[2] + 0.5:.3f}", 30)
            elif step == "move_player_b_to_goal":
                game_cmd(runner, commands, f"tp AgentB {b_target[0]:.3f} {b_target[1]:.3f} {b_target[2]:.3f}", 30)
                game_cmd(runner, commands, f"tp Dev {plate[0] + 0.5:.3f} {plate[1]:.3f} {plate[2] + 0.5:.3f}", 20)
            elif step == "verify_success" and runner.tickgate is not None:
                status = runner.tickgate.cmd("advance_wait 60 1", timeout=90.0)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        marker_plate = f"QWEN_TASK{task['id']}_PLATE_OK_{stamp}"
        marker_b = f"QWEN_TASK{task['id']}_AGENTB_OK_{stamp}"
        marker_done = f"QWEN_TASK{task['id']}_DONE_{stamp}"
        game_cmd(
            runner,
            commands,
            f"execute if block {int(plate[0])} {int(plate[1])} {int(plate[2])} minecraft:stone_pressure_plate[powered=true] run say {marker_plate}",
            10,
        )
        game_cmd(
            runner,
            commands,
            f"execute if entity @a[name=AgentB,x={region[0]},y={region[1]},z={region[2]},dx={region[3] - region[0]},dy={region[4] - region[1]},dz={region[5] - region[2]}] run say {marker_b}",
            10,
        )
        game_cmd(runner, commands, f"execute if block {region[0]} {region[1]} {region[2]} minecraft:air run say {marker_done}", 10)
        if args.capture_output:
            image = runner.capture_image(ticks=args.capture_ticks, render_frames=args.capture_render_frames)
            args.capture_output.parent.mkdir(parents=True, exist_ok=True)
            args.capture_output.write_bytes(image["image_bytes"])
            capture = {
                "output": str(args.capture_output),
                "width": image["width"],
                "height": image["height"],
                "bytes": args.capture_output.stat().st_size,
                "serverTick": image.get("serverTick"),
                "renderFrame": image.get("renderFrame"),
            }
        time.sleep(1.0)
        log_text = Path(runner.log_path).read_text(encoding="utf-8", errors="ignore") if runner.log_path else ""
    finally:
        runner.close()

    markers = {
        "pressure_plate_powered": marker_plate in log_text,
        "agent_b_in_region": marker_b in log_text,
        "door_block_air": marker_done in log_text,
    }
    result = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "model": args.model,
        "api_base_url": args.api_base_url,
        "qwen_response": qwen_text,
        "qwen_plan_raw": qwen_plan_raw,
        "qwen_plan_normalized": qwen_plan,
        "task_id": task["id"],
        "scene_id": task["scene_id"],
        "description": task["task_description"],
        "markers": markers,
        "success": all(markers.values()),
        "tickgate_status": status,
        "capture": capture,
        "commands": commands,
        "log": str(runner.log_path),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a Qwen-planned ConstructScene task smoke test in EnvMine.")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--task-index", type=int, default=0)
    parser.add_argument("--pack-src", type=Path, default=DEFAULT_PACK_SRC)
    parser.add_argument("--pack-dst", type=Path, default=DEFAULT_PACK_DST)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:3888/v1/")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--model", default="qwen2.5-vl-7b")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--capture-output", type=Path, default=None)
    parser.add_argument("--capture-ticks", type=int, default=5)
    parser.add_argument("--capture-render-frames", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    print(json.dumps(run(parse_args()), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
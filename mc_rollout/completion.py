from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from game_functions import agent_in_elevator_door_target, agent_on_pressure_plate, game_cmd, query_agent_pose

PRESSURE_PLATE_BLOCKS = (
    "minecraft:stone_pressure_plate",
    "minecraft:polished_blackstone_pressure_plate",
    "minecraft:oak_pressure_plate",
    "minecraft:spruce_pressure_plate",
    "minecraft:birch_pressure_plate",
    "minecraft:jungle_pressure_plate",
    "minecraft:acacia_pressure_plate",
    "minecraft:dark_oak_pressure_plate",
    "minecraft:mangrove_pressure_plate",
    "minecraft:cherry_pressure_plate",
    "minecraft:bamboo_pressure_plate",
    "minecraft:crimson_pressure_plate",
    "minecraft:warped_pressure_plate",
)


def pressure_plate_positions(task: dict[str, Any]) -> list[list[Any]]:
    player_a = task.get("players", {}).get("player_a", {})
    goal = player_a.get("goal", {}) if isinstance(player_a, dict) else {}
    positions = goal.get("target_positions") if isinstance(goal, dict) else None
    if isinstance(positions, list) and positions:
        return [pos for pos in positions if isinstance(pos, list) and len(pos) >= 3]
    for condition in task.get("success_conditions", []) or []:
        if not isinstance(condition, dict):
            continue
        positions = condition.get("target_positions")
        if isinstance(positions, list) and positions:
            return [pos for pos in positions if isinstance(pos, list) and len(pos) >= 3]
    plate = goal.get("target_pos") if isinstance(goal, dict) else None
    return [plate] if isinstance(plate, list) and len(plate) >= 3 else []


def pressure_plate_blocks(task: dict[str, Any]) -> list[str]:
    player_a = task.get("players", {}).get("player_a", {})
    goal = player_a.get("goal", {}) if isinstance(player_a, dict) else {}
    blocks: list[str] = []
    for value in (
        goal.get("pressure_plate_block") if isinstance(goal, dict) else None,
        task.get("pressure_plate_block"),
    ):
        if isinstance(value, str) and value and value not in blocks:
            blocks.append(value)
    for condition in task.get("success_conditions", []) or []:
        if not isinstance(condition, dict):
            continue
        value = condition.get("pressure_plate_block")
        if isinstance(value, str) and value and value not in blocks:
            blocks.append(value)
    for value in PRESSURE_PLATE_BLOCKS:
        if value not in blocks:
            blocks.append(value)
    return blocks


def query_success_markers(
    runner: Any,
    commands: list[str],
    task: dict[str, Any],
    stamp: str,
    active_agents: tuple[str, ...] | list[str] | None = None,
) -> tuple[dict[str, bool], str]:
    player_a = task["players"]["player_a"]
    plate_positions = pressure_plate_positions(task)
    region = task["players"]["player_b"]["goal"]["target_region"]
    marker_plate = f"LOWLEVEL_TASK{task['id']}_PLATE_OK_{stamp}"
    marker_done = f"LOWLEVEL_TASK{task['id']}_DONE_{stamp}"
    for plate in plate_positions:
        for block in pressure_plate_blocks(task):
            game_cmd(
                runner,
                f"execute if block {int(plate[0])} {int(plate[1])} {int(plate[2])} {block}[powered=true] run say {marker_plate}",
                5,
                commands=commands,
            )
    game_cmd(runner, f"execute if block {region[0]} {region[1]} {region[2]} minecraft:air run say {marker_done}", 5, commands=commands)
    active = set(active_agents or ("AgentA", "AgentB"))
    agent_a_pose = query_agent_pose(runner, "AgentA") if "AgentA" in active else {"agent": "AgentA", "error": "inactive"}
    agent_b_pose = query_agent_pose(runner, "AgentB") if "AgentB" in active else {"agent": "AgentB", "error": "inactive"}
    time.sleep(0.2)
    log_text = Path(runner.log_path).read_text(encoding="utf-8", errors="ignore") if runner.log_path else ""
    plate_powered = marker_plate in log_text or agent_on_pressure_plate(task, agent_a_pose)
    return {
        "pressure_plate_powered": plate_powered,
        "agent_b_fully_in_second_room": agent_in_elevator_door_target(task, agent_b_pose, task.get("task_mode") or "multiagent"),
        "door_block_air": marker_done in log_text,
    }, log_text

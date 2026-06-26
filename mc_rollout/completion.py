from __future__ import annotations

from typing import Any

from game_functions import agent_in_elevator_door_target, agent_on_pressure_plate, query_agent_pose

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
    """Success markers from agent geometry only.

    Pure pose-based checks: no ``execute if block`` game commands, no tick
    advances, no log scraping. Each active agent's own target is evaluated
    (AgentA -> pressure plate, AgentB -> elevator door); the other is skipped
    when a single agent is being trained.
    """
    active = set(active_agents or ("AgentA", "AgentB"))
    task_mode = task.get("task_mode") or ("single_agent" if len(active) == 1 else "multiagent")

    plate_powered = False
    if "AgentA" in active:
        agent_a_pose = query_agent_pose(runner, "AgentA")
        plate_powered = agent_on_pressure_plate(task, agent_a_pose)

    door_reached = False
    if "AgentB" in active:
        agent_b_pose = query_agent_pose(runner, "AgentB")
        door_reached = agent_in_elevator_door_target(task, agent_b_pose, task_mode)

    return {
        "pressure_plate_powered": plate_powered,
        "agent_b_fully_in_second_room": door_reached,
        "door_block_air": door_reached,
    }, ""

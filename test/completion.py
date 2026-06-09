from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from game_functions import agent_fully_inside_second_room, game_cmd, query_agent_pose


def query_success_markers(runner: Any, commands: list[str], task: dict[str, Any], stamp: str) -> tuple[dict[str, bool], str]:
    player_a = task["players"]["player_a"]
    plate = player_a["goal"]["target_pos"]
    region = task["players"]["player_b"]["goal"]["target_region"]
    marker_plate = f"LOWLEVEL_TASK{task['id']}_PLATE_OK_{stamp}"
    marker_done = f"LOWLEVEL_TASK{task['id']}_DONE_{stamp}"
    game_cmd(
        runner,
        f"execute if block {int(plate[0])} {int(plate[1])} {int(plate[2])} minecraft:stone_pressure_plate[powered=true] run say {marker_plate}",
        5,
        commands=commands,
    )
    game_cmd(runner, f"execute if block {region[0]} {region[1]} {region[2]} minecraft:air run say {marker_done}", 5, commands=commands)
    agent_b_pose = query_agent_pose(runner, "AgentB")
    time.sleep(0.2)
    log_text = Path(runner.log_path).read_text(encoding="utf-8", errors="ignore") if runner.log_path else ""
    return {
        "pressure_plate_powered": marker_plate in log_text,
        "agent_b_fully_in_second_room": agent_fully_inside_second_room(task, agent_b_pose),
        "door_block_air": marker_done in log_text,
    }, log_text

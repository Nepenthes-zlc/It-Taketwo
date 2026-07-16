from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mc_rollout"))

from completion import evaluate_elevator_hold_door, evaluate_pressure_path_reveal, evaluate_task_conditions


def load_task(task_template: str) -> dict:
    data = json.loads((ROOT / "bench/data/0714_2_class/generated_tasks.json").read_text())
    return copy.deepcopy(next(task for task in data["tasks"] if task["task_template"] == task_template))


def goal_poses(task: dict) -> dict:
    return {
        "AgentA": {"pos": list(task["players"]["player_a"]["goal"]["target_pos"])},
        "AgentB": {"pos": list(task["players"]["player_b"]["goal"]["target_pos"])},
    }


def test_elevator_requires_plate_and_elevator_entry() -> None:
    task = load_task("elevator_hold_door")
    poses = goal_poses(task)
    assert evaluate_elevator_hold_door(task, poses)["task_success"] is True
    poses["AgentA"] = {"pos": list(task["players"]["player_a"]["start_pos"])}
    assert evaluate_elevator_hold_door(task, poses)["task_success"] is False
    poses = goal_poses(task)
    poses["AgentB"] = {"pos": list(task["players"]["player_b"]["start_pos"])}
    assert evaluate_elevator_hold_door(task, poses)["task_success"] is False


def test_path_uses_opposite_bank_and_fall_failure() -> None:
    task = load_task("pressure_path_reveal")
    poses = goal_poses(task)
    assert evaluate_pressure_path_reveal(task, poses)["task_success"] is True
    poses["AgentB"] = {"pos": list(task["players"]["player_b"]["start_pos"])}
    assert evaluate_pressure_path_reveal(task, poses)["task_success"] is False
    poses = goal_poses(task)
    poses["AgentB"]["pos"][1] = float(task["failure_conditions"][0]["y_below"]) - 2.0
    result = evaluate_pressure_path_reveal(task, poses)
    assert result["task_failed"] is True
    assert result["task_success"] is False


def test_path_fall_failure_has_default_initialization_tolerance() -> None:
    task = load_task("pressure_path_reveal")
    threshold = float(task["failure_conditions"][0]["y_below"])
    poses = goal_poses(task)
    poses["AgentB"]["pos"][1] = threshold - 0.01
    assert evaluate_pressure_path_reveal(task, poses)["task_failed"] is False
    poses["AgentB"]["pos"][1] = threshold - 1.49
    assert evaluate_pressure_path_reveal(task, poses)["task_failed"] is False
    poses["AgentB"]["pos"][1] = threshold - 1.51
    assert evaluate_pressure_path_reveal(task, poses)["task_failed"] is True


def test_path_fall_failure_tolerance_can_be_overridden() -> None:
    task = load_task("pressure_path_reveal")
    task["failure_conditions"][0]["tolerance"] = 0.25
    threshold = float(task["failure_conditions"][0]["y_below"])
    poses = goal_poses(task)
    poses["AgentB"]["pos"][1] = threshold - 0.2
    assert evaluate_pressure_path_reveal(task, poses)["task_failed"] is False
    poses["AgentB"]["pos"][1] = threshold - 0.3
    assert evaluate_pressure_path_reveal(task, poses)["task_failed"] is True



def test_path_fall_failure_supports_explicit_walking_height_and_drop() -> None:
    task = load_task("pressure_path_reveal")
    condition = task["failure_conditions"][0]
    condition["walking_y"] = -57.0
    condition["minimum_drop"] = 2.0
    condition["y_below"] = 999.0
    poses = goal_poses(task)
    poses["AgentB"]["pos"][1] = -58.9
    assert evaluate_pressure_path_reveal(task, poses)["task_failed"] is False
    poses["AgentB"]["pos"][1] = -59.1
    assert evaluate_pressure_path_reveal(task, poses)["task_failed"] is True

def test_dispatches_by_task_template() -> None:
    elevator = load_task("elevator_hold_door")
    path = load_task("pressure_path_reveal")
    assert "agent_b_in_elevator" in evaluate_task_conditions(elevator, goal_poses(elevator))
    assert "agent_b_on_opposite_bank" in evaluate_task_conditions(path, goal_poses(path))

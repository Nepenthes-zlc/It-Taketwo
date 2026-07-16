from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "mc_rollout", ROOT / "bench"):
    if str(path) in sys.path:
        sys.path.remove(str(path))
    sys.path.insert(0, str(path))

from completion import evaluate_task_conditions
from prompts import build_agent_action_prompt
from rollout import rollout_success, rollout_terminal


def load_task(index: int) -> dict:
    data = json.loads((ROOT / "assert/ConstructScene/generated/generated_tasks.json").read_text())
    return copy.deepcopy(data["tasks"][index])


def poses_for_goals(task: dict) -> dict:
    pose_a = {"pos": list(task["players"]["player_a"]["goal"]["target_pos"])}
    region = task["players"]["player_b"]["goal"]["target_region"]
    pose_b = {
        "pos": [
            (float(region[0]) + float(region[3]) + 1.0) / 2.0,
            float(region[1]),
            (float(region[2]) + float(region[5]) + 1.0) / 2.0,
        ]
    }
    return {"AgentA": pose_a, "AgentB": pose_b}


def test_current_task_types_succeed_from_schema():
    for index in (0, 50):
        task = load_task(index)
        result = evaluate_task_conditions(task, poses_for_goals(task))
        assert result["task_success"] is True
        assert result["task_failed"] is False
        assert result["unsupported_conditions"] == []


def test_pressure_path_succeeds_at_opposite_bank_without_plate_requirement():
    task = load_task(50)
    poses = poses_for_goals(task)
    poses["AgentA"]["pos"] = list(task["players"]["player_a"]["start_pos"])
    poses["AgentB"]["pos"][2] = 13.7
    result = evaluate_task_conditions(task, poses)
    assert result["task_success"] is True
    assert result["task_failed"] is False


def test_pressure_path_does_not_succeed_before_opposite_bank():
    task = load_task(50)
    poses = poses_for_goals(task)
    poses["AgentB"]["pos"][2] = 13.5
    result = evaluate_task_conditions(task, poses)
    assert result["task_success"] is False


def test_elevator_still_requires_agent_a_to_hold_plate():
    task = load_task(0)
    poses = poses_for_goals(task)
    target = task["players"]["player_a"]["goal"]["target_pos"]
    poses["AgentA"]["pos"] = [float(target[0]) + 20.0, float(target[1]), float(target[2]) + 20.0]
    result = evaluate_task_conditions(task, poses)
    assert result["task_success"] is False


def test_unknown_template_is_rejected():
    task = load_task(50)
    task["task_template"] = "future_unknown_coop_type"
    task["players"]["player_b"]["role"] = "artifact_carrier"
    task["players"]["player_b"]["goal"]["description"] = "Carry the artifact into the marked goal region."
    with pytest.raises(ValueError, match="unsupported task_template"):
        build_agent_action_prompt(
            agent_name="AgentB",
            teammate_name="AgentA",
            task=task,
            step_index=1,
            allowed_actions=["wait", "forward"],
            poses={},
        )


def test_pressure_path_prompt_explains_opposite_bank_completion():
    task = load_task(50)
    prompt = build_agent_action_prompt(
        agent_name="AgentB",
        teammate_name="AgentA",
        task=task,
        step_index=1,
        allowed_actions=["wait", "forward"],
        poses={},
    )
    assert "pressure-path reveal cooperation" in prompt
    assert "reach the opposite-bank goal marker" in prompt
    assert "inspect only your own current image" in prompt


def test_truck_prompt_assigns_driver_and_guide_roles():
    task = {
        "task_template": "truck_driver",
        "task_mode": "multiagent",
        "players": {
            "player_a": {"role": "blind_truck_driver"},
            "player_b": {"role": "navigation_guide"},
        },
    }
    prompt_a = build_agent_action_prompt(
        agent_name="AgentA",
        teammate_name="AgentB",
        task=task,
        step_index=0,
        allowed_actions=["wait", "forward", "turn_left", "turn_right"],
        poses={},
    )
    prompt_b = build_agent_action_prompt(
        agent_name="AgentB",
        teammate_name="AgentA",
        task=task,
        step_index=0,
        allowed_actions=["wait", "forward", "turn_left", "turn_right"],
        poses={},
    )
    assert "blind truck driver" in prompt_a
    assert "following Agent B's latest navigation message" in prompt_a
    assert "gives you a clear action instruction, follow it strictly" in prompt_a
    assert "navigation guide" in prompt_b
    assert "rotate your view or reposition yourself" in prompt_b
    assert "choose wait to keep your observation position" in prompt_b
    assert "exactly which action to take" in prompt_b
    assert "from Agent A's perspective" in prompt_b
    assert "floor, walls, and ceiling are white" in prompt_a
    assert "colored floor region is the destination" in prompt_b


def test_truck_driver_succeeds_when_agent_a_enters_target_region():
    data = json.loads((ROOT / "bench/data/final_data/truck/generated_tasks.json").read_text())
    task = copy.deepcopy(data["tasks"][0])
    target = task["players"]["player_a"]["goal"]["target_pos"]
    poses = {
        "AgentA": {"pos": list(target)},
        "AgentB": {"pos": list(task["players"]["player_b"]["start_pos"])},
    }
    result = evaluate_task_conditions(task, poses)
    assert result["task_success"] is True
    assert result["agent_a_in_target_region"] is True


def test_truck_driver_does_not_require_agent_b_in_target_region():
    data = json.loads((ROOT / "bench/data/final_data/truck/generated_tasks.json").read_text())
    task = copy.deepcopy(data["tasks"][34])
    poses = {
        "AgentA": {"pos": list(task["players"]["player_a"]["start_pos"])},
        "AgentB": {"pos": list(task["players"]["player_b"]["goal"]["target_pos"])},
    }
    result = evaluate_task_conditions(task, poses)
    assert result["task_success"] is False
    assert result["agent_a_in_target_region"] is False



def test_picture_prompt_assigns_placer_and_alignment_guide_roles():
    task = {
        "task_template": "picture_center_alignment",
        "task_mode": "multiagent",
        "players": {
            "player_a": {"role": "picture_placer"},
            "player_b": {"role": "visual_alignment_guide"},
        },
    }
    prompt_a = build_agent_action_prompt(
        agent_name="AgentA",
        teammate_name="AgentB",
        task=task,
        step_index=0,
        allowed_actions=["wait", "forward", "turn_left", "turn_right"],
        poses={},
    )
    prompt_b = build_agent_action_prompt(
        agent_name="AgentB",
        teammate_name="AgentA",
        task=task,
        step_index=0,
        allowed_actions=["wait", "forward", "turn_left", "turn_right"],
        poses={},
    )
    assert "responsible for aligning the picture from the elevated platform" in prompt_a
    assert "do not need to handle the picture itself" in prompt_a
    assert "only need to move to the target position" in prompt_a
    assert "Use the message from Agent B to decide your action" in prompt_a
    assert "directly above the colored target area" in prompt_a
    assert "visual alignment guide" in prompt_b
    assert "reliably see the colored target area" in prompt_b
    assert "From the perspective of Agent A" in prompt_b
    assert "lies completely and exactly beneath the platform" in prompt_b

def test_failure_condition_ends_without_success():
    task = load_task(50)
    poses = poses_for_goals(task)
    poses["AgentB"]["pos"][1] = -59.0
    result = evaluate_task_conditions(task, poses)
    markers = {**result, "agent_a_goal_reached": True, "agent_b_goal_reached": True}
    assert result["task_failed"] is True
    assert result["task_success"] is False
    assert rollout_success(markers, ("AgentA", "AgentB")) is False
    assert rollout_terminal(markers, ("AgentA", "AgentB")) is True


def test_single_agent_uses_own_goal_not_full_team_success():
    markers = {
        "task_success": False,
        "task_failed": False,
        "agent_a_goal_reached": True,
        "agent_b_goal_reached": False,
    }
    assert rollout_success(markers, ("AgentA",)) is True
    assert rollout_success(markers, ("AgentB",)) is False

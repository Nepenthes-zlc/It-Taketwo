from __future__ import annotations

import argparse
import io
import json
import time
from pathlib import Path

from PIL import Image

from bench.training_style_bench import build_specs, load_phase_specs, model_input_images, save_agent_prompt_images, summarize, valid_episode


def make_args(mode: str) -> argparse.Namespace:
    return argparse.Namespace(
        bench_mode=mode,
        task_mode="multiagent",
        single_agents="AgentA,AgentB",
        rollout_n=1,
        chunks=1,
        instance_count=8,
        seed=None,
        atomic_role="",
    )


def test_single_parallel_expands_agents_into_separate_episodes():
    specs = build_specs([0, 50], make_args("single-parallel"))
    assert len(specs) == 4
    assert [(spec.task_index, spec.controlled_agent) for spec in specs] == [
        (0, "AgentA"),
        (0, "AgentB"),
        (50, "AgentA"),
        (50, "AgentB"),
    ]
    assert all(spec.task_mode == "single_agent" for spec in specs)


def test_duo_parallel_keeps_both_agents_in_each_episode():
    specs = build_specs([0, 50], make_args("duo-parallel"))
    assert len(specs) == 2
    assert all(spec.task_mode == "multiagent" for spec in specs)
    assert all(spec.controlled_agent is None for spec in specs)


def test_phase_plan_builds_one_global_episode_sequence(tmp_path: Path):
    plan = tmp_path / "phases.json"
    plan.write_text(
        json.dumps(
            [
                {"name": "easy", "task_indices": "0-1"},
                {"name": "medium", "task_indices": "2"},
            ]
        ),
        encoding="utf-8",
    )
    args = make_args("duo-parallel")
    args.phase_plan = plan
    args.task_indices = ""
    task_indices, specs = load_phase_specs(args)
    assert task_indices == [0, 1, 2]
    assert [spec.episode_id for spec in specs] == [0, 1, 2]
    assert [spec.phase_name for spec in specs] == ["easy", "easy", "medium"]


def test_only_normal_results_count_toward_requested_repeats():
    assert valid_episode({"ok": True, "success": True})
    assert valid_episode({"ok": True, "success": False})
    assert not valid_episode({"ok": True, "success": False, "discarded": True})
    assert not valid_episode({"ok": False, "success": False})


def test_duo_images_are_saved_with_explicit_agent_names(tmp_path: Path):
    save_agent_prompt_images(
        tmp_path,
        step_index=3,
        active_agents=("AgentA", "AgentB"),
        agent_images={"AgentA": b"image-a", "AgentB": b"image-b"},
    )
    assert (tmp_path / "step_003_agent_a.png").read_bytes() == b"image-a"
    assert (tmp_path / "step_003_agent_b.png").read_bytes() == b"image-b"
    assert (tmp_path / "step_003_agenta_image_1_own.png").read_bytes() == b"image-a"
    assert (tmp_path / "step_003_agentb_image_1_own.png").read_bytes() == b"image-b"
    assert not list(tmp_path.glob("*teammate*.png"))


def png_bytes(color: tuple[int, int, int], size: tuple[int, int] = (8, 6)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


def test_truck_driver_receives_black_image_while_guide_keeps_real_image(tmp_path: Path):
    original = {
        "AgentA": png_bytes((200, 100, 50)),
        "AgentB": png_bytes((20, 40, 60)),
    }
    model_images = model_input_images({"task_template": "truck_driver"}, original)
    save_agent_prompt_images(
        tmp_path,
        step_index=4,
        active_agents=("AgentA", "AgentB"),
        agent_images=original,
        model_agent_images=model_images,
    )

    with Image.open(io.BytesIO(model_images["AgentA"])) as image:
        assert image.size == (8, 6)
        assert image.convert("RGB").getextrema() == ((0, 0), (0, 0), (0, 0))
    assert model_images["AgentB"] == original["AgentB"]
    assert (tmp_path / "step_004_agent_a.png").read_bytes() == original["AgentA"]
    assert (tmp_path / "step_004_agenta_image_1_own.png").read_bytes() == model_images["AgentA"]
    assert (tmp_path / "step_004_agent_b.png").read_bytes() == original["AgentB"]
    assert (tmp_path / "step_004_agentb_image_1_own.png").read_bytes() == original["AgentB"]


def test_non_truck_model_inputs_are_unchanged():
    original = {"AgentA": b"image-a", "AgentB": b"image-b"}
    assert model_input_images({"task_template": "elevator_hold_door"}, original) == original


def test_summary_reports_single_and_duo_timing():
    records = [
        {"ok": True, "success": True, "task_mode": "single_agent", "controlled_agent": "AgentA", "elapsed_sec": 2.0},
        {"ok": True, "success": False, "task_mode": "single_agent", "controlled_agent": "AgentB", "elapsed_sec": 4.0},
        {"ok": True, "success": True, "task_mode": "multiagent", "controlled_agent": None, "elapsed_sec": 6.0},
    ]
    result = summarize(records, 3, time.time())
    assert result["average_episode_sec"] == 4.0
    assert result["timing_by_agent"]["AgentA"]["average_episode_sec"] == 2.0
    assert result["timing_by_agent"]["AgentB"]["average_episode_sec"] == 4.0
    assert result["timing_by_agent"]["duo"]["average_episode_sec"] == 6.0


def test_prompt_includes_previous_teammate_message():
    from mc_rollout.prompts import build_agent_action_prompt

    task = {
        "task_mode": "multiagent",
        "task_template": "elevator_hold_door",
        "task_description": "Coordinate to finish the task.",
        "players": {
            "player_a": {"role": "holder", "goal": {"description": "Hold the switch."}},
            "player_b": {"role": "crosser", "goal": {"description": "Cross the path."}},
        },
    }
    prompt = build_agent_action_prompt(
        agent_name="AgentA",
        teammate_name="AgentB",
        task=task,
        step_index=2,
        allowed_actions=["wait", "forward"],
        poses={},
        teammate_previous_message="The path is visible; keep holding.",
    )
    assert "The path is visible; keep holding." in prompt
    assert '"message"' in prompt
    assert "previous round" in prompt
    assert "inspect only your own current image" in prompt
    assert "cannot see the teammate's camera view or any agent coordinates" in prompt

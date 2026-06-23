"""Tests for pressure-plate reward shaping.

These pin two behavioral contracts we rely on for GRPO:

1. ``reward()`` returns the *terminal* (final-step) shaped reward, not the
   max over the episode. Max immortalizes a lucky early frame (spawn
   orientation) and destroys skill-correlated variance.
2. For a *failed* single-agent pressure-plate trajectory, the shaped reward
   reflects how much closer the agent got to the plate by the end
   (final distance progress), not a step-0 view-alignment spike.

We test the pure reward path (``_annotate_reward`` / ``_compute_reward_breakdown``
/ ``reward``) directly with hand-crafted observation dicts. The env is built in
mock mode so ``__init__`` loads the task without launching Minecraft, but we do
not use the mock stepping; we drive the reward math with controlled poses.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
for p in (str(PROJECT_ROOT), str(PROJECT_ROOT / "mc_rollout")):
    if p not in sys.path:
        sys.path.insert(0, p)

from verl_adapter.mc_env import MinecraftEnvConfig, MinecraftRolloutEnv

EYE_HEIGHT = 1.35


def _make_env() -> MinecraftRolloutEnv:
    cfg = MinecraftEnvConfig(
        rollout_yaml=Path("yaml/lowlevel_train_episode.yaml"),
        task_index=0,
        mock=True,
        max_steps=16,
        task_mode="single_agent",
        controlled_agent="AgentA",
        atomic_role="pressure_plate_hold",
        save_trace=False,
        use_images=False,
    )
    return MinecraftRolloutEnv(cfg)


def _pose_aimed_at_plate(env: MinecraftRolloutEnv, x: float, z: float) -> dict[str, Any]:
    """AgentA pose at (x,-58,z) with yaw/pitch pointed at the plate center,
    so view_alignment is ~1.0 and the alignment gate is satisfied."""
    target = env._target_points()["pressure_plate"]
    eye = [x, -58.0 + EYE_HEIGHT, z]
    dx, dy, dz = target[0] - eye[0], target[1] - eye[1], target[2] - eye[2]
    horizontal = max(math.hypot(dx, dz), 0.001)
    yaw = math.degrees(math.atan2(-dx, dz))
    pitch = math.degrees(math.atan2(-dy, horizontal))
    return {"agent": "AgentA", "type": "mock", "pos": [x, -58.0, z], "yaw": yaw, "pitch": pitch}


def _observation(env: MinecraftRolloutEnv, pose_a: dict[str, Any], powered: bool) -> dict[str, Any]:
    return {
        "step": 0,
        "task_mode": "single_agent",
        "controlled_agent": "AgentA",
        "atomic_role": "pressure_plate_hold",
        "active_agents": ["AgentA"],
        "poses": {"AgentA": pose_a, "AgentB": None},
        "markers": {"pressure_plate_powered": bool(powered)},
    }


def _step(env: MinecraftRolloutEnv, x: float, z: float, powered: bool = False) -> float:
    """Annotate a controlled observation and return its shaped reward."""
    obs = _observation(env, _pose_aimed_at_plate(env, x, z), powered)
    env.last_actions = {"AgentA": "forward", "AgentB": "wait"}
    env._annotate_reward(obs)
    return float(obs["reward"])


def test_reward_returns_terminal_not_max():
    """A trajectory that peaks early then ends low must score by its END.

    Step 0 sits on the plate center aimed at it (high shaped reward); the
    final step walks far away (low shaped reward). reward() must equal the
    final-step value, proving it is terminal, not max-over-episode.
    """
    env = _make_env()
    cx, _, cz = env._target_points()["pressure_plate"]

    _step(env, cx + 8.0, cz)              # establish a far initial distance
    peak = _step(env, cx, cz)             # on the plate, aimed -> high
    terminal = _step(env, cx + 20.0, cz + 20.0)  # far away -> low

    assert peak > terminal + 0.2, f"test setup invalid: peak={peak} terminal={terminal}"
    assert env.reward() == terminal, (
        f"reward() should be terminal ({terminal:.4f}); got {env.reward():.4f} "
        f"(looks like max-over-episode ~{peak:.4f})"
    )


def test_failed_reward_tracks_final_distance_progress():
    """Two failed trajectories differing only in how close they ended must
    receive different rewards, the closer one higher. Signal must come from
    final distance progress (skill), giving GRPO variance."""
    cx = _make_env()._target_points()["pressure_plate"][0]
    cz = _make_env()._target_points()["pressure_plate"][2]
    start_x = cx + 10.0

    env_a = _make_env()
    _step(env_a, start_x, cz)                 # far start
    reward_a = _step(env_a, cx + 1.5, cz)     # ended ~1.5 away (failed, big progress)

    env_b = _make_env()
    _step(env_b, start_x, cz)                 # same far start
    reward_b = _step(env_b, start_x - 0.5, cz)  # barely moved (failed, tiny progress)

    assert reward_a > reward_b + 0.1, (
        f"closer-ending trajectory should score higher: "
        f"closer={reward_a:.3f} vs barely-moved={reward_b:.3f}"
    )


def test_failed_reward_not_inflated_by_spawn_alignment_spike():
    """A failed agent that merely spawned aimed at the plate (good alignment,
    zero net distance progress) must not score meaningfully above zero."""
    env = _make_env()
    cx, _, cz = env._target_points()["pressure_plate"]
    start_x = cx + 8.0

    _step(env, start_x, cz)               # initial distance
    # Same spot, perfectly aimed, never advanced -> no progress.
    terminal = _step(env, start_x, cz)

    assert terminal < 0.1, (
        f"perfect aim with no distance progress must stay near zero; got {terminal:.3f} "
        f"(spawn-orientation luck is leaking into reward)"
    )


def test_success_is_full_reward():
    """Stepping onto a plate tile (marker powered) is full-credit terminal success."""
    env = _make_env()
    cx, _, cz = env._target_points()["pressure_plate"]
    _step(env, cx + 8.0, cz)                       # far, failed
    terminal = _step(env, cx, cz, powered=True)    # on plate, powered -> success
    assert terminal == 1.0, f"powered plate must score 1.0, got {terminal}"
    assert env.reward() == 1.0, f"reward() must be 1.0 on success, got {env.reward()}"


# --- Elevator-door target regions: two modes -------------------------------
# multiagent target = the door cells themselves.
# single_agent target = a 2xN pad = door cells + one floor row on the player's side.

from game_functions import (  # noqa: E402
    agent_in_elevator_door_target,
    elevator_door_cell_region,
    elevator_door_front_region,
)


def _door_task() -> dict[str, Any]:
    return _make_env().task


def _pose_b(x: float, z: float) -> dict[str, Any]:
    return {"agent": "AgentB", "type": "mock", "pos": [float(x), -58.0, float(z)]}


def _door_geom(task: dict[str, Any]):
    """Return (xlo, xhi, door_z, player_on_low_side) for the z-line door."""
    reg = task["players"]["player_b"]["goal"]["target_region"]
    x0, y0, z0, x1, y1, z1 = [float(v) for v in reg[:6]]
    b_start = task["players"]["player_b"]["start_pos"]
    return min(x0, x1), max(x0, x1), z0, float(b_start[2]) <= z0


def test_door_regions_geometry():
    """Front region is the cell region extended by exactly one row toward the player."""
    task = _door_task()
    cell = elevator_door_cell_region(task)
    front = elevator_door_front_region(task)
    xlo, xhi, door_z, low_side = _door_geom(task)
    # cell sits on the door line; same x-width as the door
    assert cell[0] == xlo and cell[3] == xhi
    assert cell[2] == door_z and cell[5] == door_z
    # front shares the door x-width and adds one row on the player's side
    assert front[0] == xlo and front[3] == xhi
    if low_side:
        assert front[2] == door_z - 1.0 and front[5] == door_z
    else:
        assert front[2] == door_z and front[5] == door_z + 1.0


def test_single_agent_pad_accepts_front_row_multiagent_rejects():
    """A pose one row in front of the door: single_agent target = success,
    multiagent (door cells only) = not yet."""
    task = _door_task()
    xlo, xhi, door_z, low_side = _door_geom(task)
    cx = (xlo + xhi + 1.0) / 2.0
    front_z = (door_z - 0.5) if low_side else (door_z + 1.5)
    pose = _pose_b(cx, front_z)
    assert agent_in_elevator_door_target(task, pose, "single_agent") is True
    assert agent_in_elevator_door_target(task, pose, "multiagent") is False


def test_door_cell_accepts_both_modes():
    """Standing in the doorway cell counts for both single_agent and multiagent."""
    task = _door_task()
    xlo, xhi, door_z, _ = _door_geom(task)
    cx = (xlo + xhi + 1.0) / 2.0
    pose = _pose_b(cx, door_z + 0.5)  # inside the door cell row
    assert agent_in_elevator_door_target(task, pose, "single_agent") is True
    assert agent_in_elevator_door_target(task, pose, "multiagent") is True


def test_door_targets_reject_far_and_interior():
    """Far from the door and deep inside the second room both fail in either mode."""
    task = _door_task()
    xlo, xhi, door_z, low_side = _door_geom(task)
    cx = (xlo + xhi + 1.0) / 2.0
    far_z = (door_z - 4.0) if low_side else (door_z + 4.0)
    interior_z = (door_z + 1.6) if low_side else (door_z - 1.6)
    for z in (far_z, interior_z):
        pose = _pose_b(cx, z)
        assert agent_in_elevator_door_target(task, pose, "single_agent") is False
        assert agent_in_elevator_door_target(task, pose, "multiagent") is False


def test_door_target_rejects_outside_door_width():
    """A pose beside the door (outside its x-width) is not on target, even on the door line."""
    task = _door_task()
    xlo, xhi, door_z, _ = _door_geom(task)
    pose = _pose_b(xhi + 2.0, door_z + 0.5)  # well past the right edge
    assert agent_in_elevator_door_target(task, pose, "single_agent") is False
    assert agent_in_elevator_door_target(task, pose, "multiagent") is False


# --- Wall-bump penalty -----------------------------------------------------
# A forward/backward that barely moves AgentB = walked into a wall. Penalty
# accumulates over the episode (capped) and is subtracted from the terminal score.

from verl_adapter.mc_env import (  # noqa: E402
    WALL_BUMP_MOVE_EPS,
    WALL_BUMP_PENALTY_CAP,
    WALL_BUMP_PENALTY_PER_HIT,
)

STUCK = {"dx": 0.0, "dz": 0.0, "dy": 0.0}
MOVED = {"dx": 0.4, "dz": 0.0, "dy": 0.0}


def test_wall_bump_only_on_move_actions():
    """Stuck while waiting/turning is NOT a wall bump (only forward/backward count)."""
    env = _make_env()
    for a in ("wait", "turn_left", "turn_right", "look_up", "look_down"):
        env._accumulate_wall_bump(a, STUCK)
    assert env.wall_bump_penalty_total == 0.0


def test_wall_bump_penalizes_stuck_forward():
    """forward that does not move position = one wall-bump penalty."""
    env = _make_env()
    env._accumulate_wall_bump("forward", STUCK)
    assert env.wall_bump_penalty_total == -WALL_BUMP_PENALTY_PER_HIT


def test_wall_bump_skips_successful_move():
    """forward that actually advances is not penalized."""
    env = _make_env()
    env._accumulate_wall_bump("forward", MOVED)
    assert env.wall_bump_penalty_total == 0.0


def test_wall_bump_accumulates_and_caps():
    """Repeated bumps accumulate but never exceed the per-episode cap."""
    env = _make_env()
    for _ in range(50):
        env._accumulate_wall_bump("backward", STUCK)
    assert env.wall_bump_penalty_total == WALL_BUMP_PENALTY_CAP


def test_reward_subtracts_wall_penalty_clamped_nonneg():
    """Terminal reward is shaped + accumulated penalty, floored at 0."""
    env = _make_env()
    cx, _, cz = env._target_points()["pressure_plate"]
    _step(env, cx + 8.0, cz)             # establish initial distance
    _step(env, cx + 1.5, cz)             # some distance progress -> positive shaped
    base = env.reward()
    assert base > 0.0
    # one bump reduces the score by exactly the per-hit penalty
    env._accumulate_wall_bump("forward", STUCK)
    assert abs(env.reward() - max(0.0, base - WALL_BUMP_PENALTY_PER_HIT)) < 1e-9
    # enough bumps drive it to the floor, never negative
    for _ in range(50):
        env._accumulate_wall_bump("forward", STUCK)
    assert env.reward() >= 0.0


def test_success_survives_wall_penalty_cap():
    """A successful terminal (1.0) stays clearly winning even at the penalty cap."""
    env = _make_env()
    cx, _, cz = env._target_points()["pressure_plate"]
    _step(env, cx + 8.0, cz)
    _step(env, cx, cz, powered=True)     # success -> shaped 1.0
    for _ in range(50):
        env._accumulate_wall_bump("forward", STUCK)
    assert env.reward() == 1.0 + WALL_BUMP_PENALTY_CAP  # 0.7, still well above any failed run

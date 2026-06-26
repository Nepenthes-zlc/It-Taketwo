from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MC_ROLLOUT_DIR = PROJECT_ROOT / "mc_rollout"
if str(MC_ROLLOUT_DIR) not in sys.path:
    sys.path.insert(0, str(MC_ROLLOUT_DIR))

from action_space import ALLOWED_ACTIONS  # noqa: E402
from completion import query_success_markers  # noqa: E402
from game_functions import (  # noqa: E402
    agent_in_elevator_door_target,
    capture_rollout_agent_pov,
    capture_rollout_observer_view,
    datapack_dst,
    ensure_datapack,
    load_task_list,
    query_agent_pose,
    second_room_entry_goal,
    send_agent_action,
)
from rollout import reset_agents, setup_rollout_world, spawn_agents  # noqa: E402
from launch import (  # noqa: E402
    DEFAULT_LOG_DIR,
    DEFAULT_PACK_SRC,
    DEFAULT_TASKS,
    InstanceConfig,
    InstanceRunner,
    load_instance_config,
)


PATH_KEYS = {
    "tasks",
    "pack_src",
    "pack_dst",
    "output_dir",
    "output",
    "frames_dir",
    "qwen_frames_dir",
    "video_output",
    "log_dir",
    "config",
}

AGENTS = ("AgentA", "AgentB")

# Wall-bump penalty: a forward/backward action that moves AgentB less than
# WALL_BUMP_MOVE_EPS blocks counts as walking into a wall. Each hit subtracts
# WALL_BUMP_PENALTY_PER_HIT from the terminal score, accumulated over the episode
# but floored at WALL_BUMP_PENALTY_CAP so it never overpowers distance shaping (<=0.5).
WALL_BUMP_MOVE_EPS = 0.02
WALL_BUMP_PENALTY_PER_HIT = 0.05
WALL_BUMP_PENALTY_CAP = -0.3


def _step_timing_root() -> Path | None:
    """Directory for per-step timing JSONL. Independent of the trace switch so it
    records even when rollout-trace saving is off. Disabled only if explicitly set
    to 0/false/off."""
    flag = os.environ.get("IT_TAKETWO_STEP_TIMING", "1").lower()
    if flag in {"0", "false", "no", "off"}:
        return None
    root_value = (
        os.environ.get("IT_TAKETWO_STEP_TIMING_DIR")
        or os.environ.get("IT_TAKETWO_ROLLOUT_TRACE_DIR")
        or "runs/verl_rollouts"
    )
    return _resolve_project_path(root_value) / "step_timing"


def _discarded_root() -> Path | None:
    """Directory for the discarded-rollout JSONL. Independent of the trace switch,
    default-on; disabled only if IT_TAKETWO_DISCARD_LOG is 0/false/off."""
    flag = os.environ.get("IT_TAKETWO_DISCARD_LOG", "1").lower()
    if flag in {"0", "false", "no", "off"}:
        return None
    root_value = (
        os.environ.get("IT_TAKETWO_DISCARD_LOG_DIR")
        or os.environ.get("IT_TAKETWO_ROLLOUT_TRACE_DIR")
        or "runs/verl_rollouts"
    )
    return _resolve_project_path(root_value)


@dataclass(frozen=True)
class MinecraftEnvConfig:
    rollout_yaml: Path
    task_index: int = 0
    random_seed: int | None = None
    max_steps: int | None = None
    mock: bool = False
    instance_index: int | None = None
    instance_prefix: str = "instance-train"
    train_tickgate_base_port: int = 25690
    use_images: bool = False
    image_view: str = "agent_pov"
    persistent_instance: bool = False
    save_trace: bool = True
    trace_root: Path | None = None
    task_mode: str = "multiagent"
    controlled_agent: str | None = None
    atomic_role: str | None = None


def _resolve_project_path(value: Any) -> Any:
    if value is None:
        return None
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _load_rollout_yaml(path: Path) -> dict[str, Any]:
    config_path = _resolve_project_path(path)
    with Path(config_path).open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"rollout YAML must be a mapping: {config_path}")
    return data


def normalize_task_mode(value: str | None) -> str:
    mode = str(value or "multiagent").strip().lower().replace("-", "_")
    if mode in {"multi", "multi_agent", "multiagent"}:
        return "multiagent"
    if mode in {"single", "single_agent", "singleagent", "atomic"}:
        return "single_agent"
    raise ValueError(f"unsupported task mode: {value!r}")


def normalize_agent_name(value: str | None) -> str:
    agent = str(value or "AgentA").strip()
    lowered = agent.lower().replace("_", "")
    if lowered in {"agenta", "a", "playera"}:
        return "AgentA"
    if lowered in {"agentb", "b", "playerb"}:
        return "AgentB"
    raise ValueError(f"unsupported agent name: {value!r}")


def default_atomic_role(agent_name: str) -> str:
    return "pressure_plate_hold" if agent_name == "AgentA" else "elevator_door_approach"


def is_pressure_plate_role(role: str) -> bool:
    return role in {"pressure_plate", "pressure_plate_hold"}


def is_elevator_door_role(role: str) -> bool:
    return role in {"elevator_door_approach", "second_room_entry"}


def training_instance_config(base_config: InstanceConfig, prefix: str, index: int, tickgate_base_port: int) -> InstanceConfig:
    if index < 1:
        raise ValueError(f"instance index must be >= 1, got {index}")
    name = f"{prefix}-{index:02d}"
    root = (PROJECT_ROOT / "env" / name).resolve()
    # GPU render: spread instances across the available EGL devices round-robin.
    # IT_TAKETWO_EGL_DEVICES (e.g. "egl0,egl1,egl2,egl3") overrides; default 4 GPUs.
    device = base_config.device
    if str(device).startswith("egl"):
        egl_devices = [d.strip() for d in os.environ.get("IT_TAKETWO_EGL_DEVICES", "egl0,egl1,egl2,egl3").split(",") if d.strip()]
        if egl_devices:
            device = egl_devices[(index - 1) % len(egl_devices)]
    return replace(
        base_config,
        name=name,
        root=root,
        tickgate_port=int(tickgate_base_port) + index - 1,
        device=device,
    )


def make_rollout_args(config: MinecraftEnvConfig) -> argparse.Namespace:
    data = _load_rollout_yaml(config.rollout_yaml)
    raw_args = dict(data.get("args") or {})
    raw_args["entry"] = "lowlevel_episode"
    raw_args["policy"] = "fixed"
    raw_args.setdefault("tasks", DEFAULT_TASKS)
    raw_args.setdefault("pack_src", DEFAULT_PACK_SRC)
    raw_args.setdefault("pack_dst", None)
    raw_args.setdefault("log_dir", DEFAULT_LOG_DIR)
    raw_args.setdefault("refresh_pack", False)
    raw_args.setdefault("hide_hud", True)
    raw_args.setdefault("randomize_starts", False)
    raw_args.setdefault("start_position_jitter", 0.6)
    raw_args.setdefault("start_yaw_jitter", 35.0)
    raw_args.setdefault("start_pitch_min", 20.0)
    raw_args.setdefault("start_pitch_max", 40.0)
    raw_args.setdefault("action_ticks", 4)
    raw_args.setdefault("agent_pov_mode", "camera_entity")
    raw_args.setdefault("max_steps", 32)
    raw_args.setdefault("write_video", False)
    raw_args.setdefault("fail_on_video_error", False)
    raw_args["task_index"] = int(config.task_index)
    if config.random_seed is not None:
        raw_args["random_seed"] = int(config.random_seed)
    if config.max_steps is not None:
        raw_args["max_steps"] = int(config.max_steps)
    for key in list(raw_args):
        if key in PATH_KEYS and raw_args[key] is not None:
            raw_args[key] = _resolve_project_path(raw_args[key])
    if raw_args.get("config") is None:
        raw_args["config"] = _resolve_project_path("yaml/instance_single.yaml")
    return argparse.Namespace(**raw_args)


class MinecraftRolloutEnv:
    """Step-based wrapper around mc_rollout's Minecraft runtime."""

    def __init__(self, config: MinecraftEnvConfig):
        self.config = config
        self.task_mode = normalize_task_mode(config.task_mode or os.environ.get("IT_TAKETWO_TASK_MODE"))
        self.controlled_agent = normalize_agent_name(config.controlled_agent or os.environ.get("IT_TAKETWO_CONTROLLED_AGENT") or "AgentA")
        self.atomic_role = str(config.atomic_role or os.environ.get("IT_TAKETWO_ATOMIC_ROLE") or default_atomic_role(self.controlled_agent))
        self.active_agents = (self.controlled_agent,) if self.task_mode == "single_agent" else AGENTS
        self.args = make_rollout_args(config)
        self.task = load_task_list(self.args.tasks)[self.args.task_index]
        self.runner: InstanceRunner | None = None
        self.commands: list[str] = []
        self.reset_state: dict[str, Any] = {}
        self.step_index = 0
        self.markers = {
            "pressure_plate_powered": False,
            "agent_b_fully_in_second_room": False,
            "door_block_air": False,
        }
        self.records: list[dict[str, Any]] = []
        self.last_observation: dict[str, Any] | None = None
        self.initial_goal_distances: dict[str, float | None] | None = None
        self.best_shaped_reward = 0.0
        self.last_shaped_reward = 0.0
        self.wall_bump_penalty_total = 0.0
        self.plate_hold_steps = 0
        self.phase_timing = {"act_ticks": 0.0, "observe": 0.0, "marker": 0.0, "n_steps": 0}
        self._observe_timing: dict[str, float] = {"pose": 0.0, "markers": 0.0, "image": 0.0}
        self._step_timing_path = self._make_step_timing_path()
        self._step_timing_seq = 0
        self._consecutive_pose_fail = 0
        self._discarded = False
        self._discard_step: int | None = None
        self._discard_reason: str | None = None
        self._pose_fail_limit = int(os.environ.get("IT_TAKETWO_POSE_FAIL_LIMIT", "3"))
        self._discard_agent = "AgentB" if "AgentB" in self.active_agents else self.controlled_agent
        self._consecutive_slow_shot = 0
        self._shot_slow_secs = float(os.environ.get("IT_TAKETWO_SHOT_SLOW_SECS", "15"))
        self._shot_slow_limit = int(os.environ.get("IT_TAKETWO_SHOT_SLOW_LIMIT", "3"))
        self.last_actions: dict[str, str] = {"AgentA": "wait", "AgentB": "wait"}
        self.last_action_alignment: dict[str, Any] = {}
        self.last_reward_breakdown: dict[str, Any] = {}
        self.trace_dir = self._make_trace_dir()
        self.frames_dir = self.trace_dir / "observer_frames" if self.trace_dir is not None else None
        self.agent_frames_dir = self.trace_dir / "agent_pov_frames" if self.trace_dir is not None else None
        self.llm_frames_dir = self.trace_dir / "llm_input_frames" if self.trace_dir is not None else None
        self.steps_path = self.trace_dir / "steps.jsonl" if self.trace_dir is not None else None
        self._force_restart_on_close = False
        self._failure_reason: str | None = None
        self._mock_positions = {
            "AgentA": [5.5, -58.0, 2.5],
            "AgentB": [2.5, -58.0, 3.5],
        }

    def _task_done(self, markers: dict[str, Any]) -> bool:
        if self.task_mode == "single_agent":
            if is_pressure_plate_role(self.atomic_role):
                return bool(markers.get("pressure_plate_powered"))
            if is_elevator_door_role(self.atomic_role):
                return bool(markers.get("agent_b_within_elevator_door_1"))
        return bool(markers.get("agent_b_fully_in_second_room") and markers.get("pressure_plate_powered"))

    def _make_trace_dir(self) -> Path | None:
        if self.config.mock or not self.config.save_trace:
            return None
        env_save = os.environ.get("IT_TAKETWO_SAVE_ROLLOUT_TRACE")
        if env_save is not None and env_save.lower() in {"0", "false", "no", "off"}:
            return None
        root_value = self.config.trace_root or os.environ.get("IT_TAKETWO_ROLLOUT_TRACE_DIR") or "runs/verl_rollouts"
        root = _resolve_project_path(root_value)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        instance = int(self.config.instance_index or 0)
        trace_dir = Path(root) / f"{stamp}_task{self.config.task_index:03d}_instance{instance:02d}"
        for name in ("observer_frames", "agent_pov_frames", "llm_input_frames"):
            (trace_dir / name).mkdir(parents=True, exist_ok=True)
        return trace_dir

    def start(self) -> dict[str, Any]:
        if self.config.mock:
            self.reset_state = {"mock": True, "random_seed": self.config.random_seed}
            return self.observe()
        instance_config = load_instance_config(self.args.config)
        if self.config.instance_index is not None:
            instance_config = training_instance_config(
                instance_config,
                self.config.instance_prefix,
                self.config.instance_index,
                self.config.train_tickgate_base_port,
            )
        if self.config.persistent_instance:
            instance_config = replace(instance_config, keep_running=True)
        pack_dst = self.args.pack_dst or datapack_dst(instance_config.root)
        ensure_datapack(self.args.pack_src, pack_dst, refresh=getattr(self.args, "refresh_pack", False))
        self.runner = InstanceRunner(instance_config, Path(self.args.log_dir))
        self.runner.start()
        setup_rollout_world(self.runner, self.commands, self.task, self.args)
        spawn_agents(self.runner, self.commands, active_agents=self.active_agents)
        self.reset_state = reset_agents(self.runner, self.commands, self.task, self.args, active_agents=self.active_agents)
        return self.observe()

    def _target_points(self) -> dict[str, Any]:
        plate_target = pressure_plate_target_center(self.task)
        b_goal = second_room_entry_goal(self.task)["target_center"]
        door = self._elevator_door_target()
        return {
            "pressure_plate": [round(float(plate_target[0]), 3), round(float(plate_target[1]), 3), round(float(plate_target[2]), 3)],
            "elevator_door": [round(float(door[0]), 3), round(float(door[1]), 3), round(float(door[2]), 3)],
            "second_room_entry": [round(float(b_goal[0]), 3), round(float(b_goal[1]) + 1.0, 3), round(float(b_goal[2]), 3)],
        }

    def _elevator_door_target(self) -> list[float]:
        goal = self.task["players"]["player_b"].get("goal", {})
        target = goal.get("target_pos")
        if isinstance(target, list) and len(target) >= 3:
            return [float(target[0]), float(target[1]) + 1.0, float(target[2])]
        entry = second_room_entry_goal(self.task)
        return [float(entry["target_center"][0]), float(entry["target_center"][1]) + 1.0, float(entry["door_coord"]) + 0.5]

    def _distance_to_elevator_door(self, pose: Any) -> float | None:
        door = self._elevator_door_target()
        return xz_distance(pose, [float(door[0]), float(door[2])])

    def _augment_atomic_markers(self, poses: dict[str, Any]) -> None:
        pose_b = poses.get("AgentB")
        distance = self._distance_to_elevator_door(pose_b)
        self.markers["agent_b_to_elevator_door"] = round(distance, 4) if distance is not None else None
        reached = bool(isinstance(pose_b, dict) and agent_in_elevator_door_target(self.task, pose_b, self.task_mode))
        self.markers["agent_b_within_elevator_door_1"] = reached

    def _capture_observation_image(self, poses: dict[str, Any]) -> dict[str, Any] | None:
        if not self.config.use_images:
            return None
        if self.runner is None:
            return None
        view = self.config.image_view.lower().replace("-", "_")
        if view == "observer":
            image = capture_rollout_observer_view(self.runner, self.commands, self.task, poses, self.args)
            image_info = {
                "view": "observer",
                "image_bytes": image.get("image_bytes"),
                "camera_pose": image.get("camera_pose"),
                "serverTick": image.get("serverTick"),
                "renderFrame": image.get("renderFrame"),
                "split_frame_crop": image.get("split_frame_crop"),
            }
            if self.frames_dir is not None and isinstance(image_info.get("image_bytes"), bytes):
                frame_path = self.frames_dir / f"rollout_frame_{self.step_index:03d}.png"
                frame_path.write_bytes(image_info["image_bytes"])
                image_info["screenshot"] = str(frame_path)
            return image_info
        if view not in {"agent_pov", "agents", "first_person", "agent_first_person"}:
            raise ValueError(f"unsupported image_view: {self.config.image_view!r}")

        agents: dict[str, dict[str, Any]] = {}
        for agent in self.active_agents:
            image = capture_rollout_agent_pov(self.runner, self.commands, agent, poses[agent], self.args)
            image_info = {
                "view": "first_person",
                "agent": agent,
                "image_bytes": image.get("image_bytes"),
                "camera_pose": image.get("camera_pose"),
                "serverTick": image.get("serverTick"),
                "renderFrame": image.get("renderFrame"),
                "split_frame_crop": image.get("split_frame_crop"),
            }
            if self.agent_frames_dir is not None and isinstance(image_info.get("image_bytes"), bytes):
                frame_path = self.agent_frames_dir / f"rollout_step_{self.step_index:03d}_{agent_key(agent)}.png"
                frame_path.write_bytes(image_info["image_bytes"])
                image_info["screenshot"] = str(frame_path)
            agents[agent] = image_info
        return {"view": "agent_pov", "agents": agents}

    def mark_failed(self, exc: BaseException | None = None) -> None:
        self._failure_reason = repr(exc) if exc is not None else "rollout failed"
        restart = os.environ.get("IT_TAKETWO_RESTART_ON_ROLLOUT_ERROR", "1").lower()
        if self.config.persistent_instance and restart not in {"0", "false", "no", "off"}:
            self._force_restart_on_close = True

    def close(self) -> None:
        if self.runner is not None:
            self.runner.close(force=self._force_restart_on_close)
            self.runner = None

    def observe(self) -> dict[str, Any]:
        if self.config.mock:
            poses = {
                agent: {"agent": agent, "type": "mock", "pos": list(self._mock_positions[agent]), "yaw": 0.0, "pitch": 0.0}
                for agent in self.active_agents
            }
            self._augment_atomic_markers(poses)
            observation = {
                "step": self.step_index,
                "task_id": self.task.get("id"),
                "scene_id": self.task.get("scene_id"),
                "description": self.task.get("task_description"),
                "task_mode": self.task_mode,
                "controlled_agent": self.controlled_agent,
                "atomic_role": self.atomic_role,
                "active_agents": list(self.active_agents),
                "targets": self._target_points(),
                "poses": poses,
                "markers": dict(self.markers),
                "done": self._task_done(self.markers),
            }
            self._annotate_reward(observation)
            observation["done"] = self._task_done(self.markers)
            if self._discarded:
                observation["done"] = True
                observation["discarded"] = True
            self.last_observation = observation
            return observation
        if self.runner is None:
            raise RuntimeError("MinecraftRolloutEnv.observe called before start")
        self._observe_timing = {"pose": 0.0, "markers": 0.0, "image": 0.0}
        _t_pose = time.perf_counter()
        poses = self._query_poses()
        self._observe_timing["pose"] = time.perf_counter() - _t_pose
        self._update_discard_state(poses)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        _t_marker = time.perf_counter()
        self.markers, _ = query_success_markers(self.runner, self.commands, self.task, stamp, active_agents=self.active_agents)
        self._observe_timing["markers"] = time.perf_counter() - _t_marker
        self._augment_atomic_markers(poses)
        observation = {
            "step": self.step_index,
            "task_id": self.task.get("id"),
            "scene_id": self.task.get("scene_id"),
            "description": self.task.get("task_description"),
            "task_mode": self.task_mode,
            "controlled_agent": self.controlled_agent,
            "atomic_role": self.atomic_role,
            "active_agents": list(self.active_agents),
            "targets": self._target_points(),
            "poses": poses,
            "markers": dict(self.markers),
            "done": self._task_done(self.markers),
        }
        _t_image = time.perf_counter()
        image = self._capture_observation_image(poses)
        self._observe_timing["image"] = time.perf_counter() - _t_image
        if image is not None:
            observation["image"] = image
        self._annotate_reward(observation)
        observation["done"] = self._task_done(self.markers)
        if self._discarded:
            observation["done"] = True
            observation["discarded"] = True
        self.last_observation = observation
        return observation

    def step(self, actions: dict[str, Any]) -> dict[str, Any]:
        before_observation = self.last_observation
        tick_dt = 0.0
        raw_action_a = actions.get("agent_a") or actions.get("AgentA") or actions.get("action_a") or "wait"
        raw_action_b = actions.get("agent_b") or actions.get("AgentB") or actions.get("action_b") or "wait"
        action_a = normalize_action(raw_action_a)
        action_b = normalize_action(raw_action_b)
        before_breakdown = before_observation.get("reward_breakdown") if isinstance(before_observation, dict) else {}
        self.last_actions = {"AgentA": action_a, "AgentB": action_b}
        self.last_action_alignment = (
            dict(before_breakdown.get("target_alignment") or {}) if isinstance(before_breakdown, dict) else {}
        )
        action_meta = actions.get("_meta") if isinstance(actions.get("_meta"), dict) else {}
        if self.config.mock:
            if "AgentA" in self.active_agents and action_a == "forward":
                self._mock_positions["AgentA"][2] += 0.5
            if "AgentB" in self.active_agents and action_b == "forward":
                self._mock_positions["AgentB"][2] += 0.5
            self.markers["pressure_plate_powered"] = self.step_index >= 0 and action_a in {"wait", "forward"}
            self.markers["door_block_air"] = self.markers["pressure_plate_powered"]
            self.markers["agent_b_fully_in_second_room"] = self._mock_positions["AgentB"][2] >= 5.5
            self.markers["pressure_plate_powered"] = self.markers["pressure_plate_powered"] and self._mock_positions["AgentA"][2] >= 4.5
        else:
            if self.runner is None:
                raise RuntimeError("MinecraftRolloutEnv.step called before start")
            if "AgentA" in self.active_agents:
                send_agent_action(self.runner, "AgentA", action_a)
            if "AgentB" in self.active_agents:
                send_agent_action(self.runner, "AgentB", action_b)
            if self.runner.tickgate is not None:
                _t_act = time.perf_counter()
                self.runner.tickgate.cmd(f"advance_wait {self.args.action_ticks} 1", timeout=90.0)
                tick_dt = time.perf_counter() - _t_act
                self.phase_timing["act_ticks"] += tick_dt
        self.step_index += 1
        _t_obs = time.perf_counter()
        obs = self.observe()
        obs_dt = time.perf_counter() - _t_obs
        self.phase_timing["observe"] += obs_dt
        self.phase_timing["n_steps"] += 1
        self._update_shot_discard_state(float(self._observe_timing.get("image", 0.0)))
        if self._discarded:
            obs["done"] = True
            obs["discarded"] = True
        gen_dt = 0.0
        if isinstance(action_meta, dict):
            try:
                gen_dt = float(action_meta.get("generate_s") or 0.0)
            except (TypeError, ValueError):
                gen_dt = 0.0
        self._record_step_timing(tick_dt, obs_dt, gen_dt)
        image_info = obs.get("image") if isinstance(obs.get("image"), dict) else None
        reward_breakdown = obs.get("reward_breakdown") if isinstance(obs.get("reward_breakdown"), dict) else {}
        shaped_reward = float(obs.get("reward", 0.0) or 0.0)
        deltas = pose_delta(
            before_observation.get("poses") if isinstance(before_observation, dict) else None,
            obs.get("poses"),
        )
        if "AgentB" in self.active_agents:
            self._accumulate_wall_bump(action_b, deltas.get("AgentB"))
        record = {
            "step": self.step_index,
            "raw_actions": {"agent_a": raw_action_a, "agent_b": raw_action_b},
            "actions": {"agent_a": action_a, "agent_b": action_b},
            "active_agents": list(self.active_agents),
            "agent_decisions": action_meta.get("agent_decisions"),
            "llm_input_frames": action_meta.get("llm_input_frames"),
            "poses_before": before_observation.get("poses") if isinstance(before_observation, dict) else None,
            "poses_after": obs.get("poses"),
            "pose_delta": deltas,
            "markers": obs["markers"],
            "done": obs["done"],
            "reward": shaped_reward,
            "binary_reward": 1.0 if obs["done"] else 0.0,
            "episode_reward": float(obs.get("episode_reward", shaped_reward) or 0.0),
            "reward_breakdown": reward_breakdown,
            "observer_frame": observer_frame_path(image_info),
            "agent_pov_frames": agent_frame_paths(image_info),
            "serverTick": image_ticks(image_info, "serverTick"),
            "renderFrame": image_ticks(image_info, "renderFrame"),
        }
        self.records.append(record)
        self._append_trace_record(record)
        return obs

    def _query_poses(self) -> dict[str, Any]:
        return {agent: query_agent_pose(self.runner, agent) for agent in self.active_agents}

    @staticmethod
    def _pose_failed(pose: Any) -> bool:
        return not (isinstance(pose, dict) and isinstance(pose.get("pos"), list) and len(pose["pos"]) >= 3)

    def _update_discard_state(self, poses: dict[str, Any]) -> None:
        if self._discarded:
            return
        if self._pose_failed(poses.get(self._discard_agent)):
            self._consecutive_pose_fail += 1
        else:
            self._consecutive_pose_fail = 0
        if self._consecutive_pose_fail >= self._pose_fail_limit:
            self._mark_discarded("pose_timeout")

    def _update_shot_discard_state(self, shot_secs: float) -> None:
        """Discard a rollout whose per-step screenshot keeps timing out. A wedged
        render thread makes advance_image hang for tens of seconds every step,
        dragging the whole GRPO step (it waits for the slowest rollout)."""
        if self._discarded:
            return
        if shot_secs >= self._shot_slow_secs:
            self._consecutive_slow_shot += 1
        else:
            self._consecutive_slow_shot = 0
        if self._consecutive_slow_shot >= self._shot_slow_limit:
            self._mark_discarded("screenshot_slow")

    def _mark_discarded(self, reason: str) -> None:
        self._discarded = True
        self._discard_step = self.step_index
        self._discard_reason = reason
        self._record_discarded()

    def was_discarded(self) -> bool:
        return self._discarded

    def _record_discarded(self) -> None:
        root = _discarded_root()
        if root is None:
            return
        try:
            root.mkdir(parents=True, exist_ok=True)
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "reason": self._discard_reason,
                "task_index": int(self.config.task_index),
                "task_id": self.task.get("id"),
                "scene_id": self.task.get("scene_id"),
                "instance_index": int(self.config.instance_index or 0),
                "atomic_role": self.atomic_role,
                "task_mode": self.task_mode,
                "step_count": int(self.step_index),
                "consecutive_fail_count": int(self._consecutive_pose_fail),
                "consecutive_slow_shot": int(self._consecutive_slow_shot),
                "pose_fail_limit": int(self._pose_fail_limit),
                "shot_slow_secs": float(self._shot_slow_secs),
                "shot_slow_limit": int(self._shot_slow_limit),
                "discard_agent": self._discard_agent,
            }
            with (root / "discarded_rollouts.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _append_trace_record(self, record: dict[str, Any]) -> None:
        if self.steps_path is None:
            return
        with self.steps_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _make_step_timing_path(self) -> Path | None:
        if self.config.mock:
            return None
        root = _step_timing_root()
        if root is None:
            return None
        root.mkdir(parents=True, exist_ok=True)
        instance = int(self.config.instance_index or 0)
        # One file per instance so offline stats can group by instance directly.
        return root / f"instance{instance:02d}.jsonl"

    def _record_step_timing(self, tick_dt: float, obs_dt: float, gen_dt: float = 0.0) -> None:
        if self._step_timing_path is None:
            return
        ot = self._observe_timing
        accounted = gen_dt + tick_dt + obs_dt
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "instance_index": int(self.config.instance_index or 0),
            "task_index": int(self.config.task_index),
            "task_id": self.task.get("id"),
            "atomic_role": self.atomic_role,
            "step": self.step_index,
            "seq": self._step_timing_seq,
            "generate_s": round(gen_dt, 4),
            "tick_advance_s": round(tick_dt, 4),
            "observe_s": round(obs_dt, 4),
            "pose_s": round(ot.get("pose", 0.0), 4),
            "markers_s": round(ot.get("markers", 0.0), 4),
            "screenshot_s": round(ot.get("image", 0.0), 4),
            # observe minus its three sub-phases: parsing/marker-augment overhead
            "observe_other_s": round(max(0.0, obs_dt - ot.get("pose", 0.0) - ot.get("markers", 0.0) - ot.get("image", 0.0)), 4),
            "total_s": round(accounted, 4),
        }
        self._step_timing_seq += 1
        self.phase_timing["generate"] = self.phase_timing.get("generate", 0.0) + gen_dt
        self.phase_timing["pose"] = self.phase_timing.get("pose", 0.0) + ot.get("pose", 0.0)
        self.phase_timing["markers"] = self.phase_timing.get("markers", 0.0) + ot.get("markers", 0.0)
        self.phase_timing["screenshot"] = self.phase_timing.get("screenshot", 0.0) + ot.get("image", 0.0)
        self.phase_timing["step_max_s"] = max(self.phase_timing.get("step_max_s", 0.0), accounted)
        self.phase_timing["tick_max_s"] = max(self.phase_timing.get("tick_max_s", 0.0), tick_dt)
        self.phase_timing["generate_max_s"] = max(self.phase_timing.get("generate_max_s", 0.0), gen_dt)
        self.phase_timing["screenshot_max_s"] = max(self.phase_timing.get("screenshot_max_s", 0.0), ot.get("image", 0.0))
        try:
            with self._step_timing_path.open("a", encoding="utf-8") as file:
                file.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def _annotate_reward(self, observation: dict[str, Any]) -> None:
        self._update_atomic_state(observation)
        breakdown = self._compute_reward_breakdown(observation)
        shaped_reward = float(breakdown["shaped_reward"])
        self.best_shaped_reward = max(self.best_shaped_reward, shaped_reward)
        self.last_shaped_reward = shaped_reward
        self.last_reward_breakdown = breakdown
        observation["reward"] = shaped_reward
        observation["episode_reward"] = self.best_shaped_reward
        observation["reward_breakdown"] = breakdown

    def _accumulate_wall_bump(self, action: str, delta_b: Any) -> None:
        """A move action (forward/backward) that barely changed position means AgentB
        walked into a wall. Accumulate a small penalty, capped per episode, so the
        agent is nudged away from wall-hugging without overpowering distance shaping."""
        if action not in {"forward", "backward"}:
            return
        if not isinstance(delta_b, dict):
            return
        moved = math.hypot(float(delta_b.get("dx", 0.0)), float(delta_b.get("dz", 0.0)))
        if moved >= WALL_BUMP_MOVE_EPS:
            return
        self.wall_bump_penalty_total = max(
            WALL_BUMP_PENALTY_CAP,
            self.wall_bump_penalty_total - WALL_BUMP_PENALTY_PER_HIT,
        )

    def _update_atomic_state(self, observation: dict[str, Any]) -> None:
        markers = observation.get("markers") if isinstance(observation.get("markers"), dict) else {}
        if self.task_mode == "single_agent" and is_pressure_plate_role(self.atomic_role):
            if markers.get("pressure_plate_powered"):
                self.plate_hold_steps += 1
            else:
                self.plate_hold_steps = 0
        observation["atomic_state"] = {
            "plate_hold_steps": self.plate_hold_steps,
            "plate_bonus_steps": 0,
            "plate_bonus_steps_required": 0,
        }

    def _compute_reward_breakdown(self, observation: dict[str, Any]) -> dict[str, Any]:
        markers = observation.get("markers") if isinstance(observation.get("markers"), dict) else {}
        distances = self._goal_distances(observation.get("poses"))
        if self.initial_goal_distances is None:
            self.initial_goal_distances = dict(distances)

        agent_a_progress = progress_ratio(
            self.initial_goal_distances.get("agent_a_to_plate"),
            distances.get("agent_a_to_plate"),
        )
        agent_b_progress = progress_ratio(
            self.initial_goal_distances.get("agent_b_to_second_room"),
            distances.get("agent_b_to_second_room"),
        )
        target_alignment = self._target_alignment(observation.get("poses"))
        agent_a_alignment = target_alignment.get("AgentA", {}).get("score", 0.0)
        agent_b_alignment = target_alignment.get("AgentB", {}).get("score", 0.0)

        if self.task_mode == "single_agent":
            if is_pressure_plate_role(self.atomic_role):
                plate_reward = 1.0 if markers.get("pressure_plate_powered") else 0.0
                binary_reward = plate_reward
                # Dense signal is distance progress only: how much closer to the
                # plate the agent is *now* vs its start. Skill-correlated and not
                # gameable by spawn-orientation luck. View-alignment is still
                # computed below for traces but deliberately excluded from the
                # shaped total (see [[reward-terminal-not-max]]).
                progress_reward = round(min(0.5, 0.5 * float(agent_a_progress)), 4)
                alignment_reward = round(0.2 * float(agent_a_alignment), 4)
                action_reward = correct_alignment_action_reward(
                    self.last_actions.get("AgentA"),
                    self.last_action_alignment.get("AgentA") if isinstance(self.last_action_alignment, dict) else None,
                    target_alignment.get("AgentA"),
                )
                marker_reward = max(plate_reward, progress_reward)
                look_reward = alignment_reward
                pass_reward = 0.0
                marker_weights = {
                    "pressure_plate_distance_progress_max": 0.5,
                    "pressure_plate_first_contact": 1.0,
                }
            elif is_elevator_door_role(self.atomic_role):
                door_reward = 1.0 if markers.get("agent_b_within_elevator_door_1") else 0.0
                binary_reward = door_reward
                # Pure terminal reward: ONLY entering the door pays off (1.0), no
                # distance-progress shaping. Distance progress is still computed for
                # traces but excluded from the shaped reward.
                agent_b_door_progress = progress_ratio(
                    self.initial_goal_distances.get("agent_b_to_elevator_door"),
                    distances.get("agent_b_to_elevator_door"),
                )
                progress_reward = 0.0
                marker_reward = door_reward
                plate_reward = 0.0
                pass_reward = door_reward
                look_reward = 0.0
                marker_weights = {
                    "agent_b_within_elevator_door_1": 1.0,
                }
            else:
                binary_reward = 1.0 if self._task_done(markers) else 0.0
                marker_reward = binary_reward
                progress_reward = 0.0
                look_reward = 0.0
                plate_reward = 0.0
                pass_reward = 0.0
                marker_weights = {self.atomic_role: 1.0}
        else:
            binary_reward = 1.0 if self._task_done(markers) else 0.0
            plate_reward = 0.5 if markers.get("pressure_plate_powered") else 0.0
            pass_reward = 1.0 if self._task_done(markers) else 0.0
            marker_reward = max(plate_reward, pass_reward)
            look_reward = 0.10 * (0.6 * float(agent_a_alignment) + 0.4 * float(agent_b_alignment))
            progress_reward = 0.20 * max(agent_a_progress, agent_b_progress)
            marker_weights = {
                "pressure_plate_powered": 0.5,
                "agent_b_fully_in_second_room": 1.0,
            }
        if self.task_mode == "single_agent" and (
            is_pressure_plate_role(self.atomic_role) or is_elevator_door_role(self.atomic_role)
        ):
            shaped_reward = min(1.0, max(binary_reward, marker_reward))
        else:
            shaped_reward = min(1.0, max(binary_reward, marker_reward) + progress_reward + look_reward)
        return {
            "task_mode": self.task_mode,
            "controlled_agent": self.controlled_agent if self.task_mode == "single_agent" else None,
            "atomic_role": self.atomic_role if self.task_mode == "single_agent" else None,
            "shaped_reward": shaped_reward,
            "binary_reward": binary_reward,
            "marker_reward": marker_reward,
            "plate_reward": plate_reward,
            "pass_reward": pass_reward,
            "progress_reward": progress_reward,
            "look_reward": look_reward,
            "action_reward": locals().get("action_reward", 0.0),
            "marker_weights": marker_weights,
            "markers": dict(markers),
            "atomic_state": dict(observation.get("atomic_state") or {}),
            "progress": {
                "agent_a_to_plate": agent_a_progress,
                "agent_b_to_second_room": agent_b_progress,
            },
            "distances": distances,
            "initial_distances": dict(self.initial_goal_distances or {}),
            "target_alignment": target_alignment,
        }

    def _target_alignment(self, poses: Any) -> dict[str, dict[str, float | str | list[float]]]:
        poses = poses if isinstance(poses, dict) else {}
        plate_target = pressure_plate_target_center(self.task)
        door_target = self._elevator_door_target()
        return {
            "AgentA": view_alignment(poses.get("AgentA"), plate_target, "pressure_plate", self.args.pov_eye_height),
            "AgentB": view_alignment(poses.get("AgentB"), door_target, "second_room_entry", self.args.pov_eye_height),
        }

    def _goal_distances(self, poses: Any) -> dict[str, float | None]:
        poses = poses if isinstance(poses, dict) else {}
        b_goal = second_room_entry_goal(self.task)["target_center"]
        b_center = [float(b_goal[0]), float(b_goal[2])]
        return {
            "agent_a_to_plate": xz_distance_to_pressure_plate(self.task, poses.get("AgentA")),
            "agent_b_to_second_room": xz_distance(poses.get("AgentB"), b_center),
            "agent_b_to_elevator_door": self._distance_to_elevator_door(poses.get("AgentB")),
        }

    def reward(self) -> float:
        return max(0.0, self.last_shaped_reward + self.wall_bump_penalty_total)

    def summary(self) -> dict[str, Any]:
        return {
            "task_id": self.task.get("id"),
            "scene_id": self.task.get("scene_id"),
            "task_mode": self.task_mode,
            "controlled_agent": self.controlled_agent if self.task_mode == "single_agent" else None,
            "atomic_role": self.atomic_role if self.task_mode == "single_agent" else None,
            "success": self._task_done(self.markers),
            "reward": self.reward(),
            "binary_reward": 1.0 if self._task_done(self.markers) else 0.0,
            "reward_breakdown": self.last_reward_breakdown,
            "markers": dict(self.markers),
            "active_agents": list(self.active_agents),
            "phase_timing": dict(self.phase_timing),
            "discarded": self._discarded,
            "discard_step": self._discard_step,
            "consecutive_pose_fail": self._consecutive_pose_fail,
            "atomic_state": {
                "plate_hold_steps": self.plate_hold_steps,
                "plate_bonus_steps": 0,
                "plate_bonus_steps_required": 0,
            },
            "step_count": self.step_index,
            "reset_state": self.reset_state,
            "records": self.records,
            "trace_dir": str(self.trace_dir) if self.trace_dir is not None else None,
            "steps_path": str(self.steps_path) if self.steps_path is not None else None,
            "log": str(self.runner.log_path) if self.runner and self.runner.log_path else None,
            "force_restart_on_close": self._force_restart_on_close,
            "failure_reason": self._failure_reason,
            "mock": self.config.mock,
        }


def agent_key(agent: str) -> str:
    return "agent_a" if agent == "AgentA" else "agent_b"


def normalize_action(value: Any) -> str:
    action = str(value).strip()
    return action if action in ALLOWED_ACTIONS else "wait"


def angle_delta_degrees(current: float, target: float) -> float:
    return (float(current) - float(target) + 180.0) % 360.0 - 180.0


def pressure_plate_region(task: dict[str, Any]) -> list[float] | None:
    goal = task.get("players", {}).get("player_a", {}).get("goal", {})
    region = goal.get("target_region") if isinstance(goal, dict) else None
    if isinstance(region, list) and len(region) >= 6:
        return [float(v) for v in region[:6]]
    return None


def pressure_plate_target_center(task: dict[str, Any]) -> list[float]:
    region = pressure_plate_region(task)
    if region is not None:
        x0, y0, z0, x1, _y1, z1 = region
        return [(min(x0, x1) + max(x0, x1) + 1.0) / 2.0, y0 + 0.05, (min(z0, z1) + max(z0, z1) + 1.0) / 2.0]
    plate = task["players"]["player_a"]["goal"]["target_pos"]
    return [float(plate[0]) + 0.5, float(plate[1]) + 0.05, float(plate[2]) + 0.5]


def xz_distance_to_pressure_plate(task: dict[str, Any], pose: Any) -> float | None:
    if not isinstance(pose, dict):
        return None
    pos = pose.get("pos")
    if not isinstance(pos, list) or len(pos) < 3:
        return None
    region = pressure_plate_region(task)
    if region is None:
        target = pressure_plate_target_center(task)
        return math.hypot(float(pos[0]) - float(target[0]), float(pos[2]) - float(target[2]))
    x0, _y0, z0, x1, _y1, z1 = region
    min_x, max_x = min(x0, x1), max(x0, x1) + 1.0
    min_z, max_z = min(z0, z1), max(z0, z1) + 1.0
    x, z = float(pos[0]), float(pos[2])
    dx = max(min_x - x, 0.0, x - max_x)
    dz = max(min_z - z, 0.0, z - max_z)
    return math.hypot(dx, dz)


def view_alignment(pose: Any, target: list[float], target_name: str, eye_height: float) -> dict[str, float | str | list[float]]:
    if not isinstance(pose, dict):
        return {"target": target_name, "score": 0.0, "error": "missing_pose"}
    pos = pose.get("pos")
    if not isinstance(pos, list) or len(pos) < 3:
        return {"target": target_name, "score": 0.0, "error": "missing_position"}

    eye = [float(pos[0]), float(pos[1]) + float(eye_height), float(pos[2])]
    dx = float(target[0]) - eye[0]
    dy = float(target[1]) - eye[1]
    dz = float(target[2]) - eye[2]
    horizontal = max(math.hypot(dx, dz), 0.001)
    desired_yaw = math.degrees(math.atan2(-dx, dz))
    desired_pitch = math.degrees(math.atan2(-dy, horizontal))
    yaw_delta = angle_delta_degrees(float(pose.get("yaw", 0.0)), desired_yaw)
    pitch_delta = float(pose.get("pitch", 0.0)) - desired_pitch
    yaw_error = abs(yaw_delta)
    pitch_error = abs(pitch_delta)
    yaw_score = max(0.0, 1.0 - yaw_error / 90.0)
    pitch_score = max(0.0, 1.0 - pitch_error / 45.0)
    score = yaw_score * pitch_score
    return {
        "target": target_name,
        "score": round(score, 4),
        "yaw_error": round(yaw_error, 2),
        "yaw_delta": round(yaw_delta, 2),
        "pitch_error": round(pitch_error, 2),
        "pitch_delta": round(pitch_delta, 2),
        "desired_yaw": round(desired_yaw, 2),
        "desired_pitch": round(desired_pitch, 2),
    }


def correct_alignment_action_reward(action: Any, before_alignment: Any, after_alignment: Any = None) -> float:
    if not isinstance(before_alignment, dict):
        return 0.0
    action = normalize_action(action)
    yaw_delta = before_alignment.get("yaw_delta")
    pitch_delta = before_alignment.get("pitch_delta")
    try:
        yaw_delta_f = float(yaw_delta)
    except (TypeError, ValueError):
        yaw_delta_f = 0.0
    try:
        pitch_delta_f = float(pitch_delta)
    except (TypeError, ValueError):
        pitch_delta_f = 0.0

    before_score = alignment_score(before_alignment)
    after_score = alignment_score(after_alignment)
    reward = 0.0

    if yaw_delta_f > 15.0 and action == "turn_left":
        reward += 0.15
    elif yaw_delta_f < -15.0 and action == "turn_right":
        reward += 0.15
    elif abs(yaw_delta_f) > 15.0:
        if action == "forward":
            reward -= 0.10
        elif action in {"turn_left", "turn_right"}:
            reward -= 0.05
    elif pitch_delta_f > 10.0 and action == "look_up":
        reward += 0.08
    elif pitch_delta_f < -10.0 and action == "look_down":
        reward += 0.08
    elif abs(pitch_delta_f) > 10.0 and action == "forward":
        reward -= 0.05
    elif action == "forward":
        reward += 0.05

    if action in {"turn_left", "turn_right", "look_up", "look_down"}:
        improvement = after_score - before_score
        if improvement > 0.03:
            reward += min(0.10, improvement * 0.30)
        elif improvement < -0.03:
            reward -= min(0.05, abs(improvement) * 0.20)

    return round(max(-0.10, min(0.25, reward)), 4)


def alignment_score(alignment: Any) -> float:
    if not isinstance(alignment, dict):
        return 0.0
    try:
        return float(alignment.get("score", 0.0))
    except (TypeError, ValueError):
        return 0.0


def xz_distance(pose: Any, target_xz: list[float]) -> float | None:
    if not isinstance(pose, dict):
        return None
    pos = pose.get("pos")
    if not isinstance(pos, list) or len(pos) < 3:
        return None
    return math.hypot(float(pos[0]) - float(target_xz[0]), float(pos[2]) - float(target_xz[1]))


def progress_ratio(initial_distance: float | None, current_distance: float | None) -> float:
    if initial_distance is None or current_distance is None or initial_distance <= 1e-6:
        return 0.0
    return max(0.0, min(1.0, (initial_distance - current_distance) / initial_distance))


def parse_joint_action(text: str) -> tuple[dict[str, str], str]:
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            payload = json.loads(text[start : end + 1])
        else:
            payload = {}
    except Exception:
        payload = {}
    action_a = payload.get("agent_a", payload.get("AgentA", payload.get("action_a", payload.get("action", "wait"))))
    action_b = payload.get("agent_b", payload.get("AgentB", payload.get("action_b", payload.get("action", "wait"))))
    actions = {"agent_a": normalize_action(action_a), "agent_b": normalize_action(action_b)}
    reason = str(payload.get("reason", "")) if isinstance(payload, dict) else ""
    return actions, reason


def parse_agent_action(text: str, agent_name: str) -> tuple[str, str]:
    try:
        start = text.find("{")
        end = text.rfind("}")
        payload = json.loads(text[start : end + 1]) if start >= 0 and end > start else {}
    except Exception:
        payload = {}
    action_key = agent_key(agent_name)
    action = payload.get("action", payload.get(action_key, payload.get(agent_name, "wait")))
    reason = str(payload.get("reason", "")) if isinstance(payload, dict) else ""
    return normalize_action(action), reason


def _compact_pose(pose: Any, include_agent: bool = True) -> dict[str, Any]:
    if not isinstance(pose, dict):
        return {"error": "missing"}
    pos = pose.get("pos")
    compact: dict[str, Any] = {"agent": pose.get("agent")} if include_agent else {}
    if isinstance(pos, list) and len(pos) >= 3:
        compact["pos"] = [round(float(pos[0]), 2), round(float(pos[1]), 2), round(float(pos[2]), 2)]
    if "yaw" in pose:
        compact["yaw"] = round(float(pose.get("yaw", 0.0)), 1)
    if "pitch" in pose:
        compact["pitch"] = round(float(pose.get("pitch", 0.0)), 1)
    if "error" in pose:
        compact["error"] = pose.get("error")
    return compact


def pose_delta(before: Any, after: Any) -> dict[str, Any]:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {}
    deltas: dict[str, Any] = {}
    for agent in AGENTS:
        before_pose = before.get(agent)
        after_pose = after.get(agent)
        if not isinstance(before_pose, dict) or not isinstance(after_pose, dict):
            continue
        before_pos = before_pose.get("pos")
        after_pos = after_pose.get("pos")
        if isinstance(before_pos, list) and len(before_pos) >= 3 and isinstance(after_pos, list) and len(after_pos) >= 3:
            deltas[agent] = {
                "dx": round(float(after_pos[0]) - float(before_pos[0]), 3),
                "dy": round(float(after_pos[1]) - float(before_pos[1]), 3),
                "dz": round(float(after_pos[2]) - float(before_pos[2]), 3),
            }
    return deltas


def observer_frame_path(image_info: Any) -> str | None:
    if not isinstance(image_info, dict) or image_info.get("view") != "observer":
        return None
    value = image_info.get("screenshot")
    return str(value) if value else None


def agent_frame_paths(image_info: Any) -> dict[str, str] | None:
    if not isinstance(image_info, dict) or image_info.get("view") != "agent_pov":
        return None
    agents = image_info.get("agents") if isinstance(image_info.get("agents"), dict) else {}
    paths: dict[str, str] = {}
    for agent in AGENTS:
        info = agents.get(agent) if isinstance(agents.get(agent), dict) else {}
        screenshot = info.get("screenshot")
        if screenshot:
            paths[agent] = str(screenshot)
    return paths or None


def image_ticks(image_info: Any, key: str) -> Any:
    if not isinstance(image_info, dict):
        return None
    if image_info.get("view") == "observer":
        return image_info.get(key)
    if image_info.get("view") == "agent_pov":
        agents = image_info.get("agents") if isinstance(image_info.get("agents"), dict) else {}
        return {agent: agents.get(agent, {}).get(key) for agent in AGENTS if isinstance(agents.get(agent), dict)}
    return None


def format_observation(observation: dict[str, Any]) -> str:
    poses = observation.get("poses") if isinstance(observation.get("poses"), dict) else {}
    image = observation.get("image") if isinstance(observation.get("image"), dict) else None
    compact = {
        "step": observation.get("step"),
        "task": display_task,
        "task_mode": observation.get("task_mode", "multiagent"),
        "controlled_agent": observation.get("controlled_agent"),
        "atomic_role": observation.get("atomic_role"),
        "active_agents": display_active_agents,
        "targets": observation.get("targets"),
        "poses": {"AgentA": _compact_pose(poses.get("AgentA")), "AgentB": _compact_pose(poses.get("AgentB"))},
        "markers": display_markers,
        "atomic_state": observation.get("atomic_state"),
        "done": observation.get("done"),
        "image_view": image.get("view") if image else None,
        "allowed_actions": ALLOWED_ACTIONS,
        "required_output": {"agent_a": "one_allowed_action", "agent_b": "one_allowed_action", "reason": "detailed_reason_with_visual_evidence_target_position_teammate_state_and_action_rationale"},
    }
    return "Minecraft observation JSON:\n" + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def format_agent_observation(observation: dict[str, Any], agent_name: str) -> str:
    poses = observation.get("poses") if isinstance(observation.get("poses"), dict) else {}
    task_mode = str(observation.get("task_mode", "multiagent"))
    teammate = None if task_mode == "single_agent" else ("AgentB" if agent_name == "AgentA" else "AgentA")
    atomic_role = str(observation.get("atomic_role") or "")
    if task_mode == "single_agent":
        if agent_name == "AgentA":
            role_goal = "Your task is to find the pressure plate and step onto it, using only what you see."
            visual_focus = (
                "The pressure plate is the colored region on the floor. Keep it near the center of your view while you "
                "navigate toward it. Use look_up/look_down only for brief pitch corrections, not as a repeated search action. "
                "Use turn_left/turn_right to center the pressure plate and move forward when it is aligned."
            )
        else:
            role_goal = "Your task is to find the elevator door and walk into it, using only what you see."
            visual_focus = (
                "Focus on the elevator door. If it is not near the center of your view, use turn_left/turn_right "
                "to bring it toward the center before moving forward. Walk into the doorway once it is aligned."
            )
    elif agent_name == "AgentA":
        role_goal = "You are AgentA. Your job is to find the pressure plate and step onto it, using only what you see."
        visual_focus = (
            "The pressure plate is the colored region on the floor. Keep it near the center of your view while you navigate toward it. "
            "Use look_up/look_down only for brief pitch corrections, not as a repeated search action. "
            "Use turn_left/turn_right to center the pressure plate and move forward when it is aligned."
        )
    else:
        role_goal = "You are AgentB. Your job is to find the elevator door and walk into it, using only what you see."
        visual_focus = (
            "Focus on the elevator door. If it is not near the center of your view, use turn_left/turn_right "
            "to bring it toward the center before moving forward."
        )
    raw_markers = observation.get("markers") if isinstance(observation.get("markers"), dict) else {}
    if task_mode == "single_agent" and agent_name == "AgentA":
        display_task = "Find the pressure plate and step onto it, using only what you see."
        display_agent = "self"
        display_markers = {"pressure_plate_powered": raw_markers.get("pressure_plate_powered")}
        display_active_agents = None
        display_atomic_role = None
    elif task_mode == "single_agent":
        display_task = "Find the elevator door and walk into it, using only what you see."
        display_agent = "self"
        display_markers = {"within_elevator_door_1": raw_markers.get("agent_b_within_elevator_door_1")}
        display_active_agents = None
        display_atomic_role = None
    else:
        display_task = observation.get("description")
        display_agent = agent_name
        display_markers = raw_markers
        display_active_agents = observation.get("active_agents")
        display_atomic_role = None
    compact = {
        "step": observation.get("step"),
        "task": display_task,
        "your_agent": display_agent,
        "teammate": teammate,
        "task_mode": task_mode,
        "atomic_role": display_atomic_role,
        "active_agents": display_active_agents,
        "scene_colors": {
            "walls_floor_ceiling": "white",
            "pressure_plate": "red",
            "elevator_door": "black",
        },
        "your_role": role_goal,
        "visual_focus_instruction": visual_focus,
        "markers": display_markers,
        "atomic_state": observation.get("atomic_state"),
        "done": observation.get("done"),
        "allowed_actions": ALLOWED_ACTIONS,
        "required_output": {"action": "one_allowed_action", "reason": "detailed_reason_with_visual_evidence_and_action_rationale"},
    }
    return "Minecraft first-person agent observation JSON:\n" + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

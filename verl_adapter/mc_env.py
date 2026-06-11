from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
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
    save_trace: bool = True
    trace_root: Path | None = None


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


def training_instance_config(base_config: InstanceConfig, prefix: str, index: int, tickgate_base_port: int) -> InstanceConfig:
    if index < 1:
        raise ValueError(f"instance index must be >= 1, got {index}")
    name = f"{prefix}-{index:02d}"
    root = (PROJECT_ROOT / "env" / name).resolve()
    return replace(
        base_config,
        name=name,
        root=root,
        tickgate_port=int(tickgate_base_port) + index - 1,
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
    raw_args.setdefault("action_ticks", 4)
    raw_args.setdefault("max_steps", 20)
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
        self.last_reward_breakdown: dict[str, Any] = {}
        self.trace_dir = self._make_trace_dir()
        self.frames_dir = self.trace_dir / "observer_frames" if self.trace_dir is not None else None
        self.agent_frames_dir = self.trace_dir / "agent_pov_frames" if self.trace_dir is not None else None
        self.llm_frames_dir = self.trace_dir / "llm_input_frames" if self.trace_dir is not None else None
        self.steps_path = self.trace_dir / "steps.jsonl" if self.trace_dir is not None else None
        self._mock_positions = {
            "AgentA": [5.5, -58.0, 2.5],
            "AgentB": [2.5, -58.0, 3.5],
        }

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
        pack_dst = self.args.pack_dst or datapack_dst(instance_config.root)
        ensure_datapack(self.args.pack_src, pack_dst, refresh=getattr(self.args, "refresh_pack", False))
        self.runner = InstanceRunner(instance_config, Path(self.args.log_dir))
        self.runner.start()
        setup_rollout_world(self.runner, self.commands, self.task, self.args)
        spawn_agents(self.runner, self.commands)
        self.reset_state = reset_agents(self.runner, self.commands, self.task, self.args)
        return self.observe()

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
        for agent in AGENTS:
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

    def close(self) -> None:
        if self.runner is not None:
            self.runner.close()
            self.runner = None

    def observe(self) -> dict[str, Any]:
        if self.config.mock:
            poses = {
                agent: {"agent": agent, "type": "mock", "pos": list(pos), "yaw": 0.0, "pitch": 0.0}
                for agent, pos in self._mock_positions.items()
            }
            observation = {
                "step": self.step_index,
                "task_id": self.task.get("id"),
                "scene_id": self.task.get("scene_id"),
                "description": self.task.get("task_description"),
                "poses": poses,
                "markers": dict(self.markers),
                "done": all(self.markers.values()),
            }
            self._annotate_reward(observation)
            self.last_observation = observation
            return observation
        if self.runner is None:
            raise RuntimeError("MinecraftRolloutEnv.observe called before start")
        poses = {"AgentA": query_agent_pose(self.runner, "AgentA"), "AgentB": query_agent_pose(self.runner, "AgentB")}
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        self.markers, _ = query_success_markers(self.runner, self.commands, self.task, stamp)
        observation = {
            "step": self.step_index,
            "task_id": self.task.get("id"),
            "scene_id": self.task.get("scene_id"),
            "description": self.task.get("task_description"),
            "poses": poses,
            "markers": dict(self.markers),
            "done": all(self.markers.values()),
        }
        image = self._capture_observation_image(poses)
        if image is not None:
            observation["image"] = image
        self._annotate_reward(observation)
        self.last_observation = observation
        return observation

    def step(self, actions: dict[str, Any]) -> dict[str, Any]:
        before_observation = self.last_observation
        raw_action_a = actions.get("agent_a") or actions.get("AgentA") or actions.get("action_a") or "wait"
        raw_action_b = actions.get("agent_b") or actions.get("AgentB") or actions.get("action_b") or "wait"
        action_a = normalize_action(raw_action_a)
        action_b = normalize_action(raw_action_b)
        action_meta = actions.get("_meta") if isinstance(actions.get("_meta"), dict) else {}
        if self.config.mock:
            if action_a == "forward":
                self._mock_positions["AgentA"][2] += 0.5
            if action_b == "forward":
                self._mock_positions["AgentB"][2] += 0.5
            self.markers["pressure_plate_powered"] = self.step_index >= 0 and action_a in {"wait", "forward"}
            self.markers["door_block_air"] = self.markers["pressure_plate_powered"]
            self.markers["agent_b_fully_in_second_room"] = self._mock_positions["AgentB"][2] >= 5.5
        else:
            if self.runner is None:
                raise RuntimeError("MinecraftRolloutEnv.step called before start")
            send_agent_action(self.runner, "AgentA", action_a)
            send_agent_action(self.runner, "AgentB", action_b)
            if self.runner.tickgate is not None:
                self.runner.tickgate.cmd(f"advance_wait {self.args.action_ticks} 1", timeout=90.0)
        self.step_index += 1
        obs = self.observe()
        image_info = obs.get("image") if isinstance(obs.get("image"), dict) else None
        reward_breakdown = obs.get("reward_breakdown") if isinstance(obs.get("reward_breakdown"), dict) else {}
        shaped_reward = float(obs.get("reward", 0.0) or 0.0)
        record = {
            "step": self.step_index,
            "raw_actions": {"agent_a": raw_action_a, "agent_b": raw_action_b},
            "actions": {"agent_a": action_a, "agent_b": action_b},
            "agent_decisions": action_meta.get("agent_decisions"),
            "llm_input_frames": action_meta.get("llm_input_frames"),
            "poses_before": before_observation.get("poses") if isinstance(before_observation, dict) else None,
            "poses_after": obs.get("poses"),
            "pose_delta": pose_delta(
                before_observation.get("poses") if isinstance(before_observation, dict) else None,
                obs.get("poses"),
            ),
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

    def _append_trace_record(self, record: dict[str, Any]) -> None:
        if self.steps_path is None:
            return
        with self.steps_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _annotate_reward(self, observation: dict[str, Any]) -> None:
        breakdown = self._compute_reward_breakdown(observation)
        shaped_reward = float(breakdown["shaped_reward"])
        self.best_shaped_reward = max(self.best_shaped_reward, shaped_reward)
        self.last_reward_breakdown = breakdown
        observation["reward"] = shaped_reward
        observation["episode_reward"] = self.best_shaped_reward
        observation["reward_breakdown"] = breakdown

    def _compute_reward_breakdown(self, observation: dict[str, Any]) -> dict[str, Any]:
        markers = observation.get("markers") if isinstance(observation.get("markers"), dict) else {}
        binary_reward = 1.0 if all(bool(markers.get(name)) for name in self.markers) else 0.0
        marker_reward = (
            (0.3 if markers.get("pressure_plate_powered") else 0.0)
            + (0.3 if markers.get("door_block_air") else 0.0)
            + (0.4 if markers.get("agent_b_fully_in_second_room") else 0.0)
        )
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
        progress_reward = 0.0
        if not markers.get("pressure_plate_powered"):
            progress_reward += 0.05 * agent_a_progress
        if not markers.get("agent_b_fully_in_second_room"):
            progress_reward += 0.05 * agent_b_progress

        shaped_reward = min(1.0, max(binary_reward, marker_reward + progress_reward))
        return {
            "shaped_reward": shaped_reward,
            "binary_reward": binary_reward,
            "marker_reward": marker_reward,
            "progress_reward": progress_reward,
            "marker_weights": {
                "pressure_plate_powered": 0.3,
                "door_block_air": 0.3,
                "agent_b_fully_in_second_room": 0.4,
            },
            "markers": dict(markers),
            "progress": {
                "agent_a_to_plate": agent_a_progress,
                "agent_b_to_second_room": agent_b_progress,
            },
            "distances": distances,
            "initial_distances": dict(self.initial_goal_distances or {}),
        }

    def _goal_distances(self, poses: Any) -> dict[str, float | None]:
        poses = poses if isinstance(poses, dict) else {}
        plate = self.task["players"]["player_a"]["goal"]["target_pos"]
        plate_center = [float(plate[0]) + 0.5, float(plate[2]) + 0.5]
        b_goal = second_room_entry_goal(self.task)["target_center"]
        b_center = [float(b_goal[0]), float(b_goal[2])]
        return {
            "agent_a_to_plate": xz_distance(poses.get("AgentA"), plate_center),
            "agent_b_to_second_room": xz_distance(poses.get("AgentB"), b_center),
        }

    def reward(self) -> float:
        return self.best_shaped_reward

    def summary(self) -> dict[str, Any]:
        return {
            "task_id": self.task.get("id"),
            "scene_id": self.task.get("scene_id"),
            "success": all(self.markers.values()),
            "reward": self.reward(),
            "binary_reward": 1.0 if all(self.markers.values()) else 0.0,
            "reward_breakdown": self.last_reward_breakdown,
            "markers": dict(self.markers),
            "step_count": self.step_index,
            "reset_state": self.reset_state,
            "records": self.records,
            "trace_dir": str(self.trace_dir) if self.trace_dir is not None else None,
            "steps_path": str(self.steps_path) if self.steps_path is not None else None,
            "log": str(self.runner.log_path) if self.runner and self.runner.log_path else None,
            "mock": self.config.mock,
        }


def agent_key(agent: str) -> str:
    return "agent_a" if agent == "AgentA" else "agent_b"


def normalize_action(value: Any) -> str:
    action = str(value).strip()
    return action if action in ALLOWED_ACTIONS else "wait"


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


def _compact_pose(pose: Any) -> dict[str, Any]:
    if not isinstance(pose, dict):
        return {"error": "missing"}
    pos = pose.get("pos")
    compact: dict[str, Any] = {"agent": pose.get("agent")}
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
        "task": observation.get("description"),
        "poses": {"AgentA": _compact_pose(poses.get("AgentA")), "AgentB": _compact_pose(poses.get("AgentB"))},
        "markers": observation.get("markers"),
        "done": observation.get("done"),
        "image_view": image.get("view") if image else None,
        "allowed_actions": ALLOWED_ACTIONS,
        "required_output": {"agent_a": "one_allowed_action", "agent_b": "one_allowed_action", "reason": "short reason"},
    }
    return "Minecraft observation JSON:\n" + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def format_agent_observation(observation: dict[str, Any], agent_name: str) -> str:
    teammate = "AgentB" if agent_name == "AgentA" else "AgentA"
    poses = observation.get("poses") if isinstance(observation.get("poses"), dict) else {}
    if agent_name == "AgentA":
        role_goal = "You are AgentA. Your job is to find, step onto, and keep holding the pressure plate when needed."
    else:
        role_goal = "You are AgentB. Your job is to move through the doorway/elevator door into the second room when it is open."
    compact = {
        "step": observation.get("step"),
        "task": observation.get("description"),
        "your_agent": agent_name,
        "teammate": teammate,
        "your_role": role_goal,
        "your_pose": _compact_pose(poses.get(agent_name)),
        "teammate_pose": _compact_pose(poses.get(teammate)),
        "markers": observation.get("markers"),
        "done": observation.get("done"),
        "allowed_actions": ALLOWED_ACTIONS,
        "required_output": {"action": "one_allowed_action", "reason": "short reason"},
    }
    return "Minecraft first-person agent observation JSON:\n" + json.dumps(compact, ensure_ascii=False, separators=(",", ":"))

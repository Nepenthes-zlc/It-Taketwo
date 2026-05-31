from __future__ import annotations

import json
import random
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from .instance_pool import ensure_envmine_on_path
from .paths import WorkspacePaths, discover_workspace


ACTION_TO_PUPPET = {
    "wait": "stop",
    "forward": "w 0.12",
    "backward": "s 0.12",
    "strafe_left": "a 0.12",
    "strafe_right": "d 0.12",
    "jump": "jump 0.2",
    "turn_left": "turn -20 0 0.1",
    "turn_right": "turn 20 0 0.1",
    "look_up": "turn 0 -15 0.1",
    "look_down": "turn 0 15 0.1",
}
ALLOWED_ACTIONS = list(ACTION_TO_PUPPET)
PLAYER_HALF_WIDTH = 0.3
SECOND_ROOM_ENTRY_DEPTH = 1.0


@dataclass
class EnvMineEpisodeConfig:
    tasks: Path
    pack_src: Path
    log_dir: Path
    output_dir: Path | None = None
    task_index: int = 0
    random_seed: int | None = None
    max_steps: int = 20
    action_ticks: int = 4
    capture_ticks: int = 2
    capture_render_frames: int = 2
    pov_camera_settle_ticks: int = 16
    pov_extra_settle_ticks: int = 8
    pov_settle_render_frames: int = 10
    capture_timeout: float = 90.0
    hide_hud: bool = True
    refresh_pack: bool = False
    randomize_starts: bool = False
    start_position_jitter: float = 0.6
    start_yaw_jitter: float = 35.0
    write_debug_images: bool = False


@dataclass
class EnvMineObservation:
    step: int
    agent_images: dict[str, bytes]
    poses: dict[str, Any]
    image_paths: dict[str, str] = field(default_factory=dict)


@dataclass
class EnvMineStepResult:
    reward: float
    done: bool
    markers: dict[str, bool]
    record: dict[str, Any]


def _to_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()


def load_task(tasks_path: Path, task_index: int) -> dict[str, Any]:
    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(f"task file has no tasks list: {tasks_path}")
    if task_index < 0 or task_index >= len(tasks):
        raise IndexError(f"task_index {task_index} out of range for {tasks_path} with {len(tasks)} tasks")
    return tasks[task_index]


def game_cmd(runner: Any, commands: list[str], command: str, ticks: int = 20) -> dict[str, Any]:
    if runner.tickgate is None or runner.puppet is None:
        raise RuntimeError("runner is not connected")
    commands.append(command)
    runner.puppet.send("cmd " + command, wait=False)
    return runner.tickgate.cmd(f"advance_wait {ticks} 1", timeout=90.0)


def second_room_entry_goal(task: dict[str, Any]) -> dict[str, Any]:
    region = task["players"]["player_b"]["goal"]["target_region"]
    start_pos = task["players"]["player_b"]["start_pos"]
    center_x = (float(region[0]) + float(region[3])) / 2.0 + 0.5
    center_z = (float(region[2]) + float(region[5])) / 2.0 + 0.5
    if int(region[2]) == int(region[5]):
        axis = "z"
        door_coord = float(region[2])
        direction = 1.0 if float(start_pos[2]) <= door_coord else -1.0
        center_z = door_coord + 0.5 + direction * SECOND_ROOM_ENTRY_DEPTH
    elif int(region[0]) == int(region[3]):
        axis = "x"
        door_coord = float(region[0])
        direction = 1.0 if float(start_pos[0]) <= door_coord else -1.0
        center_x = door_coord + 0.5 + direction * SECOND_ROOM_ENTRY_DEPTH
    else:
        axis = "unknown"
        door_coord = 0.0
        direction = 0.0
    return {
        "axis": axis,
        "door_coord": door_coord,
        "direction": direction,
        "target_center": [center_x, float(region[1]), center_z],
    }


def agent_fully_inside_second_room(task: dict[str, Any], pose: dict[str, Any]) -> bool:
    pos = pose.get("pos") if isinstance(pose, dict) else None
    if not isinstance(pos, list) or len(pos) < 3:
        return False
    goal = second_room_entry_goal(task)
    axis = goal["axis"]
    direction = float(goal["direction"])
    if axis not in {"x", "z"} or direction == 0.0:
        return False
    coord_index = 0 if axis == "x" else 2
    coord = float(pos[coord_index])
    door_coord = float(goal["door_coord"])
    interior_boundary = door_coord + 1.0 if direction > 0 else door_coord
    if direction > 0:
        return coord - PLAYER_HALF_WIDTH >= interior_boundary
    return coord + PLAYER_HALF_WIDTH <= interior_boundary


def randomized_reset_pose(
    base_pos: list[float],
    rng: random.Random,
    args: SimpleNamespace,
) -> tuple[list[float], float, float]:
    x_jitter = rng.uniform(-args.start_position_jitter, args.start_position_jitter)
    z_jitter = rng.uniform(-args.start_position_jitter, args.start_position_jitter)
    yaw = rng.uniform(-args.start_yaw_jitter, args.start_yaw_jitter)
    return [float(base_pos[0]) + x_jitter, float(base_pos[1]), float(base_pos[2]) + z_jitter], yaw, 0.0


def query_agent_pose(runner: Any, agent: str) -> dict[str, Any]:
    if runner.puppet is None:
        raise RuntimeError("Puppet is not connected")

    def parse_entity_line(raw_text: str) -> dict[str, Any] | None:
        for line in raw_text.splitlines():
            parts = line.strip().split()
            if len(parts) >= 8 and parts[0] == "ENTITY" and parts[1].lower() == agent.lower():
                return {
                    "agent": agent,
                    "type": parts[2],
                    "pos": [float(parts[3]), float(parts[4]), float(parts[5])],
                    "yaw": float(parts[6]),
                    "pitch": float(parts[7]),
                    "raw": line.strip(),
                }
        return None

    runner.puppet.sock.settimeout(1.0)
    runner.puppet.sock.sendall((f"query_entity {agent}\n").encode("utf-8"))
    if runner.tickgate is not None:
        runner.tickgate.cmd("advance_wait 3 1", timeout=30.0)
    chunks: list[str] = []
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            data = runner.puppet.sock.recv(4096)
        except TimeoutError:
            if runner.tickgate is not None:
                runner.tickgate.cmd("advance_wait 3 1", timeout=30.0)
            continue
        if not data:
            break
        chunks.append(data.decode("utf-8", "ignore"))
        parsed = parse_entity_line("".join(chunks))
        if parsed is not None:
            return parsed
    raw = "".join(chunks).strip()
    return {"agent": agent, "error": raw}


def capture_agent_pov(runner: Any, agent: str, pose: dict[str, Any], args: SimpleNamespace) -> dict[str, Any]:
    pos = pose.get("pos") if isinstance(pose, dict) else None
    if not isinstance(pos, list) or len(pos) < 3:
        raise RuntimeError(f"cannot capture {agent} POV without a valid pose: {pose!r}")
    if runner.puppet is not None:
        runner.puppet.send(f"pov {agent}", wait=False)
        runner.puppet.send("camera first_person", wait=False)
    if runner.tickgate is not None:
        ticks = args.pov_camera_settle_ticks + args.pov_extra_settle_ticks
        runner.tickgate.cmd(f"advance_wait {ticks} {args.pov_settle_render_frames}", timeout=30.0)
    image = runner.capture_image(
        ticks=args.capture_ticks,
        render_frames=args.capture_render_frames,
        timeout=args.capture_timeout,
    )
    image["camera_entity"] = agent
    return image


def send_agent_action(runner: Any, agent: str, action: str) -> None:
    if runner.puppet is None:
        raise RuntimeError("Puppet is not connected")
    runner.puppet.send(f"{agent} {ACTION_TO_PUPPET[action]}", wait=False)


def query_success_markers(
    runner: Any,
    commands: list[str],
    task: dict[str, Any],
    stamp: str,
) -> tuple[dict[str, bool], str]:
    player_a = task["players"]["player_a"]
    plate = player_a["goal"]["target_pos"]
    region = task["players"]["player_b"]["goal"]["target_region"]
    marker_plate = f"LOWLEVEL_TASK{task['id']}_PLATE_OK_{stamp}"
    marker_done = f"LOWLEVEL_TASK{task['id']}_DONE_{stamp}"
    game_cmd(
        runner,
        commands,
        (
            f"execute if block {int(plate[0])} {int(plate[1])} {int(plate[2])} "
            f"minecraft:stone_pressure_plate[powered=true] run say {marker_plate}"
        ),
        5,
    )
    game_cmd(runner, commands, f"execute if block {region[0]} {region[1]} {region[2]} minecraft:air run say {marker_done}", 5)
    agent_b_pose = query_agent_pose(runner, "AgentB")
    time.sleep(0.2)
    log_text = Path(runner.log_path).read_text(encoding="utf-8", errors="ignore") if runner.log_path else ""
    return {
        "pressure_plate_powered": marker_plate in log_text,
        "agent_b_fully_in_second_room": agent_fully_inside_second_room(task, agent_b_pose),
        "door_block_air": marker_done in log_text,
    }, log_text


class EnvMineLowLevelEpisode:
    def __init__(
        self,
        instance_config: Any,
        cfg: EnvMineEpisodeConfig,
        *,
        workspace: WorkspacePaths | None = None,
    ):
        self.workspace = ensure_envmine_on_path(workspace or discover_workspace())
        from envmine.runner import InstanceRunner

        self.instance_config = instance_config
        self.cfg = cfg
        self.args = self._args_from_config(cfg)
        self.task = load_task(cfg.tasks, cfg.task_index)
        self.runner = InstanceRunner(instance_config, cfg.log_dir)
        self.commands: list[str] = []
        self.records: list[dict[str, Any]] = []
        self.reset_state: dict[str, Any] = {}
        self.markers = {
            "pressure_plate_powered": False,
            "agent_b_fully_in_second_room": False,
            "door_block_air": False,
        }
        self._started = False

    @staticmethod
    def _args_from_config(cfg: EnvMineEpisodeConfig) -> SimpleNamespace:
        return SimpleNamespace(
            start_position_jitter=cfg.start_position_jitter,
            start_yaw_jitter=cfg.start_yaw_jitter,
            pov_camera_settle_ticks=cfg.pov_camera_settle_ticks,
            pov_extra_settle_ticks=cfg.pov_extra_settle_ticks,
            pov_settle_render_frames=cfg.pov_settle_render_frames,
            capture_ticks=cfg.capture_ticks,
            capture_render_frames=cfg.capture_render_frames,
            capture_timeout=cfg.capture_timeout,
        )

    def _pack_dst(self) -> Path:
        return self.instance_config.root / "run" / "saves" / "New World" / "datapacks" / "multiagent_scene_pack"

    def _sync_datapack(self) -> None:
        pack_dst = self._pack_dst()
        if self.cfg.refresh_pack and pack_dst.exists():
            shutil.rmtree(pack_dst)
        if not pack_dst.exists():
            shutil.copytree(self.cfg.pack_src, pack_dst)

    def start(self) -> EnvMineObservation:
        self._sync_datapack()
        if self.cfg.output_dir is not None:
            self.cfg.output_dir.mkdir(parents=True, exist_ok=True)

        player_a = self.task["players"]["player_a"]
        player_b = self.task["players"]["player_b"]
        rng = random.Random(self.cfg.random_seed)

        self.runner.start()
        self._started = True
        game_cmd(self.runner, self.commands, "reload", 40)
        game_cmd(self.runner, self.commands, "gamerule commandBlockOutput false", 5)
        game_cmd(self.runner, self.commands, "gamerule sendCommandFeedback false", 5)
        game_cmd(self.runner, self.commands, "gamerule logAdminCommands false", 5)
        game_cmd(self.runner, self.commands, f"function {self.task['scene_clear_function']}", 20)
        game_cmd(self.runner, self.commands, f"function {self.task['scene_setup_function']}", 40)
        game_cmd(self.runner, self.commands, "gamemode spectator Dev", 5)
        game_cmd(self.runner, self.commands, "effect give Dev minecraft:night_vision 999 0 true", 5)

        if self.runner.puppet is not None:
            self.runner.puppet.send("camera first_person", wait=False)
            if self.runner.tickgate is not None:
                self.runner.tickgate.cmd("advance_wait 5 5", timeout=30.0)
        if self.cfg.hide_hud and self.runner.puppet is not None:
            self.runner.puppet.send("f1", wait=False)
            if self.runner.tickgate is not None:
                self.runner.tickgate.cmd("advance_wait 5 1", timeout=30.0)

        game_cmd(self.runner, self.commands, "player AgentA spawn", 40)
        game_cmd(self.runner, self.commands, "player AgentB spawn", 40)
        game_cmd(self.runner, self.commands, "gamemode creative AgentA", 5)
        game_cmd(self.runner, self.commands, "gamemode creative AgentB", 5)
        game_cmd(self.runner, self.commands, "effect give AgentA minecraft:glowing 999 0 true", 5)
        game_cmd(self.runner, self.commands, "effect give AgentB minecraft:glowing 999 0 true", 5)

        a_start = [float(v) for v in player_a["start_pos"]]
        b_start = [float(v) for v in player_b["start_pos"]]
        a_yaw = 0.0
        b_yaw = 0.0
        if self.cfg.randomize_starts:
            a_start, a_yaw, _ = randomized_reset_pose(a_start, rng, self.args)
            b_start, b_yaw, _ = randomized_reset_pose(b_start, rng, self.args)

        self.reset_state = {
            "randomize_starts": self.cfg.randomize_starts,
            "random_seed": self.cfg.random_seed,
            "AgentA": {"pos": a_start, "yaw": a_yaw, "pitch": 0.0},
            "AgentB": {"pos": b_start, "yaw": b_yaw, "pitch": 0.0},
        }
        game_cmd(self.runner, self.commands, f"tp AgentA {a_start[0]:.3f} {a_start[1]:.3f} {a_start[2]:.3f} {a_yaw:.3f} 0.0", 20)
        game_cmd(self.runner, self.commands, f"tp AgentB {b_start[0]:.3f} {b_start[1]:.3f} {b_start[2]:.3f} {b_yaw:.3f} 0.0", 20)
        return self.observe(0)

    def observe(self, step_index: int) -> EnvMineObservation:
        poses = {
            "AgentA": query_agent_pose(self.runner, "AgentA"),
            "AgentB": query_agent_pose(self.runner, "AgentB"),
        }
        pov_a = capture_agent_pov(self.runner, "AgentA", poses["AgentA"], self.args)
        pov_b = capture_agent_pov(self.runner, "AgentB", poses["AgentB"], self.args)
        image_paths: dict[str, str] = {}
        if self.cfg.write_debug_images and self.cfg.output_dir is not None:
            frames_dir = self.cfg.output_dir / "agent_pov_frames"
            frames_dir.mkdir(parents=True, exist_ok=True)
            a_path = frames_dir / f"rollout_step_{step_index:03d}_agent_a.png"
            b_path = frames_dir / f"rollout_step_{step_index:03d}_agent_b.png"
            a_path.write_bytes(pov_a["image_bytes"])
            b_path.write_bytes(pov_b["image_bytes"])
            image_paths = {"AgentA": str(a_path), "AgentB": str(b_path)}
        return EnvMineObservation(
            step=step_index,
            agent_images={"AgentA": pov_a["image_bytes"], "AgentB": pov_b["image_bytes"]},
            poses=poses,
            image_paths=image_paths,
        )

    def step(self, step_index: int, actions: dict[str, str], raw_response: str = "") -> EnvMineStepResult:
        agent_a = actions.get("agent_a", "wait")
        agent_b = actions.get("agent_b", "wait")
        if agent_a not in ACTION_TO_PUPPET:
            agent_a = "wait"
        if agent_b not in ACTION_TO_PUPPET:
            agent_b = "wait"

        send_agent_action(self.runner, "AgentA", agent_a)
        send_agent_action(self.runner, "AgentB", agent_b)
        if self.runner.tickgate is not None:
            self.runner.tickgate.cmd(f"advance_wait {self.cfg.action_ticks} 1", timeout=90.0)

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        self.markers, _ = query_success_markers(self.runner, self.commands, self.task, stamp)
        done = all(self.markers.values())
        reward = 1.0 if done else 0.0
        record = {
            "step": step_index,
            "actions": {"agent_a": agent_a, "agent_b": agent_b, "reason": actions.get("reason", "")},
            "raw_response": raw_response,
            "markers": self.markers,
            "reward": reward,
            "done": done,
        }
        self.records.append(record)
        return EnvMineStepResult(reward=reward, done=done, markers=dict(self.markers), record=record)

    def result_summary(self) -> dict[str, Any]:
        success = all(self.markers.values())
        return {
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "task_id": self.task.get("id"),
            "scene_id": self.task.get("scene_id"),
            "description": self.task.get("task_description"),
            "success": success,
            "episode_reward": 1.0 if success else 0.0,
            "markers": self.markers,
            "reset_state": self.reset_state,
            "step_count": len(self.records),
            "records": self.records,
            "commands": self.commands if self.cfg.write_debug_images else [],
            "log": str(self.runner.log_path) if self.runner.log_path else None,
        }

    def close(self) -> None:
        if self._started:
            self.runner.close()
            self._started = False

    def __enter__(self) -> "EnvMineLowLevelEpisode":
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

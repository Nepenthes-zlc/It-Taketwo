from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

from .env_episode import ALLOWED_ACTIONS, EnvMineEpisodeConfig, EnvMineLowLevelEpisode
from .instance_pool import acquire_instance
from .paths import discover_workspace

try:
    from omegaconf import OmegaConf
except Exception:  # pragma: no cover - verl environments normally provide omegaconf.
    OmegaConf = None

from verl.experimental.agent_loop.agent_loop import AgentLoopBase, AgentLoopOutput, register
from verl.utils.profiler import simple_timer
from verl.utils.rollout_trace import rollout_trace_op


@dataclass(frozen=True)
class ParsedActions:
    actions: dict[str, str]
    valid_json: bool
    valid_actions: bool
    error: str | None = None


def _to_plain(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return value


def _config_to_dict(config: Any) -> dict[str, Any]:
    if config is None:
        return {}
    if OmegaConf is not None and OmegaConf.is_config(config):
        return OmegaConf.to_container(config, resolve=True) or {}
    return dict(config)


def _path_from_config(value: Any, default: Path, *, base: Path | None = None) -> Path:
    if value is None or value == "":
        return default.resolve()
    path = Path(str(value)).expanduser()
    if not path.is_absolute():
        path = (base or default.parent) / path
    return path.resolve()


def _stable_seed(*parts: Any) -> int:
    digest = hashlib.sha1("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def extract_first_json_object(text: str) -> dict[str, Any]:
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object found")
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : index + 1])
    raise ValueError("unclosed JSON object")


def parse_actions(text: str) -> ParsedActions:
    try:
        parsed = extract_first_json_object(text)
    except Exception as exc:
        return ParsedActions(
            actions={"agent_a": "wait", "agent_b": "wait", "reason": f"parse error: {exc}"},
            valid_json=False,
            valid_actions=False,
            error=repr(exc),
        )

    raw_a = str(parsed.get("agent_a", parsed.get("AgentA", "wait"))).strip()
    raw_b = str(parsed.get("agent_b", parsed.get("AgentB", "wait"))).strip()
    valid_actions = raw_a in ALLOWED_ACTIONS and raw_b in ALLOWED_ACTIONS
    agent_a = raw_a if raw_a in ALLOWED_ACTIONS else "wait"
    agent_b = raw_b if raw_b in ALLOWED_ACTIONS else "wait"
    return ParsedActions(
        actions={"agent_a": agent_a, "agent_b": agent_b, "reason": str(parsed.get("reason", ""))},
        valid_json=True,
        valid_actions=valid_actions,
        error=None if valid_actions else f"invalid actions: agent_a={raw_a!r}, agent_b={raw_b!r}",
    )


def image_from_bytes(png_bytes: bytes) -> Image.Image:
    return Image.open(BytesIO(png_bytes)).convert("RGB")


def build_observation_message(step_index: int, task_description: str, previous: dict[str, Any] | None = None) -> dict[str, Any]:
    previous_text = ""
    if previous is not None:
        previous_text = (
            "\nPrevious step result: "
            f"AgentA={previous.get('agent_a', 'wait')}, AgentB={previous.get('agent_b', 'wait')}."
        )
    text = f"""You control two Minecraft fake players from their own first-person screenshots.
This is a LOW-LEVEL ACTION rollout. You may only choose actions from the allowed list.
No teleport action is allowed. The executor will apply your actions to AgentA and AgentB.

Task: {task_description}
AgentA should reach and stay on the pressure plate. AgentB should pass fully through the open doorway into the second room.
AgentA must visually search for a small stone pressure plate on the floor near the elevator door.
If the pressure plate is not clearly visible under AgentA's feet or centered in view, AgentA should not wait; it should rotate or move to search.

Allowed actions for each agent: {json.dumps(ALLOWED_ACTIONS)}
Action meanings: forward/backward/strafe_left/strafe_right move relative to the agent's own current view. turn_left/turn_right rotate the view. look_up/look_down adjust the view. wait stops movement for this step.
Use only the task text and the two first-person screenshots to decide what each agent should do.
Do not assume any hidden coordinates, navigation deltas, block-state sensors, or success markers.
AgentA should wait only if the visual evidence suggests it is actually standing on and holding the pressure plate.
Step index: {step_index}.{previous_text}
The first image is AgentA first-person view. The second image is AgentB first-person view.

Return ONLY compact JSON: {{"agent_a":"action","agent_b":"action","reason":"short reason"}}"""
    return {
        "role": "user",
        "content": [
            {"type": "image"},
            {"type": "text", "text": "\nAgentA first-person view.\n"},
            {"type": "image"},
            {"type": "text", "text": "\nAgentB first-person view.\n" + text},
        ],
    }


@register("envmine_lowlevel")
class EnvMineLowLevelAgentLoop(AgentLoopBase):
    """verl AgentLoop that runs one EnvMine low-level Minecraft episode online."""

    def __init__(self, *args, envmine: dict[str, Any] | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = discover_workspace()
        cfg = _config_to_dict(envmine)
        envmine_root = self.workspace.envmine
        self.batch_config = _path_from_config(
            cfg.get("batch_config"), envmine_root / "configs" / "qwen_batch_lowlevel.json", base=self.workspace.root
        )
        self.tasks = _path_from_config(
            cfg.get("tasks"), self.workspace.root / "ConstructScene" / "generated" / "generated_tasks.json", base=self.workspace.root
        )
        self.pack_src = _path_from_config(
            cfg.get("pack_src"),
            self.workspace.root / "ConstructScene" / "generated" / "datapacks" / "multiagent_scene_pack",
            base=self.workspace.root,
        )
        self.log_dir = _path_from_config(cfg.get("log_dir"), envmine_root / "logs", base=self.workspace.root)
        self.lock_dir = _path_from_config(cfg.get("lock_dir"), self.workspace.root / "runs" / "locks", base=self.workspace.root)
        self.output_root = _path_from_config(
            cfg.get("output_root"), self.workspace.root / "runs" / "online_envmine", base=self.workspace.root
        )
        self.acquire_timeout = float(cfg.get("acquire_timeout", 600.0))
        self.max_steps = int(cfg.get("max_steps", 20))
        self.action_ticks = int(cfg.get("action_ticks", 4))
        self.capture_ticks = int(cfg.get("capture_ticks", 2))
        self.capture_render_frames = int(cfg.get("capture_render_frames", 2))
        self.pov_camera_settle_ticks = int(cfg.get("pov_camera_settle_ticks", 16))
        self.pov_extra_settle_ticks = int(cfg.get("pov_extra_settle_ticks", 8))
        self.pov_settle_render_frames = int(cfg.get("pov_settle_render_frames", 10))
        self.capture_timeout = float(cfg.get("capture_timeout", 90.0))
        self.hide_hud = bool(cfg.get("hide_hud", True))
        self.refresh_pack = bool(cfg.get("refresh_pack", False))
        self.randomize_starts = bool(cfg.get("randomize_starts", False))
        self.start_position_jitter = float(cfg.get("start_position_jitter", 0.6))
        self.start_yaw_jitter = float(cfg.get("start_yaw_jitter", 35.0))
        self.write_debug_images = bool(cfg.get("write_debug_images", False))
        self.keep_extra_records = bool(cfg.get("keep_extra_records", True))
        self.success_reward = float(cfg.get("success_reward", 1.0))
        self.failure_reward = float(cfg.get("failure_reward", 0.0))
        self.invalid_action_penalty = float(cfg.get("invalid_action_penalty", 0.05))
        self.step_penalty = float(cfg.get("step_penalty", 0.0))
        self.prompt_length = self.rollout_config.prompt_length
        self.response_length = self.rollout_config.response_length

    def _task_index(self, kwargs: dict[str, Any]) -> int:
        if "task_index" in kwargs:
            return int(_to_plain(kwargs["task_index"]))
        extra_info = kwargs.get("extra_info") or {}
        if isinstance(extra_info, dict) and "task_index" in extra_info:
            return int(_to_plain(extra_info["task_index"]))
        ground_truth = (kwargs.get("reward_model") or {}).get("ground_truth", {})
        if isinstance(ground_truth, dict) and "task_index" in ground_truth:
            return int(_to_plain(ground_truth["task_index"]))
        return 0

    def _random_seed(self, kwargs: dict[str, Any], task_index: int) -> int | None:
        explicit = kwargs.get("random_seed")
        if explicit is None:
            extra_info = kwargs.get("extra_info") or {}
            if isinstance(extra_info, dict):
                explicit = extra_info.get("random_seed")
        if explicit is not None:
            return int(_to_plain(explicit))
        uid = _to_plain(kwargs.get("uid", uuid4().hex))
        return _stable_seed(task_index, uid)

    def _episode_config(self, kwargs: dict[str, Any], task_index: int) -> EnvMineEpisodeConfig:
        random_seed = self._random_seed(kwargs, task_index)
        uid = str(_to_plain(kwargs.get("uid", uuid4().hex)))[:12]
        output_dir = self.output_root / f"task_{task_index}_seed_{random_seed}_{uid}"
        return EnvMineEpisodeConfig(
            tasks=self.tasks,
            pack_src=self.pack_src,
            log_dir=self.log_dir,
            output_dir=output_dir if self.write_debug_images else None,
            task_index=task_index,
            random_seed=random_seed,
            max_steps=self.max_steps,
            action_ticks=self.action_ticks,
            capture_ticks=self.capture_ticks,
            capture_render_frames=self.capture_render_frames,
            pov_camera_settle_ticks=self.pov_camera_settle_ticks,
            pov_extra_settle_ticks=self.pov_extra_settle_ticks,
            pov_settle_render_frames=self.pov_settle_render_frames,
            capture_timeout=self.capture_timeout,
            hide_hud=self.hide_hud,
            refresh_pack=self.refresh_pack,
            randomize_starts=self.randomize_starts,
            start_position_jitter=self.start_position_jitter,
            start_yaw_jitter=self.start_yaw_jitter,
            write_debug_images=self.write_debug_images,
        )

    async def _add_observation_tokens(
        self,
        sequence_ids: list[int],
        response_mask: list[int],
        response_logprobs: list[float],
        image_data: list[Image.Image],
        message: dict[str, Any],
        images: list[Image.Image],
        *,
        initial: bool,
        mm_processor_kwargs: dict[str, Any],
    ) -> bool:
        if initial:
            prompt_ids = await self.apply_chat_template(
                [message],
                images=images,
                mm_processor_kwargs=mm_processor_kwargs,
            )
            sequence_ids.extend(prompt_ids)
            image_data.extend(images)
            return True

        obs_ids = await self.apply_chat_template(
            [message],
            images=images,
            mm_processor_kwargs=mm_processor_kwargs,
            remove_system_prompt=True,
        )
        if len(response_mask) + len(obs_ids) >= self.response_length:
            return False
        sequence_ids.extend(obs_ids)
        response_mask.extend([0] * len(obs_ids))
        if response_logprobs:
            response_logprobs.extend([0.0] * len(obs_ids))
        image_data.extend(images)
        return True

    @rollout_trace_op
    async def run(self, sampling_params: dict[str, Any], **kwargs) -> AgentLoopOutput:
        if self.processor is None:
            raise RuntimeError("EnvMineLowLevelAgentLoop requires a vision-language processor")

        task_index = self._task_index(kwargs)
        episode_cfg = self._episode_config(kwargs, task_index)
        request_id = uuid4().hex
        sequence_ids: list[int] = []
        response_mask: list[int] = []
        response_logprobs: list[float] = []
        image_data: list[Image.Image] = []
        turn_records: list[dict[str, Any]] = []
        invalid_actions = 0
        reward_score = self.failure_reward
        previous_actions: dict[str, Any] | None = None
        metrics: dict[str, Any] = {}

        lease = acquire_instance(
            self.batch_config,
            lock_dir=self.lock_dir,
            timeout=self.acquire_timeout,
            workspace=self.workspace,
        )
        episode = EnvMineLowLevelEpisode(lease.instance, episode_cfg, workspace=self.workspace)
        try:
            obs = episode.start()
            for step_index in range(self.max_steps):
                images = [image_from_bytes(obs.agent_images["AgentA"]), image_from_bytes(obs.agent_images["AgentB"])]
                message = build_observation_message(
                    step_index,
                    str(episode.task.get("task_description", "Player A holds the pressure plate so Player B can pass.")),
                    previous=previous_actions,
                )
                ok = await self._add_observation_tokens(
                    sequence_ids,
                    response_mask,
                    response_logprobs,
                    image_data,
                    message,
                    images,
                    initial=step_index == 0,
                    mm_processor_kwargs=self._get_mm_processor_kwargs(None),
                )
                if not ok:
                    break

                remaining = self.response_length - len(response_mask)
                if remaining <= 0:
                    break

                with simple_timer("generate_sequences", metrics):
                    output = await self.server_manager.generate(
                        request_id=request_id,
                        prompt_ids=sequence_ids,
                        sampling_params=sampling_params,
                        image_data=image_data,
                        mm_processor_kwargs=self._get_mm_processor_kwargs(None),
                    )
                if metrics.get("num_preempted") is None:
                    metrics["num_preempted"] = output.num_preempted if output.num_preempted is not None else -1

                generated_ids = output.token_ids[:remaining]
                generated_logprobs = output.log_probs[:remaining] if output.log_probs else None
                raw_response = self.tokenizer.decode(generated_ids, skip_special_tokens=True)
                parsed = parse_actions(raw_response)
                if not parsed.valid_actions:
                    invalid_actions += 1

                sequence_ids.extend(generated_ids)
                response_mask.extend([1] * len(generated_ids))
                if generated_logprobs:
                    response_logprobs.extend(generated_logprobs)

                step = episode.step(step_index, parsed.actions, raw_response=raw_response)
                previous_actions = parsed.actions
                turn_records.append(
                    {
                        "step": step_index,
                        "actions": parsed.actions,
                        "valid_json": parsed.valid_json,
                        "valid_actions": parsed.valid_actions,
                        "parse_error": parsed.error,
                        "markers": step.markers,
                        "reward": step.reward,
                        "done": step.done,
                    }
                )
                if step.done:
                    reward_score = self.success_reward
                    break
                if step_index + 1 < self.max_steps:
                    obs = episode.observe(step_index + 1)

            reward_score -= invalid_actions * self.invalid_action_penalty
            reward_score -= len(turn_records) * self.step_penalty
            summary = episode.result_summary()
        finally:
            episode.close()
            lease.release()

        if response_logprobs and len(response_logprobs) < len(response_mask):
            response_logprobs.extend([0.0] * (len(response_mask) - len(response_logprobs)))

        if not response_mask:
            fallback = self.tokenizer.encode('{"agent_a":"wait","agent_b":"wait","reason":"empty"}', add_special_tokens=False)
            remaining = max(1, min(len(fallback), self.response_length))
            sequence_ids.extend(fallback[:remaining])
            response_mask.extend([1] * remaining)

        response_ids = sequence_ids[-len(response_mask) :]
        prompt_ids = sequence_ids[: len(sequence_ids) - len(response_mask)]
        extra_fields = {
            "envmine_summary": {
                "task_id": summary.get("task_id"),
                "scene_id": summary.get("scene_id"),
                "success": summary.get("success"),
                "markers": summary.get("markers"),
                "step_count": summary.get("step_count"),
                "log": summary.get("log"),
            },
            "turn_scores": [record["reward"] for record in turn_records],
            "tool_rewards": [],
        }
        if self.keep_extra_records:
            extra_fields["envmine_records"] = turn_records

        return AgentLoopOutput(
            prompt_ids=prompt_ids,
            response_ids=response_ids[: self.response_length],
            response_mask=response_mask[: self.response_length],
            response_logprobs=response_logprobs[: self.response_length] if response_logprobs else None,
            multi_modal_data={"images": image_data},
            mm_processor_kwargs=self._get_mm_processor_kwargs(None),
            reward_score=reward_score,
            num_turns=max(2, 2 * len(turn_records)),
            metrics=metrics,
            extra_fields=extra_fields,
        )

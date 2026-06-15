from __future__ import annotations

import fcntl
import os
import sys
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from verl.experimental.agent_loop.agent_loop import AgentLoopBase, AgentLoopOutput, register
from verl.utils.profiler import simple_timer
from verl.utils.rollout_trace import rollout_trace_op
from verl.workers.rollout.replica import TokenOutput

from verl_adapter.mc_env import (
    AGENTS,
    MinecraftEnvConfig,
    MinecraftRolloutEnv,
    agent_key,
    format_agent_observation,
    parse_agent_action,
)


def _env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


@register("minecraft_agent")
class MinecraftAgentLoop(AgentLoopBase):
    """verl AgentLoop that drives two Minecraft agents from their own POV images."""

    def __init__(
        self,
        *args: Any,
        rollout_yaml: str = "yaml/lowlevel_train_episode.yaml",
        max_steps: int | None = 20,
        max_action_tokens: int = 64,
        mock_env: bool = False,
        train_instance_prefix: str = "instance-train",
        train_instance_count: int = 4,
        train_tickgate_base_port: int = 25690,
        use_images: bool = True,
        image_view: str = "agent_pov",
        persistent_minecraft: bool = False,
        image_max_width: int = 384,
        image_max_height: int = 216,
        history_window_images: int = 3,
        history_max_tokens: int = 3072,
        **kwargs: Any,
    ):
        super().__init__(*args, **kwargs)
        self.rollout_yaml = rollout_yaml
        self.max_steps = max_steps
        self.max_action_tokens = int(max_action_tokens)
        self.mock_env = bool(mock_env or os.environ.get("IT_TAKETWO_MOCK_MC") == "1")
        self.train_instance_prefix = os.environ.get("IT_TAKETWO_TRAIN_INSTANCE_PREFIX", train_instance_prefix)
        self.train_instance_count = int(os.environ.get("IT_TAKETWO_TRAIN_INSTANCE_COUNT", train_instance_count))
        self.train_tickgate_base_port = int(os.environ.get("IT_TAKETWO_TRAIN_TICKGATE_BASE_PORT", train_tickgate_base_port))
        self.use_images = _env_flag("IT_TAKETWO_USE_IMAGES", bool(use_images)) and not self.mock_env and self.processor is not None
        self.image_view = os.environ.get("IT_TAKETWO_IMAGE_VIEW", image_view)
        self.persistent_minecraft = _env_flag("IT_TAKETWO_PERSISTENT_MC", bool(persistent_minecraft)) and not self.mock_env
        self.image_max_width = int(os.environ.get("IT_TAKETWO_IMAGE_MAX_WIDTH", image_max_width))
        self.image_max_height = int(os.environ.get("IT_TAKETWO_IMAGE_MAX_HEIGHT", image_max_height))
        self.response_length = int(self.rollout_config.response_length)
        self.history_window_images = max(
            0,
            int(os.environ.get("IT_TAKETWO_HISTORY_WINDOW_IMAGES", history_window_images)),
        )
        self.history_max_tokens = max(
            0,
            int(os.environ.get("IT_TAKETWO_HISTORY_MAX_TOKENS", history_max_tokens)),
        )
        default_rollout_n = int(getattr(self.rollout_config, "n", 1) or 1)
        self.rollout_n = int(os.environ.get("IT_TAKETWO_ROLLOUT_N", default_rollout_n))

    @rollout_trace_op
    async def run(self, sampling_params: dict[str, Any], **kwargs: Any) -> AgentLoopOutput:
        base_messages = list(kwargs.get("raw_prompt") or default_prompt())
        prompt_ids: list[int] = []
        response_ids: list[int] = []
        response_mask: list[int] = []
        image_data: list[Image.Image] | None = None
        agent_histories: dict[str, list[dict[str, Any]]] = {agent: [] for agent in AGENTS}
        transcript_turns: list[dict[str, Any]] = []
        turn_scores: list[float] = []
        tool_rewards: list[float] = []
        metrics: dict[str, float | int] = {
            "generate_sequences": 0.0,
            "tool_calls": 0.0,
            "compute_score": 0.0,
            "num_preempted": -1,
            "agent_decision_calls": 0,
        }
        mm_processor_kwargs = self._get_mm_processor_kwargs(None)

        extra_info = kwargs.get("extra_info") if isinstance(kwargs.get("extra_info"), dict) else {}
        task_index = int(extra_info.get("task_index", kwargs.get("task_index", 0) or 0))
        random_seed = extra_info.get("random_seed")
        if random_seed is not None:
            random_seed = int(random_seed)
        rollout_n_index = int(kwargs.get("rollout_n", extra_info.get("rollout_n", 0) or 0))
        instance_index = self._resolve_instance_index(extra_info, rollout_n_index=rollout_n_index)
        instance_lock = None
        if not self.mock_env:
            instance_index, instance_lock = self._claim_instance_index(instance_index)

        env = MinecraftRolloutEnv(
            MinecraftEnvConfig(
                rollout_yaml=Path(self.rollout_yaml),
                task_index=task_index,
                random_seed=random_seed,
                max_steps=self.max_steps,
                mock=self.mock_env,
                instance_index=None if self.mock_env else instance_index,
                instance_prefix=self.train_instance_prefix,
                train_tickgate_base_port=self.train_tickgate_base_port,
                use_images=self.use_images,
                image_view=self.image_view,
                persistent_instance=self.persistent_minecraft,
            )
        )
        request_id = uuid4().hex
        num_turns = 1
        reward_score = 0.0
        summary: dict[str, Any] = {}
        try:
            prompt_ids = await self.apply_chat_template(base_messages, mm_processor_kwargs=mm_processor_kwargs)
            with simple_timer("tool_calls", metrics):
                observation = env.start()

            max_steps = int(self.max_steps or env.args.max_steps)
            for _ in range(max_steps):
                if observation.get("done"):
                    break

                actions: dict[str, str] = {}
                agent_decisions: dict[str, Any] = {}
                llm_input_frames: dict[str, str] = {}
                agent_turns: list[dict[str, Any]] = []
                history_meta = {
                    "mode": "per_agent",
                    "window_images": self.history_window_images,
                    "max_tokens": self.history_max_tokens,
                    "agents": {},
                }
                decision_observation = observation

                for agent_name in AGENTS:
                    step_base_response_ids, _, step_base_image_data = self._materialize_history(
                        agent_histories[agent_name]
                    )
                    history_meta["agents"][agent_name] = {
                        "tokens_before_step": len(step_base_response_ids),
                        "images_before_step": len(step_base_image_data or []),
                        "turns_before_step": len(agent_histories[agent_name]),
                    }
                    obs_ids, used_image, llm_image = await self._build_agent_observation_tokens(
                        decision_observation,
                        agent_name,
                        mm_processor_kwargs,
                        max(0, self.response_length - len(step_base_response_ids)),
                    )
                    frame_path = self._save_llm_input_image(env, decision_observation, agent_name, llm_image) if used_image else None
                    if frame_path is not None:
                        llm_input_frames[agent_name] = frame_path

                    prompt_for_generation = prompt_ids + step_base_response_ids + obs_ids
                    prompt_image_data = list(step_base_image_data or [])
                    if used_image and llm_image is not None:
                        prompt_image_data.append(llm_image)
                    max_context = int(self.rollout_config.prompt_length) + self.response_length
                    if len(step_base_response_ids) + len(obs_ids) >= self.response_length:
                        generated = self._encode_text('{"action":"wait","reason":"response_budget_exhausted"}')[: self.max_action_tokens]
                    elif prompt_image_data and len(prompt_for_generation) > max_context:
                        generated = self._encode_text('{"action":"wait","reason":"context_budget_exhausted"}')[: self.max_action_tokens]
                    else:
                        action_sampling_params = dict(sampling_params)
                        action_sampling_params["max_tokens"] = min(self.max_action_tokens, self.response_length - len(step_base_response_ids) - len(obs_ids))
                        with simple_timer("generate_sequences", metrics):
                            output: TokenOutput = await self.server_manager.generate(
                                request_id=f"{request_id}-{agent_name}-{decision_observation.get('step', 0)}",
                                prompt_ids=prompt_for_generation,
                                sampling_params=action_sampling_params,
                                image_data=prompt_image_data or None,
                                mm_processor_kwargs=mm_processor_kwargs,
                            )
                        if getattr(output, "num_preempted", None) is not None:
                            metrics["num_preempted"] = output.num_preempted
                        generated = list(output.token_ids or [])[: max(0, self.response_length - len(step_base_response_ids) - len(obs_ids))]
                        if not generated:
                            generated = self._encode_text('{"action":"wait","reason":"empty_generation"}')[: self.max_action_tokens]

                    action_text = self.tokenizer.decode(generated, skip_special_tokens=True)
                    action, reason = parse_agent_action(action_text, agent_name)
                    actions[agent_key(agent_name)] = action
                    agent_decisions[agent_name] = {
                        "action": action,
                        "reason": reason,
                        "raw_response": action_text,
                        "used_image": bool(used_image),
                        "llm_input_frame": frame_path,
                    }
                    agent_turns.append(
                        {
                            "agent": agent_name,
                            "observation_ids": obs_ids,
                            "used_image": used_image,
                            "image": llm_image,
                            "generated": generated,
                        }
                    )
                    metrics["agent_decision_calls"] = int(metrics["agent_decision_calls"]) + 1
                    num_turns += 2

                for turn in agent_turns:
                    agent_name = str(turn["agent"])
                    agent_histories[agent_name].append(turn)
                    agent_histories[agent_name] = self._trim_history_turns(agent_histories[agent_name])
                    agent_response_ids, _, agent_image_data = self._materialize_history(agent_histories[agent_name])
                    history_meta["agents"].setdefault(agent_name, {})
                    history_meta["agents"][agent_name].update(
                        {
                            "tokens_after_trim": len(agent_response_ids),
                            "images_after_trim": len(agent_image_data or []),
                            "turns_after_trim": len(agent_histories[agent_name]),
                        }
                    )

                transcript_turns.extend(agent_turns)
                transcript_turns = self._trim_history_turns(transcript_turns)
                response_ids, response_mask, image_data = self._materialize_history(transcript_turns)
                history_meta["transcript"] = {
                    "tokens_after_trim": len(response_ids),
                    "images_after_trim": len(image_data or []),
                    "turns_after_trim": len(transcript_turns),
                }

                actions.setdefault("agent_a", "wait")
                actions.setdefault("agent_b", "wait")
                step_payload: dict[str, Any] = {
                    "agent_a": actions["agent_a"],
                    "agent_b": actions["agent_b"],
                    "_meta": {
                        "agent_decisions": agent_decisions,
                        "llm_input_frames": llm_input_frames,
                        "history": history_meta,
                    },
                }
                with simple_timer("tool_calls", metrics):
                    observation = env.step(step_payload)
                reward = float(observation.get("reward", env.reward()) or 0.0)
                turn_scores.append(reward)
                tool_rewards.append(reward)
                if observation.get("done"):
                    response_ids, response_mask = self._append_env_text(response_ids, response_mask, "Episode finished successfully.")
                    break

            reward_score = env.reward()
            summary = env.summary()
        except Exception as exc:
            print(
                f"[MinecraftAgentLoop] rollout failed task={task_index} instance={instance_index}: {type(exc).__name__}: {exc}",
                flush=True,
            )
            reward_score = 0.0
            try:
                summary = env.summary()
            except Exception:
                summary = {}
            summary.update(
                {
                    "success": False,
                    "reward": 0.0,
                    "error": repr(exc),
                    "error_type": type(exc).__name__,
                }
            )
            if not prompt_ids:
                prompt_ids = self._encode_text("Minecraft rollout failed before prompt construction.")[: int(self.rollout_config.prompt_length)]
            response_ids, response_mask = self._append_env_text(
                response_ids,
                response_mask,
                f"Minecraft rollout failed: {type(exc).__name__}: {exc}",
            )
        finally:
            try:
                env.close()
            finally:
                self._release_instance_lock(instance_lock)

        response_ids = response_ids[: self.response_length]
        response_mask = response_mask[: self.response_length]
        if not response_ids:
            response_ids = self._encode_text("No Minecraft rollout tokens were produced.")[: self.response_length]
            response_mask = [0] * len(response_ids)

        metrics["image_count"] = len(image_data or [])
        multi_modal_data = {"images": image_data} if image_data else None
        return AgentLoopOutput(
            prompt_ids=prompt_ids,
            response_ids=response_ids,
            response_mask=response_mask,
            multi_modal_data=multi_modal_data,
            mm_processor_kwargs=mm_processor_kwargs,
            reward_score=reward_score,
            num_turns=num_turns,
            metrics=metrics,
            extra_fields={
                "turn_scores": turn_scores,
                "tool_rewards": tool_rewards,
                "minecraft_summary": summary,
            },
        )

    async def _build_agent_observation_tokens(
        self,
        observation: dict[str, Any],
        agent_name: str,
        mm_processor_kwargs: dict[str, Any],
        remaining: int,
    ) -> tuple[list[int], bool, Image.Image | None]:
        if remaining <= 0:
            return [], False, None

        image = self._image_from_observation(observation, agent_name)
        message = self._agent_observation_message(observation, agent_name, image is not None)
        used_image = image is not None
        try:
            ids = await self.apply_chat_template(
                [message],
                images=[image] if image is not None else None,
                mm_processor_kwargs=mm_processor_kwargs,
                remove_system_prompt=True,
            )
        except ValueError:
            used_image = False
            ids = await self.apply_chat_template(
                [self._agent_observation_message(observation, agent_name, False, image_omitted=True)],
                remove_system_prompt=True,
            )

        if len(ids) > remaining and used_image:
            used_image = False
            ids = await self.apply_chat_template(
                [self._agent_observation_message(observation, agent_name, False, image_omitted=True)],
                remove_system_prompt=True,
            )
        if len(ids) > remaining:
            ids = ids[:remaining]
        return ids, used_image, image if used_image else None

    def _trim_history_turns(self, history_turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        trimmed = list(history_turns)
        while self._count_history_images(trimmed) > self.history_window_images and trimmed:
            trimmed.pop(0)

        token_cap = self.history_max_tokens or self.response_length
        token_cap = min(token_cap, self.response_length)
        while trimmed and self._history_token_count(trimmed) > token_cap:
            trimmed.pop(0)
        return trimmed

    def _materialize_history(
        self,
        history_turns: list[dict[str, Any]],
    ) -> tuple[list[int], list[int], list[Image.Image] | None]:
        response_ids: list[int] = []
        response_mask: list[int] = []
        image_data: list[Image.Image] = []
        for turn in history_turns:
            obs_ids = list(turn["observation_ids"])
            if len(response_ids) + len(obs_ids) >= self.response_length:
                break
            response_ids.extend(obs_ids)
            response_mask.extend([0] * len(obs_ids))
            if turn["used_image"] and turn["image"] is not None:
                image_data.append(turn["image"])
            if len(response_ids) >= self.response_length:
                break
            generated = list(turn["generated"])[: self.response_length - len(response_ids)]
            response_ids.extend(generated)
            response_mask.extend([1] * len(generated))
        return response_ids, response_mask, image_data or None

    def _history_token_count(self, history_turns: list[dict[str, Any]]) -> int:
        total = 0
        for turn in history_turns:
            total += len(turn["observation_ids"]) + len(turn["generated"])
        return total

    def _count_history_images(self, history_turns: list[dict[str, Any]]) -> int:
        return sum(1 for turn in history_turns if turn["used_image"] and turn["image"] is not None)

    def _image_from_observation(self, observation: dict[str, Any], agent_name: str) -> Image.Image | None:
        if not self.use_images:
            return None
        image_info = observation.get("image") if isinstance(observation.get("image"), dict) else None
        raw: Any = None
        if image_info and image_info.get("view") == "agent_pov":
            agents = image_info.get("agents") if isinstance(image_info.get("agents"), dict) else {}
            agent_info = agents.get(agent_name) if isinstance(agents.get(agent_name), dict) else None
            raw = agent_info.get("image_bytes") if agent_info else None
        elif image_info and image_info.get("view") == "observer":
            raw = image_info.get("image_bytes")
        if not isinstance(raw, bytes):
            return None
        image = Image.open(BytesIO(raw)).convert("RGB")
        if self.image_max_width > 0 and self.image_max_height > 0:
            resampling = getattr(getattr(Image, "Resampling", Image), "LANCZOS")
            image.thumbnail((self.image_max_width, self.image_max_height), resampling)
        return image.copy()

    def _save_llm_input_image(
        self,
        env: MinecraftRolloutEnv,
        observation: dict[str, Any],
        agent_name: str,
        image: Image.Image | None,
    ) -> str | None:
        if image is None or env.llm_frames_dir is None:
            return None
        step = int(observation.get("step") or 0)
        path = env.llm_frames_dir / f"rollout_step_{step:03d}_{agent_key(agent_name)}.png"
        image.save(path)
        return str(path)

    def _agent_observation_message(
        self,
        observation: dict[str, Any],
        agent_name: str,
        has_image: bool,
        *,
        image_omitted: bool = False,
    ) -> dict[str, Any]:
        text = format_agent_observation(observation, agent_name)
        if has_image:
            text = (
                f"You are {agent_name}. Use the attached first-person image from YOUR own eyes. "
                "Focus on your assigned target object. Prefer actions that bring that target toward the center "
                "of your view, then move toward it when it is aligned. Choose exactly one low-level action for only yourself.\n"
                + text
            )
        elif image_omitted:
            text = f"You are {agent_name}. Your image was omitted because the token budget was too small.\n" + text
        else:
            text = (
                f"You are {agent_name}. Focus on your assigned target object and choose exactly one low-level action "
                "for only yourself.\n" + text
            )
        text += '\nReturn ONLY compact JSON: {"action":"one_allowed_action","reason":"short reason"}'
        if has_image:
            return {"role": "user", "content": [{"type": "image"}, {"type": "text", "text": text}]}
        return {"role": "user", "content": text}

    def _claim_instance_index(self, preferred_index: int) -> tuple[int, Any]:
        lock_dir = Path(os.environ.get("IT_TAKETWO_INSTANCE_LOCK_DIR", "/local_nvme/tmp/it_taketwo_instance_locks"))
        lock_dir.mkdir(parents=True, exist_ok=True)
        count = max(1, self.train_instance_count)
        preferred_index = (int(preferred_index) - 1) % count + 1
        candidates = [preferred_index] + [idx for idx in range(1, count + 1) if idx != preferred_index]
        for idx in candidates:
            lock_path = lock_dir / f"{self.train_instance_prefix}-{idx:02d}.lock"
            handle = lock_path.open("a+")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                continue
            handle.seek(0)
            handle.truncate()
            handle.write(f"pid={os.getpid()} preferred={preferred_index} claimed={idx}\n")
            handle.flush()
            return idx, handle
        raise RuntimeError(f"no free Minecraft train instance lock among {count} instances")

    def _release_instance_lock(self, handle: Any) -> None:
        if handle is None:
            return
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()

    def _resolve_instance_index(self, extra_info: dict[str, Any], rollout_n_index: int = 0) -> int:
        raw_index = extra_info.get("instance_index")
        repeat_count = max(1, int(self.rollout_n))
        if raw_index is None:
            base_zero = int(extra_info.get("index", 0))
        else:
            base_zero = int(raw_index) - 1

        if repeat_count > 1:
            offset = base_zero * repeat_count + int(rollout_n_index)
            return offset % max(1, self.train_instance_count) + 1
        return base_zero % max(1, self.train_instance_count) + 1

    def _encode_text(self, text: str) -> list[int]:
        return self.tokenizer.encode(text, add_special_tokens=False)

    def _append_env_text(self, response_ids: list[int], response_mask: list[int], text: str) -> tuple[list[int], list[int]]:
        remaining = self.response_length - len(response_ids)
        if remaining <= 0:
            return response_ids, response_mask
        env_ids = self._encode_text("\n" + text.strip() + "\n")[:remaining]
        response_ids.extend(env_ids)
        response_mask.extend([0] * len(env_ids))
        return response_ids, response_mask


def default_prompt() -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are the shared policy model for two Minecraft agents. "
                "The rollout code will ask you separately as AgentA and AgentB. "
                "For each request, act only as the named agent and return compact JSON only."
            ),
        }
    ]

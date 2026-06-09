from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any, Protocol

from action_space import ALLOWED_ACTIONS
from closed_model import ClosedModelClient, ClosedModelConfig, is_closed_model_provider
from game_functions import data_url
from prompts import build_agent_action_prompt, extract_first_json_object


@dataclass(frozen=True)
class AgentDecision:
    action: str
    reason: str
    raw_response: str | None = None
    model: str | None = None
    provider: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "raw_response": self.raw_response,
            "model": self.model,
            "provider": self.provider,
        }


@dataclass(frozen=True)
class AgentModelConfig:
    agent_name: str
    provider: str
    model: str
    api_base_url: str | None
    api_key: str | None
    api_key_env: str | None
    temperature: float
    max_tokens: int


class AgentDriver(Protocol):
    agent_name: str

    def choose(
        self,
        *,
        task: dict[str, Any],
        step_index: int,
        own_image: bytes,
        teammate_image: bytes,
        poses: dict[str, Any],
        rng: random.Random,
    ) -> AgentDecision:
        ...

    def metadata(self) -> dict[str, Any]:
        ...


class FixedAgentDriver:
    def __init__(self, agent_name: str, action: str):
        self.agent_name = agent_name
        self.action = action if action in ALLOWED_ACTIONS else "wait"

    def choose(self, **_: Any) -> AgentDecision:
        return AgentDecision(action=self.action, reason="fixed policy", provider="fixed")

    def metadata(self) -> dict[str, Any]:
        return {"provider": "fixed", "action": self.action}


class RandomAgentDriver:
    def __init__(self, agent_name: str):
        self.agent_name = agent_name

    def choose(self, *, rng: random.Random, **_: Any) -> AgentDecision:
        return AgentDecision(action=rng.choice(ALLOWED_ACTIONS), reason="random policy", provider="random")

    def metadata(self) -> dict[str, Any]:
        return {"provider": "random"}


class OpenAICompatibleAgentDriver:
    def __init__(self, config: AgentModelConfig):
        self.agent_name = config.agent_name
        self.config = config
        from openai import OpenAI

        kwargs: dict[str, Any] = {"api_key": config.api_key or "EMPTY"}
        if config.api_base_url:
            kwargs["base_url"] = config.api_base_url
        self.client = OpenAI(**kwargs)

    def choose(
        self,
        *,
        task: dict[str, Any],
        step_index: int,
        own_image: bytes,
        teammate_image: bytes,
        poses: dict[str, Any],
        rng: random.Random,
    ) -> AgentDecision:
        teammate_name = "AgentB" if self.agent_name == "AgentA" else "AgentA"
        prompt = build_agent_action_prompt(
            agent_name=self.agent_name,
            teammate_name=teammate_name,
            task=task,
            step_index=step_index,
            allowed_actions=ALLOWED_ACTIONS,
            poses=poses,
        )
        response = self.client.chat.completions.create(
            model=self.config.model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": data_url(own_image)}},
                        {"type": "image_url", "image_url": {"url": data_url(teammate_image)}},
                    ],
                }
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        text = response.choices[0].message.content or ""
        return _decision_from_text(text, self.config.model, self.config.provider)

    def metadata(self) -> dict[str, Any]:
        return {
            "provider": self.config.provider,
            "model": self.config.model,
            "api_base_url": self.config.api_base_url,
            "api_key_env": self.config.api_key_env,
        }


class ClosedModelAgentDriver:
    def __init__(self, config: AgentModelConfig):
        self.agent_name = config.agent_name
        self.config = config
        self.closed_model = ClosedModelClient(
            ClosedModelConfig(
                provider=config.provider,
                model=config.model,
                api_base_url=config.api_base_url,
                api_key=config.api_key,
                api_key_env=config.api_key_env,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
            )
        )

    def choose(
        self,
        *,
        task: dict[str, Any],
        step_index: int,
        own_image: bytes,
        teammate_image: bytes,
        poses: dict[str, Any],
        rng: random.Random,
    ) -> AgentDecision:
        teammate_name = "AgentB" if self.agent_name == "AgentA" else "AgentA"
        prompt = build_agent_action_prompt(
            agent_name=self.agent_name,
            teammate_name=teammate_name,
            task=task,
            step_index=step_index,
            allowed_actions=ALLOWED_ACTIONS,
            poses=poses,
        )
        text = self.closed_model.complete_with_images(prompt=prompt, images=[own_image, teammate_image])
        return _decision_from_text(text, self.config.model, self.config.provider)

    def metadata(self) -> dict[str, Any]:
        return self.closed_model.metadata()


def _decision_from_text(text: str, model: str, provider: str) -> AgentDecision:
    parsed = extract_first_json_object(text)
    action = str(parsed.get("action", "wait"))
    if action not in ALLOWED_ACTIONS:
        action = "wait"
    return AgentDecision(
        action=action,
        reason=str(parsed.get("reason", "")),
        raw_response=text,
        model=model,
        provider=provider,
    )


def _get_agent_arg(args: Any, prefix: str, name: str, fallback: Any = None) -> Any:
    value = getattr(args, f"{prefix}_{name}", None)
    if value is None or value == "":
        return fallback
    return value


def _resolved_api_key(args: Any, prefix: str, *, use_global_fallback: bool) -> str | None:
    env_name = _get_agent_arg(args, prefix, "api_key_env", None)
    if env_name:
        import os

        value = os.environ.get(str(env_name))
        if value:
            return value
    fallback = getattr(args, "api_key", None) if use_global_fallback else None
    return _get_agent_arg(args, prefix, "api_key", fallback)


def _model_config(args: Any, agent_name: str) -> AgentModelConfig:
    prefix = "agent_a" if agent_name == "AgentA" else "agent_b"
    provider = str(_get_agent_arg(args, prefix, "provider", "openai_compatible"))
    use_global_fallback = not is_closed_model_provider(provider)
    return AgentModelConfig(
        agent_name=agent_name,
        provider=provider,
        model=str(_get_agent_arg(args, prefix, "model", getattr(args, "model", "qwen2.5-vl-7b"))),
        api_base_url=_get_agent_arg(
            args,
            prefix,
            "api_base_url",
            getattr(args, "api_base_url", None) if use_global_fallback else None,
        ),
        api_key=_resolved_api_key(args, prefix, use_global_fallback=use_global_fallback),
        api_key_env=_get_agent_arg(args, prefix, "api_key_env", None),
        temperature=float(getattr(args, "agent_temperature", 0.0)),
        max_tokens=int(getattr(args, "agent_max_tokens", 256)),
    )


def _build_ai_driver(config: AgentModelConfig) -> AgentDriver:
    if is_closed_model_provider(config.provider):
        return ClosedModelAgentDriver(config)
    return OpenAICompatibleAgentDriver(config)


def build_agent_drivers(args: Any) -> dict[str, AgentDriver]:
    if args.policy == "fixed":
        return {
            "AgentA": FixedAgentDriver("AgentA", args.fixed_agent_a_action),
            "AgentB": FixedAgentDriver("AgentB", args.fixed_agent_b_action),
        }
    if args.policy == "random":
        return {"AgentA": RandomAgentDriver("AgentA"), "AgentB": RandomAgentDriver("AgentB")}
    if args.policy in {"ai", "qwen"}:
        return {
            "AgentA": _build_ai_driver(_model_config(args, "AgentA")),
            "AgentB": _build_ai_driver(_model_config(args, "AgentB")),
        }
    raise ValueError(f"unsupported policy: {args.policy}")


def choose_agent_actions(
    drivers: dict[str, AgentDriver],
    *,
    task: dict[str, Any],
    step_index: int,
    agent_images: dict[str, bytes],
    poses: dict[str, Any],
    rng: random.Random,
) -> tuple[dict[str, str], dict[str, Any]]:
    decision_a = drivers["AgentA"].choose(
        task=task,
        step_index=step_index,
        own_image=agent_images["AgentA"],
        teammate_image=agent_images["AgentB"],
        poses=poses,
        rng=rng,
    )
    decision_b = drivers["AgentB"].choose(
        task=task,
        step_index=step_index,
        own_image=agent_images["AgentB"],
        teammate_image=agent_images["AgentA"],
        poses=poses,
        rng=rng,
    )
    actions = {
        "agent_a": decision_a.action,
        "agent_b": decision_b.action,
        "reason": f"AgentA: {decision_a.reason}; AgentB: {decision_b.reason}",
    }
    return actions, {"AgentA": decision_a.as_dict(), "AgentB": decision_b.as_dict()}


def driver_metadata(drivers: dict[str, AgentDriver]) -> dict[str, Any]:
    return {name: driver.metadata() for name, driver in drivers.items()}

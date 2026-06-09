from __future__ import annotations

import base64
import os
import sys
import time
from dataclasses import dataclass
from typing import Any


DEFAULT_CLOUDGPT_DIR = "/local_nvme/zhanglechao/wm_eval/eval_code"
DEFAULT_CLOSED_MODEL = "gpt-5.5-20260424"


@dataclass(frozen=True)
class ClosedModelConfig:
    provider: str
    model: str = DEFAULT_CLOSED_MODEL
    api_base_url: str | None = None
    api_key: str | None = None
    api_key_env: str | None = None
    temperature: float = 0.0
    max_tokens: int = 256
    timeout: float = 120.0
    max_retries: int = 6
    cloudgpt_dir: str | None = None

    @property
    def resolved_api_key(self) -> str | None:
        if self.api_key_env:
            value = os.environ.get(self.api_key_env)
            if value:
                return value
        return self.api_key


def is_closed_model_provider(provider: str | None) -> bool:
    if not provider:
        return False
    return provider.lower() in {"closed_api", "cloudgpt", "gpt", "gpt55"}


def _is_gpt55(model: str) -> bool:
    return str(model).lower().startswith("gpt-5.5")


def _supports_temperature_zero(model: str) -> bool:
    return not _is_gpt55(model)


def _image_data_url(image_bytes: bytes) -> str:
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def build_multimodal_messages(prompt: str, images: list[bytes]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for image in images:
        content.append({"type": "image_url", "image_url": {"url": _image_data_url(image)}})
    content.append({"type": "text", "text": prompt})
    return [{"role": "user", "content": content}]


def _load_cloudgpt_client(config: ClosedModelConfig) -> Any:
    cloudgpt_dir = config.cloudgpt_dir or os.environ.get("WM_EVAL_CLOUDGPT_DIR") or DEFAULT_CLOUDGPT_DIR
    if cloudgpt_dir and cloudgpt_dir not in sys.path:
        sys.path.insert(0, cloudgpt_dir)
    import cloudgpt_aoai  # type: ignore

    # wm_eval does this in the GPT-5.5 rollout experiments to avoid extra ping
    # rate-limits when many workers start clients at once.
    if hasattr(cloudgpt_aoai, "_validate_token"):
        cloudgpt_aoai._validate_token = lambda _token: True
    return cloudgpt_aoai.get_openai_client()


def _load_direct_openai_client(config: ClosedModelConfig) -> Any:
    from openai import OpenAI

    kwargs: dict[str, Any] = {"timeout": config.timeout}
    if config.resolved_api_key:
        kwargs["api_key"] = config.resolved_api_key
    else:
        kwargs["api_key"] = "EMPTY"
    if config.api_base_url:
        kwargs["base_url"] = config.api_base_url
    return OpenAI(**kwargs)


class ClosedModelClient:
    def __init__(self, config: ClosedModelConfig):
        self.config = config
        if config.api_key_env and not config.resolved_api_key:
            raise RuntimeError(f"environment variable {config.api_key_env!r} is not set")
        if config.api_base_url or config.resolved_api_key:
            self.client = _load_direct_openai_client(config)
            self.client_kind = "openai_compatible_closed_api"
        else:
            self.client = _load_cloudgpt_client(config)
            self.client_kind = "cloudgpt_aoai"

    def complete_with_images(self, *, prompt: str, images: list[bytes]) -> str:
        messages = build_multimodal_messages(prompt, images)
        last_error: Exception | None = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                kwargs: dict[str, Any] = {
                    "model": self.config.model,
                    "messages": messages,
                    "max_completion_tokens": self.config.max_tokens,
                }
                if _supports_temperature_zero(self.config.model):
                    kwargs["temperature"] = self.config.temperature
                response = self.client.chat.completions.create(**kwargs)
                choice = response.choices[0]
                text = (choice.message.content or "").strip()
                finish_reason = getattr(choice, "finish_reason", None)
                if text and finish_reason != "length":
                    return text
                last_error = RuntimeError(
                    f"empty or truncated response from {self.config.model}: "
                    f"finish_reason={finish_reason!r} content_len={len(text)}"
                )
                if attempt >= self.config.max_retries:
                    break
                print(
                    f"[CLOSED MODEL EMPTY] model={self.config.model} "
                    f"attempt={attempt}/{self.config.max_retries} finish_reason={finish_reason!r}; retry",
                    flush=True,
                )
                time.sleep(2 ** (attempt - 1))
                continue
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt >= self.config.max_retries:
                    break
                text = str(exc)
                is_rate_limit = "429" in text or "rate" in text.lower() or "Too Many Requests" in text
                wait_seconds = (2 ** (attempt - 1)) * (5 if is_rate_limit else 1)
                print(
                    f"[CLOSED MODEL ERROR] model={self.config.model} "
                    f"attempt={attempt}/{self.config.max_retries}: {exc}; retry in {wait_seconds}s",
                    flush=True,
                )
                time.sleep(wait_seconds)
        raise RuntimeError(f"closed model call failed after {self.config.max_retries} attempts: {last_error}")

    def metadata(self) -> dict[str, Any]:
        return {
            "provider": self.config.provider,
            "client_kind": self.client_kind,
            "model": self.config.model,
            "api_base_url": self.config.api_base_url,
            "api_key_env": self.config.api_key_env,
            "max_tokens": self.config.max_tokens,
            "max_retries": self.config.max_retries,
        }

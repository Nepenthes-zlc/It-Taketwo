from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class EpisodeRecord:
    env: str
    episode_id: int
    task_index: int
    output: str
    ok: bool
    success: bool | None = None
    episode_reward: float | None = None
    step_count: int | None = None
    random_seed: int | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepRecord:
    env: str
    episode_id: int
    task_index: int
    task_id: int | str | None
    scene_id: int | str | None
    step: int
    obs: dict[str, Any]
    action: dict[str, Any]
    reward: float
    done: bool
    policy: str | None = None
    model: str | None = None
    raw_response: str | None = None
    markers: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

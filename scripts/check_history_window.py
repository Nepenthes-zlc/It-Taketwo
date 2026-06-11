#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
VERL_HOME = Path("/local_nvme/zhanglechao/verl")
for path in (ROOT_DIR, VERL_HOME):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from verl_adapter.minecraft_agent_loop import MinecraftAgentLoop


def make_loop(*, window_images: int = 3, max_tokens: int = 3072, response_length: int = 8192) -> MinecraftAgentLoop:
    loop = object.__new__(MinecraftAgentLoop)
    loop.history_window_images = window_images
    loop.history_max_tokens = max_tokens
    loop.response_length = response_length
    return loop


def fake_turn(index: int, *, obs_tokens: int = 50, action_tokens: int = 10, has_image: bool = True) -> dict:
    return {
        "agent": "AgentA" if index % 2 == 0 else "AgentB",
        "observation_ids": [1000 + index] * obs_tokens,
        "generated": [2000 + index] * action_tokens,
        "used_image": has_image,
        "image": object() if has_image else None,
    }


def assert_recent_image_window() -> None:
    loop = make_loop(window_images=3, max_tokens=1000)
    turns = [fake_turn(i) for i in range(5)]

    trimmed = loop._trim_history_turns(turns)
    ids, mask, images = loop._materialize_history(trimmed)

    kept_turn_ids = [turn["observation_ids"][0] for turn in trimmed]
    assert kept_turn_ids == [1002, 1003, 1004], kept_turn_ids
    assert len(images or []) == 3
    assert len(ids) == 180
    assert mask.count(0) == 150
    assert mask.count(1) == 30
    print("image window: 5 turns -> 3 newest image turns, tokens=180")


def assert_token_window() -> None:
    loop = make_loop(window_images=10, max_tokens=125)
    turns = [fake_turn(i, has_image=False) for i in range(4)]

    trimmed = loop._trim_history_turns(turns)
    ids, mask, images = loop._materialize_history(trimmed)

    kept_turn_ids = [turn["observation_ids"][0] for turn in trimmed]
    assert kept_turn_ids == [1002, 1003], kept_turn_ids
    assert images is None
    assert loop._history_token_count(trimmed) == 120
    assert len(ids) == len(mask) == 120
    print("token window: 4 text turns -> 2 newest turns under 125 tokens")


def assert_response_cap() -> None:
    loop = make_loop(window_images=10, max_tokens=1000, response_length=100)
    turns = [fake_turn(0, obs_tokens=60, action_tokens=20), fake_turn(1, obs_tokens=60, action_tokens=20)]

    ids, mask, images = loop._materialize_history(turns)

    assert len(ids) == 80
    assert len(mask) == 80
    assert len(images or []) == 1
    print("response cap: materialize stops before overflowing response_length")


def main() -> None:
    assert_recent_image_window()
    assert_token_window()
    assert_response_cap()
    print("history window checks passed")


if __name__ == "__main__":
    main()

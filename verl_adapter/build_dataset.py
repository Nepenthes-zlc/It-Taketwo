from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MC_ROLLOUT_DIR = PROJECT_ROOT / "mc_rollout"
if str(MC_ROLLOUT_DIR) not in sys.path:
    sys.path.insert(0, str(MC_ROLLOUT_DIR))

from action_space import ALLOWED_ACTIONS  # noqa: E402
from game_functions import load_task_list  # noqa: E402
from launch import DEFAULT_TASKS  # noqa: E402

SYSTEM_PROMPT = (
    "You are the shared policy model for two Minecraft agents. "
    "During rollout you will be asked separately as AgentA and AgentB. "
    "For each request, act only as the named agent and return compact JSON only."
)

USER_TEMPLATE = """Task: {task_description}
Scene id: {scene_id}
Task id: {task_id}

Allowed actions for each agent: {allowed_actions}

Goal: AgentA should operate the pressure plate/door mechanism when needed, while AgentB enters the second room.
The runtime will ask for one agent at a time using that agent's own first-person image.
When asked as one agent, respond with exactly one JSON object: {{"action":"<action>","reason":"<short reason>"}}.
"""


def resolve_project_path(path: str | Path) -> Path:
    value = Path(path).expanduser()
    if not value.is_absolute():
        value = PROJECT_ROOT / value
    return value.resolve()


def build_prompt(task: dict[str, Any]) -> list[dict[str, str]]:
    content = USER_TEMPLATE.format(
        task_description=task.get("task_description") or task.get("description") or "",
        scene_id=task.get("scene_id", ""),
        task_id=task.get("id", ""),
        allowed_actions=", ".join(ALLOWED_ACTIONS),
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": content},
    ]


def make_row(task: dict[str, Any], task_index: int, split: str, row_index: int, agent_name: str, seed: int, train_instance_count: int) -> dict[str, Any]:
    return {
        "data_source": "it_taketwo_minecraft",
        "agent_name": agent_name,
        "prompt": build_prompt(task),
        "ability": "minecraft_rollout",
        "reward_model": {"style": "rule", "ground_truth": "success"},
        "extra_info": {
            "split": split,
            "index": row_index,
            "task_index": task_index,
            "task_id": task.get("id"),
            "scene_id": task.get("scene_id"),
            "random_seed": seed + row_index,
            "instance_index": row_index % max(1, train_instance_count) + 1,
        },
    }


def build_rows(tasks: list[dict[str, Any]], size: int, split: str, agent_name: str, seed: int, shuffle: bool, train_instance_count: int) -> list[dict[str, Any]]:
    if not tasks:
        raise ValueError("No Minecraft tasks were loaded")
    indices = list(range(len(tasks)))
    if shuffle:
        rng = random.Random(seed)
        rng.shuffle(indices)
    rows = []
    for row_index in range(size):
        task_index = indices[row_index % len(indices)]
        rows.append(make_row(tasks[task_index], task_index, split, row_index, agent_name, seed, train_instance_count))
    return rows


def write_parquet(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, str(path))
    print(f"wrote {len(rows)} rows -> {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build verl parquet data for the It-Taketwo Minecraft AgentLoop.")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS), help="Task JSON file used by mc_rollout.")
    parser.add_argument("--output-dir", default="data/verl_minecraft", help="Directory for train.parquet and val.parquet.")
    parser.add_argument("--train-size", type=int, default=4)
    parser.add_argument("--val-size", type=int, default=1)
    parser.add_argument("--agent-name", default="minecraft_agent")
    parser.add_argument("--seed", type=int, default=20260609)
    parser.add_argument("--train-instance-count", type=int, default=4)
    parser.add_argument("--shuffle", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    tasks = load_task_list(resolve_project_path(args.tasks))
    output_dir = resolve_project_path(args.output_dir)
    train_rows = build_rows(tasks, args.train_size, "train", args.agent_name, args.seed, args.shuffle, args.train_instance_count)
    val_rows = build_rows(tasks, args.val_size, "val", args.agent_name, args.seed + 100000, args.shuffle, args.train_instance_count)
    write_parquet(train_rows, output_dir / "train.parquet")
    write_parquet(val_rows, output_dir / "val.parquet")


if __name__ == "__main__":
    main()

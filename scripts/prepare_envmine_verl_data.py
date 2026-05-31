#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any


WORKSPACE = Path(__file__).resolve().parents[1]
DEFAULT_TASKS = WORKSPACE / "ConstructScene" / "generated" / "generated_tasks.json"


def parse_task_indices(value: str, total: int) -> list[int]:
    if not value.strip():
        return list(range(total))
    indices: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            pieces = [int(piece) for piece in part.split(":")]
            if len(pieces) == 2:
                start, stop = pieces
                step = 1
            elif len(pieces) == 3:
                start, stop, step = pieces
            else:
                raise ValueError(f"bad task index range: {part!r}")
            indices.extend(range(start, stop, step))
        else:
            indices.append(int(part))
    if not indices:
        raise ValueError("empty task index list")
    for index in indices:
        if index < 0 or index >= total:
            raise IndexError(f"task index {index} out of range [0, {total})")
    return indices


def load_tasks(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(f"task file has no tasks list: {path}")
    return tasks


def make_rows(
    tasks: list[dict[str, Any]],
    indices: list[int],
    *,
    episodes_per_task: int,
    seed: int,
    split: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    row_index = 0
    for task_index in indices:
        task = tasks[task_index]
        description = str(task.get("task_description") or "Player A holds a pressure plate so Player B can pass.")
        for repeat in range(episodes_per_task):
            random_seed = seed + row_index
            prompt = (
                "Run one online EnvMine low-level Minecraft rollout. "
                "The policy must choose JSON low-level actions from visual observations only. "
                f"Task: {description}"
            )
            rows.append(
                {
                    "data_source": "envmine_lowlevel",
                    "prompt": [{"role": "user", "content": prompt}],
                    "ability": "minecraft_multiagent_navigation",
                    "agent_name": "envmine_lowlevel",
                    "task_index": task_index,
                    "random_seed": random_seed,
                    "reward_model": {
                        "style": "envmine_online",
                        "ground_truth": {
                            "task_index": task_index,
                            "task_id": task.get("id"),
                            "scene_id": task.get("scene_id"),
                        },
                    },
                    "extra_info": {
                        "split": split,
                        "index": row_index,
                        "task_index": task_index,
                        "task_id": task.get("id"),
                        "scene_id": task.get("scene_id"),
                        "description": description,
                        "random_seed": random_seed,
                    },
                }
            )
            row_index += 1
    return rows


def split_indices(indices: list[int], val_fraction: float, seed: int) -> tuple[list[int], list[int]]:
    if len(indices) == 1:
        return indices, indices
    shuffled = list(indices)
    random.Random(seed).shuffle(shuffled)
    val_count = max(1, int(round(len(shuffled) * val_fraction))) if val_fraction > 0 else 1
    val_count = min(val_count, len(shuffled) - 1)
    val_indices = sorted(shuffled[:val_count])
    train_indices = sorted(shuffled[val_count:])
    return train_indices, val_indices


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_rows(path: Path, rows: list[dict[str, Any]], fmt: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "jsonl":
        write_jsonl(path, rows)
        return
    try:
        import pandas as pd
    except Exception as exc:
        raise RuntimeError("pandas and pyarrow are required for parquet output; use --format jsonl as a fallback") from exc
    pd.DataFrame(rows).to_parquet(path, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare EnvMine online AgentLoop prompt data for verl.")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--task-indices", default="0", help="Comma list or Python-style ranges, e.g. 0,2,5:8. Empty means all.")
    parser.add_argument("--episodes-per-task", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260529)
    parser.add_argument("--val-fraction", type=float, default=0.1)
    parser.add_argument("--output-dir", type=Path, default=WORKSPACE / "data" / "envmine_lowlevel")
    parser.add_argument("--format", choices=["parquet", "jsonl"], default="parquet")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    tasks = load_tasks(args.tasks)
    indices = parse_task_indices(args.task_indices, len(tasks))
    train_indices, val_indices = split_indices(indices, args.val_fraction, args.seed)
    train_rows = make_rows(tasks, train_indices, episodes_per_task=args.episodes_per_task, seed=args.seed, split="train")
    val_rows = make_rows(tasks, val_indices, episodes_per_task=1, seed=args.seed + 1_000_000, split="test")
    suffix = "jsonl" if args.format == "jsonl" else "parquet"
    train_path = args.output_dir / f"train.{suffix}"
    val_path = args.output_dir / f"test.{suffix}"
    write_rows(train_path, train_rows, args.format)
    write_rows(val_path, val_rows, args.format)
    summary = {
        "ok": True,
        "tasks": str(args.tasks),
        "task_indices": indices,
        "train_indices": train_indices,
        "val_indices": val_indices,
        "train_rows": len(train_rows),
        "val_rows": len(val_rows),
        "train_file": str(train_path),
        "val_file": str(val_path),
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

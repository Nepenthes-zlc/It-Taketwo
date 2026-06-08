#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE / "adapter"))

from envmine_verl import EnvMineRolloutConfig, discover_workspace, run_batch_rollout  # noqa: E402


def parse_args() -> argparse.Namespace:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    workspace = discover_workspace(WORKSPACE)
    parser = argparse.ArgumentParser(description="Run EnvMine batch rollout from the It-Taketwo wrapper workspace.")
    parser.add_argument("--config", type=Path, default=workspace.envmine / "configs" / "qwen_batch_lowlevel.json")
    parser.add_argument("--task-indices", default="0")
    parser.add_argument("--episodes-per-task", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=None)
    parser.add_argument("--policy", choices=["fixed", "random", "qwen"], default="fixed")
    parser.add_argument("--model", default="qwen2.5-vl-7b")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:3888/v1/")
    parser.add_argument("--max-steps", type=int, default=2)
    parser.add_argument("--output-dir", type=Path, default=workspace.root / "runs" / f"envmine_rollout_{stamp}")
    parser.add_argument("--write-video", action="store_true")
    parser.add_argument("--random-seed", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg = EnvMineRolloutConfig(
        config=args.config,
        task_indices=args.task_indices,
        episodes_per_task=args.episodes_per_task,
        policy=args.policy,
        model=args.model,
        api_base_url=args.api_base_url,
        max_steps=args.max_steps,
        parallel=args.parallel,
        output_dir=args.output_dir,
        write_video=args.write_video,
        random_seed=args.random_seed,
    )
    summary = run_batch_rollout(cfg, dry_run=args.dry_run)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return int(summary.get("returncode", 0))


if __name__ == "__main__":
    raise SystemExit(main())

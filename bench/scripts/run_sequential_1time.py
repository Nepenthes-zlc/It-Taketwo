#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
BENCH_SCRIPT = ROOT / "bench" / "scripts" / "bench.py"


def load_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def write_metadata(config_path: Path, run_dir: Path, task_name: str, start_time: str) -> None:
    config = load_config(config_path)
    rollout_n = int(config["runner"]["rollout_n"])
    task_count = sum(
        len(range(int(start), int(end) + 1))
        for start, end in (
            str(phase["task_indices"]).split("-", 1)
            for phase in config["phases"]
        )
    )
    payload = {
        "name": config["name"],
        "task": task_name,
        "run_dir": str(run_dir),
        "config": str(config_path),
        "start_time_utc": start_time,
        "model": config["model"],
        "expected_episodes": task_count * rollout_n,
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    latest = ROOT / "bench" / "runs" / f"latest_{config['name']}.txt"
    latest.write_text(str(run_dir) + "\n", encoding="utf-8")


def run_task(task_name: str, config_path: Path, date: str, stamp: str) -> Path:
    config = load_config(config_path)
    run_name = f"{config['name']}_{stamp}"
    run_dir = ROOT / "bench" / "runs" / task_name / date / "1time" / run_name
    run_dir.mkdir(parents=True, exist_ok=False)
    start_time = dt.datetime.now(dt.timezone.utc).isoformat()
    write_metadata(config_path, run_dir, task_name, start_time)
    command = [
        str(config.get("python", "/home/azvm/miniconda3/envs/verl/bin/python")),
        str(BENCH_SCRIPT),
        "run",
        "--config",
        str(config_path),
        "--run-dir",
        str(run_dir),
    ]
    with (run_dir / "controller.log").open("a", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"{task_name} benchmark failed with exit code {result.returncode}: {run_dir}")
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Elevator then Path as one-pass sequential benchmarks.")
    parser.add_argument("--elevator-config", type=Path, required=True)
    parser.add_argument("--path-config", type=Path, required=True)
    args = parser.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    date = now.strftime("%Y%m%d")
    stamp = now.strftime("%Y%m%d_%H%M%S")
    elevator_config = args.elevator_config.expanduser().resolve()
    path_config = args.path_config.expanduser().resolve()
    elevator_dir = run_task("elevator", elevator_config, date, stamp)
    print(f"elevator_complete={elevator_dir}", flush=True)
    path_dir = run_task("path", path_config, date, stamp)
    print(f"path_complete={path_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

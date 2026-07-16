#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import shutil
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bench.training_style_bench as bench


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def valid(record: dict[str, Any]) -> bool:
    return bool(record.get("ok")) and not bool(record.get("discarded"))


def build_args(config: dict[str, Any], run_dir: Path) -> argparse.Namespace:
    saved = config["args"]
    original_argv = sys.argv
    try:
        sys.argv = [str(Path(bench.__file__))]
        args = bench.parse_args()
    finally:
        sys.argv = original_argv
    for key, value in saved.items():
        if hasattr(args, key):
            setattr(args, key, value)
    for key in ("tasks", "rollout_yaml", "instance_config", "pack_src"):
        setattr(args, key, Path(getattr(args, key)).resolve())
    args.output_dir = run_dir
    args.python = str(saved.get("python") or sys.executable)
    args.cleanup_after = False
    args.skip_prepare = False
    args.skip_prewarm = False
    args.prewarm_each_chunk = False
    return args


def remove_attempt_artifacts(run_dir: Path, episode_id: int, record: dict[str, Any] | None = None) -> None:
    shutil.rmtree(run_dir / f"episode_{episode_id:04d}", ignore_errors=True)
    if record and record.get("trace_dir"):
        shutil.rmtree(Path(record["trace_dir"]), ignore_errors=True)


def prune_invalid_records(run_dir: Path) -> list[dict[str, Any]]:
    records = load_jsonl(run_dir / "episodes.jsonl")
    kept = [record for record in records if valid(record)]
    removed = [record for record in records if not valid(record)]
    kept_trace_dirs = {
        Path(record["trace_dir"]).resolve()
        for record in kept
        if record.get("trace_dir")
    }
    for record in removed:
        remove_attempt_artifacts(run_dir, int(record["episode_id"]), record)
    removed_trace_dirs = 0
    trace_root = run_dir / "traces"
    if trace_root.exists():
        for child in trace_root.iterdir():
            if child.is_dir() and child.name != "step_timing" and child.resolve() not in kept_trace_dirs:
                shutil.rmtree(child, ignore_errors=True)
                removed_trace_dirs += 1
    ordered = sorted(kept, key=lambda record: int(record["episode_id"]))
    temp_path = run_dir / "episodes.jsonl.tmp"
    temp_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in ordered),
        encoding="utf-8",
    )
    temp_path.replace(run_dir / "episodes.jsonl")
    bench.write_json(
        run_dir / "prune_status.json",
        {
            "original_records": len(records),
            "kept_valid": len(kept),
            "removed_invalid": len(removed),
            "removed_trace_dirs": removed_trace_dirs,
            "time_utc": bench.datetime.now(bench.timezone.utc).isoformat(),
        },
    )
    return ordered


def write_summary(run_dir: Path, records: list[dict[str, Any]], attempts: int, started: float) -> None:
    bench.write_json(
        run_dir / "top_up_status.json",
        {
            "state": "completed" if len(records) == 400 else "running",
            "valid_episodes": len(records),
            "remaining": 400 - len(records),
            "attempts": attempts,
            "elapsed_sec": round(time.time() - started, 3),
            "time_utc": bench.datetime.now(bench.timezone.utc).isoformat(),
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args_cli = parser.parse_args()
    run_dir = args_cli.run_dir.resolve()
    config = json.loads((run_dir / "bench_config.json").read_text(encoding="utf-8"))
    runner_args = build_args(config, run_dir)
    specs = {spec["episode_id"]: bench.EpisodeSpec(**spec) for spec in config["specs"]}
    records = prune_invalid_records(run_dir)
    records_by_id = {int(record["episode_id"]): record for record in records if valid(record)}
    if len(records_by_id) != len(records):
        raise RuntimeError("episodes.jsonl must contain only unique valid records before top-up")

    started = time.time()
    attempts = 0
    env = bench.training_env(runner_args, run_dir)
    bench.prepare_instances(runner_args, env)
    bench.prewarm_instances(runner_args, env, run_dir)
    try:
        while len(records_by_id) < len(specs):
            missing = [episode_id for episode_id in sorted(specs) if episode_id not in records_by_id]
            batch_ids = missing[: max(1, min(args_cli.workers, runner_args.instance_count))]
            batch_specs = [replace(specs[episode_id], instance_index=index + 1) for index, episode_id in enumerate(batch_ids)]
            for spec in batch_specs:
                remove_attempt_artifacts(run_dir, spec.episode_id)
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(batch_specs)) as pool:
                futures = {
                    pool.submit(bench.run_episode_subprocess, spec, runner_args, env, run_dir): spec
                    for spec in batch_specs
                }
                for future in concurrent.futures.as_completed(futures):
                    spec = futures[future]
                    attempts += 1
                    try:
                        record = future.result()
                    except BaseException as exc:
                        record = {
                            "ok": False,
                            "episode_id": spec.episode_id,
                            "task_index": spec.task_index,
                            "repeat_index": spec.repeat_index,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    record["top_up_attempt"] = attempts
                    bench.append_jsonl(run_dir / "top_up_attempts.jsonl", [record])
                    if valid(record):
                        records_by_id[spec.episode_id] = record
                        ordered = [records_by_id[key] for key in sorted(records_by_id)]
                        temp_path = run_dir / "episodes.jsonl.tmp"
                        temp_path.write_text(
                            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in ordered),
                            encoding="utf-8",
                        )
                        temp_path.replace(run_dir / "episodes.jsonl")
                    else:
                        remove_attempt_artifacts(run_dir, spec.episode_id, record)
            write_summary(run_dir, list(records_by_id.values()), attempts, started)
    finally:
        bench.cleanup_instances(list(range(1, runner_args.instance_count + 1)), runner_args, env, run_dir)

    records = [records_by_id[key] for key in sorted(records_by_id)]
    bench.write_json(run_dir / "summary.json", bench.summarize(records, len(records), started))
    write_summary(run_dir, records, attempts, started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

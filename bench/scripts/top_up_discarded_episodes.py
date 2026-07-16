#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import bench.scripts.top_up_valid_episodes as top_up
import bench.training_style_bench as bench


def write_records(run_dir: Path, records_by_id: dict[int, dict]) -> None:
    ordered = [records_by_id[key] for key in sorted(records_by_id)]
    temp_path = run_dir / "episodes.jsonl.tmp"
    temp_path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in ordered),
        encoding="utf-8",
    )
    temp_path.replace(run_dir / "episodes.jsonl")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args_cli = parser.parse_args()
    run_dir = args_cli.run_dir.resolve()
    config = json.loads((run_dir / "bench_config.json").read_text(encoding="utf-8"))
    runner_args = top_up.build_args(config, run_dir)
    specs = {spec["episode_id"]: bench.EpisodeSpec(**spec) for spec in config["specs"]}
    records = top_up.load_jsonl(run_dir / "episodes.jsonl")
    discarded = [record for record in records if bool(record.get("discarded"))]
    records_by_id = {
        int(record["episode_id"]): record
        for record in records
        if not bool(record.get("discarded"))
    }
    for record in discarded:
        top_up.remove_attempt_artifacts(run_dir, int(record["episode_id"]), record)
    write_records(run_dir, records_by_id)
    bench.write_json(
        run_dir / "prune_status.json",
        {
            "original_records": len(records),
            "kept_non_discarded": len(records_by_id),
            "removed_discarded": len(discarded),
            "time_utc": bench.datetime.now(bench.timezone.utc).isoformat(),
        },
    )

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
                top_up.remove_attempt_artifacts(run_dir, spec.episode_id)
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
                    if top_up.valid(record):
                        records_by_id[spec.episode_id] = record
                        write_records(run_dir, records_by_id)
                    else:
                        top_up.remove_attempt_artifacts(run_dir, spec.episode_id, record)
            top_up.write_summary(run_dir, list(records_by_id.values()), attempts, started)
    finally:
        bench.cleanup_instances(list(range(1, runner_args.instance_count + 1)), runner_args, env, run_dir)

    final_records = [records_by_id[key] for key in sorted(records_by_id)]
    bench.write_json(run_dir / "summary.json", bench.summarize(final_records, len(final_records), started))
    top_up.write_summary(run_dir, final_records, attempts, started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

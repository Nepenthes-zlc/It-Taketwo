#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from envmine.config import BatchConfig, InstanceConfig, load_batch_config
from qwen_lowlevel_task_rollout import (
    ALLOWED_ACTIONS,
    DEFAULT_PACK_SRC,
    DEFAULT_TASKS,
    ROOT,
    run as run_lowlevel_episode,
)


@dataclass(frozen=True)
class EpisodeSpec:
    episode_id: int
    task_index: int
    repeat_index: int
    random_seed: int | None


def parse_task_indices(value: str) -> list[int]:
    if not value.strip():
        return [0]
    indices = []
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
    return indices


def build_episode_specs(task_indices: list[int], episodes_per_task: int, seed: int | None) -> list[EpisodeSpec]:
    specs = []
    episode_id = 0
    for task_index in task_indices:
        for repeat_index in range(episodes_per_task):
            episode_seed = None if seed is None else seed + episode_id
            specs.append(
                EpisodeSpec(
                    episode_id=episode_id,
                    task_index=task_index,
                    repeat_index=repeat_index,
                    random_seed=episode_seed,
                )
            )
            episode_id += 1
    return specs


def assign_specs(instances: list[InstanceConfig], specs: list[EpisodeSpec]) -> dict[str, list[EpisodeSpec]]:
    assignments = {instance.name: [] for instance in instances}
    for index, spec in enumerate(specs):
        instance = instances[index % len(instances)]
        assignments[instance.name].append(spec)
    return assignments


def episode_output_dir(base_dir: Path, instance: InstanceConfig, spec: EpisodeSpec) -> Path:
    seed_label = "none" if spec.random_seed is None else str(spec.random_seed)
    return base_dir / instance.name / f"episode_{spec.episode_id:04d}_task_{spec.task_index}_seed_{seed_label}"


def make_episode_args(base_args: argparse.Namespace, instance: InstanceConfig, spec: EpisodeSpec, output_dir: Path) -> argparse.Namespace:
    return argparse.Namespace(
        tasks=base_args.tasks,
        task_index=spec.task_index,
        pack_src=base_args.pack_src,
        pack_dst=instance.root / "run" / "saves" / "New World" / "datapacks" / "multiagent_scene_pack",
        config=base_args.config,
        instance_config=instance,
        api_base_url=base_args.api_base_url,
        api_key=base_args.api_key,
        model=base_args.model,
        policy=base_args.policy,
        fixed_agent_a_action=base_args.fixed_agent_a_action,
        fixed_agent_b_action=base_args.fixed_agent_b_action,
        frames_dir=output_dir / "observer_frames",
        qwen_frames_dir=output_dir / "agent_pov_frames",
        video_output=output_dir / "rollout.mp4",
        output=output_dir / "result.json",
        log_dir=base_args.log_dir,
        max_steps=base_args.max_steps,
        action_ticks=base_args.action_ticks,
        capture_ticks=base_args.capture_ticks,
        capture_render_frames=base_args.capture_render_frames,
        camera_settle_ticks=base_args.camera_settle_ticks,
        camera_settle_render_frames=base_args.camera_settle_render_frames,
        pov_eye_height=base_args.pov_eye_height,
        pov_forward_offset=base_args.pov_forward_offset,
        pov_camera_settle_ticks=base_args.pov_camera_settle_ticks,
        pov_extra_settle_ticks=base_args.pov_extra_settle_ticks,
        pov_settle_render_frames=base_args.pov_settle_render_frames,
        capture_timeout=base_args.capture_timeout,
        fps=base_args.fps,
        write_video=base_args.write_video,
        fail_on_video_error=base_args.fail_on_video_error,
        hide_hud=base_args.hide_hud,
        refresh_pack=base_args.refresh_pack,
        randomize_starts=base_args.randomize_starts,
        random_seed=spec.random_seed,
        start_position_jitter=base_args.start_position_jitter,
        start_yaw_jitter=base_args.start_yaw_jitter,
    )


def compact_episode_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": True,
        "task_id": result.get("task_id"),
        "scene_id": result.get("scene_id"),
        "success": result.get("success"),
        "episode_reward": result.get("episode_reward"),
        "step_count": result.get("step_count"),
        "markers": result.get("markers"),
        "log": result.get("log"),
    }


def run_worker(instance: InstanceConfig, specs: list[EpisodeSpec], args: argparse.Namespace) -> dict[str, Any]:
    worker_started = time.time()
    records = []
    for spec in specs:
        out_dir = episode_output_dir(args.output_dir, instance, spec)
        out_dir.mkdir(parents=True, exist_ok=True)
        episode_args = make_episode_args(args, instance, spec, out_dir)
        started = time.time()
        try:
            result = run_lowlevel_episode(episode_args)
            record = compact_episode_result(result)
            record.update(
                {
                    "env": instance.name,
                    "episode_id": spec.episode_id,
                    "task_index": spec.task_index,
                    "repeat_index": spec.repeat_index,
                    "random_seed": spec.random_seed,
                    "elapsed_sec": round(time.time() - started, 3),
                    "output": str(episode_args.output),
                }
            )
        except Exception as exc:
            record = {
                "ok": False,
                "env": instance.name,
                "episode_id": spec.episode_id,
                "task_index": spec.task_index,
                "repeat_index": spec.repeat_index,
                "random_seed": spec.random_seed,
                "elapsed_sec": round(time.time() - started, 3),
                "output": str(episode_args.output),
                "error": repr(exc),
            }
        records.append(record)
        print(json.dumps(record, ensure_ascii=False), flush=True)
    return {
        "env": instance.name,
        "ok": all(record.get("ok") for record in records),
        "episodes": len(records),
        "elapsed_sec": round(time.time() - worker_started, 3),
        "records": records,
    }


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_batch(args: argparse.Namespace) -> dict[str, Any]:
    batch = load_batch_config(args.config)
    if args.parallel is not None:
        batch = BatchConfig(instances=batch.instances, parallel=max(1, args.parallel))
    task_indices = parse_task_indices(args.task_indices)
    specs = build_episode_specs(task_indices, args.episodes_per_task, args.random_seed)
    assignments = assign_specs(batch.instances, specs)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    active_instances = [instance for instance in batch.instances if assignments[instance.name]]
    if not active_instances:
        raise ValueError("no active instances; check --task-indices and --episodes-per-task")
    if args.dry_run:
        planned = []
        for instance in active_instances:
            for spec in assignments[instance.name]:
                planned.append(
                    {
                        "env": instance.name,
                        "root": str(instance.root),
                        "tickgate_port": instance.tickgate_port,
                        "episode_id": spec.episode_id,
                        "task_index": spec.task_index,
                        "repeat_index": spec.repeat_index,
                        "random_seed": spec.random_seed,
                        "output_dir": str(episode_output_dir(args.output_dir, instance, spec)),
                    }
                )
        return {
            "time_utc": datetime.now(timezone.utc).isoformat(),
            "ok": True,
            "dry_run": True,
            "policy": args.policy,
            "config": str(args.config),
            "parallel": batch.parallel,
            "total_episodes": len(planned),
            "planned": planned,
        }
    worker_results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(batch.parallel, len(active_instances))) as executor:
        future_map = {
            executor.submit(run_worker, instance, assignments[instance.name], args): instance
            for instance in active_instances
        }
        for future in concurrent.futures.as_completed(future_map):
            instance = future_map[future]
            try:
                worker_results.append(future.result())
            except Exception as exc:
                worker_results.append({"env": instance.name, "ok": False, "episodes": 0, "records": [], "error": repr(exc)})

    episode_records = [record for worker in worker_results for record in worker.get("records", [])]
    ok_records = [record for record in episode_records if record.get("ok")]
    success_records = [record for record in ok_records if record.get("success")]
    summary = {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "ok": len(ok_records) == len(episode_records),
        "policy": args.policy,
        "model": args.model if args.policy == "qwen" else None,
        "config": str(args.config),
        "tasks": str(args.tasks),
        "task_indices": task_indices,
        "episodes_per_task": args.episodes_per_task,
        "total_episodes": len(episode_records),
        "completed_episodes": len(ok_records),
        "successful_episodes": len(success_records),
        "success_rate": (len(success_records) / len(ok_records)) if ok_records else 0.0,
        "output_dir": str(args.output_dir),
        "workers": [{k: v for k, v in worker.items() if k != "records"} for worker in worker_results],
        "episodes": episode_records,
    }
    write_jsonl(args.output_dir / "episodes.jsonl", episode_records)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def parse_args() -> argparse.Namespace:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    parser = argparse.ArgumentParser(description="Run batched Qwen/vision low-level EnvMine rollouts.")
    parser.add_argument("--config", type=Path, default=ROOT / "configs" / "qwen_batch_lowlevel.json")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--task-indices", default="0", help="Comma list or Python-style ranges, e.g. '0,2,5:8'.")
    parser.add_argument("--episodes-per-task", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=None, help="Override config.parallel.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned worker assignments without launching Minecraft.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "test_results" / f"qwen_batch_lowlevel_{stamp}")
    parser.add_argument("--log-dir", type=Path, default=ROOT / "logs")
    parser.add_argument("--pack-src", type=Path, default=DEFAULT_PACK_SRC)
    parser.add_argument("--api-base-url", default="http://127.0.0.1:3888/v1/")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--model", default="qwen2.5-vl-7b")
    parser.add_argument("--policy", choices=["qwen", "fixed", "random"], default="qwen")
    parser.add_argument("--fixed-agent-a-action", choices=ALLOWED_ACTIONS, default="wait")
    parser.add_argument("--fixed-agent-b-action", choices=ALLOWED_ACTIONS, default="forward")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--action-ticks", type=int, default=4)
    parser.add_argument("--capture-ticks", type=int, default=2)
    parser.add_argument("--capture-render-frames", type=int, default=2)
    parser.add_argument("--camera-settle-ticks", type=int, default=10)
    parser.add_argument("--camera-settle-render-frames", type=int, default=6)
    parser.add_argument("--pov-eye-height", type=float, default=1.35)
    parser.add_argument("--pov-forward-offset", type=float, default=0.0)
    parser.add_argument("--pov-camera-settle-ticks", type=int, default=16)
    parser.add_argument("--pov-extra-settle-ticks", type=int, default=8)
    parser.add_argument("--pov-settle-render-frames", type=int, default=10)
    parser.add_argument("--capture-timeout", type=float, default=90.0)
    parser.add_argument("--fps", type=int, default=2)
    parser.add_argument("--write-video", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--fail-on-video-error", action="store_true")
    parser.add_argument("--hide-hud", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--refresh-pack", action="store_true")
    parser.add_argument("--randomize-starts", action="store_true")
    parser.add_argument("--random-seed", type=int, default=None)
    parser.add_argument("--start-position-jitter", type=float, default=0.6)
    parser.add_argument("--start-yaw-jitter", type=float, default=35.0)
    return parser.parse_args()


def main() -> int:
    summary = run_batch(parse_args())
    print(json.dumps({k: v for k, v in summary.items() if k != "episodes"}, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

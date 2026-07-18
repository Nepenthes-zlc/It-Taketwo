#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import queue
import threading
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "mc_rollout") not in sys.path:
    sys.path.insert(0, str(ROOT / "mc_rollout"))

from verl_adapter.mc_env import MinecraftEnvConfig, MinecraftRolloutEnv  # noqa: E402

DEFAULT_PYTHON = "/home/azvm/miniconda3/envs/verl/bin/python"
DEFAULT_TASKS = ROOT / "bench/data/final_data/picture/generated_tasks.json"
DEFAULT_PACK = ROOT / "bench/data/final_data/picture/datapacks/picture_scene_pack"
DEFAULT_ROLLOUT_YAML = ROOT / "yaml/lowlevel_episode.yaml"


def run_checked(command: list[str], *, env: dict[str, str], timeout: float | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True, timeout=timeout)


def prepare_instances(args: argparse.Namespace, env: dict[str, str]) -> None:
    if args.skip_prepare:
        return
    prep_env = dict(env)
    prep_env.update(
        {
            "TRAIN_INSTANCE_PREFIX": args.instance_prefix,
            "TRAIN_INSTANCE_COUNT": str(args.instance_count),
            "TRAIN_TICKGATE_BASE_PORT": str(args.base_port),
        }
    )
    run_checked([str(ROOT / "scripts/prepare_train_instances.sh")], env=prep_env)


def prewarm_instances(args: argparse.Namespace, env: dict[str, str]) -> None:
    if args.skip_prewarm:
        return
    command = [
        args.python,
        str(ROOT / "scripts/prewarm_train_instances.py"),
        "--config",
        str(ROOT / "yaml/instance_train_single.yaml"),
        "--count",
        str(args.instance_count),
        "--prefix",
        args.instance_prefix,
        "--base-port",
        str(args.base_port),
        "--parallel",
        str(args.prewarm_parallel),
        "--ready-timeout",
        str(args.prewarm_ready_timeout),
        "--puppet-timeout",
        str(args.prewarm_puppet_timeout),
        "--retries",
        str(args.prewarm_retries),
        "--retry-delay",
        str(args.prewarm_retry_delay),
        "--log-dir",
        str(args.output_dir / "logs"),
        "--pack-src",
        str(args.pack_src),
        "--refresh-pack",
    ]
    run_checked(command, env=env, timeout=args.prewarm_total_timeout)


def cleanup_instances(args: argparse.Namespace, env: dict[str, str]) -> None:
    command = [
        args.python,
        str(ROOT / "bench/training_style_bench.py"),
        "--output-dir",
        str(args.output_dir / ".cleanup"),
        "--tasks",
        str(args.tasks),
        "--pack-src",
        str(args.pack_src),
        "--rollout-yaml",
        str(args.rollout_yaml),
        "--instance-count",
        str(args.instance_count),
        "--instance-prefix",
        args.instance_prefix,
        "--base-port",
        str(args.base_port),
        "--cleanup-only",
    ]
    subprocess.run(command, cwd=ROOT, env=env, check=False)


def extract_agent_images(observation: dict[str, Any]) -> dict[str, bytes]:
    image = observation.get("image")
    if not isinstance(image, dict):
        raise RuntimeError(f"observation has no image: {list(observation)}")
    agents = image.get("agents")
    if not isinstance(agents, dict):
        raise RuntimeError("observation image has no agents map")
    result: dict[str, bytes] = {}
    for agent in ("AgentA", "AgentB"):
        info = agents.get(agent)
        if not isinstance(info, dict) or not isinstance(info.get("image_bytes"), bytes):
            raise RuntimeError(f"missing image bytes for {agent}")
        result[agent] = info["image_bytes"]
    return result


def capture_one(task_index: int, instance_index: int, args: argparse.Namespace, env: dict[str, str]) -> dict[str, Any]:
    os.environ.update(env)
    task_dir = args.output_dir / f"task_{task_index:03d}"
    task_dir.mkdir(parents=True, exist_ok=True)
    env_obj: MinecraftRolloutEnv | None = None
    started = time.time()
    try:
        env_obj = MinecraftRolloutEnv(
            MinecraftEnvConfig(
                rollout_yaml=args.rollout_yaml,
                tasks=args.tasks,
                pack_src=args.pack_src,
                refresh_pack=True,
                task_index=task_index,
                max_steps=0,
                mock=False,
                instance_index=instance_index,
                instance_prefix=args.instance_prefix,
                train_tickgate_base_port=args.base_port,
                use_images=True,
                image_view="agent_pov",
                persistent_instance=True,
                save_trace=False,
                trace_root=task_dir / "traces",
                task_mode="multiagent",
            )
        )
        obs = env_obj.start()
        images = extract_agent_images(obs)
        (task_dir / "step_000_agent_a.png").write_bytes(images["AgentA"])
        (task_dir / "step_000_agent_b.png").write_bytes(images["AgentB"])
        meta = {
            "ok": True,
            "task_index": task_index,
            "instance_index": instance_index,
            "elapsed_sec": round(time.time() - started, 3),
            "task_id": obs.get("task_id"),
            "scene_id": obs.get("scene_id"),
            "description": obs.get("description"),
            "reset_state": env_obj.reset_state if env_obj else None,
            "poses": obs.get("poses"),
            "markers": obs.get("markers"),
            "agent_a_image": str(task_dir / "step_000_agent_a.png"),
            "agent_b_image": str(task_dir / "step_000_agent_b.png"),
        }
        (task_dir / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
        return meta
    except BaseException as exc:  # noqa: BLE001
        meta = {
            "ok": False,
            "task_index": task_index,
            "instance_index": instance_index,
            "elapsed_sec": round(time.time() - started, 3),
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        (task_dir / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n")
        return meta
    finally:
        if env_obj is not None:
            env_obj.close()


def render_video(output_dir: Path, records: list[dict[str, Any]], fps: int = 2) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    video = output_dir / "picture_initial_positions_100_ab.mp4"
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    font_bold = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 25)
    width, height = 1280, 410
    view_size = (620, 349)
    ffmpeg = "/home/azvm/miniconda3/envs/verl/bin/ffmpeg"
    command = [
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-r",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(video),
    ]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE)
    try:
        for index, record in enumerate(records, start=1):
            if not record.get("ok"):
                continue
            left = Image.open(record["agent_a_image"]).convert("RGB").resize(view_size, Image.Resampling.BILINEAR)
            right = Image.open(record["agent_b_image"]).convert("RGB").resize(view_size, Image.Resampling.BILINEAR)
            canvas = Image.new("RGB", (width, height), (16, 19, 25))
            canvas.paste(left, (20, 50))
            canvas.paste(right, (660, 50))
            draw = ImageDraw.Draw(canvas)
            task_index = int(record["task_index"])
            phase = "easy" if task_index <= 33 else ("medium" if task_index <= 66 else "hard")
            label = f"Picture init {index:03d}/100 | {phase.upper()} | Task {task_index:03d} | scene {record.get('scene_id')}"
            draw.text((20, 12), label, font=font_bold, fill=(245, 248, 255))
            draw.rectangle((28, 58, 155, 92), fill=(10, 25, 43))
            draw.rectangle((668, 58, 795, 92), fill=(43, 25, 10))
            draw.text((40, 62), "Agent A", font=font, fill=(130, 202, 255))
            draw.text((680, 62), "Agent B", font=font, fill=(255, 197, 126))
            frame = canvas.tobytes()
            assert proc.stdin is not None
            for _ in range(max(1, fps)):
                proc.stdin.write(frame)
    finally:
        if proc.stdin:
            proc.stdin.close()
        rc = proc.wait()
    if rc:
        raise SystemExit(rc)
    return video


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "bench/runs/picture/init_debug_20260717_all100")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--pack-src", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--rollout-yaml", type=Path, default=DEFAULT_ROLLOUT_YAML)
    parser.add_argument("--python", default=DEFAULT_PYTHON)
    parser.add_argument("--instance-count", type=int, default=16)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--instance-prefix", default="instance-train")
    parser.add_argument("--base-port", type=int, default=25690)
    parser.add_argument("--task-indices", default="0-99")
    parser.add_argument("--prewarm-parallel", type=int, default=16)
    parser.add_argument("--prewarm-retries", type=int, default=3)
    parser.add_argument("--prewarm-retry-delay", type=float, default=5.0)
    parser.add_argument("--prewarm-ready-timeout", type=float, default=600.0)
    parser.add_argument("--prewarm-puppet-timeout", type=float, default=180.0)
    parser.add_argument("--prewarm-total-timeout", type=float, default=2400.0)
    parser.add_argument("--skip-prepare", action="store_true")
    parser.add_argument("--skip-prewarm", action="store_true")
    parser.add_argument("--cleanup-after", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--capture-retries", type=int, default=3)
    args = parser.parse_args()

    args.output_dir = args.output_dir.expanduser().resolve()
    args.tasks = args.tasks.expanduser().resolve()
    args.pack_src = args.pack_src.expanduser().resolve()
    args.rollout_yaml = args.rollout_yaml.expanduser().resolve()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    task_indices: list[int] = []
    for part in args.task_indices.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = [int(x) for x in part.split("-", 1)]
            task_indices.extend(range(start, end + 1))
        else:
            task_indices.append(int(part))

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = ":".join([str(ROOT), str(ROOT / "mc_rollout")] + ([existing_pythonpath] if existing_pythonpath else []))
    env["JAVA_HOME"] = env.get("JAVA_HOME", "/usr")
    env["IT_TAKETWO_TASK_MODE"] = "multiagent"
    env["IT_TAKETWO_TRAIN_INSTANCE_PREFIX"] = args.instance_prefix
    env["IT_TAKETWO_TRAIN_INSTANCE_COUNT"] = str(args.instance_count)
    env["IT_TAKETWO_TRAIN_TICKGATE_BASE_PORT"] = str(args.base_port)
    env["IT_TAKETWO_PERSISTENT_MC"] = "1"
    env["IT_TAKETWO_USE_IMAGES"] = "1"
    env["IT_TAKETWO_IMAGE_VIEW"] = "agent_pov"
    env["IT_TAKETWO_CAPTURE_TIMEOUT"] = "30"
    env["IT_TAKETWO_FORCE_RESPAWN_AGENTS"] = "1"
    env["IT_TAKETWO_PREWARM_AGENTS"] = "AgentA,AgentB"
    env["IT_TAKETWO_EGL_DEVICES"] = env.get("IT_TAKETWO_EGL_DEVICES", "egl0,egl1,egl2,egl3")
    env["IT_TAKETWO_REFRESH_PACK"] = "1"
    env["IT_TAKETWO_SAVE_ROLLOUT_TRACE"] = "0"
    env["IT_TAKETWO_QUIET_MC_LOGS"] = "1"
    env["IT_TAKETWO_START_POSE_ATTEMPTS"] = "12"
    env["IT_TAKETWO_START_POSE_CONSECUTIVE"] = "2"
    env["IT_TAKETWO_START_POSE_TOLERANCE"] = "0.75"

    config_payload = {
        "args": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items()},
        "task_indices": task_indices,
    }
    (args.output_dir / "capture_config.json").write_text(json.dumps(config_payload, indent=2, ensure_ascii=False) + "\n")

    prepare_instances(args, env)
    prewarm_instances(args, env)

    task_queue: queue.Queue[int] = queue.Queue()
    for task_index in task_indices:
        task_queue.put(task_index)
    attempt_counts: dict[int, int] = {task_index: 0 for task_index in task_indices}
    completed: set[int] = set()
    lock = threading.Lock()

    def capture_worker(instance_index: int) -> list[dict[str, Any]]:
        worker_records: list[dict[str, Any]] = []
        while True:
            try:
                task_index = task_queue.get_nowait()
            except queue.Empty:
                break
            with lock:
                if task_index in completed:
                    task_queue.task_done()
                    continue
                attempt_counts[task_index] = attempt_counts.get(task_index, 0) + 1
                attempt = attempt_counts[task_index]
            record = capture_one(task_index, instance_index, args, env)
            record["attempt"] = attempt
            worker_records.append(record)
            if record.get("ok"):
                with lock:
                    completed.add(task_index)
            elif attempt < max(1, args.capture_retries):
                task_queue.put(task_index)
            print(
                json.dumps(
                    {
                        k: record.get(k)
                        for k in ("ok", "task_index", "instance_index", "attempt", "elapsed_sec", "error_type", "error")
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            task_queue.task_done()
        return worker_records

    records: list[dict[str, Any]] = []
    try:
        max_workers = min(args.workers, args.instance_count, len(task_indices))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(capture_worker, instance_index + 1) for instance_index in range(max_workers)]
            for future in concurrent.futures.as_completed(futures):
                records.extend(future.result())
    finally:
        if args.cleanup_after:
            cleanup_instances(args, env)

    records.sort(key=lambda r: int(r.get("task_index", 10**9)))
    (args.output_dir / "metadata.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    summary = {
        "total": len(records),
        "ok": sum(1 for r in records if r.get("ok")),
        "failed": sum(1 for r in records if not r.get("ok")),
        "output_dir": str(args.output_dir),
    }
    video = render_video(args.output_dir, records)
    summary["video"] = str(video)
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

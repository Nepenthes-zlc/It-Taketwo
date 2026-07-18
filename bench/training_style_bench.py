#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import io
import json
import os
import random
import shutil
import signal
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MC_ROLLOUT_DIR = ROOT / "mc_rollout"
DEFAULT_PYTHON = "/home/azvm/miniconda3/envs/verl/bin/python"
DEFAULT_TASKS = ROOT / "assert" / "ConstructScene" / "generated" / "generated_tasks.json"
DEFAULT_MIX8_SELECTION = (
    ROOT
    / "data"
    / "verl_minecraft"
    / "single_agent"
    / "elevator_door"
    / "door_agentb_mix8_2easy4medium2hard_20260702"
    / "difficulty_selection.json"
)


@dataclass(frozen=True)
class EpisodeSpec:
    episode_id: int
    task_index: int
    repeat_index: int
    chunk_index: int
    instance_index: int
    task_mode: str = "multiagent"
    controlled_agent: str | None = None
    atomic_role: str | None = None
    random_seed: int | None = None
    phase_name: str = "all"


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def resolve_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def parse_indices(raw: str) -> list[int]:
    result: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            step = 1 if end >= start else -1
            result.extend(range(start, end + step, step))
        else:
            result.append(int(part))
    return result


def normalize_agent(value: str) -> str:
    normalized = str(value).strip().lower().replace("_", "")
    if normalized in {"agenta", "a", "playera"}:
        return "AgentA"
    if normalized in {"agentb", "b", "playerb"}:
        return "AgentB"
    raise ValueError(f"unsupported agent: {value!r}")


def parse_agents(raw: str) -> list[str]:
    agents: list[str] = []
    for value in str(raw or "AgentA,AgentB").replace(";", ",").split(","):
        if value.strip():
            agent = normalize_agent(value)
            if agent not in agents:
                agents.append(agent)
    if not agents:
        raise ValueError("single-parallel mode requires at least one agent")
    return agents


def resolve_bench_mode(args: argparse.Namespace) -> str:
    if args.bench_mode:
        return args.bench_mode
    return "duo-parallel" if args.task_mode == "multiagent" else "single-parallel"


def default_task_indices() -> list[int]:
    with DEFAULT_MIX8_SELECTION.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    values = data.get("selected_task_indices")
    if not isinstance(values, list) or not values:
        raise ValueError(f"missing selected_task_indices in {DEFAULT_MIX8_SELECTION}")
    return [int(v) for v in values]


def training_env(args: argparse.Namespace, output_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH", "")
    paths = [str(ROOT), str(MC_ROLLOUT_DIR)]
    if existing_pythonpath:
        paths.append(existing_pythonpath)
    env.update(
        {
            "PYTHONPATH": ":".join(paths),
            "JAVA_HOME": env.get("JAVA_HOME", "/usr"),
            "IT_TAKETWO_TASK_MODE": "multiagent" if args.bench_mode == "duo-parallel" else "single_agent",
            "IT_TAKETWO_SINGLE_AGENT_DEFAULT": args.controlled_agent,
            "IT_TAKETWO_CONTROLLED_AGENT": args.controlled_agent,
            "IT_TAKETWO_ATOMIC_ROLE": args.atomic_role,
            "IT_TAKETWO_TRAIN_INSTANCE_PREFIX": args.instance_prefix,
            "IT_TAKETWO_TRAIN_INSTANCE_COUNT": str(args.instance_count),
            "IT_TAKETWO_TRAIN_TICKGATE_BASE_PORT": str(args.base_port),
            "IT_TAKETWO_ROLLOUT_N": str(args.rollout_n),
            "IT_TAKETWO_PERSISTENT_MC": "1",
            "IT_TAKETWO_POST_PREWARM": "0",
            "IT_TAKETWO_STRICT_POST_PREWARM": "1",
            "IT_TAKETWO_USE_IMAGES": "1" if args.use_images else "0",
            "IT_TAKETWO_IMAGE_VIEW": args.image_view,
            "IT_TAKETWO_HISTORY_WINDOW_IMAGES": str(args.history_window_images),
            "IT_TAKETWO_HISTORY_MAX_TOKENS": str(args.history_max_tokens),
            "IT_TAKETWO_IMAGE_MAX_WIDTH": str(args.image_max_width),
            "IT_TAKETWO_IMAGE_MAX_HEIGHT": str(args.image_max_height),
            "IT_TAKETWO_CAPTURE_TIMEOUT": str(args.capture_timeout),
            "IT_TAKETWO_RESTART_ON_ROLLOUT_ERROR": "1",
            "IT_TAKETWO_RESTART_ON_SYSTEM_DISCARD": "1",
            "IT_TAKETWO_FLUSH_PUPPET_BEFORE_QUERY": "1",
            "IT_TAKETWO_FORCE_RESPAWN_AGENTS": "1",
            "IT_TAKETWO_POSE_QUERY_TIMEOUT": str(args.pose_query_timeout),
            "IT_TAKETWO_ENV_START_RETRIES": str(args.env_start_retries),
            "IT_TAKETWO_ENV_START_RETRY_DELAY": str(args.env_start_retry_delay),
            "IT_TAKETWO_START_POSE_ATTEMPTS": str(args.start_pose_attempts),
            "IT_TAKETWO_START_POSE_CONSECUTIVE": str(args.start_pose_consecutive),
            "IT_TAKETWO_START_POSE_TOLERANCE": str(args.start_pose_tolerance),
            "IT_TAKETWO_POSE_FAIL_LIMIT": str(args.pose_fail_limit),
            "IT_TAKETWO_SHOT_SLOW_SECS": str(args.shot_slow_secs),
            "IT_TAKETWO_SHOT_SLOW_LIMIT": str(args.shot_slow_limit),
            "IT_TAKETWO_QUIET_MC_LOGS": "1",
            "IT_TAKETWO_SAVE_ROLLOUT_TRACE": "1" if args.save_trace else "0",
            "IT_TAKETWO_ROLLOUT_TRACE_DIR": str(output_dir / "traces"),
            "IT_TAKETWO_STEP_TIMING": "1",
            "IT_TAKETWO_DISCARD_LOG": "1",
        }
    )
    env["IT_TAKETWO_PREWARM_AGENTS"] = "AgentA,AgentB" if args.bench_mode in {"single-parallel", "duo-parallel"} else args.controlled_agent
    return env


def run_checked(command: list[str], *, cwd: Path, env: dict[str, str], timeout: float | None = None) -> None:
    print("+ " + " ".join(command), flush=True)
    subprocess.run(command, cwd=str(cwd), env=env, check=True, timeout=timeout)


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
    run_checked([str(ROOT / "scripts" / "prepare_train_instances.sh")], cwd=ROOT, env=prep_env)


def prewarm_instances(args: argparse.Namespace, env: dict[str, str], output_dir: Path) -> None:
    if args.skip_prewarm:
        return
    command = [
        args.python,
        str(ROOT / "scripts" / "prewarm_train_instances.py"),
        "--config",
        str(args.instance_config),
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
        str(output_dir / "logs"),
        "--pack-src",
        str(args.pack_src),
    ]
    if args.refresh_pack:
        command.append("--refresh-pack")
    run_checked(command, cwd=ROOT, env=env, timeout=args.prewarm_total_timeout)


def cleanup_instances(indices: list[int], args: argparse.Namespace, env: dict[str, str], output_dir: Path) -> None:
    if not indices:
        return
    helper = (
        "from pathlib import Path\n"
        "from dataclasses import replace\n"
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT)!r})\n"
        f"sys.path.insert(0, {str(MC_ROLLOUT_DIR)!r})\n"
        "from launch import InstanceRunner, load_instance_config\n"
        "from verl_adapter.mc_env import training_instance_config\n"
        f"base = load_instance_config(Path({str(args.instance_config)!r}))\n"
        f"log_root = Path({str(output_dir / 'logs')!r})\n"
        f"prefix = {args.instance_prefix!r}\n"
        f"base_port = {int(args.base_port)!r}\n"
        f"indices = {indices!r}\n"
        "import os, signal, subprocess, time\n"
        "for idx in indices:\n"
        "    cfg = replace(training_instance_config(base, prefix, int(idx), base_port), keep_running=True)\n"
        "    try:\n"
        "        InstanceRunner(cfg, log_root).close(force=True)\n"
        "    except BaseException as exc:\n"
        "        print(f'cleanup close failed {cfg.name}: {type(exc).__name__}: {exc}', flush=True)\n"
        "    patterns = [\n"
        "        str(cfg.root / 'run' / 'launch' / 'clientRunProgramArgs.txt'),\n"
        "        str(cfg.root / 'launch' / 'clientRunProgramArgs.txt'),\n"
        "    ]\n"
        "    pids = set()\n"
        "    for pattern in patterns:\n"
        "        try:\n"
        "            out = subprocess.run(['pgrep', '-f', pattern], check=False, capture_output=True, text=True).stdout\n"
        "        except BaseException:\n"
        "            out = ''\n"
        "        for raw in out.split():\n"
        "            try:\n"
        "                pid = int(raw)\n"
        "            except ValueError:\n"
        "                continue\n"
        "            if pid != os.getpid():\n"
        "                pids.add(pid)\n"
        "    pgids = set()\n"
        "    for pid in pids:\n"
        "        try:\n"
        "            pgids.add(os.getpgid(pid))\n"
        "        except BaseException:\n"
        "            pass\n"
        "    for pgid in pgids:\n"
        "        try:\n"
        "            os.killpg(pgid, signal.SIGTERM)\n"
        "        except BaseException:\n"
        "            pass\n"
        "    time.sleep(1.0)\n"
        "    for pgid in pgids:\n"
        "        try:\n"
        "            os.killpg(pgid, 0)\n"
        "        except ProcessLookupError:\n"
        "            continue\n"
        "        except BaseException:\n"
        "            continue\n"
        "        try:\n"
        "            os.killpg(pgid, signal.SIGKILL)\n"
        "        except BaseException:\n"
        "            pass\n"
        "    print(f'closed {cfg.name} pids={sorted(pids)}', flush=True)\n"
    )
    subprocess.run([args.python, "-c", helper], cwd=str(ROOT), env=env, check=False, timeout=120)


def build_specs(
    task_indices: list[int],
    args: argparse.Namespace,
    *,
    episode_id_start: int = 0,
    phase_name: str = "all",
) -> list[EpisodeSpec]:
    specs: list[EpisodeSpec] = []
    episode_id = episode_id_start
    mode = resolve_bench_mode(args)
    agent_variants: list[str | None] = parse_agents(args.single_agents) if mode == "single-parallel" else [None]
    for task_index in task_indices:
        for repeat_index in range(args.rollout_n):
            for controlled_agent in agent_variants:
                specs.append(
                    EpisodeSpec(
                        episode_id=episode_id,
                        task_index=int(task_index),
                        repeat_index=repeat_index,
                        chunk_index=0,
                        instance_index=1,
                        task_mode="single_agent" if mode == "single-parallel" else "multiagent",
                        controlled_agent=controlled_agent,
                        atomic_role=args.atomic_role or None,
                        random_seed=(args.seed + episode_id if args.seed is not None else None),
                        phase_name=phase_name,
                    )
                )
                episode_id += 1
    chunk_size = max(1, (len(specs) + args.chunks - 1) // args.chunks)
    assigned: list[EpisodeSpec] = []
    for index, spec in enumerate(specs):
        chunk_index = index // chunk_size
        within_chunk = index % chunk_size
        assigned.append(
            EpisodeSpec(
                episode_id=spec.episode_id,
                task_index=spec.task_index,
                repeat_index=spec.repeat_index,
                chunk_index=chunk_index,
                instance_index=(within_chunk % args.instance_count) + 1,
                task_mode=spec.task_mode,
                controlled_agent=spec.controlled_agent,
                atomic_role=spec.atomic_role,
                random_seed=spec.random_seed,
                phase_name=spec.phase_name,
            )
        )
    return assigned


def load_phase_specs(args: argparse.Namespace) -> tuple[list[int], list[EpisodeSpec]]:
    if args.phase_plan is None:
        task_indices = parse_indices(args.task_indices) if args.task_indices else default_task_indices()
        return task_indices, build_specs(task_indices, args)
    plan = json.loads(Path(args.phase_plan).read_text(encoding="utf-8"))
    task_indices: list[int] = []
    specs: list[EpisodeSpec] = []
    for phase in plan:
        phase_indices = parse_indices(str(phase["task_indices"]))
        task_indices.extend(phase_indices)
        specs.extend(
            build_specs(
                phase_indices,
                args,
                episode_id_start=len(specs),
                phase_name=str(phase["name"]),
            )
        )
    return task_indices, specs


def valid_episode(record: dict[str, Any]) -> bool:
    return bool(record.get("ok")) and not bool(record.get("discarded"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_agent_prompts(
    prompt_dir: Path,
    *,
    task: dict[str, Any],
    step_index: int,
    active_agents: tuple[str, ...] | list[str],
    poses: dict[str, Any],
    previous_messages: dict[str, str] | None = None,
) -> None:
    from action_space import ALLOWED_ACTIONS
    from prompts import build_agent_action_prompt

    prompt_dir.mkdir(parents=True, exist_ok=True)
    previous_messages = previous_messages or {}
    for agent_name in active_agents:
        teammate_name = "AgentB" if agent_name == "AgentA" else "AgentA"
        prompt = build_agent_action_prompt(
            agent_name=agent_name,
            teammate_name=teammate_name,
            task=task,
            step_index=step_index,
            allowed_actions=ALLOWED_ACTIONS,
            poses=poses,
            teammate_previous_message=previous_messages.get(teammate_name),
        )
        prompt_path = prompt_dir / f"step_{step_index:03d}_{agent_name.lower()}.txt"
        prompt_path.write_text(prompt + "\n", encoding="utf-8")


def save_agent_prompt_images(
    prompt_dir: Path,
    *,
    step_index: int,
    active_agents: tuple[str, ...] | list[str],
    agent_images: dict[str, bytes],
    model_agent_images: dict[str, bytes] | None = None,
) -> None:
    prompt_dir.mkdir(parents=True, exist_ok=True)
    model_agent_images = model_agent_images or agent_images
    for agent_name in active_agents:
        agent_key = agent_name.lower()
        canonical_key = "agent_a" if agent_name == "AgentA" else "agent_b"
        image_bytes = agent_images[agent_name]
        (prompt_dir / f"step_{step_index:03d}_{canonical_key}.png").write_bytes(image_bytes)
        own_path = prompt_dir / f"step_{step_index:03d}_{agent_key}_image_1_own.png"
        own_path.write_bytes(model_agent_images[agent_name])


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def run_episode_subprocess(
    spec: EpisodeSpec,
    args: argparse.Namespace,
    env: dict[str, str],
    output_dir: Path,
) -> dict[str, Any]:
    spec_dir = output_dir / "specs"
    spec_dir.mkdir(parents=True, exist_ok=True)
    spec_path = spec_dir / f"episode_{spec.episode_id:04d}.json"
    write_json(spec_path, asdict(spec))
    command = [
        args.python,
        str(Path(__file__).resolve()),
        "--worker",
        "--spec",
        str(spec_path),
        "--output-dir",
        str(output_dir),
        "--model",
        args.model,
        "--provider",
        args.provider,
        "--api-base-url",
        args.api_base_url or "",
        "--api-key",
        args.api_key or "",
        "--api-key-env",
        args.api_key_env or "",
        "--tasks",
        str(args.tasks),
        "--pack-src",
        str(args.pack_src),
        "--rollout-yaml",
        str(args.rollout_yaml),
        "--randomize-start-agents",
        str(args.randomize_start_agents or ""),
        "--start-position-jitter",
        str(args.start_position_jitter),
        "--start-yaw-jitter",
        str(args.start_yaw_jitter),
        "--max-steps",
        str(args.max_steps),
        "--task-mode",
        spec.task_mode,
        "--controlled-agent",
        spec.controlled_agent or "AgentA",
        "--atomic-role",
        spec.atomic_role or "",
        "--instance-prefix",
        args.instance_prefix,
        "--base-port",
        str(args.base_port),
        "--agent-temperature",
        str(args.agent_temperature),
        "--agent-max-tokens",
        str(args.agent_max_tokens),
        "--agent-api-max-retries",
        str(args.agent_api_max_retries),
        "--agent-api-retry-delay",
        str(args.agent_api_retry_delay),
    ]
    if args.refresh_pack:
        command.append("--refresh-pack")
    if args.randomize_starts:
        command.append("--randomize-starts")
    started = time.time()
    proc = subprocess.Popen(
        command,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=args.episode_timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        stdout, stderr = proc.communicate()
        cleanup_instances([spec.instance_index], args, env, output_dir)
        return {
            "ok": False,
            "timeout": True,
            "episode_id": spec.episode_id,
            "task_index": spec.task_index,
            "repeat_index": spec.repeat_index,
            "chunk_index": spec.chunk_index,
            "instance_index": spec.instance_index,
            "task_mode": spec.task_mode,
            "controlled_agent": spec.controlled_agent,
            "elapsed_sec": round(time.time() - started, 3),
            "error": f"episode timed out after {args.episode_timeout}s",
            "stdout_tail": stdout[-4000:],
            "stderr_tail": stderr[-4000:],
        }
    if proc.returncode != 0:
        cleanup_instances([spec.instance_index], args, env, output_dir)
        return {
            "ok": False,
            "episode_id": spec.episode_id,
            "task_index": spec.task_index,
            "repeat_index": spec.repeat_index,
            "chunk_index": spec.chunk_index,
            "instance_index": spec.instance_index,
            "task_mode": spec.task_mode,
            "controlled_agent": spec.controlled_agent,
            "elapsed_sec": round(time.time() - started, 3),
            "returncode": proc.returncode,
            "stdout_tail": stdout[-4000:],
            "stderr_tail": stderr[-4000:],
        }
    result_path = output_dir / f"episode_{spec.episode_id:04d}" / "result.json"
    if result_path.exists():
        with result_path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    return {
        "ok": False,
        "episode_id": spec.episode_id,
        "task_index": spec.task_index,
        "repeat_index": spec.repeat_index,
        "chunk_index": spec.chunk_index,
        "instance_index": spec.instance_index,
        "elapsed_sec": round(time.time() - started, 3),
        "error": "worker exited without result.json",
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }


def summarize(records: list[dict[str, Any]], total_episodes: int, started: float) -> dict[str, Any]:
    ok_records = [r for r in records if r.get("ok")]
    success_records = [r for r in ok_records if r.get("success")]
    timeout_records = [r for r in records if r.get("timeout")]
    discarded_records = [r for r in records if r.get("discarded")]
    episode_times = [float(r["elapsed_sec"]) for r in records if isinstance(r.get("elapsed_sec"), (int, float))]
    timing_by_agent: dict[str, dict[str, float | int]] = {}
    for agent_name in ("AgentA", "AgentB", "duo"):
        selected = [
            float(r["elapsed_sec"])
            for r in records
            if isinstance(r.get("elapsed_sec"), (int, float))
            and ((r.get("controlled_agent") == agent_name) if agent_name != "duo" else r.get("task_mode") == "multiagent")
        ]
        if selected:
            timing_by_agent[agent_name] = {
                "episodes": len(selected),
                "average_episode_sec": round(sum(selected) / len(selected), 3),
                "total_episode_sec": round(sum(selected), 3),
            }
    return {
        "time_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_sec": round(time.time() - started, 3),
        "average_episode_sec": round(sum(episode_times) / len(episode_times), 3) if episode_times else 0.0,
        "timing_by_agent": timing_by_agent,
        "total_episodes": int(total_episodes),
        "records": len(records),
        "completed_episodes": len(ok_records),
        "successful_episodes": len(success_records),
        "failed_or_incomplete": int(total_episodes) - len(success_records),
        "timeouts": len(timeout_records),
        "discarded": len(discarded_records),
        "success_rate": (len(success_records) / total_episodes) if total_episodes else 0.0,
    }


def remove_attempt_artifacts(output_dir: Path, episode_id: int, record: dict[str, Any] | None = None) -> None:
    shutil.rmtree(output_dir / f"episode_{episode_id:04d}", ignore_errors=True)
    if record and record.get("trace_dir"):
        shutil.rmtree(Path(record["trace_dir"]), ignore_errors=True)


def phase_output_dir(output_dir: Path, spec: EpisodeSpec) -> Path:
    return output_dir if spec.phase_name == "all" else output_dir / spec.phase_name


def write_phase_summaries(
    output_dir: Path,
    specs: list[EpisodeSpec],
    records_by_id: dict[int, dict[str, Any]],
    started: float,
) -> None:
    for phase_name in dict.fromkeys(spec.phase_name for spec in specs):
        phase_specs = [spec for spec in specs if spec.phase_name == phase_name]
        phase_records = [records_by_id[spec.episode_id] for spec in phase_specs if spec.episode_id in records_by_id]
        phase_dir = output_dir if phase_name == "all" else output_dir / phase_name
        write_json(phase_dir / "summary.json", summarize(phase_records, len(phase_specs), started))


def run_parent(args: argparse.Namespace) -> int:
    output_dir = args.output_dir or (ROOT / "bench" / "runs" / f"training_style_{utc_stamp()}")
    output_dir = resolve_path(output_dir)
    assert output_dir is not None
    output_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir = output_dir
    args.tasks = resolve_path(args.tasks)
    args.rollout_yaml = resolve_path(args.rollout_yaml)
    args.instance_config = resolve_path(args.instance_config)
    args.pack_src = resolve_path(args.pack_src)
    args.phase_plan = resolve_path(args.phase_plan)
    args.bench_mode = resolve_bench_mode(args)

    env = training_env(args, output_dir)
    if args.cleanup_only:
        cleanup_instances(list(range(1, args.instance_count + 1)), args, env, output_dir)
        return 0

    task_indices, specs = load_phase_specs(args)
    if args.batch_size and len(task_indices) != args.batch_size:
        print(f"warning: batch_size={args.batch_size}, but task_indices has {len(task_indices)} tasks", flush=True)
    for phase_name in dict.fromkeys(spec.phase_name for spec in specs):
        (output_dir / phase_name).mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir / "bench_config.json",
        {
            "task_indices": task_indices,
            "specs": [asdict(spec) for spec in specs],
            "args": {k: str(v) if isinstance(v, Path) else v for k, v in vars(args).items() if k != "worker"},
        },
    )

    records_by_id: dict[int, dict[str, Any]] = {}
    if args.resume:
        for spec in specs:
            result_path = phase_output_dir(output_dir, spec) / f"episode_{spec.episode_id:04d}" / "result.json"
            if result_path.exists():
                with result_path.open("r", encoding="utf-8") as fh:
                    record = json.load(fh)
                if valid_episode(record):
                    records_by_id[spec.episode_id] = record
        print(
            f"resume: keeping={len(records_by_id)} rerunning={len(specs) - len(records_by_id)} total={len(specs)}",
            flush=True,
        )

    started = time.time()
    specs_to_run = deque(spec for spec in specs if spec.episode_id not in records_by_id)
    if not specs_to_run:
        write_phase_summaries(output_dir, specs, records_by_id, started)
        if args.cleanup_after:
            cleanup_instances(list(range(1, args.instance_count + 1)), args, env, output_dir)
        return 0
    attempt_counts: dict[int, int] = {}
    max_workers = min(args.workers, args.instance_count, len(specs_to_run))
    available_instances = deque(range(1, max_workers + 1))
    try:
        prepare_instances(args, env)
        prewarm_instances(args, env, output_dir)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures: dict[concurrent.futures.Future[dict[str, Any]], tuple[EpisodeSpec, int, Path]] = {}
            while specs_to_run or futures:
                while specs_to_run and available_instances:
                    original_spec = specs_to_run.popleft()
                    instance_index = available_instances.popleft()
                    spec = EpisodeSpec(**{**asdict(original_spec), "instance_index": instance_index})
                    phase_dir = phase_output_dir(output_dir, spec)
                    remove_attempt_artifacts(phase_dir, spec.episode_id)
                    attempt_counts[spec.episode_id] = attempt_counts.get(spec.episode_id, 0) + 1
                    phase_env = dict(env)
                    phase_env["IT_TAKETWO_ROLLOUT_TRACE_DIR"] = str(phase_dir / "traces")
                    future = pool.submit(run_episode_subprocess, spec, args, phase_env, phase_dir)
                    futures[future] = (spec, instance_index, phase_dir)
                done, _ = concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    spec, instance_index, phase_dir = futures.pop(future)
                    available_instances.append(instance_index)
                    try:
                        record = future.result()
                    except BaseException as exc:  # noqa: BLE001
                        cleanup_instances([spec.instance_index], args, env, output_dir)
                        record = {
                            "ok": False,
                            "episode_id": spec.episode_id,
                            "task_index": spec.task_index,
                            "repeat_index": spec.repeat_index,
                            "chunk_index": spec.chunk_index,
                            "instance_index": spec.instance_index,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    record["attempt"] = attempt_counts[spec.episode_id]
                    append_jsonl(phase_dir / "attempts.jsonl", [record])
                    print(json.dumps(record, ensure_ascii=False), flush=True)
                    if valid_episode(record):
                        records_by_id[spec.episode_id] = record
                        append_jsonl(phase_dir / "episodes.jsonl", [record])
                    else:
                        remove_attempt_artifacts(phase_dir, spec.episode_id, record)
                        specs_to_run.append(spec)
                        print(
                            f"requeue episode={spec.episode_id} phase={spec.phase_name} "
                            f"attempt={attempt_counts[spec.episode_id]}",
                            flush=True,
                        )
                    write_phase_summaries(output_dir, specs, records_by_id, started)
    finally:
        if args.cleanup_after:
            cleanup_instances(list(range(1, args.instance_count + 1)), args, env, output_dir)
    write_phase_summaries(output_dir, specs, records_by_id, started)
    return 0


def extract_agent_images(observation: dict[str, Any], active_agents: tuple[str, ...]) -> dict[str, bytes]:
    image = observation.get("image")
    if not isinstance(image, dict):
        raise RuntimeError(f"observation has no image: keys={list(observation)}")
    agents = image.get("agents")
    if not isinstance(agents, dict):
        raise RuntimeError("observation image has no agents map")
    result: dict[str, bytes] = {}
    for agent in active_agents:
        info = agents.get(agent)
        if not isinstance(info, dict) or not isinstance(info.get("image_bytes"), bytes):
            raise RuntimeError(f"missing image bytes for {agent}")
        result[agent] = info["image_bytes"]
    return result


def model_input_images(task: dict[str, Any], agent_images: dict[str, bytes]) -> dict[str, bytes]:
    task_template = str(task.get("task_template") or "").strip().lower()
    if task_template not in {"truck_driver", "truck_blind_navigation"} or "AgentA" not in agent_images:
        return dict(agent_images)
    from PIL import Image

    with Image.open(io.BytesIO(agent_images["AgentA"])) as source:
        black = Image.new("RGB", source.size, (0, 0, 0))
    encoded = io.BytesIO()
    black.save(encoded, format="PNG")
    result = dict(agent_images)
    result["AgentA"] = encoded.getvalue()
    return result


def run_worker(args: argparse.Namespace) -> int:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if str(MC_ROLLOUT_DIR) not in sys.path:
        sys.path.insert(0, str(MC_ROLLOUT_DIR))
    bench_dir = str(Path(__file__).resolve().parent)
    if bench_dir in sys.path:
        sys.path.remove(bench_dir)
    sys.path.insert(0, bench_dir)

    from agent_driver import build_agent_drivers, choose_agent_actions, driver_metadata
    from verl_adapter.mc_env import MinecraftEnvConfig, MinecraftRolloutEnv

    with Path(args.spec).open("r", encoding="utf-8") as fh:
        spec = EpisodeSpec(**json.load(fh))
    output_dir = resolve_path(args.output_dir)
    assert output_dir is not None
    episode_dir = output_dir / f"episode_{spec.episode_id:04d}"
    episode_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    env_obj: MinecraftRolloutEnv | None = None
    result: dict[str, Any]
    rng = random.Random(spec.random_seed)
    try:
        worker_task_mode = spec.task_mode
        worker_controlled_agent = spec.controlled_agent or "AgentA"
        worker_atomic_role = spec.atomic_role
        env_obj = MinecraftRolloutEnv(
            MinecraftEnvConfig(
                rollout_yaml=resolve_path(args.rollout_yaml),
                tasks=resolve_path(args.tasks),
                pack_src=resolve_path(args.pack_src),
                refresh_pack=bool(args.refresh_pack),
                task_index=spec.task_index,
                random_seed=spec.random_seed,
                randomize_starts=bool(args.randomize_starts),
                randomize_start_agents=str(args.randomize_start_agents or "") or None,
                start_position_jitter=float(args.start_position_jitter),
                start_yaw_jitter=float(args.start_yaw_jitter),
                max_steps=args.max_steps,
                mock=False,
                instance_index=spec.instance_index,
                instance_prefix=args.instance_prefix,
                train_tickgate_base_port=args.base_port,
                use_images=True,
                image_view="agent_pov",
                persistent_instance=True,
                save_trace=True,
                trace_root=output_dir / "traces",
                task_mode=worker_task_mode,
                controlled_agent=worker_controlled_agent,
                atomic_role=worker_atomic_role,
            )
        )
        driver_args = argparse.Namespace(
            policy="ai",
            model=args.model,
            api_base_url=args.api_base_url or None,
            api_key=args.api_key or "EMPTY",
            agent_a_provider=args.provider,
            agent_a_model=args.model,
            agent_a_api_base_url=args.api_base_url or None,
            agent_a_api_key=args.api_key or "EMPTY",
            agent_a_api_key_env=args.api_key_env or None,
            agent_b_provider=args.provider,
            agent_b_model=args.model,
            agent_b_api_base_url=args.api_base_url or None,
            agent_b_api_key=args.api_key or "EMPTY",
            agent_b_api_key_env=args.api_key_env or None,
            agent_temperature=args.agent_temperature,
            agent_max_tokens=args.agent_max_tokens,
            agent_api_max_retries=args.agent_api_max_retries,
            agent_api_retry_delay=args.agent_api_retry_delay,
            fixed_agent_a_action="wait",
            fixed_agent_b_action="wait",
        )
        drivers = build_agent_drivers(driver_args, active_agents=env_obj.active_agents)
        env_obj.task["task_mode"] = worker_task_mode
        observation = env_obj.start()
        previous_messages: dict[str, str] = {}
        communication_records: list[dict[str, Any]] = []
        for _ in range(args.max_steps):
            if observation.get("done"):
                break
            step_index = int(observation.get("step", env_obj.step_index))
            poses = observation.get("poses") or {}
            save_agent_prompts(
                episode_dir / "prompts",
                task=env_obj.task,
                step_index=step_index,
                active_agents=env_obj.active_agents,
                poses=poses,
                previous_messages=previous_messages,
            )
            agent_images = extract_agent_images(observation, tuple(env_obj.active_agents))
            model_images = model_input_images(env_obj.task, agent_images)
            save_agent_prompt_images(
                episode_dir / "prompts",
                step_index=step_index,
                active_agents=env_obj.active_agents,
                agent_images=agent_images,
                model_agent_images=model_images,
            )
            gen_started = time.perf_counter()
            actions, decisions = choose_agent_actions(
                drivers,
                task=env_obj.task,
                step_index=step_index,
                agent_images=model_images,
                poses=poses,
                previous_messages=previous_messages,
                rng=rng,
                active_agents=env_obj.active_agents,
            )
            round_messages = {name: str(decision.get("message") or "") for name, decision in decisions.items()}
            communication_record = {"step": step_index, "received_previous_messages": dict(previous_messages), "sent_messages": round_messages, "decisions": decisions}
            communication_records.append(communication_record)
            append_jsonl(episode_dir / "communication.jsonl", [communication_record])
            previous_messages = round_messages
            actions["_meta"] = {
                "agent_decisions": decisions,
                "driver_metadata": driver_metadata(drivers),
            "communication_rounds": communication_records,
                "generate_s": time.perf_counter() - gen_started,
            }
            observation = env_obj.step(actions)
        success = bool(observation.get("done")) and not bool(observation.get("discarded")) and env_obj._task_done(env_obj.markers)
        result = {
            "ok": True,
            "success": bool(success),
            "discarded": bool(observation.get("discarded")),
            "discard_reason": getattr(env_obj, "_discard_reason", None),
            "episode_id": spec.episode_id,
            "task_index": spec.task_index,
            "repeat_index": spec.repeat_index,
            "chunk_index": spec.chunk_index,
            "instance_index": spec.instance_index,
            "task_mode": worker_task_mode,
            "controlled_agent": spec.controlled_agent,
            "active_agents": list(env_obj.active_agents),
            "random_seed": spec.random_seed,
            "elapsed_sec": round(time.time() - started, 3),
            "step_count": int(env_obj.step_index),
            "episode_reward": float(observation.get("episode_reward", 0.0) or 0.0),
            "markers": observation.get("markers"),
            "phase_timing": env_obj.phase_timing,
            "trace_dir": str(env_obj.trace_dir) if env_obj.trace_dir is not None else None,
            "driver_metadata": driver_metadata(drivers),
            "communication_rounds": communication_records,
        }
    except BaseException as exc:  # noqa: BLE001
        if env_obj is not None:
            try:
                env_obj.mark_failed(exc)
            except BaseException:
                pass
        result = {
            "ok": False,
            "episode_id": spec.episode_id,
            "task_index": spec.task_index,
            "repeat_index": spec.repeat_index,
            "chunk_index": spec.chunk_index,
            "instance_index": spec.instance_index,
            "task_mode": spec.task_mode,
            "controlled_agent": spec.controlled_agent,
            "random_seed": spec.random_seed,
            "elapsed_sec": round(time.time() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }
    finally:
        if env_obj is not None:
            try:
                env_obj.close()
            except BaseException:
                pass
    write_json(episode_dir / "result.json", result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
    return 0 if result.get("ok") else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Training-style It-Taketwo bench runner.")
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--spec", type=Path, help=argparse.SUPPRESS)

    parser.add_argument("--model", default="qwen2.5-vl-7b")
    parser.add_argument("--provider", default="openai_compatible")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:3888/v1")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--api-key-env", default="")
    parser.add_argument("--agent-temperature", type=float, default=0.0)
    parser.add_argument("--agent-max-tokens", type=int, default=160)
    parser.add_argument("--agent-api-max-retries", type=int, default=3)
    parser.add_argument("--agent-api-retry-delay", type=float, default=1.0)

    parser.add_argument("--task-indices", default="", help="Comma/range list. Default reads the mix8 selection JSON.")
    parser.add_argument("--phase-plan", type=Path, default=None, help="JSON phase list used by the config launcher.")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--rollout-n", type=int, default=4)
    parser.add_argument("--chunks", type=int, default=2)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--instance-count", type=int, default=24)
    parser.add_argument("--instance-prefix", default="instance-train")
    parser.add_argument("--base-port", type=int, default=25690)
    parser.add_argument("--instance-config", type=Path, default=ROOT / "yaml" / "instance_train_single.yaml")
    parser.add_argument("--rollout-yaml", type=Path, default=ROOT / "yaml" / "lowlevel_train_episode.yaml")
    parser.add_argument("--randomize-starts", action="store_true")
    parser.add_argument("--randomize-start-agents", default="")
    parser.add_argument("--start-position-jitter", type=float, default=0.6)
    parser.add_argument("--start-yaw-jitter", type=float, default=35.0)
    parser.add_argument("--pack-src", type=Path, default=ROOT / "assert" / "ConstructScene" / "generated" / "datapacks" / "multiagent_scene_pack")
    parser.add_argument("--max-steps", type=int, default=32)
    parser.add_argument("--seed", type=int, default=None)

    parser.add_argument(
        "--bench-mode",
        choices=("single-parallel", "duo-parallel"),
        default=None,
        help="single-parallel runs separate AgentA/AgentB episodes concurrently; duo-parallel controls both agents in each episode.",
    )
    parser.add_argument("--single-agents", default="AgentA,AgentB", help="Agents expanded into separate episodes in single-parallel mode.")
    parser.add_argument("--task-mode", default="multiagent", help="Legacy compatibility; prefer --bench-mode.")
    parser.add_argument("--controlled-agent", default="AgentB", help="Legacy single-agent fallback.")
    parser.add_argument("--atomic-role", default="", help="Optional override; empty uses each task's schema role.")
    parser.add_argument("--use-images", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--image-view", default="agent_pov")
    parser.add_argument("--image-max-width", type=int, default=512)
    parser.add_argument("--image-max-height", type=int, default=288)
    parser.add_argument("--history-window-images", type=int, default=0)
    parser.add_argument("--history-max-tokens", type=int, default=3072)

    parser.add_argument("--capture-timeout", type=float, default=20.0)
    parser.add_argument("--episode-timeout", type=float, default=600.0)
    parser.add_argument("--pose-query-timeout", type=float, default=5.0)
    parser.add_argument("--env-start-retries", type=int, default=2)
    parser.add_argument("--env-start-retry-delay", type=float, default=3.0)
    parser.add_argument("--start-pose-attempts", type=int, default=6)
    parser.add_argument("--start-pose-consecutive", type=int, default=2)
    parser.add_argument("--start-pose-tolerance", type=float, default=4.0)
    parser.add_argument("--pose-fail-limit", type=int, default=2)
    parser.add_argument("--shot-slow-secs", type=float, default=15.0)
    parser.add_argument("--shot-slow-limit", type=int, default=2)

    parser.add_argument("--skip-prepare", action="store_true")
    parser.add_argument("--skip-prewarm", action="store_true")
    parser.add_argument("--prewarm-each-chunk", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--prewarm-parallel", type=int, default=8)
    parser.add_argument("--prewarm-retries", type=int, default=3)
    parser.add_argument("--prewarm-retry-delay", type=float, default=5.0)
    parser.add_argument("--prewarm-ready-timeout", type=float, default=600.0)
    parser.add_argument("--prewarm-puppet-timeout", type=float, default=180.0)
    parser.add_argument("--prewarm-total-timeout", type=float, default=2400.0)
    parser.add_argument("--refresh-pack", action="store_true", default=True)
    parser.add_argument("--save-trace", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--cleanup-after", action="store_true", help="Stop all persistent Minecraft instances after the run.")
    parser.add_argument("--cleanup-only", action="store_true", help="Only stop bench Minecraft instances, then exit.")
    parser.add_argument("--resume", action="store_true", help="Keep normal existing results and rerun missing or abnormal episodes.")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--python", default=DEFAULT_PYTHON)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker:
        return run_worker(args)
    return run_parent(args)


if __name__ == "__main__":
    raise SystemExit(main())

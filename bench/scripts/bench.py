#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
BENCH_DIR = ROOT / "bench"
DEFAULT_PYTHON = "/home/azvm/miniconda3/envs/verl/bin/python"

VALUE_OPTIONS = {
    "task_indices",
    "tasks",
    "batch_size",
    "rollout_n",
    "chunks",
    "workers",
    "instance_count",
    "instance_prefix",
    "base_port",
    "instance_config",
    "rollout_yaml",
    "pack_src",
    "max_steps",
    "seed",
    "bench_mode",
    "single_agents",
    "task_mode",
    "controlled_agent",
    "atomic_role",
    "image_view",
    "image_max_width",
    "image_max_height",
    "history_window_images",
    "history_max_tokens",
    "capture_timeout",
    "episode_timeout",
    "pose_query_timeout",
    "env_start_retries",
    "env_start_retry_delay",
    "start_pose_attempts",
    "start_pose_consecutive",
    "start_pose_tolerance",
    "pose_fail_limit",
    "randomize_start_agents",
    "start_position_jitter",
    "start_yaw_jitter",
    "shot_slow_secs",
    "shot_slow_limit",
    "prewarm_parallel",
    "prewarm_retries",
    "prewarm_retry_delay",
    "prewarm_ready_timeout",
    "prewarm_puppet_timeout",
    "prewarm_total_timeout",
    "agent_temperature",
    "agent_max_tokens",
    "agent_api_max_retries",
    "agent_api_retry_delay",
    "phase_plan",
}

BOOLEAN_OPTIONS = {
    "use_images",
    "prewarm_each_chunk",
    "save_trace",
    "cleanup_after",
    "randomize_starts",
    "skip_prepare",
    "skip_prewarm",
    "resume",
}

PATH_OPTIONS = {"tasks", "instance_config", "rollout_yaml", "pack_src", "phase_plan"}


def load_config(path: Path) -> dict[str, Any]:
    config_path = path.expanduser().resolve()
    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("configuration root must be a mapping")
    data["_config_path"] = str(config_path)
    return data


def resolve_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (ROOT / path).resolve()


def parse_indices(raw: str) -> list[int]:
    values: list[int] = []
    for part in str(raw).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            step = 1 if end >= start else -1
            values.extend(range(start, end + step, step))
        else:
            values.append(int(part))
    return values


def phases(config: dict[str, Any]) -> list[dict[str, Any]]:
    configured = config.get("phases")
    if configured is None:
        return [{"name": "all", "task_indices": config.get("runner", {}).get("task_indices", "")}]
    if not isinstance(configured, list) or not configured:
        raise ValueError("phases must be a non-empty list")
    return configured


def expected_episodes(config: dict[str, Any]) -> int:
    rollout_n = int(config.get("runner", {}).get("rollout_n", 1))
    return sum(len(parse_indices(phase["task_indices"])) * rollout_n for phase in phases(config))


def validate(config: dict[str, Any]) -> None:
    for key in ("name", "model", "runner"):
        if key not in config:
            raise ValueError(f"missing required configuration key: {key}")
    model = config["model"]
    runner = config["runner"]
    for key in ("name", "provider", "api_base_url"):
        if not model.get(key):
            raise ValueError(f"missing model.{key}")
    for key in ("tasks", "pack_src", "bench_mode"):
        if not runner.get(key):
            raise ValueError(f"missing runner.{key}")
    for key in PATH_OPTIONS & runner.keys():
        path = resolve_path(runner[key])
        if not path.exists():
            raise FileNotFoundError(f"runner.{key} does not exist: {path}")
    validate_task_functions(resolve_path(runner["tasks"]), resolve_path(runner["pack_src"]))
    unknown = set(runner) - VALUE_OPTIONS - BOOLEAN_OPTIONS
    if unknown:
        raise ValueError(f"unsupported runner options: {sorted(unknown)}")
    phase_names: set[str] = set()
    for phase in phases(config):
        name = str(phase.get("name") or "").strip()
        if not name or name in phase_names:
            raise ValueError(f"invalid or duplicate phase name: {name!r}")
        phase_names.add(name)
        if not parse_indices(str(phase.get("task_indices") or "")):
            raise ValueError(f"phase {name!r} has no task indices")
    server = config.get("server", {})
    if server.get("enabled"):
        model_path = resolve_path(server.get("model_path", ""))
        if not model_path.exists():
            raise FileNotFoundError(f"server.model_path does not exist: {model_path}")


def validate_task_functions(tasks_path: Path, pack_src: Path) -> None:
    data = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError(f"task file has no tasks: {tasks_path}")
    missing: list[str] = []
    for task in tasks:
        for key in ("scene_setup_function", "scene_clear_function"):
            function_id = str(task.get(key) or "")
            if ":" not in function_id:
                missing.append(f"{task.get('id')}:{key}={function_id!r}")
                continue
            namespace, relative = function_id.split(":", 1)
            candidates = [
                pack_src / "data" / namespace / directory / f"{relative}.mcfunction"
                for directory in ("function", "functions")
            ]
            if not any(candidate.is_file() for candidate in candidates):
                missing.append(f"{task.get('id')}:{function_id}")
    if missing:
        preview = ", ".join(missing[:8])
        raise FileNotFoundError(f"task functions are missing from datapack: {preview}")


def option_name(key: str) -> str:
    return "--" + key.replace("_", "-")


def runner_command(
    config: dict[str, Any],
    output_dir: Path,
    *,
    phase_plan: Path | None = None,
    cleanup_only: bool = False,
) -> list[str]:
    model = config["model"]
    runner = dict(config["runner"])
    if phase_plan is not None:
        runner["phase_plan"] = phase_plan
        runner.pop("task_indices", None)
        runner["batch_size"] = sum(len(parse_indices(phase["task_indices"])) for phase in phases(config))
    command = [
        str(config.get("python", DEFAULT_PYTHON)),
        str(BENCH_DIR / "training_style_bench.py"),
        "--model",
        str(model["name"]),
        "--provider",
        str(model["provider"]),
        "--api-base-url",
        str(model["api_base_url"]),
        "--api-key",
        str(model.get("api_key", "EMPTY")),
        "--api-key-env",
        str(model.get("api_key_env", "")),
        "--output-dir",
        str(output_dir),
    ]
    for key, value in runner.items():
        if key in PATH_OPTIONS:
            value = resolve_path(value)
        if key in VALUE_OPTIONS and value is not None and value != "":
            command.extend([option_name(key), str(value)])
        elif key in BOOLEAN_OPTIONS:
            if key in {"use_images", "prewarm_each_chunk", "save_trace"}:
                command.append(option_name(key) if value else "--no-" + key.replace("_", "-"))
            elif value:
                command.append(option_name(key))
    if cleanup_only:
        command.append("--cleanup-only")
    return command


def wait_for_api(url: str, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    models_url = url.rstrip("/") + "/models"
    while True:
        try:
            with urllib.request.urlopen(models_url, timeout=5) as response:
                if response.status < 400:
                    return
        except Exception:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"model API did not become ready: {models_url}")
            time.sleep(5)


def run_config(config: dict[str, Any], run_dir: Path, *, resume: bool = False) -> int:
    validate(config)
    run_dir.mkdir(parents=True, exist_ok=True)
    if config.get("api_ready_check", True):
        wait_for_api(str(config["model"]["api_base_url"]), float(config.get("api_ready_timeout", 1800)))
    env = os.environ.copy()
    env.update({str(key): str(value) for key, value in config.get("env", {}).items()})
    phase_list = phases(config)
    for phase in phase_list:
        phase_dir = run_dir / str(phase["name"])
        phase_dir.mkdir(parents=True, exist_ok=True)
    phase_plan = run_dir / "phase_plan.json"
    phase_plan.write_text(json.dumps(phase_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    command = runner_command(config, run_dir, phase_plan=phase_plan)
    if resume:
        command.append("--resume")
    with (run_dir / "bench.log").open("a", encoding="utf-8") as log:
        log.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} command={shlex.join(command)}\n")
        log.flush()
        result = subprocess.run(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    return result.returncode


def server_command(config: dict[str, Any]) -> list[str]:
    server = config["server"]
    command = [
        str(config.get("python", DEFAULT_PYTHON)),
        "-m",
        str(server.get("module", "vllm.entrypoints.cli.main")),
        "serve",
        str(resolve_path(server["model_path"])),
        "--host",
        str(server.get("host", "127.0.0.1")),
        "--port",
        str(server.get("port", 3888)),
        "--served-model-name",
        str(config["model"]["name"]),
    ]
    for argument in server.get("args", []):
        command.append(str(argument))
    return command


def create_run_dir(config: dict[str, Any], override: Path | None) -> Path:
    if override:
        return override.expanduser().resolve()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_root = resolve_path(config.get("output_root", "bench/runs"))
    return output_root / f"{config['name']}_{stamp}"


def metadata(config: dict[str, Any], run_dir: Path, session: str) -> None:
    payload = {
        "name": config["name"],
        "session": session,
        "run_dir": str(run_dir),
        "config": config["_config_path"],
        "start_time_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model": config["model"],
        "expected_episodes": expected_episodes(config),
    }
    (run_dir / "run_metadata.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (BENCH_DIR / "runs").mkdir(parents=True, exist_ok=True)
    (BENCH_DIR / "runs" / f"latest_{config['name']}.txt").write_text(str(run_dir) + "\n", encoding="utf-8")


def tmux_start(config: dict[str, Any], run_dir: Path, session: str) -> None:
    validate(config)
    if subprocess.run(["tmux", "has-session", "-t", session], capture_output=True).returncode == 0:
        raise RuntimeError(f"tmux session already exists: {session}")
    run_dir.mkdir(parents=True, exist_ok=True)
    metadata(config, run_dir, session)
    script = Path(__file__).resolve()
    config_path = Path(config["_config_path"])
    server = config.get("server", {})
    if server.get("enabled"):
        env_prefix = ["env", f"CUDA_VISIBLE_DEVICES={server.get('cuda_visible_devices', '0')}"]
        command = env_prefix + server_command(config)
        shell_command = f"cd {shlex.quote(str(ROOT))} && {shlex.join(command)} 2>&1 | tee -a {shlex.quote(str(run_dir / 'server.log'))}"
        subprocess.run(["tmux", "new-session", "-d", "-s", session, "-n", "server", shell_command], check=True)
    else:
        subprocess.run(["tmux", "new-session", "-d", "-s", session, "-n", "monitor", "sleep infinity"], check=True)
    bench_command = [str(config.get("python", DEFAULT_PYTHON)), str(script), "run", "--config", str(config_path), "--run-dir", str(run_dir)]
    bench_shell = f"cd {shlex.quote(str(ROOT))} && {shlex.join(bench_command)} 2>&1 | tee -a {shlex.quote(str(run_dir / 'controller.log'))}"
    subprocess.run(["tmux", "new-window", "-t", session, "-n", "bench", bench_shell], check=True)
    status_command = [str(config.get("python", DEFAULT_PYTHON)), str(script), "status", "--run-dir", str(run_dir), "--watch", "60"]
    subprocess.run(["tmux", "new-window", "-t", session, "-n", "status", shlex.join(status_command)], check=True)
    subprocess.run(["tmux", "set-option", "-t", session, "remain-on-exit", "on"], check=True)


def count_records(run_dir: Path) -> int:
    total = 0
    for path in run_dir.glob("*/episodes.jsonl"):
        total += sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return total


def print_status(run_dir: Path) -> None:
    metadata_path = run_dir / "run_metadata.json"
    metadata_data = json.loads(metadata_path.read_text(encoding="utf-8")) if metadata_path.exists() else {}
    expected = metadata_data.get("expected_episodes", "?")
    print(f"run_dir={run_dir} records={count_records(run_dir)}/{expected}", flush=True)
    for path in sorted(run_dir.glob("*/episodes.jsonl")):
        count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        print(f"  {path.parent.name}: {count}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Configuration-driven It-Taketwo benchmark launcher")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("validate", "run", "start"):
        subparser = subparsers.add_parser(name)
        subparser.add_argument("--config", required=True, type=Path)
        if name in {"run", "start"}:
            subparser.add_argument("--run-dir", type=Path)
        if name == "run":
            subparser.add_argument("--resume", action="store_true")
        if name == "start":
            subparser.add_argument("--session")
    status_parser = subparsers.add_parser("status")
    status_parser.add_argument("--run-dir", required=True, type=Path)
    status_parser.add_argument("--watch", type=float, default=0)
    stop_parser = subparsers.add_parser("stop")
    stop_parser.add_argument("--config", required=True, type=Path)
    stop_parser.add_argument("--session")

    args = parser.parse_args()
    if args.command == "status":
        while True:
            print_status(args.run_dir.expanduser().resolve())
            if args.watch <= 0:
                return 0
            time.sleep(args.watch)

    config = load_config(args.config)
    validate(config)
    if args.command == "validate":
        print(f"valid: {config['name']} expected_episodes={expected_episodes(config)}")
        return 0
    if args.command == "run":
        return run_config(config, create_run_dir(config, args.run_dir), resume=args.resume)
    session = args.session or str(config.get("session") or config["name"])
    if args.command == "start":
        run_dir = create_run_dir(config, args.run_dir)
        tmux_start(config, run_dir, session)
        print(f"session={session}\nrun_dir={run_dir}")
        return 0
    subprocess.run(["tmux", "kill-session", "-t", session], check=False)
    cleanup_dir = resolve_path(config.get("output_root", "bench/runs")) / ".cleanup"
    command = runner_command(config, cleanup_dir, cleanup_only=True)
    return subprocess.run(command, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())

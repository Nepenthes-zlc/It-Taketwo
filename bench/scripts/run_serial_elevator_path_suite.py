#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "bench" / "scripts" / "bench.py"
SUITE_PRESET = os.environ.get("BENCH_SUITE_PRESET", "default")
if SUITE_PRESET == "internvl35_8b":
    SUITE_NAME = "internvl35_8b_elevator_path_4times"
    SESSION_NAME = "internvl35_8b_elevator_path_4times"
    EXPERIMENTS = (
        ("internvl35_8b_elevator", "elevator", ROOT / "bench/yaml/final_elevator_internvl35_8b_fast16.yaml"),
        ("internvl35_8b_path", "path", ROOT / "bench/yaml/final_path_internvl35_8b_fast16.yaml"),
    )
    RUN_COUNT_DIR = "4times"
elif SUITE_PRESET == "elevator_new_medium_1time":
    SUITE_NAME = "elevator_new_medium_1time_four_models"
    SESSION_NAME = "elevator_new_medium_1time"
    EXPERIMENTS = (
        ("qwen25vl7b_new_medium", "elevator", ROOT / "bench/yaml/elevator_new_medium_qwen25vl7b_1time.yaml"),
        ("qwen3vl8b_new_medium", "elevator", ROOT / "bench/yaml/elevator_new_medium_qwen3vl8b_1time.yaml"),
        ("qwen35_9b_new_medium", "elevator", ROOT / "bench/yaml/elevator_new_medium_qwen35_9b_1time.yaml"),
        ("internvl35_8b_new_medium", "elevator", ROOT / "bench/yaml/elevator_new_medium_internvl35_8b_1time.yaml"),
    )
    RUN_COUNT_DIR = "1time"
else:
    SUITE_NAME = "qwen25_path_qwen3_qwen35_elevator_path_4times"
    SESSION_NAME = "serial_elevator_path_4times"
    EXPERIMENTS = (
        ("qwen25_path", "path", ROOT / "bench/yaml/final_path_qwen25vl7b_fast16.yaml"),
        ("qwen3_elevator", "elevator", ROOT / "bench/yaml/final_elevator_qwen3vl8b_fast16.yaml"),
        ("qwen3_path", "path", ROOT / "bench/yaml/final_path_qwen3vl8b_fast16.yaml"),
        ("qwen35_elevator", "elevator", ROOT / "bench/yaml/final_elevator_qwen35_9b_fast16.yaml"),
        ("qwen35_path", "path", ROOT / "bench/yaml/final_path_qwen35_9b_fast16.yaml"),
    )
    RUN_COUNT_DIR = "4times"
SERVER_PORT = 3888
LATEST_PATH = ROOT / "bench/runs/serial_suites" / f"latest_{SUITE_NAME}.txt"


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid YAML: {path}")
    return data


def server_signature(config: dict[str, Any]) -> tuple[Any, ...]:
    server = config["server"]
    return (
        config["python"],
        config["model"]["name"],
        server["model_path"],
        tuple(str(value) for value in server.get("args", [])),
    )


def server_command(config: dict[str, Any]) -> list[str]:
    server = config["server"]
    return [
        str(config["python"]),
        "-m",
        str(server.get("module", "vllm.entrypoints.cli.main")),
        "serve",
        str(server["model_path"]),
        "--host",
        str(server.get("host", "127.0.0.1")),
        "--port",
        str(server.get("port", SERVER_PORT)),
        "--served-model-name",
        str(config["model"]["name"]),
        *(str(value) for value in server.get("args", [])),
    ]


def wait_for_api(base_url: str, process: subprocess.Popen[Any], timeout: float = 1800.0) -> None:
    url = base_url.rstrip("/") + "/models"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"model server exited before becoming ready: returncode={process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 400:
                    return
        except Exception:
            time.sleep(5)
    raise TimeoutError(f"model API did not become ready: {url}")


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(1.0)
        return client.connect_ex(("127.0.0.1", port)) == 0


def wait_for_gpu_memory(log: Any, maximum_used_mib: int = 2048, timeout: float = 300.0) -> None:
    deadline = time.monotonic() + timeout
    last_values: list[int] = []
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            check=False,
            capture_output=True,
            text=True,
        )
        try:
            last_values = [int(line.strip()) for line in result.stdout.splitlines() if line.strip()]
        except ValueError:
            last_values = []
        if len(last_values) >= 4 and max(last_values[:4]) <= maximum_used_mib:
            print(f"[{utc_now()}] GPUs ready: used_mib={last_values[:4]}", file=log, flush=True)
            return
        time.sleep(5)
    raise TimeoutError(f"GPU memory did not clear within {timeout}s: used_mib={last_values[:4]}")


def stop_process_group(process: subprocess.Popen[Any] | None, log: Any) -> None:
    if process is None or process.poll() is not None:
        return
    print(f"[{utc_now()}] stopping vLLM process group pgid={process.pid}", file=log, flush=True)
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=60)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=30)


def stop_stale_server(log: Any) -> None:
    if not port_open(SERVER_PORT):
        return
    print(f"[{utc_now()}] clearing stale listener on tcp/{SERVER_PORT}", file=log, flush=True)
    subprocess.run(["fuser", "-k", f"{SERVER_PORT}/tcp"], check=False, stdout=log, stderr=log)
    deadline = time.monotonic() + 60
    while port_open(SERVER_PORT) and time.monotonic() < deadline:
        time.sleep(1)
    if port_open(SERVER_PORT):
        raise RuntimeError(f"tcp/{SERVER_PORT} is still occupied")


def cleanup_minecraft(config_path: Path, log: Any) -> None:
    config = load_yaml(config_path)
    command = [
        str(config["python"]),
        str(BENCH),
        "stop",
        "--config",
        str(config_path),
        "--session",
        "__serial_suite_cleanup__",
    ]
    print(f"[{utc_now()}] Minecraft cleanup: {' '.join(command)}", file=log, flush=True)
    subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False, timeout=300)


def expected_episode_count(config_path: Path) -> int:
    config = load_yaml(config_path)
    rollout_n = int(config.get("runner", {}).get("rollout_n", 1))
    total_tasks = 0
    for phase in config.get("phases", []):
        value = str(phase.get("task_indices", ""))
        for part in value.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start, end = (int(item) for item in part.split("-", 1))
                total_tasks += end - start + 1
            else:
                total_tasks += 1
    return total_tasks * rollout_n


def completed(run_dir: Path, config_path: Path) -> bool:
    total = 0
    for path in run_dir.glob("*/episodes.jsonl"):
        total += sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    return total == expected_episode_count(config_path)


def run_suite(suite_dir: Path, resume: bool) -> int:
    suite_dir.mkdir(parents=True, exist_ok=True)
    state_path = suite_dir / "state.json"
    suite_log_path = suite_dir / "suite.log"
    state: dict[str, Any] = {
        "suite": SUITE_NAME,
        "suite_dir": str(suite_dir),
        "pid": os.getpid(),
        "started_utc": utc_now(),
        "status": "starting",
        "experiments": [],
    }
    if resume and state_path.exists():
        previous = json.loads(state_path.read_text(encoding="utf-8"))
        state["started_utc"] = previous.get("started_utc", state["started_utc"])
        state["experiments"] = previous.get("experiments", [])
    records = {item["name"]: item for item in state["experiments"] if isinstance(item, dict) and item.get("name")}
    server_process: subprocess.Popen[Any] | None = None
    server_log: Any = None
    active_signature: tuple[Any, ...] | None = None
    active_bench_process: subprocess.Popen[Any] | None = None
    interrupted = False

    def handle_signal(signum: int, _frame: Any) -> None:
        nonlocal interrupted
        interrupted = True
        state["status"] = "stopping"
        state["signal"] = signum
        write_json(state_path, state)
        if active_bench_process is not None and active_bench_process.poll() is None:
            try:
                os.killpg(active_bench_process.pid, signal.SIGTERM)
                active_bench_process.wait(timeout=60)
            except ProcessLookupError:
                pass
            except subprocess.TimeoutExpired:
                os.killpg(active_bench_process.pid, signal.SIGKILL)
                active_bench_process.wait(timeout=30)
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    with suite_log_path.open("a", encoding="utf-8") as suite_log:
        try:
            stop_stale_server(suite_log)
            wait_for_gpu_memory(suite_log)
            cleanup_minecraft(EXPERIMENTS[0][2], suite_log)
            state["status"] = "running"
            write_json(state_path, state)
            for index, (name, task_name, config_path) in enumerate(EXPERIMENTS, start=1):
                existing_record = records.get(name)
                if existing_record and existing_record.get("run_dir"):
                    run_dir = Path(existing_record["run_dir"])
                else:
                    date = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
                    run_dir = ROOT / "bench/runs" / task_name / date / RUN_COUNT_DIR / f"serial_{name}_{suite_dir.name}"
                record = records.setdefault(name, {"name": name, "config": str(config_path), "run_dir": str(run_dir)})
                if completed(run_dir, config_path):
                    record.update({"status": "completed", "skipped_on_resume": True})
                    state["experiments"] = [records[item[0]] for item in EXPERIMENTS if item[0] in records]
                    write_json(state_path, state)
                    continue

                config = load_yaml(config_path)
                signature = server_signature(config)
                if signature != active_signature:
                    stop_process_group(server_process, suite_log)
                    if server_log is not None:
                        server_log.close()
                    stop_stale_server(suite_log)
                    wait_for_gpu_memory(suite_log)
                    server_log_path = suite_dir / f"server_{config['model']['name']}.log"
                    server_log = server_log_path.open("a", encoding="utf-8")
                    environment = os.environ.copy()
                    environment["CUDA_VISIBLE_DEVICES"] = str(config["server"].get("cuda_visible_devices", "0,1,2,3"))
                    command = server_command(config)
                    print(f"[{utc_now()}] starting server: {' '.join(command)}", file=suite_log, flush=True)
                    server_process = subprocess.Popen(
                        command,
                        cwd=ROOT,
                        env=environment,
                        stdout=server_log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    wait_for_api(str(config["model"]["api_base_url"]), server_process)
                    active_signature = signature

                cleanup_minecraft(config_path, suite_log)
                run_dir.mkdir(parents=True, exist_ok=True)
                experiment_log_path = run_dir / "serial_controller.log"
                command = [
                    str(config["python"]),
                    str(BENCH),
                    "run",
                    "--config",
                    str(config_path),
                    "--run-dir",
                    str(run_dir),
                ]
                if resume:
                    command.append("--resume")
                record.update({"status": "running", "started_utc": utc_now(), "sequence": index})
                state["current"] = name
                state["experiments"] = [records[item[0]] for item in EXPERIMENTS if item[0] in records]
                write_json(state_path, state)
                with experiment_log_path.open("a", encoding="utf-8") as experiment_log:
                    active_bench_process = subprocess.Popen(
                        command,
                        cwd=ROOT,
                        stdout=experiment_log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    returncode = active_bench_process.wait()
                    active_bench_process = None
                cleanup_minecraft(config_path, suite_log)
                if returncode != 0 or not completed(run_dir, config_path):
                    record.update({"status": "failed", "returncode": returncode, "ended_utc": utc_now()})
                    state["status"] = "failed"
                    state["experiments"] = [records[item[0]] for item in EXPERIMENTS if item[0] in records]
                    write_json(state_path, state)
                    return returncode or 1
                record.update({"status": "completed", "returncode": 0, "ended_utc": utc_now()})
                state["experiments"] = [records[item[0]] for item in EXPERIMENTS if item[0] in records]
                write_json(state_path, state)
            state.pop("current", None)
            state.update({"status": "completed", "ended_utc": utc_now()})
            write_json(state_path, state)
            return 0
        except KeyboardInterrupt:
            state.update({"status": "stopped" if interrupted else "interrupted", "ended_utc": utc_now()})
            write_json(state_path, state)
            return 130
        except BaseException as exc:
            state.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "ended_utc": utc_now()})
            write_json(state_path, state)
            print(f"[{utc_now()}] fatal: {type(exc).__name__}: {exc}", file=suite_log, flush=True)
            return 1
        finally:
            try:
                cleanup_minecraft(EXPERIMENTS[0][2], suite_log)
            except BaseException as exc:
                print(f"final Minecraft cleanup failed: {exc}", file=suite_log, flush=True)
            stop_process_group(server_process, suite_log)
            if server_log is not None:
                server_log.close()


def latest_suite_dir() -> Path | None:
    if not LATEST_PATH.exists():
        return None
    return Path(LATEST_PATH.read_text(encoding="utf-8").strip())


def start_tmux(resume_dir: Path | None) -> int:
    if subprocess.run(["tmux", "has-session", "-t", SESSION_NAME], capture_output=True).returncode == 0:
        raise RuntimeError(f"tmux session already exists: {SESSION_NAME}")
    if resume_dir is None:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        suite_dir = ROOT / "bench/runs/serial_suites" / f"{SUITE_NAME}_{stamp}"
    else:
        suite_dir = resume_dir.resolve()
    suite_dir.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(str(suite_dir) + "\n", encoding="utf-8")
    command = [sys.executable, str(Path(__file__).resolve()), "run", "--suite-dir", str(suite_dir)]
    if resume_dir is not None:
        command.append("--resume")
    shell_command = (
        f"cd {shlex.quote(str(ROOT))} && "
        f"BENCH_SUITE_PRESET={shlex.quote(SUITE_PRESET)} "
        f"{shlex.join(command)} 2>&1 | tee -a {shlex.quote(str(suite_dir / 'launcher.log'))}"
    )
    subprocess.run(["tmux", "new-session", "-d", "-s", SESSION_NAME, "-n", "suite", shell_command], check=True)
    subprocess.run(["tmux", "set-option", "-t", SESSION_NAME, "remain-on-exit", "on"], check=True)
    print(f"session={SESSION_NAME}\nsuite_dir={suite_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run configured Elevator/Path benchmark experiments serially.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("start")
    resume_parser = subparsers.add_parser("resume")
    resume_parser.add_argument("--suite-dir", type=Path)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--suite-dir", type=Path, required=True)
    run_parser.add_argument("--resume", action="store_true")
    subparsers.add_parser("status")
    subparsers.add_parser("stop")
    args = parser.parse_args()

    if args.command == "start":
        return start_tmux(None)
    if args.command == "resume":
        return start_tmux(args.suite_dir or latest_suite_dir())
    if args.command == "run":
        return run_suite(args.suite_dir.resolve(), args.resume)
    suite_dir = latest_suite_dir()
    if args.command == "status":
        if suite_dir is None:
            print("No serial suite has been started.")
            return 1
        state_path = suite_dir / "state.json"
        print(state_path.read_text(encoding="utf-8") if state_path.exists() else f"starting: {suite_dir}")
        return 0
    if suite_dir is not None:
        state_path = suite_dir / "state.json"
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            pid = state.get("pid")
            if isinstance(pid, int):
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                deadline = time.monotonic() + 360
                while time.monotonic() < deadline:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        break
                    time.sleep(1)
    subprocess.run(["tmux", "kill-session", "-t", SESSION_NAME], check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

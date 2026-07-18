#!/usr/bin/env python3
from __future__ import annotations

import datetime as dt
import json
import os
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
SUITE_NAME = "picture_models_only_4times"
SESSION_NAME = "serial_picture_models_4times"
PORT = 3888
LATEST_PATH = ROOT / "bench/runs/serial_suites/latest_picture_models_only_4times.txt"

EXPERIMENTS = (
    {
        "name": "qwen3_picture",
        "task": "picture",
        "config": ROOT / "bench/yaml/serial_qwen3_picture_4times_fast16.yaml",
    },
    {
        "name": "qwen35_picture",
        "task": "picture",
        "config": ROOT / "bench/yaml/serial_qwen35_picture_4times_fast16.yaml",
    },
    {
        "name": "internvl35_picture",
        "task": "picture",
        "config": ROOT / "bench/yaml/serial_internvl35_picture_4times_fast16.yaml",
    },
)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_yaml(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid YAML: {path}")
    return data


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(1.0)
        return client.connect_ex(("127.0.0.1", port)) == 0


def wait_for_api(base_url: str, process: subprocess.Popen[Any], timeout: float = 1800.0) -> None:
    url = base_url.rstrip("/") + "/models"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"model server exited early: returncode={process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                if response.status < 400:
                    return
        except Exception:
            time.sleep(5)
    raise TimeoutError(f"model API did not become ready: {url}")


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
    raise TimeoutError(f"GPU memory did not clear: used_mib={last_values[:4]}")


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
    if not port_open(PORT):
        return
    print(f"[{utc_now()}] clearing stale listener on tcp/{PORT}", file=log, flush=True)
    subprocess.run(["fuser", "-k", f"{PORT}/tcp"], check=False, stdout=log, stderr=log)
    deadline = time.monotonic() + 60
    while port_open(PORT) and time.monotonic() < deadline:
        time.sleep(1)
    if port_open(PORT):
        raise RuntimeError(f"tcp/{PORT} is still occupied")


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
        str(server.get("port", PORT)),
        "--served-model-name",
        str(config["model"]["name"]),
        *(str(value) for value in server.get("args", [])),
    ]


def cleanup_minecraft(config_path: Path, log: Any) -> None:
    config = load_yaml(config_path)
    command = [
        str(config["python"]),
        str(BENCH),
        "stop",
        "--config",
        str(config_path),
        "--session",
        "__picture_only_cleanup__",
    ]
    print(f"[{utc_now()}] Minecraft cleanup: {' '.join(command)}", file=log, flush=True)
    subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=False, timeout=300)


def run_suite(suite_dir: Path) -> int:
    suite_dir.mkdir(parents=True, exist_ok=True)
    state_path = suite_dir / "state.json"
    state: dict[str, Any] = {
        "suite": SUITE_NAME,
        "suite_dir": str(suite_dir),
        "pid": os.getpid(),
        "started_utc": utc_now(),
        "status": "running",
        "experiments": [],
    }
    write_json(state_path, state)
    server_process: subprocess.Popen[Any] | None = None
    server_log: Any = None
    with (suite_dir / "suite.log").open("a", encoding="utf-8") as suite_log:
        try:
            for index, exp in enumerate(EXPERIMENTS, start=1):
                config_path = exp["config"]
                config = load_yaml(config_path)
                date = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d")
                run_dir = ROOT / "bench/runs" / exp["task"] / date / "4times" / f"serial_{exp['name']}_{suite_dir.name}"
                record = {
                    "name": exp["name"],
                    "config": str(config_path),
                    "run_dir": str(run_dir),
                    "status": "running",
                    "started_utc": utc_now(),
                    "sequence": index,
                }
                state["current"] = exp["name"]
                state["experiments"].append(record)
                write_json(state_path, state)
                stop_process_group(server_process, suite_log)
                if server_log is not None:
                    server_log.close()
                    server_log = None
                stop_stale_server(suite_log)
                wait_for_gpu_memory(suite_log)
                environment = os.environ.copy()
                environment["CUDA_VISIBLE_DEVICES"] = str(config["server"].get("cuda_visible_devices", "0,1,2,3"))
                command = server_command(config)
                server_log = (suite_dir / f"server_{exp['name']}.log").open("a", encoding="utf-8")
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
                cleanup_minecraft(config_path, suite_log)
                run_dir.mkdir(parents=True, exist_ok=True)
                bench_command = [
                    str(config["python"]),
                    str(BENCH),
                    "run",
                    "--config",
                    str(config_path),
                    "--run-dir",
                    str(run_dir),
                    "--resume",
                ]
                with (run_dir / "serial_controller.log").open("a", encoding="utf-8") as experiment_log:
                    process = subprocess.Popen(
                        bench_command,
                        cwd=ROOT,
                        stdout=experiment_log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    returncode = process.wait()
                cleanup_minecraft(config_path, suite_log)
                if returncode != 0:
                    record.update({"status": "failed", "returncode": returncode, "ended_utc": utc_now()})
                    state["status"] = "failed"
                    write_json(state_path, state)
                    return returncode
                record.update({"status": "completed", "returncode": 0, "ended_utc": utc_now()})
                write_json(state_path, state)
            state.pop("current", None)
            state.update({"status": "completed", "ended_utc": utc_now()})
            write_json(state_path, state)
            return 0
        except BaseException as exc:
            state.update({"status": "failed", "error": f"{type(exc).__name__}: {exc}", "ended_utc": utc_now()})
            write_json(state_path, state)
            print(f"[{utc_now()}] fatal: {type(exc).__name__}: {exc}", file=suite_log, flush=True)
            return 1
        finally:
            try:
                cleanup_minecraft(EXPERIMENTS[0]["config"], suite_log)
            except BaseException as exc:
                print(f"final Minecraft cleanup failed: {exc}", file=suite_log, flush=True)
            stop_process_group(server_process, suite_log)
            if server_log is not None:
                server_log.close()


def latest_suite_dir() -> Path | None:
    if not LATEST_PATH.exists():
        return None
    text = LATEST_PATH.read_text(encoding="utf-8").strip()
    return Path(text) if text else None


def start_tmux() -> int:
    if subprocess.run(["tmux", "has-session", "-t", SESSION_NAME], capture_output=True).returncode == 0:
        raise RuntimeError(f"tmux session already exists: {SESSION_NAME}")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
    suite_dir = ROOT / "bench/runs/serial_suites" / f"picture_models_only_{stamp}"
    suite_dir.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LATEST_PATH.write_text(str(suite_dir) + "\n", encoding="utf-8")
    command = [sys.executable, str(Path(__file__).resolve()), "run", "--suite-dir", str(suite_dir)]
    shell_command = f"cd {ROOT} && {' '.join(command)} 2>&1 | tee -a {suite_dir / 'launcher.log'}"
    subprocess.run(["tmux", "new-session", "-d", "-s", SESSION_NAME, "-n", "suite", shell_command], check=True)
    subprocess.run(["tmux", "set-option", "-t", SESSION_NAME, "remain-on-exit", "on"], check=True)
    print(f"session={SESSION_NAME}\nsuite_dir={suite_dir}")
    return 0


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "start"
    if command == "start":
        return start_tmux()
    if command == "run":
        if "--suite-dir" not in sys.argv:
            raise SystemExit("run requires --suite-dir")
        suite_dir = Path(sys.argv[sys.argv.index("--suite-dir") + 1]).resolve()
        return run_suite(suite_dir)
    if command == "status":
        suite_dir = latest_suite_dir()
        if suite_dir is None:
            print("No picture-only suite has been started.")
            return 1
        state_path = suite_dir / "state.json"
        print(state_path.read_text(encoding="utf-8") if state_path.exists() else f"starting: {suite_dir}")
        return 0
    if command == "stop":
        suite_dir = latest_suite_dir()
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
        subprocess.run(["tmux", "kill-session", "-t", SESSION_NAME], check=False)
        subprocess.run(["fuser", "-k", f"{PORT}/tcp"], check=False)
        return 0
    raise SystemExit(f"unknown command: {command}")


if __name__ == "__main__":
    raise SystemExit(main())

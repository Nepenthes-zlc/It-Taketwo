#!/usr/bin/env python3
"""Rollout launcher: CLI parsing, runtime config, Minecraft process, and clients."""
from __future__ import annotations

import argparse
import base64
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

sys.modules.setdefault("launch", sys.modules[__name__])

TEST_DIR = Path(__file__).resolve().parent
WORKSPACE = TEST_DIR.parent
GENERATED_SCENE_DIR = WORKSPACE / "assert" / "ConstructScene" / "generated"
DEFAULT_TASKS = GENERATED_SCENE_DIR / "generated_tasks.json"
DEFAULT_PACK_SRC = GENERATED_SCENE_DIR / "datapacks" / "multiagent_scene_pack"
DEFAULT_ENV_ROOT = WORKSPACE / "env" / "instance-test-01"
DEFAULT_OUTPUT_DIR = WORKSPACE / "runs"
DEFAULT_LOG_DIR = WORKSPACE / "runs" / "logs"
DEFAULT_YAML_DIR = WORKSPACE / "yaml"
DEFAULT_SINGLE_INSTANCE_CONFIG = DEFAULT_YAML_DIR / "instance_single.yaml"
DEFAULT_BATCH_CONFIG = DEFAULT_YAML_DIR / "instances_batch.yaml"


@dataclass
class InstanceConfig:
    name: str
    root: Path
    device: str = "cpu"
    ready_timeout: float = 180.0
    puppet_host: str = "127.0.0.1"
    puppet_port: int = 0
    puppet_timeout: float = 60.0
    tickgate_host: str = "127.0.0.1"
    tickgate_port: int = 25575
    action: str = "w 1.0"
    ticks: int = 5
    render_frames: int = 1
    rounds: int = 3
    use_puppet: bool = True
    keep_running: bool = False


@dataclass
class BatchConfig:
    instances: list[InstanceConfig] = field(default_factory=list)
    parallel: int = 1


def _require_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _load_mapping(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        if path.suffix.lower() in {".yaml", ".yml"}:
            data = yaml.safe_load(file) or {}
        else:
            data = json.load(file)
    return _require_dict(data, str(path))


def _instance_from_dict(data: dict[str, Any], base_dir: Path, default_name: str = "default") -> InstanceConfig:
    if "root" not in data:
        raise ValueError("instance.root is required")
    root = Path(str(data["root"]))
    if not root.is_absolute():
        root = (base_dir / root).resolve()
    return InstanceConfig(
        name=str(data.get("name", default_name)),
        root=root,
        device=str(data.get("device", "cpu")),
        ready_timeout=float(data.get("ready_timeout", 180.0)),
        puppet_host=str(data.get("puppet_host", "127.0.0.1")),
        puppet_port=int(data.get("puppet_port", 0)),
        puppet_timeout=float(data.get("puppet_timeout", 60.0)),
        tickgate_host=str(data.get("tickgate_host", "127.0.0.1")),
        tickgate_port=int(data.get("tickgate_port", 25575)),
        action=str(data.get("action", "w 1.0")),
        ticks=int(data.get("ticks", 5)),
        render_frames=int(data.get("render_frames", 1)),
        rounds=int(data.get("rounds", 3)),
        use_puppet=bool(data.get("use_puppet", True)),
        keep_running=bool(data.get("keep_running", False)),
    )


def load_instance_config(path: str | Path) -> InstanceConfig:
    config_path = Path(path).resolve()
    data = _load_mapping(config_path)
    if "instance" in data:
        data = _require_dict(data["instance"], "instance")
    return _instance_from_dict(data, config_path.parent)


def load_batch_config(path: str | Path) -> BatchConfig:
    config_path = Path(path).resolve()
    data = _load_mapping(config_path)
    raw_instances = data.get("instances")
    if not isinstance(raw_instances, list) or not raw_instances:
        raise ValueError("batch config requires non-empty instances list")
    instances = [
        _instance_from_dict(_require_dict(item, f"instances[{i}]"), config_path.parent, f"instance-{i + 1}")
        for i, item in enumerate(raw_instances)
    ]
    return BatchConfig(instances=instances, parallel=max(1, int(data.get("parallel", 1))))


def read_tickgate_port(env_root: Path, default: int = 25590) -> int:
    config_path = env_root / "run" / "config" / "tickgate-common.toml"
    if not config_path.exists():
        return default
    for line in config_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if stripped.startswith("ipcPort"):
            _, raw_value = stripped.split("=", 1)
            return int(raw_value.strip().split("#", 1)[0])
    return default


def instance_config_from_cli(args: argparse.Namespace) -> InstanceConfig:
    tickgate_port = args.tickgate_port if args.tickgate_port is not None else read_tickgate_port(args.env_root)
    return InstanceConfig(
        name=args.env_root.name,
        root=args.env_root.resolve(),
        device=args.device,
        ready_timeout=args.ready_timeout,
        puppet_host=args.puppet_host,
        puppet_port=args.puppet_port,
        puppet_timeout=args.puppet_timeout,
        tickgate_host=args.tickgate_host,
        tickgate_port=tickgate_port,
        use_puppet=True,
        keep_running=args.keep_running,
    )


def wait_for_tcp(host: str, port: int, timeout: float) -> None:
    deadline = time.time() + timeout
    last_error: OSError | None = None
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2.0):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.5)
    raise TimeoutError(f"timed out waiting for {host}:{port}: {last_error}")


class JsonLineClient:
    def __init__(self, host: str, port: int, timeout: float = 10.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.file = self.sock.makefile("rwb", buffering=0)

    def close(self) -> None:
        try:
            self.file.close()
        finally:
            self.sock.close()

    def cmd(self, line: str, timeout: float = 30.0) -> dict[str, Any]:
        self.sock.settimeout(timeout)
        self.file.write((line + "\n").encode("utf-8"))
        raw = self.file.readline()
        if not raw:
            raise RuntimeError(f"empty response for {line!r}")
        obj = json.loads(raw.decode("utf-8", "ignore"))
        if not obj.get("ok", False):
            raise RuntimeError(f"command failed: {line!r}: {obj}")
        return obj

    def cmd_image(self, line: str = "observe_image 1", timeout: float = 30.0) -> dict[str, Any]:
        obj = self.cmd(line, timeout=timeout)
        if obj.get("imageEncoding") != "png_base64":
            raise RuntimeError(f"unexpected image encoding: {obj.get('imageEncoding')!r}")
        obj["image_bytes"] = base64.b64decode(obj.pop("image"))
        return obj


class TextLineClient:
    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)

    def close(self) -> None:
        self.sock.close()

    def send(self, line: str, wait: bool = True) -> str | None:
        self.sock.sendall((line + "\n").encode("utf-8"))
        if not wait:
            return None
        data = self.sock.recv(4096)
        return data.decode("utf-8", "ignore").strip() if data else None


def discover_puppet_port(root: Path, host: str, configured_port: int, timeout: float) -> int:
    if configured_port:
        wait_for_tcp(host, configured_port, timeout)
        return configured_port

    port_file = root / "run" / "socketpuppet_data" / "port.txt"
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        if port_file.exists():
            try:
                port = int(port_file.read_text(encoding="utf-8").strip())
                if 1 <= port <= 65535:
                    wait_for_tcp(host, port, 2.0)
                    return port
            except Exception as exc:
                last_error = exc
        time.sleep(0.5)
    raise TimeoutError(f"Puppet port not ready from {port_file}: {last_error}")


class InstanceRunner:
    def __init__(self, config: InstanceConfig, log_root: Path):
        self.config = config
        self.log_root = log_root
        self.proc: subprocess.Popen[str] | None = None
        self.tickgate: JsonLineClient | None = None
        self.puppet: TextLineClient | None = None
        self.log_path: Path | None = None

    def start(self) -> None:
        self._start_launcher()
        self._connect_tickgate()
        if self.config.use_puppet:
            self._connect_puppet()

    def capture_image(self, ticks: int = 1, render_frames: int = 1, timeout: float = 60.0) -> dict[str, Any]:
        if self.tickgate is None:
            raise RuntimeError("TickGate is not connected")
        return self.tickgate.cmd_image(f"advance_image {ticks} {render_frames}", timeout=timeout)

    def close(self) -> None:
        if self.puppet:
            try:
                self.puppet.send("stop", wait=True)
            except Exception:
                pass
            self.puppet.close()
        if self.tickgate:
            self.tickgate.close()
        if self.proc and not self.config.keep_running:
            self._terminate_process()

    def _start_launcher(self) -> None:
        launcher = self.config.root / "launch_tickgate.sh"
        if not launcher.exists():
            raise FileNotFoundError(f"launcher not found: {launcher}")
        log_dir = self.log_root / self.config.name
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = log_dir / f"launch-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
        self.proc = subprocess.Popen(
            [str(launcher), "--device", self.config.device],
            cwd=str(self.config.root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            preexec_fn=os.setsid,
        )
        self._start_log_pump()
        print(f"[{self.config.name}] launch log: {self.log_path}")

    def _start_log_pump(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None and self.log_path is not None

        def pump() -> None:
            assert self.proc is not None and self.proc.stdout is not None and self.log_path is not None
            with self.log_path.open("w", encoding="utf-8") as log:
                for line in self.proc.stdout:
                    print(f"[{self.config.name}] {line}", end="")
                    log.write(line)
                    log.flush()

        threading.Thread(target=pump, name=f"{self.config.name}-log-pump", daemon=True).start()

    def _connect_tickgate(self) -> None:
        wait_for_tcp(self.config.tickgate_host, self.config.tickgate_port, self.config.ready_timeout)
        self.tickgate = JsonLineClient(self.config.tickgate_host, self.config.tickgate_port, timeout=10.0)
        self.tickgate.cmd("ping", timeout=5.0)
        self.tickgate.cmd("wait_ready", timeout=self.config.ready_timeout)
        self.tickgate.cmd("pause", timeout=5.0)
        status = self.tickgate.cmd(f"observe_ready {self.config.render_frames}", timeout=20.0)
        print(
            f"[{self.config.name}] TickGate ready: "
            f"server={status.get('completedServerTicks')} render={status.get('completedRenderFrames')}"
        )

    def _connect_puppet(self) -> None:
        port = discover_puppet_port(
            self.config.root,
            self.config.puppet_host,
            self.config.puppet_port,
            self.config.puppet_timeout,
        )
        self.puppet = TextLineClient(self.config.puppet_host, port, timeout=5.0)
        print(f"[{self.config.name}] Puppet ready: {self.config.puppet_host}:{port}")

    def _terminate_process(self) -> None:
        assert self.proc is not None
        if self.proc.poll() is not None:
            return
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
            self.proc.wait(timeout=10)
        except Exception:
            if self.proc.poll() is None:
                os.killpg(self.proc.pid, signal.SIGKILL)
                self.proc.wait(timeout=10)


def _default_config_for(entry: str) -> Path:
    if entry == "lowlevel_batch":
        return DEFAULT_BATCH_CONFIG
    return DEFAULT_SINGLE_INSTANCE_CONFIG


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an It-Taketwo rollout test.")
    parser.add_argument("--entry", choices=["three_views", "lowlevel_episode", "lowlevel_batch"], required=True)
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS)
    parser.add_argument("--task-index", type=int, default=0)
    parser.add_argument("--task-indices", default=None)
    parser.add_argument("--episodes-per-task", type=int, default=1)
    parser.add_argument("--parallel", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")

    parser.add_argument("--pack-src", type=Path, default=DEFAULT_PACK_SRC)
    parser.add_argument("--pack-dst", type=Path, default=None)
    parser.add_argument("--env-root", type=Path, default=DEFAULT_ENV_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR / "qwen_lowlevel_rollout_result.json")
    parser.add_argument("--frames-dir", type=Path, default=DEFAULT_OUTPUT_DIR / "qwen_lowlevel_frames")
    parser.add_argument("--qwen-frames-dir", type=Path, default=DEFAULT_OUTPUT_DIR / "qwen_lowlevel_qwen_pov_frames")
    parser.add_argument("--video-output", type=Path, default=DEFAULT_OUTPUT_DIR / "qwen_lowlevel_rollout.mp4")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--config", type=Path, default=None)

    parser.add_argument("--device", default="cpu")
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--puppet-host", default="127.0.0.1")
    parser.add_argument("--puppet-port", type=int, default=0)
    parser.add_argument("--puppet-timeout", type=float, default=60.0)
    parser.add_argument("--tickgate-host", default="127.0.0.1")
    parser.add_argument("--tickgate-port", type=int, default=None)
    parser.add_argument("--keep-running", action="store_true")

    parser.add_argument("--capture-ticks", type=int, default=2)
    parser.add_argument("--capture-render-frames", type=int, default=2)
    parser.add_argument("--capture-timeout", type=float, default=90.0)
    parser.add_argument("--camera-settle-ticks", type=int, default=10)
    parser.add_argument("--camera-settle-render-frames", type=int, default=6)
    parser.add_argument("--pov-eye-height", type=float, default=1.35)
    parser.add_argument("--pov-forward-offset", type=float, default=0.25)
    parser.add_argument("--pov-camera-settle-ticks", type=int, default=16)
    parser.add_argument("--pov-extra-settle-ticks", type=int, default=8)
    parser.add_argument("--pov-settle-render-frames", type=int, default=10)

    parser.add_argument("--policy", choices=["ai", "qwen", "fixed", "random"], default="qwen")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:3888/v1/")
    parser.add_argument("--api-key", default="EMPTY")
    parser.add_argument("--model", default="qwen2.5-vl-7b")
    parser.add_argument("--agent-a-provider", default="openai_compatible")
    parser.add_argument("--agent-a-model", default=None)
    parser.add_argument("--agent-a-api-base-url", default=None)
    parser.add_argument("--agent-a-api-key", default=None)
    parser.add_argument("--agent-a-api-key-env", default=None)
    parser.add_argument("--agent-b-provider", default="openai_compatible")
    parser.add_argument("--agent-b-model", default=None)
    parser.add_argument("--agent-b-api-base-url", default=None)
    parser.add_argument("--agent-b-api-key", default=None)
    parser.add_argument("--agent-b-api-key-env", default=None)
    parser.add_argument("--agent-temperature", type=float, default=0.0)
    parser.add_argument("--agent-max-tokens", type=int, default=256)
    parser.add_argument("--fixed-agent-a-action", default="wait")
    parser.add_argument("--fixed-agent-b-action", default="forward")
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--action-ticks", type=int, default=4)
    parser.add_argument("--fps", type=int, default=2)
    parser.add_argument("--write-video", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--fail-on-video-error", action="store_true")
    parser.add_argument("--hide-hud", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--refresh-pack", action="store_true")
    parser.add_argument("--fail-fast", action="store_true")
    parser.add_argument("--randomize-starts", action="store_true")
    parser.add_argument("--random-seed", type=int, default=None)
    parser.add_argument("--start-position-jitter", type=float, default=0.6)
    parser.add_argument("--start-yaw-jitter", type=float, default=35.0)
    args = parser.parse_args()
    if args.config is None:
        args.config = _default_config_for(args.entry)
    if args.entry == "lowlevel_batch" and args.output_dir == DEFAULT_OUTPUT_DIR:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        args.output_dir = DEFAULT_OUTPUT_DIR / f"qwen_batch_lowlevel_{stamp}"
    return args


def main() -> int:
    from rollout import run_rollout

    result = run_rollout(parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())

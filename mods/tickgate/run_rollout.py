#!/usr/bin/env python3
import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TICKGATE_HOST = "127.0.0.1"
TICKGATE_PORT = 25575


class JsonLineClient:
    def __init__(self, host: str, port: int, timeout: float = 10.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self.file = self.sock.makefile("rwb", buffering=0)

    def close(self):
        try:
            self.file.close()
        finally:
            self.sock.close()

    def cmd(self, line: str, timeout: float = 30.0) -> dict:
        self.sock.settimeout(timeout)
        self.file.write((line + "\n").encode("utf-8"))
        raw = self.file.readline()
        if not raw:
            raise RuntimeError(f"empty TickGate response for {line!r}")
        obj = json.loads(raw.decode("utf-8", "ignore"))
        if not obj.get("ok", False):
            raise RuntimeError(f"TickGate command failed: {line!r}: {obj}")
        return obj


class TextLineClient:
    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)

    def close(self):
        self.sock.close()

    def send(self, line: str, wait: bool = True) -> str | None:
        self.sock.sendall((line + "\n").encode("utf-8"))
        if not wait:
            return None
        data = self.sock.recv(4096)
        return data.decode("utf-8", "ignore").strip() if data else None


def wait_for_tcp(host: str, port: int, timeout: float):
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            sock = socket.create_connection((host, port), timeout=2.0)
            sock.close()
            return
        except OSError as exc:
            last_error = exc
            time.sleep(0.5)
    raise TimeoutError(f"timed out waiting for {host}:{port}: {last_error}")


def start_launcher(args):
    log_dir = ROOT / "run" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"tickgate-launch-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
    cmd = [str(ROOT / "launch_tickgate.sh"), "--device", args.device]
    proc = subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        preexec_fn=os.setsid,
    )

    def pump():
        with log_path.open("w", encoding="utf-8") as log:
            assert proc.stdout is not None
            for line in proc.stdout:
                print(line, end="")
                log.write(line)
                log.flush()

    thread = threading.Thread(target=pump, name="tickgate-log-pump", daemon=True)
    thread.start()
    print(f"[runner] launch log: {log_path}")
    return proc, log_path


def connect_tickgate(timeout: float) -> JsonLineClient:
    wait_for_tcp(TICKGATE_HOST, TICKGATE_PORT, timeout)
    cli = JsonLineClient(TICKGATE_HOST, TICKGATE_PORT, timeout=10.0)
    cli.cmd("ping", timeout=5.0)
    cli.cmd("wait_ready", timeout=timeout)
    cli.cmd("pause", timeout=5.0)
    status = cli.cmd("observe_ready 1", timeout=20.0)
    print(f"[runner] TickGate ready: server={status.get('completedServerTicks')} render={status.get('completedRenderFrames')}")
    return cli


def discover_puppet_port(args) -> int | None:
    if args.puppet_port:
        wait_for_tcp(args.puppet_host, args.puppet_port, args.puppet_timeout)
        return args.puppet_port

    port_file = ROOT / "run" / "socketpuppet_data" / "port.txt"
    deadline = time.time() + args.puppet_timeout
    last_error = None
    while time.time() < deadline:
        if port_file.exists():
            try:
                port = int(port_file.read_text(encoding="utf-8").strip())
                if 1 <= port <= 65535:
                    wait_for_tcp(args.puppet_host, port, 2.0)
                    return port
            except Exception as exc:
                last_error = exc
        time.sleep(0.5)

    if args.use_puppet:
        raise TimeoutError(f"Puppet port not ready from {port_file}: {last_error}")
    return None


def run_rollout(tickgate: JsonLineClient, puppet: TextLineClient | None, args):
    for i in range(1, args.rounds + 1):
        before = tickgate.cmd("observe_ready 1", timeout=20.0)
        if puppet:
            reply = puppet.send(args.action, wait=True)
            print(f"[runner] round {i}: Puppet {args.action!r} -> {reply}")
        else:
            print(f"[runner] round {i}: no Puppet action")
        after = tickgate.cmd(f"advance_wait {args.ticks} 1", timeout=max(30.0, args.ticks * 2.0))
        if not after.get("paused") or after.get("pendingTicks") != 0:
            raise RuntimeError(f"bad post-step status: {after}")
        print(
            f"[runner] round {i}: server {before.get('completedServerTicks')} -> {after.get('completedServerTicks')}, "
            f"render {before.get('completedRenderFrames')} -> {after.get('completedRenderFrames')}"
        )


def terminate_process(proc: subprocess.Popen):
    if proc.poll() is not None:
        return
    try:
        os.killpg(proc.pid, signal.SIGTERM)
        proc.wait(timeout=10)
    except Exception:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--puppet-host", default="127.0.0.1")
    parser.add_argument("--puppet-port", type=int, default=0)
    parser.add_argument("--puppet-timeout", type=float, default=60.0)
    parser.add_argument("--use-puppet", action="store_true")
    parser.add_argument("--no-rollout", action="store_true")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--ticks", type=int, default=5)
    parser.add_argument("--action", default="w 1.0")
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()

    proc = None
    tickgate = None
    puppet = None
    try:
        proc, _ = start_launcher(args)
        tickgate = connect_tickgate(args.ready_timeout)

        if args.use_puppet:
            port = discover_puppet_port(args)
            assert port is not None
            puppet = TextLineClient(args.puppet_host, port, timeout=5.0)
            print(f"[runner] Puppet ready: {args.puppet_host}:{port}")

        if not args.no_rollout:
            run_rollout(tickgate, puppet, args)

        if args.keep_running:
            print("[runner] keeping Minecraft process alive; press Ctrl+C to stop")
            proc.wait()
    finally:
        if puppet:
            try:
                puppet.send("stop", wait=True)
            except Exception:
                pass
            puppet.close()
        if tickgate:
            tickgate.close()
        if proc and not args.keep_running:
            terminate_process(proc)


if __name__ == "__main__":
    main()

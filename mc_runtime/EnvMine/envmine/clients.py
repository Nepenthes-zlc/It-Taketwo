from __future__ import annotations

import json
import socket
import time
import base64
from pathlib import Path


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

    def cmd(self, line: str, timeout: float = 30.0) -> dict:
        self.sock.settimeout(timeout)
        self.file.write((line + "\n").encode("utf-8"))
        raw = self.file.readline()
        if not raw:
            raise RuntimeError(f"empty response for {line!r}")
        obj = json.loads(raw.decode("utf-8", "ignore"))
        if not obj.get("ok", False):
            raise RuntimeError(f"command failed: {line!r}: {obj}")
        return obj

    def cmd_image(self, line: str = "observe_image 1", timeout: float = 30.0) -> dict:
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


def discover_puppet_port(root: Path, host: str, configured_port: int, timeout: float) -> int | None:
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

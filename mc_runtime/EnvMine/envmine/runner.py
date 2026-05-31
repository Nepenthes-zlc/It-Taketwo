from __future__ import annotations

import os
import signal
import subprocess
import threading
from datetime import datetime
from pathlib import Path

from .clients import JsonLineClient, TextLineClient, discover_puppet_port, wait_for_tcp
from .config import InstanceConfig


class InstanceRunner:
    def __init__(self, config: InstanceConfig, log_root: Path):
        self.config = config
        self.log_root = log_root
        self.proc: subprocess.Popen[str] | None = None
        self.tickgate: JsonLineClient | None = None
        self.puppet: TextLineClient | None = None
        self.log_path: Path | None = None

    def run(self) -> dict:
        try:
            self.start()
            rounds = self._run_rollout()
            return {"name": self.config.name, "ok": True, "rounds": rounds, "log": str(self.log_path)}
        finally:
            self.close()

    def start(self) -> None:
        self._start_launcher()
        self._connect_tickgate()
        if self.config.use_puppet:
            self._connect_puppet()

    def step(
        self,
        action: str,
        ticks: int | None = None,
        render_frames: int | None = None,
        advance_timeout: float | None = None,
        wait_puppet: bool = False,
    ) -> dict:
        if self.tickgate is None:
            raise RuntimeError("TickGate is not connected")
        ticks = self.config.ticks if ticks is None else ticks
        render_frames = self.config.render_frames if render_frames is None else render_frames
        before = self.tickgate.cmd(f"observe_ready {render_frames}", timeout=20.0)
        puppet_reply = None
        if self.puppet:
            puppet_reply = self.puppet.send(action, wait=wait_puppet)
            print(f"[{self.config.name}] step: Puppet {action!r} -> {puppet_reply}")
        else:
            print(f"[{self.config.name}] step: no Puppet action")
        timeout = advance_timeout if advance_timeout is not None else max(30.0, ticks * 2.0)
        after = self.tickgate.cmd(f"advance_wait {ticks} {render_frames}", timeout=timeout)
        if not after.get("paused") or after.get("pendingTicks") != 0:
            raise RuntimeError(f"bad post-step status: {after}")
        return {"action": action, "puppet_reply": puppet_reply, "before": before, "after": after}

    def capture_image(self, ticks: int = 1, render_frames: int = 1, timeout: float = 60.0) -> dict:
        if self.tickgate is None:
            raise RuntimeError("TickGate is not connected")
        return self.tickgate.cmd_image(f"advance_image {ticks} {render_frames}", timeout=timeout)

    def step_image(
        self,
        action: str,
        ticks: int | None = None,
        render_frames: int | None = None,
        timeout: float | None = None,
        wait_puppet: bool = False,
    ) -> dict:
        if self.tickgate is None:
            raise RuntimeError("TickGate is not connected")
        ticks = self.config.ticks if ticks is None else ticks
        render_frames = self.config.render_frames if render_frames is None else render_frames
        puppet_reply = None
        if self.puppet:
            puppet_reply = self.puppet.send(action, wait=wait_puppet)
            print(f"[{self.config.name}] step_image: Puppet {action!r} -> {puppet_reply}")
        capture_timeout = timeout if timeout is not None else max(60.0, ticks * 2.0)
        image = self.capture_image(ticks=ticks, render_frames=render_frames, timeout=capture_timeout)
        return {"action": action, "puppet_reply": puppet_reply, "image": image}

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
        cmd = [str(launcher), "--device", self.config.device]
        self.proc = subprocess.Popen(
            cmd,
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
        assert self.proc is not None
        assert self.proc.stdout is not None
        assert self.log_path is not None

        def pump() -> None:
            assert self.proc is not None
            assert self.proc.stdout is not None
            assert self.log_path is not None
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
        assert port is not None
        self.puppet = TextLineClient(self.config.puppet_host, port, timeout=5.0)
        print(f"[{self.config.name}] Puppet ready: {self.config.puppet_host}:{port}")

    def _run_rollout(self) -> list[dict]:
        if self.tickgate is None:
            raise RuntimeError("TickGate is not connected")
        results = []
        for i in range(1, self.config.rounds + 1):
            result = self.step(self.config.action, wait_puppet=True)
            puppet_reply = result["puppet_reply"]
            before = result["before"]
            after = result["after"]
            print(
                f"[{self.config.name}] round {i}: "
                f"server {before.get('completedServerTicks')} -> {after.get('completedServerTicks')}, "
                f"render {before.get('completedRenderFrames')} -> {after.get('completedRenderFrames')}"
            )
            results.append({"round": i, "puppet_reply": puppet_reply, "before": before, "after": after})
        return results

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

from __future__ import annotations

import fcntl
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

from .paths import WorkspacePaths, discover_workspace


def ensure_envmine_on_path(workspace: WorkspacePaths | None = None) -> WorkspacePaths:
    workspace = workspace or discover_workspace()
    envmine_path = str(workspace.envmine)
    if envmine_path not in sys.path:
        sys.path.insert(0, envmine_path)
    return workspace


@dataclass
class InstanceLease:
    name: str
    instance: object
    lock_path: Path
    _file: TextIO

    def release(self) -> None:
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        finally:
            self._file.close()

    def __enter__(self) -> "InstanceLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


def acquire_instance(
    batch_config: Path,
    *,
    lock_dir: Path,
    timeout: float = 600.0,
    poll_interval: float = 1.0,
    workspace: WorkspacePaths | None = None,
) -> InstanceLease:
    workspace = ensure_envmine_on_path(workspace)

    from envmine.config import load_batch_config

    config_path = Path(batch_config).expanduser().resolve()
    batch = load_batch_config(config_path)
    if not batch.instances:
        raise ValueError(f"batch config has no instances: {config_path}")

    lock_dir.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    last_error: str | None = None

    while time.monotonic() < deadline:
        for instance in batch.instances:
            lock_path = lock_dir / f"{instance.name}.lock"
            handle = lock_path.open("a+", encoding="utf-8")
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                continue
            handle.seek(0)
            handle.truncate()
            handle.write(f"{time.time():.3f}\n")
            handle.flush()
            return InstanceLease(name=instance.name, instance=instance, lock_path=lock_path, _file=handle)
        last_error = f"no free instance in {config_path}"
        time.sleep(poll_interval)

    raise TimeoutError(f"timed out acquiring EnvMine instance lock after {timeout:.1f}s: {last_error}")

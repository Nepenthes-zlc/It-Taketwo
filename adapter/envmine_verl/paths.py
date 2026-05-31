from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class WorkspacePaths:
    root: Path
    envmine: Path
    verl: Path
    adapter: Path
    configs: Path
    scripts: Path


def discover_workspace(start: Path | None = None) -> WorkspacePaths:
    current = (start or Path(__file__)).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "EnvMine").exists() and (candidate / "adapter").exists():
            return WorkspacePaths(
                root=candidate,
                envmine=(candidate / "EnvMine").resolve(),
                verl=(candidate / "verl").resolve(),
                adapter=(candidate / "adapter").resolve(),
                configs=(candidate / "configs").resolve(),
                scripts=(candidate / "scripts").resolve(),
            )
    raise FileNotFoundError("could not discover EnvMineVerl workspace root")

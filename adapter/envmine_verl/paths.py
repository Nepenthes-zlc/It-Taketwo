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
        local_envmine = candidate / "mc_runtime" / "EnvMine"
        legacy_envmine = candidate / "EnvMine"
        if (local_envmine.exists() or legacy_envmine.exists()) and (candidate / "adapter").exists():
            envmine = local_envmine if local_envmine.exists() else legacy_envmine
            return WorkspacePaths(
                root=candidate,
                envmine=envmine.resolve(),
                verl=(candidate / "verl").resolve(),
                adapter=(candidate / "adapter").resolve(),
                configs=(candidate / "configs").resolve(),
                scripts=(candidate / "scripts").resolve(),
            )
    raise FileNotFoundError("could not discover EnvMineVerl workspace root")

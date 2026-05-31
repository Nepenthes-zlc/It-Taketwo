from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .paths import WorkspacePaths, discover_workspace


@dataclass(frozen=True)
class EnvMineRolloutConfig:
    config: Path
    task_indices: str = "0"
    episodes_per_task: int = 1
    policy: str = "fixed"
    model: str = "qwen2.5-vl-7b"
    api_base_url: str = "http://127.0.0.1:3888/v1/"
    max_steps: int = 2
    parallel: int | None = None
    output_dir: Path | None = None
    write_video: bool = False
    random_seed: int | None = None


def _load_json_from_stdout(stdout: str) -> dict[str, Any]:
    decoder = json.JSONDecoder()
    for start, char in enumerate(stdout):
        if char != "{":
            continue
        try:
            obj, end = decoder.raw_decode(stdout[start:])
        except json.JSONDecodeError:
            continue
        if stdout[start + end :].strip():
            continue
        if not isinstance(obj, dict):
            raise RuntimeError(f"final JSON value is not an object: {type(obj).__name__}")
        return obj
    raise RuntimeError(f"no complete JSON object found in stdout: {stdout[-1000:]}")


def build_batch_command(workspace: WorkspacePaths, cfg: EnvMineRolloutConfig, dry_run: bool = False) -> list[str]:
    script = workspace.envmine / "qwen_batch_lowlevel_rollout.py"
    cmd = [
        sys.executable,
        str(script),
        "--config",
        str(cfg.config),
        "--task-indices",
        cfg.task_indices,
        "--episodes-per-task",
        str(cfg.episodes_per_task),
        "--policy",
        cfg.policy,
        "--model",
        cfg.model,
        "--api-base-url",
        cfg.api_base_url,
        "--max-steps",
        str(cfg.max_steps),
    ]
    if cfg.parallel is not None:
        cmd.extend(["--parallel", str(cfg.parallel)])
    if cfg.output_dir is not None:
        cmd.extend(["--output-dir", str(cfg.output_dir)])
    if not cfg.write_video:
        cmd.append("--no-write-video")
    if cfg.random_seed is not None:
        cmd.extend(["--random-seed", str(cfg.random_seed)])
    if dry_run:
        cmd.append("--dry-run")
    return cmd


def run_batch_rollout(cfg: EnvMineRolloutConfig, workspace: WorkspacePaths | None = None, dry_run: bool = False) -> dict[str, Any]:
    workspace = workspace or discover_workspace()
    cmd = build_batch_command(workspace, cfg, dry_run=dry_run)
    proc = subprocess.run(
        cmd,
        cwd=str(workspace.envmine),
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    summary = _load_json_from_stdout(proc.stdout)
    summary["returncode"] = proc.returncode
    summary["command"] = cmd
    if proc.returncode != 0:
        summary["stdout_tail"] = proc.stdout[-4000:]
    return summary

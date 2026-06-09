#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
YAML_DIR = ROOT / "yaml"
ENTRYPOINTS = {
    "three_views": {
        "script": ROOT / "test" / "launch.py",
        "description": "capture AgentA, AgentB, and observer screenshots",
    },
    "lowlevel_episode": {
        "script": ROOT / "test" / "launch.py",
        "description": "run one low-level action rollout episode",
    },
    "lowlevel_batch": {
        "script": ROOT / "test" / "launch.py",
        "description": "run batched/parallel low-level rollout episodes",
    },
}
BOOLEAN_OPTIONAL = {"write_video", "hide_hud"}


def load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError(f"YAML config must be a mapping: {path}")
    return data


def option_name(key: str) -> str:
    return "--" + key.replace("_", "-")


def value_to_string(value: Any) -> str:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def args_from_mapping(mapping: dict[str, Any]) -> list[str]:
    argv: list[str] = []
    for key, value in mapping.items():
        if value is None:
            continue
        flag = option_name(key)
        if isinstance(value, bool):
            if key in BOOLEAN_OPTIONAL:
                argv.append(flag if value else "--no-" + key.replace("_", "-"))
            elif value:
                argv.append(flag)
            continue
        argv.extend([flag, value_to_string(value)])
    return argv


def resolve_config_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    return path.resolve()


def resolve_entry(config: dict[str, Any], override: str | None) -> str:
    entry = override or config.get("entry")
    if entry not in ENTRYPOINTS:
        known = ", ".join(sorted(ENTRYPOINTS))
        raise ValueError(f"YAML must set entry to one of: {known}")
    return str(entry)


def build_command(config_path: Path, entry_override: str | None, extra: list[str]) -> tuple[list[str], dict[str, str], dict[str, Any]]:
    config = load_config(config_path)
    entry = resolve_entry(config, entry_override)
    python_bin = str(config.get("python") or sys.executable)
    runner = config.get("runner") or {}
    if not isinstance(runner, dict):
        raise ValueError("runner must be a mapping if present")
    env_updates = config.get("env") or {}
    if not isinstance(env_updates, dict):
        raise ValueError("env must be a mapping if present")
    raw_args = config.get("args") or {}
    if not isinstance(raw_args, dict):
        raise ValueError("args must be a mapping if present")

    if extra and extra[0] == "--":
        extra = extra[1:]

    command = [python_bin, str(ENTRYPOINTS[entry]["script"]), "--entry", entry] + args_from_mapping(raw_args) + extra
    env = {str(key): str(value) for key, value in env_updates.items() if value is not None}
    metadata = {
        "config": str(config_path),
        "entry": entry,
        "description": ENTRYPOINTS[entry]["description"],
        "script": str(ENTRYPOINTS[entry]["script"]),
        "python": python_bin,
        "runner": runner,
        "args": raw_args,
        "command": command,
    }
    return command, env, metadata


def shell_join(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def list_entries() -> None:
    for name, spec in sorted(ENTRYPOINTS.items()):
        print(f"{name}\t{spec['description']}")


def list_configs() -> None:
    for path in sorted(YAML_DIR.glob("*.yaml")):
        try:
            config = load_config(path)
            entry = config.get("entry")
            args = config.get("args") or {}
            dry_run = args.get("dry_run") if isinstance(args, dict) else None
            if entry:
                suffix = f"\tdry_run={dry_run}" if dry_run is not None else ""
                print(f"{path.relative_to(ROOT)}\ttype=test\tentry={entry}{suffix}")
            else:
                kind = "batch_runtime_config" if "instances" in config else "single_runtime_config" if "instance" in config else "config"
                print(f"{path.relative_to(ROOT)}\ttype={kind}")
        except Exception as exc:
            print(f"{path.relative_to(ROOT)}\tERROR={exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run an It-Taketwo test entrypoint from a YAML config.")
    parser.add_argument("--config", type=Path, help="YAML config path, usually yaml/*.yaml")
    parser.add_argument("--entry", choices=sorted(ENTRYPOINTS), default=None, help="Override or supply YAML entry.")
    parser.add_argument("--print-command", action="store_true", help="Print the resolved command before running.")
    parser.add_argument("--validate-only", action="store_true", help="Parse YAML and print the resolved command without running it.")
    parser.add_argument("--json", action="store_true", help="With --validate-only, print machine-readable metadata.")
    parser.add_argument("--list-entries", action="store_true", help="List known entry names.")
    parser.add_argument("--list-configs", action="store_true", help="List yaml/*.yaml configs.")
    parser.add_argument("extra", nargs=argparse.REMAINDER, help="Extra CLI args appended after YAML args. Use -- before extras.")
    ns = parser.parse_args()

    if ns.list_entries:
        list_entries()
        return 0
    if ns.list_configs:
        list_configs()
        return 0
    if ns.config is None:
        parser.error("--config is required unless --list-entries or --list-configs is used")

    config_path = resolve_config_path(ns.config)
    command, env_updates, metadata = build_command(config_path, ns.entry, ns.extra)
    if ns.validate_only:
        if ns.json:
            payload = dict(metadata)
            payload["env"] = env_updates
            payload["command_line"] = shell_join(command)
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"config: {metadata['config']}")
            print(f"entry: {metadata['entry']} ({metadata['description']})")
            print(f"script: {metadata['script']}")
            if env_updates:
                print("env: " + ", ".join(f"{k}={v}" for k, v in sorted(env_updates.items())))
            print("command: " + shell_join(command))
        return 0

    should_print = bool(metadata["runner"].get("print_command")) or ns.print_command
    if should_print:
        print(shell_join(command), flush=True)

    env = os.environ.copy()
    env.update(env_updates)
    return subprocess.call(command, cwd=str(ROOT), env=env)


if __name__ == "__main__":
    raise SystemExit(main())

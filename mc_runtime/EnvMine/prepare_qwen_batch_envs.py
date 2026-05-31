#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_TEMPLATE = ROOT / "envs" / "qwen-runtime-task12-purevision"
DEFAULT_DEST_ROOT = ROOT / "envs"
DEFAULT_CONFIG_OUTPUT = ROOT / "configs" / "qwen_batch_lowlevel.json"


def ensure_safe_dest(path: Path, dest_root: Path) -> None:
    resolved = path.resolve()
    root = dest_root.resolve()
    if root not in resolved.parents and resolved != root:
        raise ValueError(f"refusing to modify destination outside {root}: {resolved}")


def copy_or_link(src: Path, dst: Path, copy_shared: bool) -> None:
    if copy_shared:
        shutil.copytree(src, dst, symlinks=True)
    else:
        dst.symlink_to(src, target_is_directory=True)


def ignore_runtime_state(dir_path: str, names: list[str]) -> set[str]:
    ignored = {"logs", "crash-reports"}.intersection(names)
    if Path(dir_path).name == "socketpuppet_data":
        ignored.update(names)
    return ignored


def patch_tickgate_port(run_dir: Path, port: int) -> None:
    config_path = run_dir / "config" / "tickgate-common.toml"
    text = config_path.read_text(encoding="utf-8")
    patched, count = re.subn(r"(?m)^ipcPort\s*=\s*\d+", f"ipcPort = {port}", text)
    if count != 1:
        raise RuntimeError(f"expected exactly one ipcPort entry in {config_path}, got {count}")
    config_path.write_text(patched, encoding="utf-8")


def remove_stale_locks(run_dir: Path) -> None:
    stale_files = [
        run_dir / "socketpuppet_data" / "port.txt",
        run_dir / "saves" / "New World" / "session.lock",
    ]
    for path in stale_files:
        if path.exists() or path.is_symlink():
            path.unlink()


def prepare_one(template: Path, dest: Path, port: int, copy_shared: bool, force: bool) -> None:
    if dest.exists() or dest.is_symlink():
        if not force:
            raise FileExistsError(f"destination exists: {dest}. Use --force to replace it.")
        if dest.is_symlink() or dest.is_file():
            dest.unlink()
        else:
            shutil.rmtree(dest)
    dest.mkdir(parents=True)
    shutil.copy2(template / "launch_tickgate.sh", dest / "launch_tickgate.sh")
    readme = template / "README.md"
    if readme.exists():
        shutil.copy2(readme, dest / "README.md")
    copy_or_link(template / "launch", dest / "launch", copy_shared)
    copy_or_link(template / "libraries", dest / "libraries", copy_shared)
    shutil.copytree(template / "run", dest / "run", symlinks=True, ignore=ignore_runtime_state)
    (dest / "run" / "socketpuppet_data").mkdir(parents=True, exist_ok=True)
    remove_stale_locks(dest / "run")
    patch_tickgate_port(dest / "run", port)


def build_config(args: argparse.Namespace) -> dict[str, Any]:
    instances = []
    config_dir = args.config_output.expanduser().resolve().parent
    for index in range(args.count):
        env_index = index + 1
        instance_root = (args.dest_root / f"{args.prefix}-{env_index}").resolve()
        root_value = os.path.relpath(instance_root, config_dir)
        instances.append(
            {
                "name": f"{args.prefix}-{env_index}",
                "root": root_value,
                "device": args.device,
                "ready_timeout": args.ready_timeout,
                "tickgate_host": "127.0.0.1",
                "tickgate_port": args.base_port + index,
                "use_puppet": True,
                "puppet_host": "127.0.0.1",
                "puppet_port": 0,
                "puppet_timeout": args.puppet_timeout,
                "rounds": 3,
                "ticks": 5,
                "render_frames": 1,
                "action": "w 1.0",
            }
        )
    return {"parallel": min(args.parallel, args.count), "instances": instances}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare independent EnvMine runtime directories for batched Qwen rollouts.")
    parser.add_argument("--template", type=Path, default=DEFAULT_TEMPLATE)
    parser.add_argument("--dest-root", type=Path, default=DEFAULT_DEST_ROOT)
    parser.add_argument("--prefix", default="qwen-batch")
    parser.add_argument("--count", type=int, default=2)
    parser.add_argument("--base-port", type=int, default=25590)
    parser.add_argument("--parallel", type=int, default=2)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--puppet-timeout", type=float, default=60.0)
    parser.add_argument("--config-output", type=Path, default=DEFAULT_CONFIG_OUTPUT)
    parser.add_argument("--copy-shared", action="store_true", help="Copy launch/libraries instead of symlinking them to the template.")
    parser.add_argument("--force", action="store_true", help="Replace existing generated qwen-batch directories.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.template = args.template.expanduser().resolve()
    args.dest_root = args.dest_root.expanduser().resolve()
    if args.count < 1:
        raise ValueError("--count must be >= 1")
    if not (args.template / "launch_tickgate.sh").exists():
        raise FileNotFoundError(f"template launcher not found: {args.template / 'launch_tickgate.sh'}")
    args.dest_root.mkdir(parents=True, exist_ok=True)
    for index in range(args.count):
        dest = args.dest_root / f"{args.prefix}-{index + 1}"
        ensure_safe_dest(dest, args.dest_root)
        prepare_one(args.template, dest, args.base_port + index, args.copy_shared, args.force)

    config = build_config(args)
    args.config_output.parent.mkdir(parents=True, exist_ok=True)
    args.config_output.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "config": str(args.config_output), "instances": len(config["instances"])}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

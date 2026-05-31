#!/usr/bin/env python3
import argparse
import shutil
from pathlib import Path


DEFAULT_MODS = [
    "/mnt/shared-storage-user/steai-share/zhanglechao/multiagent/env/test/agent_b/.minecraft/versions/MultiAgent/mods/neoforge-carpet-1.21.1-1.0.8+v251027.jar",
    "/mnt/shared-storage-user/steai-share/zhanglechao/multiagent/env/test/agent_b/.minecraft/versions/MultiAgent/mods/socketpuppet-1.0.0.jar",
]


def copy_one(src: Path, dst_dir: Path, overwrite: bool) -> str:
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name

    if dst.exists() and not overwrite:
        return f"skip {dst}"

    shutil.copy2(src, dst)
    return f"copied {src} -> {dst}"


def main():
    parser = argparse.ArgumentParser(
        description="Copy one or more Minecraft mods to a batch of env slots."
    )
    parser.add_argument(
        "--env-root",
        default="/mnt/shared-storage-user/steai-share/zhanglechao/multiagent/env/env1",
    )
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=32)
    parser.add_argument("--version-dir", default="1219")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--mod",
        action="append",
        dest="mods",
        help="Source mod jar path. Can be passed multiple times.",
    )
    args = parser.parse_args()

    mods = [Path(p) for p in (args.mods or DEFAULT_MODS)]
    for mod in mods:
        if not mod.exists():
            raise FileNotFoundError(f"mod not found: {mod}")

    env_root = Path(args.env_root)

    for env_id in range(args.start, args.start + args.count):
        dst_dir = (
            env_root
            / str(env_id)
            / ".minecraft"
            / "versions"
            / args.version_dir
            / "mods"
        )
        for mod in mods:
            try:
                print(copy_one(mod, dst_dir, overwrite=args.overwrite))
            except Exception as exc:
                print(f"failed env={env_id} mod={mod.name} dst={dst_dir}: {exc}")


if __name__ == "__main__":
    main()

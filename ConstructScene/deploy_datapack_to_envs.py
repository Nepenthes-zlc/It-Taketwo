#!/usr/bin/env python3
import argparse
import shutil
from pathlib import Path


def deploy_one(src_pack: Path, dst_datapacks_dir: Path, overwrite: bool) -> str:
    dst_datapacks_dir.mkdir(parents=True, exist_ok=True)
    dst_pack = dst_datapacks_dir / src_pack.name

    if dst_pack.exists():
        if not overwrite:
            return f"skip {dst_pack}"
        if dst_pack.is_dir():
            shutil.rmtree(dst_pack)
        else:
            dst_pack.unlink()

    shutil.copytree(src_pack, dst_pack)
    return f"copied {src_pack} -> {dst_pack}"


def main():
    parser = argparse.ArgumentParser(
        description="Copy generated Minecraft datapack to a batch of env slots."
    )
    repo_root = Path(__file__).resolve().parents[1]
    parser.add_argument(
        "--src-pack",
        default=str(repo_root / "ConstructScene" / "generated" / "datapacks" / "multiagent_scene_pack"),
    )
    parser.add_argument(
        "--env-root",
        default="/mnt/shared-storage-user/steai-share/zhanglechao/multiagent/env/env1",
    )
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--count", type=int, default=32)
    parser.add_argument("--world-name", default="nature")
    parser.add_argument("--version-dir", default="1219")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    src_pack = Path(args.src_pack)
    env_root = Path(args.env_root)

    if not src_pack.exists():
        raise FileNotFoundError(f"source datapack not found: {src_pack}")

    for env_id in range(args.start, args.start + args.count):
        dst = (
            env_root
            / str(env_id)
            / ".minecraft"
            / "versions"
            / args.version_dir
            / "saves"
            / args.world_name
            / "datapacks"
        )
        try:
            print(deploy_one(src_pack, dst, overwrite=args.overwrite))
        except Exception as exc:
            print(f"failed env={env_id} dst={dst}: {exc}")


if __name__ == "__main__":
    main()

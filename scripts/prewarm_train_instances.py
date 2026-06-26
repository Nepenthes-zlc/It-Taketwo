#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MC_ROLLOUT_DIR = PROJECT_ROOT / "mc_rollout"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(MC_ROLLOUT_DIR) not in sys.path:
    sys.path.insert(0, str(MC_ROLLOUT_DIR))

from game_functions import datapack_dst, ensure_datapack, game_cmd  # noqa: E402
from launch import DEFAULT_LOG_DIR, DEFAULT_PACK_SRC, InstanceRunner, load_instance_config, tcp_ready  # noqa: E402
from verl_adapter.mc_env import training_instance_config  # noqa: E402


# World-level gamerules applied once after prewarm; they persist for the whole run
# (a per-rollout scene reload does not reset gamerules). Killing non-player entities
# is a one-shot cleanup that stays clean because doMobSpawning is disabled.
POST_PREWARM_COMMANDS = [
    "gamerule doMobLoot false",
    "gamerule doTileDrops false",
    "gamerule doMobSpawning false",
    "kill @e[type=!player]",  # keep AgentA/AgentB/Dev (all players); remove mobs, items, etc.
]


def apply_post_prewarm_setup(instance_config: Any, log_root: Path) -> bool:
    """Connect to an already-ready instance and apply persistent gamerules plus a
    one-shot non-player-entity cleanup. Best-effort: failures are logged, not fatal.

    Gated off by default: the attach+command path can time out on instances that are
    still busy right after prewarm, leaving them in a wedged state that stalls training.
    Enable with IT_TAKETWO_POST_PREWARM=1 only once it's made robust."""
    import os
    if os.environ.get("IT_TAKETWO_POST_PREWARM", "0").lower() not in {"1", "true", "yes", "on"}:
        return False
    runner = InstanceRunner(instance_config, log_root)
    try:
        runner.start()  # keep_running=True + tcp_ready => attaches without relaunch
        for cmd in POST_PREWARM_COMMANDS:
            game_cmd(runner, cmd, 5)
        return True
    except BaseException as exc:  # noqa: BLE001
        print(
            f"post-prewarm setup failed instance={instance_config.name}: {type(exc).__name__}: {exc}",
            flush=True,
        )
        return False
    finally:
        try:
            runner.close()  # keep_running=True => leaves the Minecraft process alive
        except BaseException:  # noqa: BLE001
            pass


def resolve_project_path(value: str | Path | None) -> Path | None:
    if value is None:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def read_puppet_port(root: Path) -> int | None:
    port_file = root / "run" / "socketpuppet_data" / "port.txt"
    if not port_file.exists():
        return None
    try:
        port = int(port_file.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None


def latest_launch_log(log_root: Path, name: str) -> Path | None:
    log_dir = log_root / name
    if not log_dir.exists():
        return None
    logs = sorted(log_dir.glob("launch-*.log"), key=lambda path: path.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def persistent_instance_ready(instance_config: Any) -> bool:
    if not tcp_ready(instance_config.tickgate_host, instance_config.tickgate_port, timeout=1.0):
        return False
    if not instance_config.use_puppet:
        return True
    puppet_port = instance_config.puppet_port or read_puppet_port(instance_config.root)
    if puppet_port is None:
        return False
    return tcp_ready(instance_config.puppet_host, puppet_port, timeout=1.0)


def prewarm_one(args: argparse.Namespace, index: int) -> dict[str, Any]:
    base_config = load_instance_config(resolve_project_path(args.config))
    base_config = replace(
        base_config,
        device=args.device or base_config.device,
        ready_timeout=args.ready_timeout or base_config.ready_timeout,
        puppet_timeout=args.puppet_timeout or base_config.puppet_timeout,
        keep_running=True,
    )
    instance_config = training_instance_config(base_config, args.prefix, index, args.base_port)
    pack_src = resolve_project_path(args.pack_src)
    pack_dst = datapack_dst(instance_config.root)
    ensure_datapack(pack_src, pack_dst, refresh=args.refresh_pack)
    log_root = resolve_project_path(args.log_dir) or DEFAULT_LOG_DIR

    last_exc: BaseException | None = None
    attempts = max(1, int(args.retries) + 1)
    for attempt in range(1, attempts + 1):
        if persistent_instance_ready(instance_config):
            log_path = latest_launch_log(log_root, instance_config.name)
            apply_post_prewarm_setup(instance_config, log_root)
            return {
                "index": index,
                "name": instance_config.name,
                "tickgate_port": instance_config.tickgate_port,
                "log": str(log_path) if log_path else None,
                "attempt": attempt,
                "attached": True,
            }

        runner = InstanceRunner(instance_config, log_root)
        try:
            runner._start_launcher()
            deadline = time.time() + float(args.ready_timeout)
            while time.time() < deadline:
                if runner.proc is not None and runner.proc.poll() is not None:
                    raise RuntimeError(f"Minecraft exited early with code {runner.proc.returncode}; log={runner.log_path}")
                if persistent_instance_ready(instance_config):
                    log_path = runner.log_path or latest_launch_log(log_root, instance_config.name)
                    apply_post_prewarm_setup(instance_config, log_root)
                    return {
                        "index": index,
                        "name": instance_config.name,
                        "tickgate_port": instance_config.tickgate_port,
                        "log": str(log_path) if log_path else None,
                        "attempt": attempt,
                    }
                time.sleep(1.0)
            raise TimeoutError(
                f"timed out waiting for persistent instance {instance_config.name} "
                f"tickgate={instance_config.tickgate_host}:{instance_config.tickgate_port}"
            )
        except BaseException as exc:
            last_exc = exc
            if runner.proc is not None and runner.proc.poll() is None:
                try:
                    runner._terminate_process()
                except BaseException:
                    pass
            if attempt >= attempts:
                break
            print(
                f"prewarm retry instance={index:02d} attempt={attempt}/{attempts}: {type(exc).__name__}: {exc}",
                flush=True,
            )
            time.sleep(max(0.0, float(args.retry_delay)))
    assert last_exc is not None
    raise last_exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prewarm persistent Minecraft train instances.")
    parser.add_argument("--config", default="yaml/instance_train_single.yaml")
    parser.add_argument("--count", type=int, default=4)
    parser.add_argument("--prefix", default="instance-train")
    parser.add_argument("--base-port", type=int, default=25690)
    parser.add_argument("--parallel", type=int, default=8)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--ready-timeout", type=float, default=600.0)
    parser.add_argument("--puppet-timeout", type=float, default=180.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--retry-delay", type=float, default=5.0)
    parser.add_argument("--pack-src", default=str(DEFAULT_PACK_SRC))
    parser.add_argument("--log-dir", default=str(DEFAULT_LOG_DIR))
    parser.add_argument("--refresh-pack", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    count = max(1, int(args.count))
    parallel = max(1, min(int(args.parallel), count))
    print(f"prewarm persistent Minecraft instances: count={count} parallel={parallel}", flush=True)
    failures: list[tuple[int, BaseException]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
        futures = {pool.submit(prewarm_one, args, index): index for index in range(1, count + 1)}
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                result = future.result()
            except BaseException as exc:
                failures.append((index, exc))
                print(f"prewarm failed instance={index:02d}: {type(exc).__name__}: {exc}", flush=True)
            else:
                print(
                    f"prewarm ready {result["name"]}: tickgate_port={result["tickgate_port"]} "
                    f"attempt={result.get("attempt", 1)} log={result["log"]}",
                    flush=True,
                )
    if failures:
        lines = ", ".join(f"{idx:02d}:{type(exc).__name__}" for idx, exc in failures)
        raise SystemExit(f"prewarm failed for {len(failures)} instance(s): {lines}")


if __name__ == "__main__":
    main()

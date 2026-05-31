from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class InstanceConfig:
    name: str
    root: Path
    device: str = "cpu"
    ready_timeout: float = 180.0
    puppet_host: str = "127.0.0.1"
    puppet_port: int = 0
    puppet_timeout: float = 60.0
    tickgate_host: str = "127.0.0.1"
    tickgate_port: int = 25575
    action: str = "w 1.0"
    ticks: int = 5
    render_frames: int = 1
    rounds: int = 3
    use_puppet: bool = True
    keep_running: bool = False


@dataclass
class BatchConfig:
    instances: list[InstanceConfig] = field(default_factory=list)
    parallel: int = 1


def _require_dict(value: Any, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)
    return _require_dict(data, str(path))


def _instance_from_dict(data: dict[str, Any], base_dir: Path, default_name: str = "default") -> InstanceConfig:
    if "root" not in data:
        raise ValueError("instance.root is required")
    root = Path(str(data["root"]))
    if not root.is_absolute():
        root = (base_dir / root).resolve()
    return InstanceConfig(
        name=str(data.get("name", default_name)),
        root=root,
        device=str(data.get("device", "cpu")),
        ready_timeout=float(data.get("ready_timeout", 180.0)),
        puppet_host=str(data.get("puppet_host", "127.0.0.1")),
        puppet_port=int(data.get("puppet_port", 0)),
        puppet_timeout=float(data.get("puppet_timeout", 60.0)),
        tickgate_host=str(data.get("tickgate_host", "127.0.0.1")),
        tickgate_port=int(data.get("tickgate_port", 25575)),
        action=str(data.get("action", "w 1.0")),
        ticks=int(data.get("ticks", 5)),
        render_frames=int(data.get("render_frames", 1)),
        rounds=int(data.get("rounds", 3)),
        use_puppet=bool(data.get("use_puppet", True)),
        keep_running=bool(data.get("keep_running", False)),
    )


def load_instance_config(path: str | Path) -> InstanceConfig:
    config_path = Path(path).resolve()
    data = _load_json(config_path)
    if "instance" in data:
        data = _require_dict(data["instance"], "instance")
    return _instance_from_dict(data, config_path.parent)


def load_batch_config(path: str | Path) -> BatchConfig:
    config_path = Path(path).resolve()
    data = _load_json(config_path)
    raw_instances = data.get("instances")
    if not isinstance(raw_instances, list) or not raw_instances:
        raise ValueError("batch config requires non-empty instances list")
    instances = [
        _instance_from_dict(_require_dict(item, f"instances[{i}]"), config_path.parent, f"instance-{i + 1}")
        for i, item in enumerate(raw_instances)
    ]
    return BatchConfig(instances=instances, parallel=max(1, int(data.get("parallel", 1))))

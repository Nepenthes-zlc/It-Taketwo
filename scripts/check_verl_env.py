#!/usr/bin/env python3
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]
VERL_ROOT = WORKSPACE / "verl"
ADAPTER_ROOT = WORKSPACE / "adapter"


def check_module(name: str) -> dict:
    try:
        module = importlib.import_module(name)
        return {"name": name, "ok": True, "version": str(getattr(module, "__version__", ""))}
    except Exception as exc:
        return {"name": name, "ok": False, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    sys.path.insert(0, str(VERL_ROOT))
    sys.path.insert(0, str(ADAPTER_ROOT))
    modules = [
        "torch",
        "ray",
        "transformers",
        "vllm",
        "accelerate",
        "datasets",
        "hydra",
        "peft",
        "pyarrow",
        "tensordict",
        "torchdata",
        "wandb",
        "codetiming",
        "pandas",
        "numpy",
        "tensorboard",
        "verl",
        "envmine_verl",
    ]
    results = [check_module(name) for name in modules]
    summary = {
        "python": sys.executable,
        "workspace": str(WORKSPACE),
        "ok": all(item["ok"] for item in results),
        "results": results,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

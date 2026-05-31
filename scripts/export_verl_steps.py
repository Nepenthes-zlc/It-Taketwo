#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


WORKSPACE = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export EnvMine episode results to step-level JSONL for verl-side ingestion.")
    parser.add_argument("--input", type=Path, required=True, help="Path to EnvMine batch episodes.jsonl.")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    script = WORKSPACE / "EnvMine" / "export_verl_rollout_jsonl.py"
    cmd = [sys.executable, str(script), "--input", str(args.input), "--output", str(args.output)]
    return subprocess.call(cmd, cwd=str(WORKSPACE / "EnvMine"))


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-/home/azvm/miniconda3/envs/verl/bin/python}"
exec "$PYTHON_BIN" "$ROOT/scripts/run_from_yaml.py" --list-entries "$@"

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="${1:-$ROOT/yaml/three_views.yaml}"
if [[ $# -gt 0 && "$1" != -* ]]; then
  shift
fi
PYTHON_BIN="${PYTHON_BIN:-/home/azvm/miniconda3/envs/verl/bin/python}"
exec "$PYTHON_BIN" "$ROOT/scripts/run_from_yaml.py" --config "$CONFIG" "$@"

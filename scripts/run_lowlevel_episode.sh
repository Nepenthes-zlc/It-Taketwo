#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG="$ROOT/yaml/lowlevel_episode.yaml"
if [[ $# -gt 0 && "$1" != -* ]]; then
  CONFIG="$1"
  shift
fi
PYTHON_BIN="${PYTHON_BIN:-/home/azvm/miniconda3/envs/verl/bin/python}"
exec "$PYTHON_BIN" "$ROOT/scripts/run_from_yaml.py" --entry lowlevel_episode --config "$CONFIG" "$@"

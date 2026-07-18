#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-/home/azvm/miniconda3/envs/verl/bin/python}

if [[ $# -eq 0 ]]; then
  set -- start
fi

export BENCH_SUITE_PRESET=truck_picture_qwen25_3then_models
exec "${PYTHON_BIN}" "${ROOT_DIR}/bench/scripts/run_serial_elevator_path_suite.py" "$@"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python}
SESSION=${SESSION:-elevator_qwen25vl7b_4times_p16}
DATE_UTC=$(date -u +%Y%m%d)
STAMP_UTC=$(date -u +%Y%m%d_%H%M%S)
RUN_DIR=${RUN_DIR:-${ROOT_DIR}/bench/runs/elevator/${DATE_UTC}/4times/portable_elevator_qwen25vl7b_global_p16_${STAMP_UTC}}
CONFIG=${CONFIG:-${ROOT_DIR}/bench/yaml/portable/elevator_qwen25vl7b_4times_parallel16.yaml}

mkdir -p "${RUN_DIR}"
"${PYTHON_BIN}" "${ROOT_DIR}/bench/scripts/bench.py" start \
  --config "${CONFIG}" \
  --session "${SESSION}" \
  --run-dir "${RUN_DIR}"

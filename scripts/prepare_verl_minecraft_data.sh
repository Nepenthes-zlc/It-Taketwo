#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-/home/azvm/miniconda3/envs/verl/bin/python}
VERL_HOME=${VERL_HOME:-/local_nvme/zhanglechao/verl}

export PYTHONPATH="${ROOT_DIR}:${VERL_HOME}:${PYTHONPATH:-}"

TASK_ARGS=()
if [ -n "${TASKS:-}" ]; then
  TASK_ARGS=(--tasks "${TASKS}")
fi

SHUFFLE_ARGS=()
if [ "${SHUFFLE_TASKS:-0}" = "1" ]; then
  SHUFFLE_ARGS=(--shuffle)
fi

"${PYTHON_BIN}" "${ROOT_DIR}/verl_adapter/build_dataset.py" \
  "${TASK_ARGS[@]}" \
  --output-dir "${OUTPUT_DIR:-${ROOT_DIR}/data/verl_minecraft}" \
  --train-size "${TRAIN_SIZE:-4}" \
  --val-size "${VAL_SIZE:-1}" \
  --seed "${SEED:-20260609}" \
  --train-instance-count "${TRAIN_INSTANCE_COUNT:-4}" \
  --task-mode "${TASK_MODE:-multiagent}" \
  --atomic-agents "${SINGLE_AGENT_ATOMIC_AGENTS:-AgentA}" \
  "${SHUFFLE_ARGS[@]}" \
  "$@"

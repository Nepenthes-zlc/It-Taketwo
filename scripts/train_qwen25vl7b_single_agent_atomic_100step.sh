#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
CONFIG_PATH=${CONFIG_PATH:-${ROOT_DIR}/yaml/train_qwen25vl7b_single_agent_atomic_100step.yaml}
export CONFIG_PATH
exec sh "${SCRIPT_DIR}/train_qwen25vl7b_n4_100step.sh" "$@"

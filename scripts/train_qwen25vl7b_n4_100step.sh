#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT_DIR=$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-/home/azvm/miniconda3/envs/verl/bin/python}
CONFIG_PATH=${CONFIG_PATH:-${ROOT_DIR}/yaml/train_qwen25vl7b_n4_100step.yaml}

case "${CONFIG_PATH}" in
  /*) ;;
  *) CONFIG_PATH="${ROOT_DIR}/${CONFIG_PATH}" ;;
esac

if [ ! -f "${CONFIG_PATH}" ]; then
  echo "config not found: ${CONFIG_PATH}" >&2
  exit 2
fi

CONFIG_EXPORTS=$("${PYTHON_BIN}" - "${CONFIG_PATH}" "${ROOT_DIR}" <<'PYCONFIG'
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import os
import shlex
import sys

import yaml

config_path = Path(sys.argv[1]).expanduser().resolve()
root = Path(sys.argv[2]).expanduser().resolve()
with config_path.open("r", encoding="utf-8") as file:
    cfg = yaml.safe_load(file) or {}

env = dict(cfg.get("env") or {})
for key in list(env):
    if key in os.environ:
        env[key] = os.environ[key]
prefix = str(cfg.get("experiment_name_prefix") or env.pop("EXPERIMENT_NAME_PREFIX", "qwen25vl7b_n4_100step_save50"))
experiment_name = os.environ.get("EXPERIMENT_NAME") or str(env.get("EXPERIMENT_NAME") or "")
if not experiment_name:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    experiment_name = f"{prefix}_{stamp}"
env["EXPERIMENT_NAME"] = experiment_name

def render(value: object) -> str:
    text = str(value)
    return text.replace("{experiment_name}", experiment_name).replace("${EXPERIMENT_NAME}", experiment_name)

path_keys = {
    "DATA_DIR",
    "TRAIN_FILE",
    "VAL_FILE",
    "AGENT_LOOP_CONFIG",
    "IT_TAKETWO_ROLLOUT_TRACE_DIR",
}

for key, value in env.items():
    rendered = render(value)
    if key in path_keys:
        path = Path(rendered).expanduser()
        if not path.is_absolute():
            path = root / path
        rendered = str(path.resolve())
    print(f"export {key}={shlex.quote(rendered)}")
PYCONFIG
)

eval "${CONFIG_EXPORTS}"

: "${EXPERIMENT_NAME:?EXPERIMENT_NAME is required}"
export IT_TAKETWO_ROLLOUT_TRACE_DIR=${IT_TAKETWO_ROLLOUT_TRACE_DIR:-${ROOT_DIR}/runs/verl_rollouts/${EXPERIMENT_NAME}}
RUN_CONFIG_DIR="${IT_TAKETWO_ROLLOUT_TRACE_DIR}/run_config"
mkdir -p "${RUN_CONFIG_DIR}"

cleanup_old_minecraft() {
  if [ "${CLEANUP_MINECRAFT_BEFORE_TRAIN:-1}" != "1" ]; then
    return 0
  fi

  echo "cleanup old Minecraft Java/Xvfb processes..."
  JAVA_PIDS=$(pgrep -f "${ROOT_DIR}/env/${TRAIN_INSTANCE_PREFIX:-instance-train}-[0-9][0-9]*/launch/clientRunProgramArgs.txt" || true)
  if [ -n "${JAVA_PIDS}" ]; then
    echo "stopping Minecraft Java pids: ${JAVA_PIDS}"
    for pid in ${JAVA_PIDS}; do
      kill "${pid}" 2>/dev/null || true
    done
    sleep 2
    for pid in ${JAVA_PIDS}; do
      if kill -0 "${pid}" 2>/dev/null; then
        kill -9 "${pid}" 2>/dev/null || true
      fi
    done
  else
    echo "no old Minecraft Java processes found"
  fi

  XVFB_PIDS=$(pgrep -f "Xvfb :.*-auth .*/xvfb-run\." || true)
  if [ -n "${XVFB_PIDS}" ]; then
    echo "stopping Xvfb pids: ${XVFB_PIDS}"
    for pid in ${XVFB_PIDS}; do
      kill "${pid}" 2>/dev/null || true
    done
    sleep 1
    for pid in ${XVFB_PIDS}; do
      if kill -0 "${pid}" 2>/dev/null; then
        kill -9 "${pid}" 2>/dev/null || true
      fi
    done
  else
    echo "no old Xvfb processes found"
  fi
}

"${PYTHON_BIN}" - "${CONFIG_PATH}" "${ROOT_DIR}" "${RUN_CONFIG_DIR}" "$0" <<'PYSNAPSHOT'
from __future__ import annotations

from pathlib import Path
import os
import shutil
import shlex
import sys

import yaml

config_path = Path(sys.argv[1]).expanduser().resolve()
root = Path(sys.argv[2]).expanduser().resolve()
out = Path(sys.argv[3]).expanduser().resolve()
invoked_script = Path(sys.argv[4])
if not invoked_script.is_absolute():
    invoked_script = (Path.cwd() / invoked_script).resolve()

with config_path.open("r", encoding="utf-8") as file:
    cfg = yaml.safe_load(file) or {}

snapshot_files = list(cfg.get("snapshot_files") or [])
if invoked_script.exists():
    try:
        snapshot_files.append(str(invoked_script.relative_to(root)))
    except ValueError:
        snapshot_files.append(str(invoked_script))

seen: set[Path] = set()
for item in snapshot_files:
    src = Path(str(item)).expanduser()
    if not src.is_absolute():
        src = root / src
    src = src.resolve()
    if src in seen or not src.is_file():
        continue
    seen.add(src)
    try:
        rel = src.relative_to(root)
    except ValueError:
        rel = Path(src.name)
    dst = out / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)

keys = [
    "EXPERIMENT_NAME",
    "MODEL_PATH",
    "DATA_DIR",
    "TRAIN_SIZE",
    "VAL_SIZE",
    "SHUFFLE_TASKS",
    "TOTAL_EPOCHS",
    "TOTAL_TRAINING_STEPS",
    "SAVE_FREQ",
    "TEST_FREQ",
    "TRAIN_BATCH_SIZE",
    "PPO_MINI_BATCH_SIZE",
    "ROLLOUT_N",
    "NGPUS_PER_NODE",
    "TRAIN_INSTANCE_COUNT",
    "AGENT_WORKERS",
    "PERSISTENT_MINECRAFT",
    "PREWARM_MINECRAFT",
    "PREWARM_PARALLEL",
    "PREWARM_RETRIES",
    "PREWARM_RETRY_DELAY",
    "PREWARM_READY_TIMEOUT",
    "PREWARM_PUPPET_TIMEOUT",
    "AGENT_LOOP_CONFIG",
    "USE_VLM_IMAGES",
    "MAX_PROMPT_LENGTH",
    "MAX_RESPONSE_LENGTH",
    "IT_TAKETWO_HISTORY_WINDOW_IMAGES",
    "IT_TAKETWO_HISTORY_MAX_TOKENS",
    "IT_TAKETWO_IMAGE_MAX_WIDTH",
    "IT_TAKETWO_IMAGE_MAX_HEIGHT",
    "ROLLOUT_GPU_MEMORY_UTILIZATION",
    "ROLLOUT_MAX_NUM_SEQS",
    "IT_TAKETWO_ROLLOUT_TRACE_DIR",
]
with (out / "resolved_env.sh").open("w", encoding="utf-8") as file:
    file.write("# Resolved environment for this training run.\n")
    for key in keys:
        if key in os.environ:
            file.write(f"export {key}={shlex.quote(os.environ[key])}\n")

with (out / "launch_command.txt").open("w", encoding="utf-8") as file:
    file.write("sh scripts/train_qwen25vl7b_n4_100step.sh\n")
    file.write(f"CONFIG_PATH={config_path}\n")
PYSNAPSHOT

echo "experiment: ${EXPERIMENT_NAME}"
echo "rollout trace: ${IT_TAKETWO_ROLLOUT_TRACE_DIR}"
echo "run config snapshot: ${RUN_CONFIG_DIR}"

if [ "${DRY_RUN:-0}" = "1" ]; then
  echo "DRY_RUN=1, skip launching training."
  exit 0
fi

cleanup_after_train() {
  if [ "${CLEANUP_MINECRAFT_AFTER_TRAIN:-1}" = "1" ]; then
    cleanup_old_minecraft
  fi
}
trap cleanup_after_train EXIT HUP INT TERM

cleanup_old_minecraft
bash "${ROOT_DIR}/scripts/run_verl_online_rl.sh" "$@"

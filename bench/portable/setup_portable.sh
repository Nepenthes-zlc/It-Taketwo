#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
MODEL_DIR=${MODEL_DIR:-${ROOT_DIR}/models/Qwen2.5-VL-7B-Instruct}
PYTHON_BIN=${PYTHON_BIN:-python}

if [[ ! -d "${ROOT_DIR}/minecraft_assets" ]]; then
  echo "Missing ${ROOT_DIR}/minecraft_assets; extract the runtime archive first." >&2
  exit 1
fi
if [[ ! -f "${MODEL_DIR}/config.json" ]]; then
  echo "Missing model weights at ${MODEL_DIR}; extract the model archive or set MODEL_DIR." >&2
  exit 1
fi

rm -f "${ROOT_DIR}/env/instance-test-01/assets"
ln -s ../../minecraft_assets "${ROOT_DIR}/env/instance-test-01/assets"

SOURCE_INSTANCE=instance-test-01 \
TRAIN_INSTANCE_PREFIX=instance-train \
TRAIN_INSTANCE_COUNT=16 \
TRAIN_TICKGATE_BASE_PORT=25690 \
  bash "${ROOT_DIR}/scripts/prepare_train_instances.sh"

mkdir -p "${ROOT_DIR}/bench/yaml/portable"
"${PYTHON_BIN}" - "${ROOT_DIR}" "${MODEL_DIR}" "${PYTHON_BIN}" <<'PY'
from pathlib import Path
import sys
import yaml

root = Path(sys.argv[1])
model_dir = Path(sys.argv[2]).resolve()
python_bin = sys.argv[3]
source = root / "bench/yaml/final_elevator_qwen25vl7b_fast16.yaml"
config = yaml.safe_load(source.read_text(encoding="utf-8"))
config["name"] = "portable_elevator_qwen25vl7b_4times_parallel16"
config["session"] = "portable_elevator_qwen25vl7b_4times_parallel16"
config["output_root"] = "bench/runs/elevator"
config["python"] = python_bin
config["server"]["model_path"] = str(model_dir)
target = root / "bench/yaml/portable/elevator_qwen25vl7b_4times_parallel16.yaml"
target.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
print(f"wrote {target}")
PY

echo "Portable benchmark setup complete."

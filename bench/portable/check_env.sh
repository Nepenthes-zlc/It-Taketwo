#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-python}
JAVA_HOME=${JAVA_HOME:-/usr/lib/jvm/java-21-openjdk-amd64}
failed=0

check_command() {
  if command -v "$1" >/dev/null 2>&1; then
    echo "ok command: $1"
  else
    echo "missing command: $1" >&2
    failed=1
  fi
}

for command in tmux jq vglrun nvidia-smi; do
  check_command "${command}"
done
if command -v ffmpeg >/dev/null 2>&1; then
  echo "ok optional command: ffmpeg"
else
  echo "optional command missing: ffmpeg (only required for videos)"
fi

if [[ -x "${JAVA_HOME}/bin/java" ]]; then
  echo "ok java: $(${JAVA_HOME}/bin/java -version 2>&1 | head -1)"
else
  echo "missing Java 21 under ${JAVA_HOME}" >&2
  failed=1
fi

"${PYTHON_BIN}" - <<'PY' || failed=1
modules = ["yaml", "PIL", "openai", "requests", "torch", "transformers", "vllm"]
for name in modules:
    module = __import__(name)
    print(f"ok python: {name} {getattr(module, '__version__', 'unknown')}")
PY

for path in \
  "${ROOT_DIR}/assert/minecraft/libraries" \
  "${ROOT_DIR}/minecraft_assets/indexes/17.json" \
  "${ROOT_DIR}/env/instance-test-01/launch_tickgate.sh" \
  "${ROOT_DIR}/bench/data/final_data/elevator/generated_tasks.json"; do
  if [[ -e "${path}" ]]; then
    echo "ok asset: ${path}"
  else
    echo "missing asset: ${path}" >&2
    failed=1
  fi
done

"${PYTHON_BIN}" "${ROOT_DIR}/bench/scripts/bench.py" validate \
  --config "${ROOT_DIR}/bench/yaml/portable/elevator_qwen25vl7b_4times_parallel16.yaml" || failed=1

exit "${failed}"

#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-/home/azvm/miniconda3/envs/verl/bin/python}
STAMP=${STAMP:-$(date -u +%Y%m%d_%H%M%S)}
SUITE_DIR=${SUITE_DIR:-"${ROOT_DIR}/bench/runs/serial_suites/picture_models_only_${STAMP}"}
SESSION=${SESSION:-serial_picture_models_4times}
PORT=${PORT:-3888}

CONFIGS=(
  "${ROOT_DIR}/bench/yaml/serial_qwen3_picture_4times_fast16.yaml"
  "${ROOT_DIR}/bench/yaml/serial_qwen35_picture_4times_fast16.yaml"
  "${ROOT_DIR}/bench/yaml/serial_internvl35_picture_4times_fast16.yaml"
)
NAMES=(qwen3_picture qwen35_picture internvl35_picture)
PYTHONS=(
  "/home/azvm/miniconda3/envs/verl/bin/python"
  "/local_nvme/tmp/qwen35_vllm_clean/bin/python"
  "/home/azvm/miniconda3/envs/verl/bin/python"
)
MODELS=(
  "/local_nvme/guanyiming/models/Qwen/Qwen3-VL-8B-Instruct"
  "/local_nvme/zhanglechao/models/Qwen3.5-9B"
  "/local_nvme/zhanglechao/models/InternVL3_5-8B-HF"
)
SERVED=(qwen3-vl-8b qwen3.5-9b internvl3.5-8b)
SERVER_ARGS=(
  "--dtype bfloat16 --gpu-memory-utilization 0.60 --data-parallel-size 4 --max-model-len 8192 --max-num-seqs 32 --limit-mm-per-prompt '{"image":1}' --disable-log-requests"
  "--dtype bfloat16 --gpu-memory-utilization 0.35 --data-parallel-size 4 --max-model-len 8192 --max-num-seqs 8 --limit-mm-per-prompt '{"image":1}' --default-chat-template-kwargs '{"enable_thinking":false}'"
  "--dtype bfloat16 --gpu-memory-utilization 0.60 --data-parallel-size 4 --max-model-len 8192 --max-num-seqs 32 --limit-mm-per-prompt '{"image":1}' --skip-mm-profiling --disable-log-requests"
)

ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() { echo "[$(ts)] $*" | tee -a "${SUITE_DIR}/suite.log"; }

if [[ "${1:-start}" == "status" ]]; then
  if [[ -f "${SUITE_DIR}/state.json" ]]; then
    cat "${SUITE_DIR}/state.json"
  else
    echo "suite_dir=${SUITE_DIR}"
    tmux ls 2>/dev/null | grep -F "${SESSION}" || true
  fi
  exit 0
fi

if [[ "${1:-start}" == "stop" ]]; then
  tmux kill-session -t "${SESSION}" 2>/dev/null || true
  pkill -f "bench/training_style_bench.py.*serial_.*picture" 2>/dev/null || true
  fuser -k "${PORT}/tcp" 2>/dev/null || true
  exit 0
fi

mkdir -p "${SUITE_DIR}"
if tmux has-session -t "${SESSION}" 2>/dev/null; then
  echo "tmux session already exists: ${SESSION}" >&2
  exit 1
fi

RUNNER=$(cat <<'RUNNER_EOF'
set -euo pipefail
cd "${ROOT_DIR}"
mkdir -p "${SUITE_DIR}"
trap 'fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true' EXIT
for idx in 0 1 2; do
  name="${NAMES[$idx]}"
  config="${CONFIGS[$idx]}"
  py="${PYTHONS[$idx]}"
  model="${MODELS[$idx]}"
  served="${SERVED[$idx]}"
  args="${SERVER_ARGS[$idx]}"
  run_dir="${ROOT_DIR}/bench/runs/picture/$(date -u +%Y%m%d)/4times/serial_${name}_picture_models_only_${STAMP}"
  printf '{"suite":"picture_models_only","status":"running","current":"%s","run_dir":"%s","suite_dir":"%s"}
' "$name" "$run_dir" "${SUITE_DIR}" > "${SUITE_DIR}/state.json"
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] starting ${name}" | tee -a "${SUITE_DIR}/suite.log"
  fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
  sleep 5
  CUDA_VISIBLE_DEVICES=0,1,2,3 ${py} -m vllm.entrypoints.cli.main serve "${model}" --host 127.0.0.1 --port "${PORT}" --served-model-name "${served}" ${args} > "${SUITE_DIR}/server_${name}.log" 2>&1 &
  server_pid=$!
  for _ in $(seq 1 360); do
    if curl -sf "http://127.0.0.1:${PORT}/v1/models" >/dev/null; then break; fi
    if ! kill -0 "$server_pid" 2>/dev/null; then echo "server exited for ${name}" >&2; exit 1; fi
    sleep 5
  done
  ${py} "${ROOT_DIR}/bench/scripts/bench.py" stop --config "$config" --session __picture_only_cleanup__ >/dev/null 2>&1 || true
  mkdir -p "$run_dir"
  ${py} "${ROOT_DIR}/bench/scripts/bench.py" run --config "$config" --run-dir "$run_dir" --resume 2>&1 | tee -a "${run_dir}/serial_controller.log"
  rc=${PIPESTATUS[0]}
  ${py} "${ROOT_DIR}/bench/scripts/bench.py" stop --config "$config" --session __picture_only_cleanup__ >/dev/null 2>&1 || true
  kill -TERM "$server_pid" >/dev/null 2>&1 || true
  wait "$server_pid" >/dev/null 2>&1 || true
  fuser -k "${PORT}/tcp" >/dev/null 2>&1 || true
  if [[ "$rc" -ne 0 ]]; then
    printf '{"suite":"picture_models_only","status":"failed","current":"%s","run_dir":"%s","suite_dir":"%s","returncode":%s}
' "$name" "$run_dir" "${SUITE_DIR}" "$rc" > "${SUITE_DIR}/state.json"
    exit "$rc"
  fi
  echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] completed ${name}" | tee -a "${SUITE_DIR}/suite.log"
done
printf '{"suite":"picture_models_only","status":"completed","suite_dir":"%s"}
' "${SUITE_DIR}" > "${SUITE_DIR}/state.json"
RUNNER_EOF
)

export ROOT_DIR SUITE_DIR STAMP PORT
for i in "${!CONFIGS[@]}"; do
  export "CONFIGS_${i}=${CONFIGS[$i]}"
done

tmux new-session -d -s "${SESSION}" -n suite "ROOT_DIR='${ROOT_DIR}' SUITE_DIR='${SUITE_DIR}' STAMP='${STAMP}' PORT='${PORT}' bash -lc $(printf %q "$(declare -p CONFIGS NAMES PYTHONS MODELS SERVED SERVER_ARGS; echo "$RUNNER")")"
tmux set-option -t "${SESSION}" remain-on-exit on >/dev/null
printf 'session=%s
suite_dir=%s
' "${SESSION}" "${SUITE_DIR}"

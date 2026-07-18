#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
PY=${PY:-/home/azvm/miniconda3/envs/verl/bin/python}
STAMP=${STAMP:-$(date -u +%Y%m%d_%H%M%S)}
PORT=${PORT:-3888}
RUN_DIR=${RUN_DIR:-"${ROOT}/bench/runs/maze/$(date -u +%Y%m%d)/1time/serial_qwen25_maze_1time_${STAMP}"}
LOG_DIR=${LOG_DIR:-"${ROOT}/bench/runs/serial_suites/qwen25_maze_1time_${STAMP}"}
mkdir -p "$RUN_DIR" "$LOG_DIR"
echo "run_dir=$RUN_DIR" | tee -a "$LOG_DIR/launcher.log"
echo "log_dir=$LOG_DIR" | tee -a "$LOG_DIR/launcher.log"
cleanup() {
  set +e
  "$PY" "$ROOT/bench/scripts/bench.py" stop --config "$ROOT/bench/yaml/serial_qwen25_maze_1time_fast16.yaml" --session __qwen25_maze_cleanup__ >>"$LOG_DIR/cleanup.log" 2>&1 || true
  if [[ -n "${VLLM_PID:-}" ]]; then
    kill "$VLLM_PID" >>"$LOG_DIR/cleanup.log" 2>&1 || true
    sleep 10
    kill -9 "$VLLM_PID" >>"$LOG_DIR/cleanup.log" 2>&1 || true
  fi
}
trap cleanup EXIT
CUDA_VISIBLE_DEVICES=0,1,2,3 "$PY" -m vllm.entrypoints.cli.main serve /local_nvme/guanyiming/models/Qwen/Qwen2.5-VL-7B-Instruct \
  --host 127.0.0.1 --port "$PORT" --served-model-name qwen2.5-vl-7b --dtype bfloat16 \
  --gpu-memory-utilization 0.60 --data-parallel-size 4 --max-model-len 8192 --max-num-seqs 32 \
  --limit-mm-per-prompt '{"image":1}' --disable-log-requests >"$LOG_DIR/vllm.log" 2>&1 &
VLLM_PID=$!
for i in $(seq 1 360); do
  if curl -fsS "http://127.0.0.1:${PORT}/v1/models" >/dev/null 2>&1; then
    break
  fi
  if ! kill -0 "$VLLM_PID" 2>/dev/null; then
    echo "vLLM exited early" | tee -a "$LOG_DIR/launcher.log"
    exit 1
  fi
  sleep 5
  if [[ "$i" == 360 ]]; then
    echo "vLLM not ready" | tee -a "$LOG_DIR/launcher.log"
    exit 1
  fi
done
"$PY" "$ROOT/bench/scripts/bench.py" run --config "$ROOT/bench/yaml/serial_qwen25_maze_1time_fast16.yaml" --run-dir "$RUN_DIR" 2>&1 | tee -a "$LOG_DIR/maze.log"

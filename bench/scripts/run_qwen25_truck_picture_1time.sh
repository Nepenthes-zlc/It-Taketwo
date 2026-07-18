#!/usr/bin/env bash
set -euo pipefail
ROOT=/local_nvme/zhanglechao/It-Taketwo
PY=/home/azvm/miniconda3/envs/verl/bin/python
STAMP=${1:-$(date -u +%Y%m%d_%H%M%S)}
PORT=3888
TRUCK_RUN="$ROOT/bench/runs/truck/20260717/1time/serial_qwen25_truck_agentA_random_center2of3_${STAMP}"
PICTURE_RUN="$ROOT/bench/runs/picture/20260717/1time/serial_qwen25_picture_agentA_random_center2of3_${STAMP}"
LOG_DIR="$ROOT/bench/runs/serial_suites/qwen25_truck_picture_1time_agentA_random_center2of3_${STAMP}"
SERVER_LOG="$LOG_DIR/server.log"
mkdir -p "$LOG_DIR"
cd "$ROOT"
echo "stamp=$STAMP" | tee -a "$LOG_DIR/launcher.log"
echo "truck_run=$TRUCK_RUN" | tee -a "$LOG_DIR/launcher.log"
echo "picture_run=$PICTURE_RUN" | tee -a "$LOG_DIR/launcher.log"
cleanup() {
  if [[ -n "${SERVER_PID:-}" ]]; then kill "$SERVER_PID" 2>/dev/null || true; wait "$SERVER_PID" 2>/dev/null || true; fi
}
trap cleanup EXIT
CUDA_VISIBLE_DEVICES=0,1,2,3 "$PY" -m vllm.entrypoints.cli.main serve /local_nvme/guanyiming/models/Qwen/Qwen2.5-VL-7B-Instruct \
  --host 127.0.0.1 --port "$PORT" --served-model-name qwen2.5-vl-7b --dtype bfloat16 \
  --gpu-memory-utilization 0.60 --data-parallel-size 4 --max-model-len 8192 --max-num-seqs 32 \
  --limit-mm-per-prompt '{"image":1}' --disable-log-requests > "$SERVER_LOG" 2>&1 &
SERVER_PID=$!
echo "server_pid=$SERVER_PID" | tee -a "$LOG_DIR/launcher.log"
"$PY" - <<'PY'
import time, urllib.request
url='http://127.0.0.1:3888/v1/models'
deadline=time.time()+1800
while True:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            if r.status < 400:
                print('api_ready')
                break
    except Exception as e:
        if time.time() > deadline:
            raise
        time.sleep(5)
PY
"$PY" bench/scripts/bench.py run --config bench/yaml/serial_qwen25_truck_1time_fast16.yaml --run-dir "$TRUCK_RUN" 2>&1 | tee -a "$LOG_DIR/truck.log"
"$PY" bench/scripts/bench.py run --config bench/yaml/serial_qwen25_picture_1time_fast16.yaml --run-dir "$PICTURE_RUN" 2>&1 | tee -a "$LOG_DIR/picture.log"
echo "done" | tee -a "$LOG_DIR/launcher.log"

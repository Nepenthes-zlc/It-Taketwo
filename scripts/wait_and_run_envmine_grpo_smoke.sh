#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"

GPU_ID=${GPU_ID:-auto}
MIN_FREE_MB=${MIN_FREE_MB:-40000}
CHECK_INTERVAL=${CHECK_INTERVAL:-60}
RUN_ONCE=${RUN_ONCE:-1}
LOG_DIR=${LOG_DIR:-$ROOT/runs/waited_smoke_$STAMP}
MODEL_PATH=${MODEL_PATH:-/mnt/data1/models/Qwen2-VL-2B-Instruct}
ROLLOUT_GPU_MEM_UTIL=${ROLLOUT_GPU_MEM_UTIL:-0.90}
VLLM_USE_V1=${VLLM_USE_V1:-1}

mkdir -p "$LOG_DIR"
WATCH_LOG="$LOG_DIR/watcher.log"
RUN_LOG="$LOG_DIR/run.log"
ENV_FILE="$LOG_DIR/env.sh"

log() {
  printf '[%s] %s\n' "$(date '+%F %T')" "$*" | tee -a "$WATCH_LOG"
}

save_env() {
  cat >"$ENV_FILE" <<EOF
export GPU_ID="$GPU_ID"
export MIN_FREE_MB="$MIN_FREE_MB"
export CHECK_INTERVAL="$CHECK_INTERVAL"
export MODEL_PATH="$MODEL_PATH"
export ROLLOUT_GPU_MEM_UTIL="$ROLLOUT_GPU_MEM_UTIL"
export VLLM_USE_V1="$VLLM_USE_V1"
export LOG_DIR="$LOG_DIR"
EOF
}

gpu_snapshot() {
  nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits \
    | awk -F, '{idx=$1+0; used=$2+0; total=$3+0; free=total-used; printf "gpu=%d used=%dMiB free=%dMiB total=%dMiB\n", idx, used, free, total}'
}

pick_gpu() {
  nvidia-smi --query-gpu=index,memory.used,memory.total --format=csv,noheader,nounits \
    | awk -F, -v want="$GPU_ID" -v min_free="$MIN_FREE_MB" '
        {
          idx=$1+0; used=$2+0; total=$3+0; free=total-used;
          if (want != "auto" && idx != want) next;
          if (free >= min_free && free > best_free) {
            best_free=free; best_idx=idx; best_used=used; best_total=total;
          }
        }
        END {
          if (best_idx == "") exit 1;
          printf "%d %d %d %d\n", best_idx, best_free, best_used, best_total;
        }'
}

run_smoke() {
  local selected_gpu="$1"
  log "starting smoke on GPU $selected_gpu"
  log "run log: $RUN_LOG"

  set +e
  (
    cd "$ROOT"
    export CUDA_VISIBLE_DEVICES="$selected_gpu"
    export VLLM_USE_V1
    export MODEL_PATH
    export ROLLOUT_GPU_MEM_UTIL
    ./scripts/run_envmine_grpo_smoke.sh
  ) > >(tee -a "$RUN_LOG") 2>&1
  local status=$?
  set -e

  log "smoke exited with status $status"
  return "$status"
}

save_env
log "watcher started"
log "log dir: $LOG_DIR"
log "GPU_ID=$GPU_ID MIN_FREE_MB=$MIN_FREE_MB CHECK_INTERVAL=$CHECK_INTERVAL RUN_ONCE=$RUN_ONCE"
log "MODEL_PATH=$MODEL_PATH ROLLOUT_GPU_MEM_UTIL=$ROLLOUT_GPU_MEM_UTIL VLLM_USE_V1=$VLLM_USE_V1"

while true; do
  gpu_snapshot | tee -a "$WATCH_LOG"
  if picked="$(pick_gpu)"; then
    read -r selected_gpu free_mb used_mb total_mb <<<"$picked"
    log "selected gpu=$selected_gpu free=${free_mb}MiB used=${used_mb}MiB total=${total_mb}MiB"
    if run_smoke "$selected_gpu"; then
      log "smoke succeeded"
      exit 0
    fi
    log "smoke failed"
    if [[ "$RUN_ONCE" == "1" ]]; then
      exit 1
    fi
  else
    log "no GPU has at least ${MIN_FREE_MB}MiB free; waiting ${CHECK_INTERVAL}s"
  fi
  sleep "$CHECK_INTERVAL"
done
#!/usr/bin/env bash
# Helper on A100-3: precise cleanup + stage launch. Called by the gateway watchdog.
# Usage:
#   bench_ctl.sh cleanup
#   bench_ctl.sh start <tmux_session> <yaml_filename>
#   bench_ctl.sh probe <tmux_session>     # prints RUNNING/IDLE + records line
set -u
BASE=/local_nvme/zhanglechao/It-Taketwo
PY=/home/azvm/miniconda3/envs/verl/bin/python
LOG=$BASE/bench/.watchdog.log
log(){ echo "[$(date -u '+%F %T')] ctl: $*" >> "$LOG" 2>/dev/null; }

cmd=${1:-}
case "$cmd" in
  cleanup)
    log "cleanup start"
    # bench controllers & workers
    pkill -9 -f "training_style_bench.py" 2>/dev/null
    pkill -9 -f "bench/scripts/bench.py run" 2>/dev/null
    pkill -9 -f "bench/scripts/bench.py status" 2>/dev/null
    # vLLM engine
    pkill -9 -f "vllm.entrypoints" 2>/dev/null
    pkill -9 -f "VLLM::" 2>/dev/null
    pkill -9 -f "EngineCore" 2>/dev/null
    pkill -9 -f "DPCoordinator" 2>/dev/null
    # minecraft game clients / render (bench-spawned) — precise, not blind java kill
    pkill -9 -f "instance-train" 2>/dev/null
    pkill -9 -f "minecraft" 2>/dev/null
    pkill -9 -f "Xvfb" 2>/dev/null
    pkill -9 -f "xvfb" 2>/dev/null
    # java game clients launched by bench (match by known bench/instance path fragments)
    for pid in $(pgrep -f "java"); do
      cmdline=$(tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null)
      case "$cmdline" in
        *It-Taketwo*|*instance*|*minecraft*|*malmo*|*Malmo*|*mcio*|*MCio*)
          kill -9 "$pid" 2>/dev/null; log "killed java pid=$pid" ;;
      esac
    done
    sleep 5
    # report leftover gpu procs
    left=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | wc -l)
    echo "cleanup-done gpu_compute_procs_left=$left"
    log "cleanup done, gpu_compute_left=$left"
    ;;
  start)
    sess=${2:?need session}; yaml=${3:?need yaml}
    log "start sess=$sess yaml=$yaml"
    if [ ! -f "$BASE/bench/yaml/$yaml" ]; then echo "yaml-missing"; exit 2; fi
    # Use bench.py native orchestrator: it creates the tmux session with a
    # dedicated server window (launches vLLM) + bench + status windows.
    # Must NOT pre-create the tmux session (bench.py start errors if it exists),
    # and PATH must include the verl env bin so vLLM cpp_extension can find ninja.
    tmux kill-session -t "$sess" 2>/dev/null
    ENVBIN=$(dirname "$PY")
    ( cd "$BASE" && PATH="$ENVBIN:$PATH" "$PY" bench/scripts/bench.py start --config "bench/yaml/$yaml" >> bench/.stage_${sess}.log 2>&1 )
    rc=$?
    sleep 4
    if [ "$rc" -eq 0 ] && tmux has-session -t "$sess" 2>/dev/null; then echo "started"; else echo "start-failed"; fi
    ;;
  probe)
    sess=${2:?need session}
    w=$(pgrep -fc "training_style_bench.py --worker" 2>/dev/null || echo 0)
    c=$(pgrep -fc "bench/scripts/bench.py run" 2>/dev/null || echo 0)
    rec=$(tmux capture-pane -t "$sess" -p 2>/dev/null | grep -oE "records=[0-9]+/[0-9]+" | tail -1)
    if [ "$w" -gt 0 ] || [ "$c" -gt 0 ]; then st=RUNNING; else st=IDLE; fi
    echo "$st workers=$w controller=$c ${rec:-records=?}"
    ;;
  *)
    echo "usage: bench_ctl.sh {cleanup|start <sess> <yaml>|probe <sess>}"; exit 1;;
esac

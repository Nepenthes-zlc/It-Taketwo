#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JAVA_HOME_DEFAULT="/home/zlc/Multiagent/jdk-21.0.11"
DEVICE="cpu"
GRADLE_TASK="runClient"

usage() {
  cat <<'EOF'
Usage: ./launch_tickgate.sh [--device cpu|<vgl-device>] [--task runClient]

MineStudio-style launcher:
  --device cpu         Run under xvfb-run -a.
  --device <device>    Run under vglrun -d <device>.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      DEVICE="${2:?missing value for --device}"
      shift 2
      ;;
    --task)
      GRADLE_TASK="${2:?missing value for --task}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

export JAVA_HOME="${JAVA_HOME:-$JAVA_HOME_DEFAULT}"
export PATH="$JAVA_HOME/bin:$PATH"

if [[ ! -x "$JAVA_HOME/bin/java" ]]; then
  echo "Java not found at $JAVA_HOME/bin/java" >&2
  exit 1
fi

cd "$ROOT"

if [[ "$DEVICE" == "cpu" ]]; then
  if ! command -v xvfb-run >/dev/null 2>&1; then
    echo "xvfb-run is required for --device cpu, matching MineStudio's headless path." >&2
    exit 1
  fi
  echo "[TickGate] launching with xvfb-run -a ($GRADLE_TASK)"
  exec xvfb-run -a bash ./gradlew --no-daemon "$GRADLE_TASK"
fi

if ! command -v vglrun >/dev/null 2>&1; then
  echo "vglrun is required for --device $DEVICE, matching MineStudio's GPU path." >&2
  exit 1
fi

echo "[TickGate] launching with vglrun -d $DEVICE ($GRADLE_TASK)"
exec vglrun -d "$DEVICE" bash ./gradlew --no-daemon "$GRADLE_TASK"

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JAVA_HOME_DEFAULT="/home/zlc/Multiagent/jdk-21.0.11"
DEVICE="cpu"

usage() {
  cat <<'EOF'
Usage: ./launch_tickgate.sh [--device cpu|<vgl-device>]

Runtime launcher for cloned TickGate Minecraft instances.
It does not run Gradle; it starts NeoForge/Minecraft directly from cached
classpath argfiles and uses ./run as the game directory.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --device)
      DEVICE="${2:?missing value for --device}"
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

LAUNCH_DIR="$ROOT/launch"
RUN_DIR="$ROOT/run"
LIBRARY_DIR="$ROOT/libraries"
ENVMINE_ROOT="$(cd "$ROOT/../.." && pwd)"
VM_ARGS_SRC="$LAUNCH_DIR/clientRunVmArgs.txt"
PROGRAM_ARGS="$LAUNCH_DIR/clientRunProgramArgs.txt"
LEGACY_CLASSPATH="$LAUNCH_DIR/clientLegacyClasspath.txt"
DEV_MINECRAFT_JAR="${DEV_MINECRAFT_JAR:-$ENVMINE_ROOT/runtime_jars/neoforge-21.1.230.jar}"
LOG4J_CONFIG="$LAUNCH_DIR/clientLog4j2.xml"

for required in "$VM_ARGS_SRC" "$PROGRAM_ARGS" "$LEGACY_CLASSPATH" "$LOG4J_CONFIG"; do
  if [[ ! -f "$required" ]]; then
    echo "Missing runtime launch file: $required" >&2
    exit 1
  fi
done
if [[ ! -f "$DEV_MINECRAFT_JAR" ]]; then
  echo "Missing development Minecraft/NeoForge jar: $DEV_MINECRAFT_JAR" >&2
  exit 1
fi

mkdir -p "$RUN_DIR/logs" "$RUN_DIR/mods" "$RUN_DIR/socketpuppet_data"
rm -f "$RUN_DIR/socketpuppet_data/port.txt"

VM_ARGS_TMP="$(mktemp)"
LEGACY_CLASSPATH_TMP="$(mktemp)"
trap 'rm -f "$VM_ARGS_TMP" "$LEGACY_CLASSPATH_TMP"' EXIT
cat "$LEGACY_CLASSPATH" > "$LEGACY_CLASSPATH_TMP"
printf '\n%s\n' "$DEV_MINECRAFT_JAR" >> "$LEGACY_CLASSPATH_TMP"
printf '%s\n%s\n' '-cp' "$DEV_MINECRAFT_JAR" > "$VM_ARGS_TMP"
sed \
  -e "s#^-Dlog4j2.configurationFile=.*#-Dlog4j2.configurationFile=$LOG4J_CONFIG#" \
  -e "s#^-DlegacyClassPath.file=.*#-DlegacyClassPath.file=$LEGACY_CLASSPATH_TMP#" \
  "$VM_ARGS_SRC" >> "$VM_ARGS_TMP"
printf '\n' >> "$VM_ARGS_TMP"
printf '%s\n' "-DlibraryDirectory=$LIBRARY_DIR" >> "$VM_ARGS_TMP"

run_java() {
  cd "$RUN_DIR"
  exec java @"$VM_ARGS_TMP" @"$PROGRAM_ARGS"
}

if [[ "$DEVICE" == "cpu" ]]; then
  if ! command -v xvfb-run >/dev/null 2>&1; then
    echo "xvfb-run is required for --device cpu." >&2
    exit 1
  fi
  echo "[TickGateRuntime] launching with xvfb-run -a"
  exec xvfb-run -a bash -c 'cd "$1" && exec java @"$2" @"$3"' _ "$RUN_DIR" "$VM_ARGS_TMP" "$PROGRAM_ARGS"
fi

if ! command -v vglrun >/dev/null 2>&1; then
  echo "vglrun is required for --device $DEVICE." >&2
  exit 1
fi

echo "[TickGateRuntime] launching with vglrun -d $DEVICE"
exec vglrun -d "$DEVICE" bash -c 'cd "$1" && exec java @"$2" @"$3"' _ "$RUN_DIR" "$VM_ARGS_TMP" "$PROGRAM_ARGS"
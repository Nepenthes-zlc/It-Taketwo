#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
JAVA_HOME_DEFAULT="/usr/lib/jvm/java-21-openjdk-amd64"
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
VM_ARGS_SRC="$LAUNCH_DIR/clientRunVmArgs.txt"
PROGRAM_ARGS="$LAUNCH_DIR/clientRunProgramArgs.txt"
LEGACY_CLASSPATH="$LAUNCH_DIR/clientLegacyClasspath.txt"
# NeoForge/Minecraft jar lives in the instance dir (a symlink to the template copy).
DEV_MINECRAFT_JAR="${DEV_MINECRAFT_JAR:-$ROOT/neoforge-21.1.230.jar}"
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
# Classpath entries are stored repo-relative (relative to this env dir) for
# portability. Expand each to an absolute path under $ROOT at launch time, since
# the JVM runs with cwd=$RUN_DIR and would not resolve env-relative paths.
# Lines already absolute (legacy format) are passed through unchanged.
while IFS= read -r cp_entry; do
  [[ -z "$cp_entry" ]] && continue
  if [[ "$cp_entry" == /* ]]; then
    printf '%s\n' "$cp_entry" >> "$LEGACY_CLASSPATH_TMP"
  else
    printf '%s\n' "$ROOT/$cp_entry" >> "$LEGACY_CLASSPATH_TMP"
  fi
done < "$LEGACY_CLASSPATH"

printf '%s\n%s\n' '-cp' "$DEV_MINECRAFT_JAR" > "$VM_ARGS_TMP"
# The VM args file carries a `-p <module-path>` line whose colon-separated jars
# point into a foreign Gradle cache. Rewrite each jar to its repo-local copy
# under $LIBRARY_DIR, matched by filename. Also redirect log4j/legacyClassPath.
sed \
  -e "s#^-Dlog4j2.configurationFile=.*#-Dlog4j2.configurationFile=$LOG4J_CONFIG#" \
  -e "s#^-DlegacyClassPath.file=.*#-DlegacyClassPath.file=$LEGACY_CLASSPATH_TMP#" \
  "$VM_ARGS_SRC" \
| awk -v libdir="$LIBRARY_DIR" '
    prev=="-p" {
      n=split($0, jars, ":"); out=""
      for (i=1;i<=n;i++) {
        m=split(jars[i], parts, "/"); fname=parts[m]
        cmd="find -L \"" libdir "\" -name \"" fname "\" -type f 2>/dev/null | head -1"
        cmd | getline local; close(cmd)
        out = out (i>1?":":"") (local!=""?local:jars[i])
        local=""
      }
      print out; prev=$0; next
    }
    { print; prev=$0 }
  ' >> "$VM_ARGS_TMP"
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

echo "[TickGateRuntime] launching with xvfb-run + vglrun -d $DEVICE (GPU render, EGL device pinned)"
# Xvfb provides the X display GLFW needs to create its window; vglrun -d egl<N> then
# redirects the actual 3D rendering to the Nth EGL device (= Nth physical GPU). This
# split is what spreads load across all cards: plain __NV_PRIME_RENDER_OFFLOAD ignores
# the device index and pins every instance to GPU 0.
exec xvfb-run -a bash -c 'cd "$1" && exec vglrun -d "$2" java @"$3" @"$4"' _ "$RUN_DIR" "$DEVICE" "$VM_ARGS_TMP" "$PROGRAM_ARGS"
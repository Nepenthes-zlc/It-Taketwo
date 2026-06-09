#!/usr/bin/env bash
# Create a lightweight Minecraft instance under env/<name> from the frozen
# template at assert/minecraft. Read-only bulk (libraries, neoforge jar, assets)
# is shared via symlinks; only the small per-instance writable parts (run/, the
# launch argfiles, the launcher) are really copied.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$ROOT/assert/minecraft"
ENV_ROOT="$ROOT/env"

usage() {
  cat <<'EOF'
Usage: make_env_instance.sh <name> [--tickgate-port N] [--force]

Creates env/<name> from the assert/minecraft template.
  --tickgate-port N   Set TickGate ipcPort in the instance (default: keep template's 25590).
  --force             Overwrite env/<name> if it already exists.
EOF
}

NAME=""
TICKGATE_PORT=""
FORCE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tickgate-port) TICKGATE_PORT="${2:?missing port}"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    -*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
    *) if [[ -z "$NAME" ]]; then NAME="$1"; shift; else echo "Unexpected arg: $1" >&2; exit 2; fi ;;
  esac
done

if [[ -z "$NAME" ]]; then usage >&2; exit 2; fi
if [[ ! -d "$TEMPLATE" ]]; then echo "Template not found: $TEMPLATE" >&2; exit 1; fi
if [[ ! -d "$TEMPLATE/libraries" || ! -f "$TEMPLATE/neoforge-21.1.230.jar" ]]; then
  echo "Template is incomplete (missing libraries/ or neoforge jar): $TEMPLATE" >&2; exit 1
fi

DST="$ENV_ROOT/$NAME"
if [[ -e "$DST" ]]; then
  if [[ "$FORCE" == "1" ]]; then rm -rf "$DST"; else echo "Already exists: $DST (use --force)" >&2; exit 1; fi
fi

mkdir -p "$DST"

# Shared read-only bulk -> symlinks (relative, so the tree stays movable together).
ln -s "../../assert/minecraft/libraries" "$DST/libraries"
ln -s "../../assert/minecraft/neoforge-21.1.230.jar" "$DST/neoforge-21.1.230.jar"
# Assets is an absolute external path in the template; mirror that.
ASSETS_TARGET="$(readlink "$TEMPLATE/assets" 2>/dev/null || echo /local_nvme/neoformruntime_assets)"
ln -s "$ASSETS_TARGET" "$DST/assets"

# Per-instance writable parts -> real copies (small).
cp -a "$TEMPLATE/launch" "$DST/launch"
cp -a "$TEMPLATE/launch_tickgate.sh" "$DST/launch_tickgate.sh"
cp -a "$TEMPLATE/run" "$DST/run"
[[ -f "$TEMPLATE/README.md" ]] && cp -a "$TEMPLATE/README.md" "$DST/README.md"

# Fresh-instance hygiene: drop any stray runtime artifacts the template shouldn't carry.
rm -rf "$DST/run/logs" "$DST/run/crash-reports" "$DST/run/socketpuppet_data/port.txt" "$DST/run/downloads"
mkdir -p "$DST/run/logs" "$DST/run/mods" "$DST/run/socketpuppet_data"

# Optional per-instance TickGate port.
if [[ -n "$TICKGATE_PORT" ]]; then
  TOML="$DST/run/config/tickgate-common.toml"
  if [[ -f "$TOML" ]]; then
    sed -i -E "s/^ipcPort = .*/ipcPort = $TICKGATE_PORT/" "$TOML"
    echo "[make_env_instance] set ipcPort=$TICKGATE_PORT in $TOML"
  else
    echo "[make_env_instance] WARN: $TOML not found; could not set tickgate port" >&2
  fi
fi

echo "[make_env_instance] created $DST"
echo "  libraries -> $(readlink "$DST/libraries")"
echo "  neoforge  -> $(readlink "$DST/neoforge-21.1.230.jar")"
echo "  assets    -> $(readlink "$DST/assets")"
du -sh --exclude=libraries --exclude=assets --exclude=neoforge-21.1.230.jar "$DST" | sed 's/^/  copied size: /'

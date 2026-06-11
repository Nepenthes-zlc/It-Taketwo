#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SOURCE_INSTANCE=${SOURCE_INSTANCE:-instance-test-01}
TRAIN_INSTANCE_PREFIX=${TRAIN_INSTANCE_PREFIX:-instance-train}
TRAIN_INSTANCE_COUNT=${TRAIN_INSTANCE_COUNT:-4}
TRAIN_TICKGATE_BASE_PORT=${TRAIN_TICKGATE_BASE_PORT:-25690}

SOURCE_DIR="${ROOT_DIR}/env/${SOURCE_INSTANCE}"
if [ ! -x "${SOURCE_DIR}/launch_tickgate.sh" ]; then
  echo "source instance is not prepared: ${SOURCE_DIR}" >&2
  exit 1
fi

for i in $(seq 1 "${TRAIN_INSTANCE_COUNT}"); do
  name=$(printf "%s-%02d" "${TRAIN_INSTANCE_PREFIX}" "${i}")
  dst="${ROOT_DIR}/env/${name}"
  port=$((TRAIN_TICKGATE_BASE_PORT + i - 1))

  if [ ! -e "${dst}/launch_tickgate.sh" ]; then
    mkdir -p "$(dirname "${dst}")"
    cp -a "${SOURCE_DIR}" "${dst}"
  fi

  rm -f "${dst}/run/saves/New World/session.lock"
  rm -f "${dst}/run/socketpuppet_data/port.txt"
  rm -f "${dst}/run/socketpuppet_data/recording.csv"

  python3 - "${dst}/run/config/tickgate-common.toml" "${port}" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
port = sys.argv[2]
text = path.read_text(encoding="utf-8")
lines = []
updated = False
for line in text.splitlines():
    if line.strip().startswith("ipcPort"):
        lines.append(f"ipcPort = {port}")
        updated = True
    else:
        lines.append(line)
if not updated:
    lines.append(f"ipcPort = {port}")
path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

  echo "prepared ${name}: root=${dst} tickgate_port=${port}"
done

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERL_DIR="$ROOT/verl"
VERL_REPO="${VERL_REPO:-https://github.com/verl-project/verl.git}"
RETRIES="${RETRIES:-5}"

git_retry() {
  local attempt=1
  while true; do
    echo "[bootstrap_verl] attempt $attempt/$RETRIES: git $*"
    if git \
      -c http.version=HTTP/1.1 \
      -c http.postBuffer=524288000 \
      -c core.compression=0 \
      "$@"; then
      return 0
    fi
    if [[ "$attempt" -ge "$RETRIES" ]]; then
      return 1
    fi
    sleep $((attempt * 5))
    attempt=$((attempt + 1))
  done
}

if [[ -d "$VERL_DIR/.git" ]]; then
  echo "[bootstrap_verl] found existing git repo: $VERL_DIR"
  git -C "$VERL_DIR" remote set-url origin "$VERL_REPO"
  git_retry -C "$VERL_DIR" fetch --depth 1 --filter=blob:none origin main
  git -C "$VERL_DIR" checkout -B main FETCH_HEAD
else
  if [[ -e "$VERL_DIR" ]]; then
    echo "[bootstrap_verl] $VERL_DIR exists but is not a git repo" >&2
    exit 1
  fi
  git_retry clone --depth 1 --filter=blob:none --single-branch --branch main "$VERL_REPO" "$VERL_DIR"
fi

echo "[bootstrap_verl] ready: $VERL_DIR"

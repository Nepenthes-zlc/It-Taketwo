#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${1:-$ROOT/dist/envmine_verl_training_bundle_$STAMP.tar.gz}"
INCLUDE_RUNTIME="${INCLUDE_RUNTIME:-0}"

mkdir -p "$(dirname "$OUT")"
MANIFEST="$(mktemp)"
trap 'rm -f "$MANIFEST"' EXIT

(
  cd "$ROOT"
  git ls-files -co --exclude-standard
  if [[ "$INCLUDE_RUNTIME" == "1" ]]; then
    if [[ -d verl ]]; then
      find verl \
        \( -path 'verl/.git/*' -o -path '*/__pycache__/*' -o -path '*/.pytest_cache/*' \) -prune \
        -o -type f -print
    fi
  fi
) | sed '/^$/d' | sort -u > "$MANIFEST"

tar -czf "$OUT" -C "$ROOT" -T "$MANIFEST"

echo "$OUT"
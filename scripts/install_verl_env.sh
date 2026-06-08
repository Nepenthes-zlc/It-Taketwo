#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_PREFIX="${ENV_PREFIX:-/home/zlc/.conda/envs/envmine-verl}"
BASE_ENV="${BASE_ENV:-/home/zlc/.conda/envs/multiagent}"

if [[ ! -x "$BASE_ENV/bin/python" ]]; then
  echo "Base env not found: $BASE_ENV" >&2
  exit 1
fi

if [[ ! -x "$ENV_PREFIX/bin/python" ]]; then
  echo "[install_verl_env] cloning conda env: $BASE_ENV -> $ENV_PREFIX"
  conda create -y --prefix "$ENV_PREFIX" --clone "$BASE_ENV"
fi

PY="$ENV_PREFIX/bin/python"
PIP="$PY -m pip"

echo "[install_verl_env] installing It-Taketwo adapter editable"
$PIP install -e "$ROOT"

echo "[install_verl_env] installing verl core dependencies"
$PIP install \
  "numpy<2.0.0" \
  accelerate \
  codetiming \
  datasets \
  hydra-core \
  pandas \
  peft \
  "pyarrow>=19.0.0" \
  pybind11 \
  pylatexenc \
  "tensordict>=0.8.0,<=0.10.0,!=0.9.0" \
  torchdata \
  wandb \
  tensorboard \
  packaging \
  latex2sympy2_extended \
  math_verify \
  TransferQueue==0.1.7

echo "[install_verl_env] installing verl editable without dependency resolver churn"
$PIP install --no-deps -e "$ROOT/verl"

echo "[install_verl_env] checking environment"
$PY "$ROOT/scripts/check_verl_env.py"

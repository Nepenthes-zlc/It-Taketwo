#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-/home/azvm/miniconda3/envs/verl/bin/python}
VERL_HOME=${VERL_HOME:-/local_nvme/zhanglechao/verl}
SMOKE_DATA_DIR=${SMOKE_DATA_DIR:-/tmp/it_taketwo_verl_minecraft_data}

export PYTHONPATH="${ROOT_DIR}:${VERL_HOME}:${PYTHONPATH:-}"

"${PYTHON_BIN}" -m py_compile \
  "${ROOT_DIR}/verl_adapter/mc_env.py" \
  "${ROOT_DIR}/verl_adapter/minecraft_agent_loop.py" \
  "${ROOT_DIR}/verl_adapter/build_dataset.py"

"${PYTHON_BIN}" "${ROOT_DIR}/verl_adapter/build_dataset.py" \
  --output-dir "${SMOKE_DATA_DIR}" \
  --train-size 1 \
  --val-size 1

"${PYTHON_BIN}" - <<'PYSMOKE'
from pathlib import Path

from verl_adapter.mc_env import MinecraftEnvConfig, MinecraftRolloutEnv, parse_joint_action
from verl_adapter.minecraft_agent_loop import MinecraftAgentLoop

assert MinecraftAgentLoop.__name__ == "MinecraftAgentLoop"
actions, reason = parse_joint_action('{"agent_a":"wait","agent_b":"forward","reason":"smoke"}')
assert actions == {"agent_a": "wait", "agent_b": "forward"}
assert reason == "smoke"

env = MinecraftRolloutEnv(MinecraftEnvConfig(rollout_yaml=Path("yaml/lowlevel_episode.yaml"), max_steps=4, mock=True))
try:
    obs = env.start()
    assert not obs["done"]
    for _ in range(4):
        obs = env.step({"agent_a": "wait", "agent_b": "forward"})
    assert obs["done"], obs
    assert env.reward() == 1.0
finally:
    env.close()

print("verl adapter smoke check passed")
PYSMOKE

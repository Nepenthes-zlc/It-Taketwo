# EnvMine online GRPO with verl

This path uses a custom verl `AgentLoop` to run Minecraft online during rollout.

## Smoke checks

```bash
cd /home/zlc/Multiagent/EnvMineVerl
/home/zlc/.conda/envs/envmine-verl/bin/python scripts/check_verl_env.py
bash scripts/run_envmine_grpo.sh --cfg job
```

`--cfg job` only validates the Hydra configuration. It does not start training or Minecraft.

When GPU memory is already occupied, use the smaller smoke profile first:

```bash
cd /home/zlc/Multiagent/EnvMineVerl
bash scripts/run_envmine_grpo_smoke.sh --cfg job
```

For a real minimal online run, make sure `MODEL_PATH` points to an available small vision-language model, then run:

```bash
MODEL_PATH=/path/to/Qwen2.5-VL-3B-Instruct bash scripts/run_envmine_grpo_smoke.sh
```

The smoke profile uses one GPU, batch size 1, rollout `n=1`, one AgentLoop worker, shorter token limits, vLLM GPU memory utilization `0.30`, and `configs/envmine_agent_loop_smoke.yaml` with `max_steps=2`.

To leave the smoke run waiting in tmux until a GPU has enough free memory:

```bash
cd /home/zlc/Multiagent/EnvMineVerl
GPU_ID=auto MIN_FREE_MB=40000 CHECK_INTERVAL=60 ./scripts/wait_and_run_envmine_grpo_smoke.sh
```

The watcher writes `watcher.log`, `run.log`, and `env.sh` under `runs/waited_smoke_<timestamp>/`. Set `GPU_ID=5` to wait for one specific GPU, or `RUN_ONCE=0` to keep retrying after failures.

## Start training

```bash
cd /home/zlc/Multiagent/EnvMineVerl
bash scripts/run_envmine_grpo.sh
```

Useful overrides:

```bash
TASK_INDICES=0,1 EPISODES_PER_TASK=2 ROLLOUT_N=2 AGENT_LOOP_WORKERS=2 bash scripts/run_envmine_grpo.sh
DATA_FORMAT=parquet bash scripts/run_envmine_grpo.sh
MODEL_PATH=/path/to/Qwen2.5-VL-7B-Instruct bash scripts/run_envmine_grpo.sh
```

The default data format is JSONL because verl can read it and it avoids relying on `pyarrow` in the base shell.
The `/home/zlc/.conda/envs/envmine-verl` environment has `pyarrow`, so `DATA_FORMAT=parquet` also works there.

## How it works

`configs/envmine_agent_loop.yaml` registers `envmine_lowlevel`, implemented by
`adapter/envmine_verl/agent_loop.py`.

Each rollout:

1. acquires one lock from `runs/locks/*.lock`;
2. starts one EnvMine Minecraft instance from `EnvMine/configs/qwen_batch_lowlevel.json`;
3. captures AgentA/AgentB first-person screenshots;
4. asks the policy for compact JSON low-level actions;
5. executes actions through Puppet/TickGate;
6. returns the environment success reward directly to verl.

Scale `TRAIN_BATCH_SIZE`, `ROLLOUT_N`, `AGENT_LOOP_WORKERS`, and the number of EnvMine instances together. If rollout concurrency is higher than available instances, workers wait on the lock files.

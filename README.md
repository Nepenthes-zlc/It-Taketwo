# EnvMineVerl

EnvMineVerl is the training bundle for online EnvMine Minecraft rollouts with verl GRPO. It keeps the training adapter, scene construction code, generated datapack/tasks, and the Minecraft runtime template needed to create batch workers in one repository. Model weights, `verl`, logs, and generated rollout outputs stay outside normal git tracking.

## What is included

```text
EnvMineVerl/
  adapter/envmine_verl/        # verl AgentLoop and EnvMine rollout adapter
  configs/                     # AgentLoop configs, using repository-relative paths
  ConstructScene/              # scene builder code, scene specs, generated datapack/tasks
  data/envmine_lowlevel/       # small JSONL prompt data for train/test smoke runs
  mc_runtime/EnvMine/          # local MC/TickGate/Puppet runtime template and EnvMine runner code
  scripts/                     # setup, data prep, rollout, GRPO, and packaging commands
  pyproject.toml               # editable adapter package
  ONLINE_GRPO.md               # shorter online GRPO notes
```

Runtime outputs are intentionally not committed by default:

- `verl` is the upstream verl checkout.
- `mc_runtime/EnvMine/envs/qwen-batch-*` are generated worker copies.
- `runs/`, `outputs/`, `logs/`, `test_results/`, and runtime logs are generated outputs.

## Quick start

```bash
cd /home/zlc/Multiagent/EnvMineVerl

# 1. Fetch or repair the upstream verl checkout when network is available.
./scripts/bootstrap_verl.sh

# 2. Install the adapter and verl dependencies into the local training env.
./scripts/install_verl_env.sh

# 3. Create local Minecraft batch worker directories from the committed template.
python3 mc_runtime/EnvMine/prepare_qwen_batch_envs.py --count 2 --base-port 25590 --parallel 2 --force

# 4. Check Python imports and local paths.
/home/zlc/.conda/envs/envmine-verl/bin/python scripts/check_verl_env.py
```

The committed Minecraft runtime template is:

```text
mc_runtime/EnvMine/envs/qwen-runtime-task12-purevision
```

`prepare_qwen_batch_envs.py` copies that template into runtime workers such as:

```text
mc_runtime/EnvMine/envs/qwen-batch-1
mc_runtime/EnvMine/envs/qwen-batch-2
```

and writes `mc_runtime/EnvMine/configs/qwen_batch_lowlevel.json`, which is what the training adapter reads.

## Scene construction

The scene builder is in `ConstructScene/`. It can regenerate the Minecraft datapack and task JSON used by training:

```bash
cd /home/zlc/Multiagent/EnvMineVerl/ConstructScene
python3 generate_scenes.py --spec scene_specs/elevator_time_dependency_batch.json --out generated --namespace multiagent_scene
python3 generate_tasks.py --task-category elevator --num-tasks 20 --manifest generated/scene_manifest.json --out generated/generated_tasks.json
```

The training adapter reads these repository-local files by default:

- `ConstructScene/generated/generated_tasks.json`
- `ConstructScene/generated/datapacks/multiagent_scene_pack`

Deploy the generated datapack to Minecraft env slots when the runtime worlds need refreshing:

```bash
python3 ConstructScene/deploy_datapack_to_envs.py \
  --src-pack ConstructScene/generated/datapacks/multiagent_scene_pack \
  --env-root /path/to/env/root \
  --count 4 \
  --overwrite
```

## Prepare training data

Generate verl prompt rows from the repository-local scene tasks:

```bash
python3 scripts/prepare_envmine_verl_data.py \
  --task-indices 0 \
  --episodes-per-task 1 \
  --output-dir data/envmine_lowlevel \
  --format jsonl
```

The default training launcher will create missing `train.jsonl` and `test.jsonl` automatically from `ConstructScene/generated/generated_tasks.json`.

## Smoke rollout

Dry-run the EnvMine batch wrapper without starting Minecraft:

```bash
python3 scripts/run_envmine_rollout.py --dry-run --policy fixed --episodes-per-task 2 --parallel 2
```

Run a short fixed-policy Minecraft smoke:

```bash
python3 scripts/run_envmine_rollout.py --policy fixed --max-steps 2 --parallel 2
```

Run through the Qwen-compatible endpoint:

```bash
python3 scripts/run_envmine_rollout.py --policy qwen --task-indices 0 --episodes-per-task 1 --max-steps 20 --parallel 2
```

## Online GRPO training

Validate the Hydra job config without launching training:

```bash
bash scripts/run_envmine_grpo_smoke.sh --cfg job
```

Start the small online smoke profile:

```bash
MODEL_PATH=/path/to/Qwen2.5-VL-3B-Instruct bash scripts/run_envmine_grpo_smoke.sh
```

Start the normal profile:

```bash
MODEL_PATH=/path/to/Qwen2.5-VL-7B-Instruct bash scripts/run_envmine_grpo.sh
```

Useful overrides:

```bash
TASK_INDICES=0,1 EPISODES_PER_TASK=2 ROLLOUT_N=2 AGENT_LOOP_WORKERS=2 bash scripts/run_envmine_grpo.sh
DATA_FORMAT=parquet bash scripts/run_envmine_grpo.sh
LOGGER='["console","wandb"]' bash scripts/run_envmine_grpo.sh
```

The AgentLoop is registered as `envmine_lowlevel` in `configs/envmine_agent_loop.yaml`. It reads `mc_runtime/EnvMine/configs/qwen_batch_lowlevel.json`. Each rollout acquires one local EnvMine instance lock, refreshes or uses the scene datapack, captures first-person screenshots for AgentA and AgentB, asks the policy for JSON low-level actions, executes them through Puppet/TickGate, and returns the online reward to verl.

To create more workers for larger rollout parallelism:

```bash
python3 mc_runtime/EnvMine/prepare_qwen_batch_envs.py \
  --count 8 \
  --base-port 25590 \
  --parallel 8 \
  --force
```

## Packaging

Create a source training bundle from git-visible files:

```bash
./scripts/package_training_bundle.sh
```

The archive path is printed, usually under `dist/`. This default package contains the adapter, configs, scripts, scene builder, generated datapack/tasks, small data files, and the committed `mc_runtime/EnvMine` runtime template. It does not include generated `qwen-batch-*` workers, `verl`, model weights, or outputs.

For a heavier offline archive that also includes `verl` when present:

```bash
INCLUDE_RUNTIME=1 ./scripts/package_training_bundle.sh /tmp/envmine_verl_full_runtime.tar.gz
```

## Git hygiene

Track these parts:

```bash
git add .gitignore README.md ONLINE_GRPO.md pyproject.toml adapter configs scripts data ConstructScene
git status --short
```

Ignored by design: legacy external `EnvMine` symlinks, `verl`, generated `mc_runtime/EnvMine/envs/qwen-batch-*` workers, `runs`, `outputs`, `logs`, `test_results`, caches, and package metadata. This keeps commits focused on reproducible training code, scene assets, and the reusable MC runtime template while avoiding generated outputs.

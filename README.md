# EnvMineVerl

EnvMineVerl is the training bundle for online EnvMine Minecraft rollouts with verl GRPO. It keeps the small, reviewable training adapter in git, vendors the scene construction code and generated datapack/tasks needed by training, and leaves heavyweight runtimes (`EnvMine`, `verl`, model weights, logs) outside normal git tracking.

## What is included

```text
EnvMineVerl/
  adapter/envmine_verl/        # verl AgentLoop and EnvMine rollout adapter
  configs/                     # AgentLoop configs, using repository-relative paths
  ConstructScene/              # scene builder code, scene specs, generated datapack/tasks
  data/envmine_lowlevel/       # small JSONL prompt data for train/test smoke runs
  scripts/                     # setup, data prep, rollout, GRPO, and packaging commands
  pyproject.toml               # editable adapter package
  ONLINE_GRPO.md               # shorter online GRPO notes
```

Runtime directories are intentionally not committed by default:

- `EnvMine` is a symlink or checkout containing Minecraft/TickGate/Puppet instances.
- `verl` is the upstream verl checkout.
- `runs/`, `outputs/`, `logs/`, and `test_results/` are generated outputs.

## Quick start

```bash
cd /home/zlc/Multiagent/EnvMineVerl

# 1. Make sure EnvMine runtime is available. On this machine it is a symlink:
ln -sfn ../EnvMine EnvMine

# 2. Fetch or repair the upstream verl checkout when network is available.
./scripts/bootstrap_verl.sh

# 3. Install the adapter and verl dependencies into the local training env.
./scripts/install_verl_env.sh

# 4. Check Python imports.
/home/zlc/.conda/envs/envmine-verl/bin/python scripts/check_verl_env.py
```

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

The AgentLoop is registered as `envmine_lowlevel` in `configs/envmine_agent_loop.yaml`. Each rollout acquires one EnvMine instance lock, refreshes or uses the scene datapack, captures first-person screenshots for AgentA and AgentB, asks the policy for JSON low-level actions, executes them through Puppet/TickGate, and returns the online reward to verl.

## Packaging

Create a source training bundle from git-visible files:

```bash
./scripts/package_training_bundle.sh
```

The archive path is printed, usually under `dist/`. This default package contains the adapter, configs, scripts, scene builder, generated datapack/tasks, and small data files. It does not include large runtimes or outputs.

For a heavier offline archive that also dereferences the local `EnvMine` runtime symlink and includes `verl` when present:

```bash
INCLUDE_RUNTIME=1 ./scripts/package_training_bundle.sh /tmp/envmine_verl_full_runtime.tar.gz
```

## Git hygiene

Track these parts:

```bash
git add .gitignore README.md ONLINE_GRPO.md pyproject.toml adapter configs scripts data ConstructScene
git status --short
```

Ignored by design: `EnvMine`, `verl`, `runs`, `outputs`, `logs`, `test_results`, caches, and package metadata. This keeps commits focused on reproducible training code and scene assets while avoiding large generated outputs.

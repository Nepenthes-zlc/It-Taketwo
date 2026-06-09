# Script Entrypoints

Recommended flow: use one generic script and switch behavior by choosing a YAML file under `yaml/`.

## Generic Scripts

- `run_test.sh`: run the rollout described by a YAML file.
- `check_test_yaml.sh`: validate a YAML file and print the resolved command without running it.
- `list_test_configs.sh`: list available `yaml/*.yaml` configs and their `entry` values.
- `list_test_entries.sh`: list supported entry names.
- `run_from_yaml.py`: shared implementation used by the shell scripts.

## YAML-driven Usage

```bash
./scripts/list_test_configs.sh
./scripts/check_test_yaml.sh yaml/three_views.yaml
./scripts/run_test.sh yaml/three_views.yaml
./scripts/run_test.sh yaml/lowlevel_batch.yaml
./scripts/check_test_yaml.sh yaml/lowlevel_ai_qwen.yaml
./scripts/check_test_yaml.sh yaml/lowlevel_ai_closed_api.yaml
```

Append extra CLI args after `--`:

```bash
./scripts/run_test.sh yaml/lowlevel_episode.yaml -- --help
./scripts/run_test.sh yaml/lowlevel_batch.yaml --print-command
```

## YAML Schema

```yaml
entry: lowlevel_batch
python: /home/azvm/miniconda3/envs/verl/bin/python
runner:
  print_command: false
env:
  JAVA_HOME: /usr
args:
  dry_run: true
  config: yaml/instances_batch.yaml
  task_indices: "0"
  episodes_per_task: 1
```

Supported `entry` values:

- `three_views`: capture AgentA, AgentB, and observer screenshots.
- `lowlevel_episode`: run one low-level action rollout episode.
- `lowlevel_batch`: run batched/parallel low-level rollout episodes.

Runtime instance configs live in `yaml/instance_single.yaml` and `yaml/instances_batch.yaml`.

## Compatibility Shortcuts

These still work, but they are just shortcuts around the generic YAML runner:

- `run_three_views.sh` -> `yaml/three_views.yaml`
- `run_lowlevel_episode.sh` -> `yaml/lowlevel_episode.yaml`
- `run_lowlevel_batch.sh` -> `yaml/lowlevel_batch.yaml`
- `run_from_yaml.sh` -> generic legacy name for `run_test.sh`

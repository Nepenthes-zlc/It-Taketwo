# It-Taketwo Bench

`training_style_bench.py` is the core evaluator. New experiments should be defined
as YAML files under `bench/yaml/` and launched through `bench/scripts/bench.py`.
Do not add model- or date-specific shell scripts to the `bench` root.

## Layout

- `training_style_bench.py`: core episode runner and worker process
- `scripts/bench.py`: validate, run, start, monitor, and stop evaluations
- `scripts/top_up_valid_episodes.py`: refill invalid or missing episodes
- `scripts/top_up_discarded_episodes.py`: remove and rerun discarded episodes
- `scripts/render_duo_communication_videos.py`: render communication videos
- `yaml/`: reusable evaluation configurations
- `tests/`: bench unit tests
- `data/`: task files and datapacks
- `runs/`: evaluation outputs

## Start In Tmux

```bash
cd /local_nvme/zhanglechao/It-Taketwo
python bench/scripts/bench.py validate \
  --config bench/yaml/elevator_qwen25vl7b.yaml
python bench/scripts/bench.py start \
  --config bench/yaml/elevator_qwen25vl7b.yaml
```

The launcher starts a local vLLM server when `server.enabled: true`, waits for its
OpenAI-compatible API, runs every configured phase, and opens a status window.

## Status And Stop

```bash
python bench/scripts/bench.py status \
  --run-dir "$(cat bench/runs/latest_elevator_qwen25vl7b.txt)"
python bench/scripts/bench.py stop \
  --config bench/yaml/elevator_qwen25vl7b.yaml
```

`stop` terminates the configured tmux session and closes persistent bench
Minecraft instances.

## New Tests

Copy one of these files and change only YAML values:

- `yaml/template_local_vllm.yaml`: launch a local model server
- `yaml/template_external_api.yaml`: use an existing OpenAI-compatible API

Important fields:

- `model`: served model name, provider, API URL, and credentials
- `server`: local model path, GPU visibility, port, and vLLM arguments
- `runner`: task data, datapack, repeats, workers, instances, and timeouts
- `phases`: optional named task-index groups run sequentially
- `env`: optional environment variables such as EGL device assignment

The model request uses only the current agent's first-person image. Prompt text is
provided by `mc_rollout/prompts.py`; poses are not included in the model prompt.

## Tests

```bash
/home/azvm/miniconda3/envs/verl/bin/python -m pytest -q bench/tests
```

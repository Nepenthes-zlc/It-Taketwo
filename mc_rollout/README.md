# Rollout Test Code

`mc_rollout/` is organized as one rollout system. The shell scripts under `scripts/` load a YAML file from `yaml/`, then call `mc_rollout/launch.py --entry ...`.

## Files

- `launch.py`: startup layer. It parses CLI args, reads instance YAML/JSON configs, starts Minecraft, connects TickGate/Puppet, captures raw images, and dispatches to the rollout flow.
- `action_space.py`: action space. It defines the allowed low-level actions and maps them to Puppet commands. Policy actions currently are `wait`, `forward`, `turn_left`, `turn_right`, `look_up`, and `look_down`; `backward`, `strafe_left`, and `strafe_right` are kept commented out, and `jump` remains excluded from `ALLOWED_ACTIONS`.
- `agent_driver.py`: AgentA/AgentB driver layer. It supports `fixed`, `random`, local Qwen-style OpenAI-compatible APIs, and closed API models configured per agent.
- `closed_model.py`: closed-source GPT/CloudGPT caller. It mirrors the `wm_eval` GPT style: `get_openai_client()` for CloudGPT when no key/base_url is supplied, direct `OpenAI(api_key, base_url)` when those values are supplied, GPT-5.5 temperature compatibility, and retry handling.
- `prompts.py`: prompt templates and JSON response parsing for AI-driven agent actions.
- `game_functions.py`: Minecraft helper functions. It contains commands such as datapack sync, `/tp`, command execution, pose query, screenshot capture, camera placement, PNG validation, and video writing.
- `rollout.py`: flow definition. It defines the three supported flows: `three_views`, `lowlevel_episode`, and `lowlevel_batch`.
- `completion.py`: task completion checks. It checks pressure plate state, door state, and whether AgentB entered the second room.
- `__init__.py`: Python package marker.
- `README.md`: this document.

## Flow

```text
YAML config
  -> scripts/run_test.sh
  -> mc_rollout/launch.py
  -> mc_rollout/rollout.py
  -> mc_rollout/agent_driver.py
  -> mc_rollout/closed_model.py only when provider is closed_api/cloudgpt/gpt/gpt55
  -> mc_rollout/game_functions.py + mc_rollout/completion.py
  -> outputs under runs/
```

## Supported Entries

- `three_views`: setup a task scene and capture AgentA POV, AgentB POV, and observer screenshots.
- `lowlevel_episode`: run one action-space rollout episode with `fixed`, `random`, `ai`, or legacy `qwen` policy.
- `lowlevel_batch`: assign many episodes to one or more Minecraft instances and run them in parallel.

## AI Agent Drivers

Agent models are configured from YAML. AgentA and AgentB can use different models or endpoints.

Local Qwen/OpenAI-compatible example:

```yaml
args:
  policy: ai
  agent_a_provider: openai_compatible
  agent_a_model: qwen2.5-vl-7b
  agent_a_api_base_url: http://127.0.0.1:3888/v1/
  agent_a_api_key: EMPTY
```

Closed GPT/CloudGPT example:

```yaml
args:
  policy: ai
  agent_a_provider: closed_api
  agent_a_model: gpt-5.5-20260424
  agent_a_api_base_url:
  agent_a_api_key:
  agent_a_api_key_env:
```

If `agent_*_api_base_url` or `agent_*_api_key_env` is set, `closed_model.py` uses a direct OpenAI-compatible client. If both are empty, it imports `cloudgpt_aoai.get_openai_client()` from `wm_eval` style CloudGPT auth. Override that path with `WM_EVAL_CLOUDGPT_DIR` if needed.

Examples live in `yaml/lowlevel_ai_qwen.yaml` and `yaml/lowlevel_ai_closed_api.yaml`.

## Recommended Commands

```bash
cd /local_nvme/zhanglechao/It-Taketwo
./scripts/list_test_configs.sh
./scripts/check_test_yaml.sh yaml/three_views.yaml
./scripts/check_test_yaml.sh yaml/lowlevel_ai_closed_api.yaml
./scripts/run_test.sh yaml/three_views.yaml
./scripts/run_test.sh yaml/lowlevel_batch.yaml
```

Runtime configs live in `yaml/instance_single.yaml` and `yaml/instances_batch.yaml`.

## Training-Oriented Rollout Details

- Randomized starts can now sample an initial downward camera pitch via `start_pitch_min` and `start_pitch_max`; `yaml/lowlevel_train_episode.yaml` enables this curriculum with a 20-40 degree range.
- `lowlevel_episode` and VERL training configs should assume the reduced policy action set: `wait`, `forward`, `turn_left`, `turn_right`, `look_up`, and `look_down`.
- Prompt action descriptions are kept in sync with that reduced action set so models are not encouraged to choose disabled lateral/backward moves.

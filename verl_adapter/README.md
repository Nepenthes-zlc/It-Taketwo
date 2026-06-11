# VERL integration

This package connects the `mc_rollout` Minecraft runtime to VERL's async `AgentLoop` interface.

Current scope:

- Text-observation online RL loop for AgentA/AgentB low-level actions.
- Rule reward from Minecraft completion markers: success = 1.0, otherwise 0.0.
- `scripts/check_verl_adapter.sh` for fast adapter validation with a mock environment.
- `scripts/run_verl_online_rl.sh` for real VERL GRPO training.

The VERL source tree is expected outside this repo, normally at `/local_nvme/zhanglechao/verl`, and is injected with `PYTHONPATH`.

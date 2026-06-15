# VERL integration

This package connects the `mc_rollout` Minecraft runtime to VERL's async `AgentLoop` interface.

Current scope:

- Text-observation online RL loop for AgentA/AgentB low-level actions.
- Rule reward from Minecraft completion markers: pressure plate = 0.5; AgentB reaches the second room = 1.0 and ends the task.
- Auxiliary training reward: distance progress toward each agent goal plus a small yaw/pitch target-alignment reward, logged as `progress_reward`, `look_reward`, and `target_alignment`.
- Visual curriculum for floor targets: training rollouts randomize initial pitch downward with `start_pitch_min`/`start_pitch_max`, and AgentA observations explicitly prioritize `look_down` when the floor pressure plate is not visible.
- `scripts/check_verl_adapter.sh` for fast adapter validation with a mock environment.
- `scripts/run_verl_online_rl.sh` for real VERL GRPO training.
- Persistent Minecraft training mode can be enabled with `PERSISTENT_MINECRAFT=1`; `scripts/prewarm_train_instances.py` starts or attaches to the train instances before VERL rollouts.
- `configs/verl_minecraft_agent_loop_7b_n4.yaml` and `yaml/train_qwen25vl7b_n4_100step.yaml` provide a Qwen2.5-VL-7B 4-GPU training setup with persistent instances and image inputs.

The VERL source tree is expected outside this repo, normally at `/local_nvme/zhanglechao/verl`, and is injected with `PYTHONPATH`.

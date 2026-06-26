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
- `configs/verl_minecraft_agent_loop_7b_n4.yaml` and `yaml/train_qwen25vl7b_n4_100step.yaml` remain the backward-compatible multi-agent Qwen2.5-VL-7B 4-GPU setup with persistent instances and image inputs.
- Multi-agent training uses `scripts/train_qwen25vl7b_multiagent_100step.sh`, `yaml/train_qwen25vl7b_multiagent_100step.yaml`, and writes rollout traces under `runs/multiagent/verl_rollouts/`.
- Single-agent atomic training can be run as two separated tasks: `scripts/train_qwen25vl7b_single_agent_plate_100step.sh` trains AgentA to step onto the pressure plate and hold it; `scripts/train_qwen25vl7b_single_agent_door_100step.sh` trains AgentB to approach within 1 block of the elevator door. Their traces go under `runs/single_agent/pressure_plate/` and `runs/single_agent/elevator_door/`.
- `scripts/train_qwen25vl7b_single_agent_atomic_100step.sh` remains a generic single-agent entry; set `SINGLE_AGENT_ATOMIC_AGENTS=AgentA` or `AgentB` explicitly when using it.

The VERL source tree is expected outside this repo, normally at `/local_nvme/zhanglechao/verl`, and is injected with `PYTHONPATH`.

## Training Modes

Training mode is controlled by `TASK_MODE` and is also stored in each parquet row's `extra_info`. `TASK_MODE=multiagent` asks both AgentA and AgentB each step and uses the cooperative success condition. `TASK_MODE=single_agent` spawns and asks only the row's `controlled_agent`; no second agent is placed in the world. AgentA's atom uses `pressure_plate_hold`: first powered plate step gives 0.7, then each consecutive held step adds 0.1 up to 1.0 after 3 held bonus steps. AgentB's atom uses `elevator_door_approach`: reward is 1.0 once AgentB is within 1 block of the elevator door target.

Default output roots are split by `RUN_GROUP`: data goes to `data/verl_minecraft/<RUN_GROUP>/...`, rollout traces and run snapshots go to `runs/<RUN_GROUP>/verl_rollouts/...`, and prewarm logs go to `runs/<RUN_GROUP>/logs`.

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$ROOT/adapter:$ROOT/verl:${PYTHONPATH:-}"
PYTHON=${PYTHON:-/home/zlc/.conda/envs/envmine-verl/bin/python}
if [[ ! -x "$PYTHON" ]]; then PYTHON=python3; fi

MODEL_PATH=${MODEL_PATH:-Qwen/Qwen2.5-VL-7B-Instruct}
DATA_FORMAT=${DATA_FORMAT:-jsonl}
DATA_SUFFIX=$([[ "$DATA_FORMAT" == "parquet" ]] && echo parquet || echo jsonl)
TRAIN_FILE=${TRAIN_FILE:-$ROOT/data/envmine_lowlevel/train.$DATA_SUFFIX}
VAL_FILE=${VAL_FILE:-$ROOT/data/envmine_lowlevel/test.$DATA_SUFFIX}
TASK_INDICES=${TASK_INDICES:-0}
EPISODES_PER_TASK=${EPISODES_PER_TASK:-1}
AGENT_LOOP_CONFIG=${AGENT_LOOP_CONFIG:-$ROOT/configs/envmine_agent_loop.yaml}

NNODES=${NNODES:-1}
NGPUS_PER_NODE=${NGPUS_PER_NODE:-1}
TRAIN_BATCH_SIZE=${TRAIN_BATCH_SIZE:-1}
PPO_MINI_BATCH_SIZE=${PPO_MINI_BATCH_SIZE:-1}
MAX_PROMPT_LENGTH=${MAX_PROMPT_LENGTH:-4096}
MAX_RESPONSE_LENGTH=${MAX_RESPONSE_LENGTH:-8192}
PPO_MAX_TOKEN_LEN_PER_GPU=${PPO_MAX_TOKEN_LEN_PER_GPU:-16384}
ROLLOUT_MAX_MODEL_LEN=${ROLLOUT_MAX_MODEL_LEN:-}
ROLLOUT_TP=${ROLLOUT_TP:-1}
ROLLOUT_N=${ROLLOUT_N:-2}
AGENT_LOOP_WORKERS=${AGENT_LOOP_WORKERS:-2}
ROLLOUT_GPU_MEM_UTIL=${ROLLOUT_GPU_MEM_UTIL:-0.6}
ROLLOUT_MAX_NUM_SEQS=${ROLLOUT_MAX_NUM_SEQS:-}
ROLLOUT_MAX_NUM_BATCHED_TOKENS=${ROLLOUT_MAX_NUM_BATCHED_TOKENS:-}
ACTOR_LR=${ACTOR_LR:-1e-6}
TOTAL_EPOCHS=${TOTAL_EPOCHS:-1}
SAVE_FREQ=${SAVE_FREQ:-5}
TEST_FREQ=${TEST_FREQ:--1}
PROJECT_NAME=${PROJECT_NAME:-envmine_verl}
EXPERIMENT_NAME=${EXPERIMENT_NAME:-qwen25vl_envmine_grpo}
LOGGER=${LOGGER:-'["console"]'}

if [[ ! -f "$TRAIN_FILE" || ! -f "$VAL_FILE" ]]; then
  "$PYTHON" "$ROOT/scripts/prepare_envmine_verl_data.py" \
    --task-indices "$TASK_INDICES" \
    --episodes-per-task "$EPISODES_PER_TASK" \
    --output-dir "$(dirname "$TRAIN_FILE")" \
    --format "$DATA_FORMAT"
fi

DATA=(
  algorithm.adv_estimator=grpo
  algorithm.use_kl_in_reward=False
  data.train_files="$TRAIN_FILE"
  data.val_files="$VAL_FILE"
  data.prompt_key=prompt
  data.return_raw_chat=True
  data.train_batch_size=${TRAIN_BATCH_SIZE}
  data.max_prompt_length=${MAX_PROMPT_LENGTH}
  data.max_response_length=${MAX_RESPONSE_LENGTH}
  data.filter_overlong_prompts=False
  data.truncation=error
  data.dataloader_num_workers=0
)

MODEL=(
  actor_rollout_ref.model.path="$MODEL_PATH"
  actor_rollout_ref.model.use_remove_padding=True
  actor_rollout_ref.model.enable_gradient_checkpointing=True
)

ACTOR=(
  actor_rollout_ref.actor.strategy=fsdp2
  actor_rollout_ref.actor.optim.lr=${ACTOR_LR}
  actor_rollout_ref.actor.ppo_mini_batch_size=${PPO_MINI_BATCH_SIZE}
  actor_rollout_ref.actor.use_dynamic_bsz=True
  actor_rollout_ref.actor.ppo_max_token_len_per_gpu=${PPO_MAX_TOKEN_LEN_PER_GPU}
  actor_rollout_ref.actor.use_kl_loss=True
  actor_rollout_ref.actor.kl_loss_coef=0.01
  actor_rollout_ref.actor.kl_loss_type=low_var_kl
  actor_rollout_ref.actor.entropy_coeff=0
  actor_rollout_ref.actor.fsdp_config.param_offload=False
  actor_rollout_ref.actor.fsdp_config.optimizer_offload=False
)

ROLLOUT=(
  actor_rollout_ref.rollout.name=vllm
  actor_rollout_ref.rollout.tensor_model_parallel_size=${ROLLOUT_TP}
  actor_rollout_ref.rollout.gpu_memory_utilization=${ROLLOUT_GPU_MEM_UTIL}
  actor_rollout_ref.rollout.n=${ROLLOUT_N}
  actor_rollout_ref.rollout.log_prob_use_dynamic_bsz=True
  actor_rollout_ref.rollout.log_prob_max_token_len_per_gpu=${PPO_MAX_TOKEN_LEN_PER_GPU}
  actor_rollout_ref.rollout.enable_chunked_prefill=False
  actor_rollout_ref.rollout.enforce_eager=False
  actor_rollout_ref.rollout.free_cache_engine=True
  actor_rollout_ref.rollout.agent.num_workers=${AGENT_LOOP_WORKERS}
  actor_rollout_ref.rollout.agent.default_agent_loop=envmine_lowlevel
  actor_rollout_ref.rollout.agent.agent_loop_config_path="$AGENT_LOOP_CONFIG"
)
if [[ -n "$ROLLOUT_MAX_MODEL_LEN" ]]; then
  ROLLOUT+=(actor_rollout_ref.rollout.max_model_len=${ROLLOUT_MAX_MODEL_LEN})
fi
if [[ -n "$ROLLOUT_MAX_NUM_SEQS" ]]; then
  ROLLOUT+=(actor_rollout_ref.rollout.max_num_seqs=${ROLLOUT_MAX_NUM_SEQS})
fi
if [[ -n "$ROLLOUT_MAX_NUM_BATCHED_TOKENS" ]]; then
  ROLLOUT+=(actor_rollout_ref.rollout.max_num_batched_tokens=${ROLLOUT_MAX_NUM_BATCHED_TOKENS})
fi

REF=(
  actor_rollout_ref.ref.log_prob_use_dynamic_bsz=True
  actor_rollout_ref.ref.log_prob_max_token_len_per_gpu=${PPO_MAX_TOKEN_LEN_PER_GPU}
  actor_rollout_ref.ref.fsdp_config.param_offload=True
)

TRAINER=(
  trainer.balance_batch=False
  trainer.logger="$LOGGER"
  trainer.project_name=${PROJECT_NAME}
  trainer.experiment_name=${EXPERIMENT_NAME}
  trainer.n_gpus_per_node=${NGPUS_PER_NODE}
  trainer.nnodes=${NNODES}
  trainer.save_freq=${SAVE_FREQ}
  trainer.test_freq=${TEST_FREQ}
  trainer.total_epochs=${TOTAL_EPOCHS}
  trainer.val_before_train=False
)

"$PYTHON" -m verl.trainer.main_ppo \
  "${DATA[@]}" \
  "${MODEL[@]}" \
  "${ACTOR[@]}" \
  "${ROLLOUT[@]}" \
  "${REF[@]}" \
  "${TRAINER[@]}" \
  "$@"

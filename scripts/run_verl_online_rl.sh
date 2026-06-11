#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PYTHON_BIN=${PYTHON_BIN:-/home/azvm/miniconda3/envs/verl/bin/python}
VERL_HOME=${VERL_HOME:-/local_nvme/zhanglechao/verl}
MODEL_PATH=${MODEL_PATH:-/local_nvme/zhanglechao/models/Qwen2.5-VL-3B-Instruct}
DATA_DIR=${DATA_DIR:-${ROOT_DIR}/data/verl_minecraft}
TRAIN_FILE=${TRAIN_FILE:-${DATA_DIR}/train.parquet}
VAL_FILE=${VAL_FILE:-${DATA_DIR}/val.parquet}

if [ "${MOCK_MC:-0}" = "1" ]; then
  export IT_TAKETWO_MOCK_MC=1
  DEFAULT_AGENT_LOOP_CONFIG="${ROOT_DIR}/configs/verl_minecraft_agent_loop_mock.yaml"
else
  DEFAULT_AGENT_LOOP_CONFIG="${ROOT_DIR}/configs/verl_minecraft_agent_loop.yaml"
fi
AGENT_LOOP_CONFIG=${AGENT_LOOP_CONFIG:-${DEFAULT_AGENT_LOOP_CONFIG}}

export PYTHONPATH="${ROOT_DIR}:${VERL_HOME}:${PYTHONPATH:-}"
export HYDRA_FULL_ERROR=${HYDRA_FULL_ERROR:-1}
export RAY_TMPDIR=${RAY_TMPDIR:-/local_nvme/tmp/ray_it_taketwo}
export TORCH_CUDA_ARCH_LIST=${TORCH_CUDA_ARCH_LIST:-8.0}

if [ ! -f "${TRAIN_FILE}" ] || [ ! -f "${VAL_FILE}" ]; then
  "${ROOT_DIR}/scripts/prepare_verl_minecraft_data.sh" \
    --output-dir "${DATA_DIR}" \
    --train-size "${TRAIN_SIZE:-4}" \
    --val-size "${VAL_SIZE:-1}"
fi

if [ ! -e "${MODEL_PATH}" ]; then
  echo "warning: MODEL_PATH does not exist locally: ${MODEL_PATH}" >&2
  echo "set MODEL_PATH to a local Hugging Face model path before launching a no-network run" >&2
fi

INFER_BACKEND=${INFER_BACKEND:-vllm}
NGPUS_PER_NODE=${NGPUS_PER_NODE:-4}
TRAIN_BATCH_SIZE=${TRAIN_BATCH_SIZE:-4}
PPO_MINI_BATCH_SIZE=${PPO_MINI_BATCH_SIZE:-4}
ROLLOUT_N=${ROLLOUT_N:-4}
TRAIN_INSTANCE_PREFIX=${TRAIN_INSTANCE_PREFIX:-instance-train}
TRAIN_INSTANCE_COUNT=${TRAIN_INSTANCE_COUNT:-$((TRAIN_BATCH_SIZE * ROLLOUT_N))}
TRAIN_TICKGATE_BASE_PORT=${TRAIN_TICKGATE_BASE_PORT:-25690}
USE_VLM_IMAGES_FLAG=${USE_VLM_IMAGES:-${IT_TAKETWO_USE_IMAGES:-1}}
if [ "${USE_VLM_IMAGES_FLAG}" = "1" ]; then
  MAX_PROMPT_LENGTH=${MAX_PROMPT_LENGTH:-3072}
  MAX_RESPONSE_LENGTH=${MAX_RESPONSE_LENGTH:-8192}
  ROLLOUT_GPU_MEMORY_UTILIZATION=${ROLLOUT_GPU_MEMORY_UTILIZATION:-0.35}
  VLM_MIN_PIXELS=${VLM_MIN_PIXELS:-3136}
  VLM_MAX_PIXELS=${VLM_MAX_PIXELS:-12544}
  export IT_TAKETWO_IMAGE_MAX_WIDTH=${IT_TAKETWO_IMAGE_MAX_WIDTH:-256}
  export IT_TAKETWO_IMAGE_MAX_HEIGHT=${IT_TAKETWO_IMAGE_MAX_HEIGHT:-144}
else
  MAX_PROMPT_LENGTH=${MAX_PROMPT_LENGTH:-2048}
  MAX_RESPONSE_LENGTH=${MAX_RESPONSE_LENGTH:-2048}
  ROLLOUT_GPU_MEMORY_UTILIZATION=${ROLLOUT_GPU_MEMORY_UTILIZATION:-0.6}
fi
PPO_MAX_TOKEN_LEN_PER_GPU=${PPO_MAX_TOKEN_LEN_PER_GPU:-12288}
ROLLOUT_TP=${ROLLOUT_TP:-1}
ROLLOUT_MAX_MODEL_LEN=${ROLLOUT_MAX_MODEL_LEN:-$((MAX_PROMPT_LENGTH + MAX_RESPONSE_LENGTH))}
ROLLOUT_MAX_NUM_BATCHED_TOKENS=${ROLLOUT_MAX_NUM_BATCHED_TOKENS:-$((ROLLOUT_MAX_MODEL_LEN + 1024))}
ROLLOUT_MAX_NUM_SEQS=${ROLLOUT_MAX_NUM_SEQS:-24}
ENFORCE_EAGER=${ENFORCE_EAGER:-True}
AGENT_WORKERS=${AGENT_WORKERS:-${TRAIN_INSTANCE_COUNT}}
if [ "${USE_VLM_IMAGES_FLAG}" = "1" ]; then
  DEFAULT_DYNAMIC_BSZ=False
  DEFAULT_USE_REMOVE_PADDING=False
else
  DEFAULT_DYNAMIC_BSZ=True
  DEFAULT_USE_REMOVE_PADDING=True
fi
ACTOR_USE_DYNAMIC_BSZ=${ACTOR_USE_DYNAMIC_BSZ:-${DEFAULT_DYNAMIC_BSZ}}
ROLLOUT_LOG_PROB_USE_DYNAMIC_BSZ=${ROLLOUT_LOG_PROB_USE_DYNAMIC_BSZ:-${ACTOR_USE_DYNAMIC_BSZ}}
REF_LOG_PROB_USE_DYNAMIC_BSZ=${REF_LOG_PROB_USE_DYNAMIC_BSZ:-${ACTOR_USE_DYNAMIC_BSZ}}
USE_REMOVE_PADDING=${USE_REMOVE_PADDING:-${DEFAULT_USE_REMOVE_PADDING}}
PPO_MICRO_BATCH_SIZE_PER_GPU=${PPO_MICRO_BATCH_SIZE_PER_GPU:-1}
LOG_PROB_MICRO_BATCH_SIZE_PER_GPU=${LOG_PROB_MICRO_BATCH_SIZE_PER_GPU:-1}
REF_LOG_PROB_MICRO_BATCH_SIZE_PER_GPU=${REF_LOG_PROB_MICRO_BATCH_SIZE_PER_GPU:-1}
ACTOR_LR=${ACTOR_LR:-1e-6}
TOTAL_EPOCHS=${TOTAL_EPOCHS:-1}
SAVE_FREQ=${SAVE_FREQ:--1}
TEST_FREQ=${TEST_FREQ:--1}
PROJECT_NAME=${PROJECT_NAME:-it_taketwo_verl}
EXPERIMENT_NAME=${EXPERIMENT_NAME:-minecraft_online_rl_$(date +%Y%m%d_%H%M%S)}
export IT_TAKETWO_SAVE_ROLLOUT_TRACE=${IT_TAKETWO_SAVE_ROLLOUT_TRACE:-1}
export IT_TAKETWO_ROLLOUT_TRACE_DIR=${IT_TAKETWO_ROLLOUT_TRACE_DIR:-${ROOT_DIR}/runs/verl_rollouts/${EXPERIMENT_NAME}}

export IT_TAKETWO_TRAIN_INSTANCE_PREFIX=${TRAIN_INSTANCE_PREFIX}
export IT_TAKETWO_TRAIN_INSTANCE_COUNT=${TRAIN_INSTANCE_COUNT}
export IT_TAKETWO_TRAIN_TICKGATE_BASE_PORT=${TRAIN_TICKGATE_BASE_PORT}
export IT_TAKETWO_ROLLOUT_N=${ROLLOUT_N}
export IT_TAKETWO_USE_IMAGES=${USE_VLM_IMAGES_FLAG}
export IT_TAKETWO_HISTORY_WINDOW_IMAGES=${IT_TAKETWO_HISTORY_WINDOW_IMAGES:-3}
export IT_TAKETWO_HISTORY_MAX_TOKENS=${IT_TAKETWO_HISTORY_MAX_TOKENS:-3072}
export IT_TAKETWO_QUIET_MC_LOGS=${IT_TAKETWO_QUIET_MC_LOGS:-1}

if [ "${MOCK_MC:-0}" != "1" ]; then
  TRAIN_INSTANCE_PREFIX=${TRAIN_INSTANCE_PREFIX} \
  TRAIN_INSTANCE_COUNT=${TRAIN_INSTANCE_COUNT} \
  TRAIN_TICKGATE_BASE_PORT=${TRAIN_TICKGATE_BASE_PORT} \
    "${ROOT_DIR}/scripts/prepare_train_instances.sh"
fi

DATA=(
  algorithm.adv_estimator=grpo
  algorithm.use_kl_in_reward=False
  data.train_files="${TRAIN_FILE}"
  data.val_files="${VAL_FILE}"
  data.train_batch_size=${TRAIN_BATCH_SIZE}
  data.max_prompt_length=${MAX_PROMPT_LENGTH}
  data.max_response_length=${MAX_RESPONSE_LENGTH}
  data.return_raw_chat=True
  data.filter_overlong_prompts=True
  data.truncation=error
  data.dataloader_num_workers=${DATALOADER_NUM_WORKERS:-0}
)
if [ "${USE_VLM_IMAGES_FLAG}" = "1" ]; then
  DATA+=(
    +data.mm_processor_kwargs.min_pixels=${VLM_MIN_PIXELS}
    +data.mm_processor_kwargs.max_pixels=${VLM_MAX_PIXELS}
  )
fi

MODEL=(
  actor_rollout_ref.model.path="${MODEL_PATH}"
  actor_rollout_ref.model.use_remove_padding=${USE_REMOVE_PADDING}
  actor_rollout_ref.model.enable_gradient_checkpointing=True
)

ACTOR=(
  actor_rollout_ref.actor.optim.lr=${ACTOR_LR}
  actor_rollout_ref.actor.ppo_mini_batch_size=${PPO_MINI_BATCH_SIZE}
  actor_rollout_ref.actor.use_dynamic_bsz=${ACTOR_USE_DYNAMIC_BSZ}
  actor_rollout_ref.actor.ppo_max_token_len_per_gpu=${PPO_MAX_TOKEN_LEN_PER_GPU}
  actor_rollout_ref.actor.use_kl_loss=False
  actor_rollout_ref.actor.entropy_coeff=0
  actor_rollout_ref.actor.fsdp_config.param_offload=False
  actor_rollout_ref.actor.fsdp_config.optimizer_offload=False
)

ROLLOUT=(
  actor_rollout_ref.rollout.name=${INFER_BACKEND}
  actor_rollout_ref.rollout.mode=async
  actor_rollout_ref.rollout.tensor_model_parallel_size=${ROLLOUT_TP}
  actor_rollout_ref.rollout.gpu_memory_utilization=${ROLLOUT_GPU_MEMORY_UTILIZATION}
  actor_rollout_ref.rollout.max_model_len=${ROLLOUT_MAX_MODEL_LEN}
  actor_rollout_ref.rollout.max_num_batched_tokens=${ROLLOUT_MAX_NUM_BATCHED_TOKENS}
  actor_rollout_ref.rollout.max_num_seqs=${ROLLOUT_MAX_NUM_SEQS}
  actor_rollout_ref.rollout.n=${ROLLOUT_N}
  actor_rollout_ref.rollout.log_prob_use_dynamic_bsz=${ROLLOUT_LOG_PROB_USE_DYNAMIC_BSZ}
  actor_rollout_ref.rollout.log_prob_max_token_len_per_gpu=${PPO_MAX_TOKEN_LEN_PER_GPU}
  actor_rollout_ref.rollout.agent.num_workers=${AGENT_WORKERS}
  actor_rollout_ref.rollout.agent.default_agent_loop=minecraft_agent
  actor_rollout_ref.rollout.agent.agent_loop_config_path="${AGENT_LOOP_CONFIG}"
)

REF=(
  actor_rollout_ref.ref.log_prob_use_dynamic_bsz=${REF_LOG_PROB_USE_DYNAMIC_BSZ}
  actor_rollout_ref.ref.log_prob_max_token_len_per_gpu=${PPO_MAX_TOKEN_LEN_PER_GPU}
  actor_rollout_ref.ref.fsdp_config.param_offload=True
)

if [ "${ACTOR_USE_DYNAMIC_BSZ}" != "True" ] && [ "${ACTOR_USE_DYNAMIC_BSZ}" != "true" ]; then
  ACTOR+=(actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu=${PPO_MICRO_BATCH_SIZE_PER_GPU})
fi
if [ "${ROLLOUT_LOG_PROB_USE_DYNAMIC_BSZ}" != "True" ] && [ "${ROLLOUT_LOG_PROB_USE_DYNAMIC_BSZ}" != "true" ]; then
  ROLLOUT+=(actor_rollout_ref.rollout.log_prob_micro_batch_size_per_gpu=${LOG_PROB_MICRO_BATCH_SIZE_PER_GPU})
fi
if [ "${REF_LOG_PROB_USE_DYNAMIC_BSZ}" != "True" ] && [ "${REF_LOG_PROB_USE_DYNAMIC_BSZ}" != "true" ]; then
  REF+=(actor_rollout_ref.ref.log_prob_micro_batch_size_per_gpu=${REF_LOG_PROB_MICRO_BATCH_SIZE_PER_GPU})
fi

TRAINER=(
  trainer.balance_batch=True
  trainer.logger='["console"]'
  trainer.project_name=${PROJECT_NAME}
  trainer.experiment_name=${EXPERIMENT_NAME}
  trainer.n_gpus_per_node=${NGPUS_PER_NODE}
  trainer.nnodes=1
  trainer.save_freq=${SAVE_FREQ}
  trainer.test_freq=${TEST_FREQ}
  trainer.val_before_train=False
  trainer.total_epochs=${TOTAL_EPOCHS}
)

if [ -n "${TOTAL_TRAINING_STEPS:-}" ]; then
  TRAINER+=(trainer.total_training_steps=${TOTAL_TRAINING_STEPS})
fi

EXTRA=(
  actor_rollout_ref.actor.strategy=fsdp2
  actor_rollout_ref.rollout.enforce_eager=${ENFORCE_EAGER}
  actor_rollout_ref.rollout.multi_stage_wake_up=False
  actor_rollout_ref.rollout.enable_prefix_caching=False
  actor_rollout_ref.rollout.enable_chunked_prefill=False
  actor_rollout_ref.rollout.free_cache_engine=True
  +actor_rollout_ref.rollout.engine_kwargs.vllm.max_model_len=${ROLLOUT_MAX_MODEL_LEN}
)

cd "${VERL_HOME}"
"${PYTHON_BIN}" -m verl.trainer.main_ppo \
  "${DATA[@]}" \
  "${MODEL[@]}" \
  "${ACTOR[@]}" \
  "${ROLLOUT[@]}" \
  "${REF[@]}" \
  "${TRAINER[@]}" \
  "${EXTRA[@]}" \
  "$@"

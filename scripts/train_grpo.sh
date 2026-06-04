#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/gpu_env.sh"

MODEL="${MODEL:-/root/autodl-tmp/models/Qwen3-1.7B}"
ADAPTERS="${ADAPTERS:-}"
REF_ADAPTERS="${REF_ADAPTERS:-}"
DATASET="${DATASET:-data/benchmark/grpo_train.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/checkpoints/qwen3-docagent-grpo}"
PRECISION="${PRECISION:-bfloat16}"
TUNER_ARG_NAME="${TUNER_ARG_NAME:-tuner_type}"
TUNER_TYPE="${TUNER_TYPE:-lora}"
LORA_RANK="${LORA_RANK:-8}"
LORA_ALPHA="${LORA_ALPHA:-16}"
TARGET_MODULES="${TARGET_MODULES:-all-linear}"
MAX_STEPS="${MAX_STEPS:-10}"
NUM_GENERATIONS="${NUM_GENERATIONS:-2}"
MAX_LENGTH="${MAX_LENGTH:-2048}"
MAX_COMPLETION_LENGTH="${MAX_COMPLETION_LENGTH:-512}"
PER_DEVICE_TRAIN_BATCH_SIZE="${PER_DEVICE_TRAIN_BATCH_SIZE:-1}"
GRADIENT_ACCUMULATION_STEPS="${GRADIENT_ACCUMULATION_STEPS:-4}"
LEARNING_RATE="${LEARNING_RATE:-5e-6}"
SAVE_TOTAL_LIMIT="${SAVE_TOTAL_LIMIT:-1}"
LOGGING_STEPS="${LOGGING_STEPS:-1}"
BETA="${BETA:-0}"
GENERATION_BATCH_SIZE="${GENERATION_BATCH_SIZE:-}"
USE_VLLM="${USE_VLLM:-false}"
DATALOADER_NUM_WORKERS="${DATALOADER_NUM_WORKERS:-0}"
DATASET_NUM_PROC="${DATASET_NUM_PROC:-1}"
GRADIENT_CHECKPOINTING="${GRADIENT_CHECKPOINTING:-true}"
REPORT_TO="${REPORT_TO:-none}"
SAVE_ONLY_MODEL="${SAVE_ONLY_MODEL:-true}"
DRY_RUN="${DRY_RUN:-0}"

prepare_gpu_env
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

if [[ ! -f "$MODEL/config.json" ]]; then
  echo "Local base model not found or incomplete: $MODEL" >&2
  exit 2
fi

if [[ -n "$ADAPTERS" && ! -f "$ADAPTERS/adapter_model.safetensors" ]]; then
  echo "Adapter checkpoint not found or incomplete: $ADAPTERS" >&2
  exit 2
fi

if [[ ! -f "$DATASET" ]]; then
  echo "Dataset not found: $DATASET" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR" outputs/logs

if [[ "$USE_VLLM" == "true" || "$USE_VLLM" == "1" ]]; then
  launcher=(swift rlhf)
else
  launcher=(python -m scripts.no_vllm_swift_entrypoint)
fi

cmd=(
  "${launcher[@]}"
  --rlhf_type grpo
  --model "$MODEL"
  --dataset "$DATASET"
  --external_plugins "$SCRIPT_DIR/grpo_reward_plugin.py"
  --reward_funcs docagent_docqa
  "--$TUNER_ARG_NAME" "$TUNER_TYPE"
  --lora_rank "$LORA_RANK"
  --lora_alpha "$LORA_ALPHA"
  --target_modules "$TARGET_MODULES"
  --torch_dtype "$PRECISION"
  --max_steps "$MAX_STEPS"
  --per_device_train_batch_size "$PER_DEVICE_TRAIN_BATCH_SIZE"
  --gradient_accumulation_steps "$GRADIENT_ACCUMULATION_STEPS"
  --learning_rate "$LEARNING_RATE"
  --max_length "$MAX_LENGTH"
  --max_completion_length "$MAX_COMPLETION_LENGTH"
  --num_generations "$NUM_GENERATIONS"
  --beta "$BETA"
  --use_vllm "$USE_VLLM"
  --dataloader_num_workers "$DATALOADER_NUM_WORKERS"
  --dataset_num_proc "$DATASET_NUM_PROC"
  --gradient_checkpointing "$GRADIENT_CHECKPOINTING"
  --report_to "$REPORT_TO"
  --save_only_model "$SAVE_ONLY_MODEL"
  --save_steps "$MAX_STEPS"
  --save_total_limit "$SAVE_TOTAL_LIMIT"
  --logging_steps "$LOGGING_STEPS"
  --output_dir "$OUTPUT_DIR"
)

if [[ -n "$ADAPTERS" ]]; then
  cmd+=(--adapters "$ADAPTERS")
fi

if [[ -n "$GENERATION_BATCH_SIZE" ]]; then
  cmd+=(--generation_batch_size "$GENERATION_BATCH_SIZE")
fi

if [[ -n "$REF_ADAPTERS" && "$BETA" != "0" && "$BETA" != "0.0" ]]; then
  cmd+=(--ref_adapters "$REF_ADAPTERS")
fi

if [[ "$DRY_RUN" == "1" ]]; then
  printf '%q ' "${cmd[@]}"
  printf '\n'
  exit 0
fi

"${cmd[@]}"

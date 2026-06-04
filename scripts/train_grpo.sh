#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/gpu_env.sh"

MODEL="${MODEL:-/root/autodl-tmp/models/Qwen3-1.7B}"
ADAPTERS="${ADAPTERS:-}"
REF_ADAPTERS="${REF_ADAPTERS:-$ADAPTERS}"
DATASET="${DATASET:-data/benchmark/grpo_train.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/checkpoints/qwen3-docagent-grpo}"
PRECISION="${PRECISION:-bfloat16}"
MAX_STEPS="${MAX_STEPS:-10}"
NUM_GENERATIONS="${NUM_GENERATIONS:-2}"
MAX_LENGTH="${MAX_LENGTH:-2048}"
MAX_COMPLETION_LENGTH="${MAX_COMPLETION_LENGTH:-512}"
PER_DEVICE_TRAIN_BATCH_SIZE="${PER_DEVICE_TRAIN_BATCH_SIZE:-1}"
GRADIENT_ACCUMULATION_STEPS="${GRADIENT_ACCUMULATION_STEPS:-4}"
LEARNING_RATE="${LEARNING_RATE:-5e-6}"
SAVE_TOTAL_LIMIT="${SAVE_TOTAL_LIMIT:-1}"
LOGGING_STEPS="${LOGGING_STEPS:-1}"

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

cmd=(
  swift rlhf
  --rlhf_type grpo
  --model "$MODEL"
  --dataset "$DATASET"
  --external_plugins "$SCRIPT_DIR/grpo_reward_plugin.py"
  --reward_funcs docagent_docqa
  --tuner_type lora
  --torch_dtype "$PRECISION"
  --max_steps "$MAX_STEPS"
  --per_device_train_batch_size "$PER_DEVICE_TRAIN_BATCH_SIZE"
  --gradient_accumulation_steps "$GRADIENT_ACCUMULATION_STEPS"
  --learning_rate "$LEARNING_RATE"
  --max_length "$MAX_LENGTH"
  --max_completion_length "$MAX_COMPLETION_LENGTH"
  --num_generations "$NUM_GENERATIONS"
  --save_steps "$MAX_STEPS"
  --save_total_limit "$SAVE_TOTAL_LIMIT"
  --logging_steps "$LOGGING_STEPS"
  --output_dir "$OUTPUT_DIR"
)

if [[ -n "$ADAPTERS" ]]; then
  cmd+=(--adapters "$ADAPTERS")
fi

if [[ -n "$REF_ADAPTERS" ]]; then
  cmd+=(--ref_adapters "$REF_ADAPTERS")
fi

"${cmd[@]}"

#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/gpu_env.sh"

MODEL="${MODEL:-outputs/checkpoints/qwen3-docagent-sft}"
DATASET="${DATASET:-data/benchmark/grpo_train.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/checkpoints/qwen3-docagent-grpo}"
PRECISION="${PRECISION:-bfloat16}"

prepare_gpu_env
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

if [[ ! -e "$MODEL" ]]; then
  echo "Model or checkpoint path not found: $MODEL" >&2
  exit 2
fi

if [[ ! -f "$DATASET" ]]; then
  echo "Dataset not found: $DATASET" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR" outputs/logs

swift rlhf \
  --rlhf_type grpo \
  --model "$MODEL" \
  --train_type lora \
  --dataset "$DATASET" \
  --torch_dtype "$PRECISION" \
  --per_device_train_batch_size 1 \
  --gradient_accumulation_steps 8 \
  --learning_rate 5e-6 \
  --output_dir "$OUTPUT_DIR"

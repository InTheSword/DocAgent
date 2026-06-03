#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/gpu_env.sh"

MODEL="${MODEL:-/root/autodl-tmp/models/Qwen3-1.7B}"
DATASET="${DATASET:-data/benchmark/tatqa_sft_smoke.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/checkpoints/qwen3-docagent-sft-smoke}"
PRECISION="${PRECISION:-bfloat16}"
MAX_STEPS="${MAX_STEPS:-5}"

prepare_gpu_env
export TRANSFORMERS_OFFLINE="${TRANSFORMERS_OFFLINE:-1}"
export HF_HUB_OFFLINE="${HF_HUB_OFFLINE:-1}"

if [[ ! -f "$MODEL/config.json" ]]; then
  echo "Local model not found or incomplete: $MODEL" >&2
  echo "Download Qwen3-1.7B manually to /root/autodl-tmp/models/Qwen3-1.7B before training." >&2
  exit 2
fi

if [[ ! -f "$DATASET" ]]; then
  echo "Dataset not found: $DATASET" >&2
  exit 2
fi

mkdir -p "$OUTPUT_DIR" outputs/logs

swift sft \
  --model "$MODEL" \
  --dataset "$DATASET" \
  --tuner_type lora \
  --torch_dtype "$PRECISION" \
  --max_steps "$MAX_STEPS" \
  --per_device_train_batch_size 1 \
  --gradient_accumulation_steps 4 \
  --learning_rate 1e-4 \
  --lora_rank 8 \
  --lora_alpha 16 \
  --target_modules all-linear \
  --max_length 2048 \
  --save_steps "$MAX_STEPS" \
  --save_total_limit 1 \
  --logging_steps 1 \
  --output_dir "$OUTPUT_DIR"

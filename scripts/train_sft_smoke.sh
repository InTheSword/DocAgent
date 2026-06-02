#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3-1.7B}"
DATASET="${DATASET:-data/benchmark/tatqa_sft_smoke.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/checkpoints/qwen3-docagent-sft-smoke}"
PRECISION="${PRECISION:-bfloat16}"
USE_HF="${USE_HF:-true}"
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
MAX_STEPS="${MAX_STEPS:-5}"

export CUDA_VISIBLE_DEVICES
export HF_HOME="${HF_HOME:-/root/autodl-tmp/models/huggingface}"
export MODELSCOPE_CACHE="${MODELSCOPE_CACHE:-/root/autodl-tmp/models/modelscope}"

mkdir -p "$HF_HOME" "$MODELSCOPE_CACHE" "$OUTPUT_DIR" outputs/logs

swift sft \
  --model "$MODEL" \
  --use_hf "$USE_HF" \
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


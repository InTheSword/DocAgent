#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-Qwen/Qwen3-1.7B}"
DATASET="${DATASET:-data/benchmark/train_sft.jsonl}"
VAL_DATASET="${VAL_DATASET:-data/benchmark/dev_sft.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/checkpoints/qwen3-docagent-sft}"
PRECISION="${PRECISION:-fp16}"

swift sft \
  --model "$MODEL" \
  --train_type lora \
  --dataset "$DATASET" \
  --val_dataset "$VAL_DATASET" \
  --torch_dtype "$PRECISION" \
  --num_train_epochs 1 \
  --per_device_train_batch_size 1 \
  --gradient_accumulation_steps 8 \
  --learning_rate 1e-4 \
  --lora_rank 8 \
  --lora_alpha 16 \
  --target_modules all-linear \
  --output_dir "$OUTPUT_DIR"


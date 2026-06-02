#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-outputs/checkpoints/qwen3-docagent-sft}"
DATASET="${DATASET:-data/benchmark/grpo_train.jsonl}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/checkpoints/qwen3-docagent-grpo}"
PRECISION="${PRECISION:-fp16}"

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


#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-/root/autodl-tmp/models/Qwen3-1.7B}"
ADAPTER="${ADAPTER:-outputs/checkpoints/qwen3-docagent-sft-tatqa900-20260603_204122/v0-20260603-204144/checkpoint-200}"
DATASET="${DATASET:-data/benchmark/tatqa_train_grpo_1000_v2.jsonl}"
LIMIT="${LIMIT:-1000}"
MAX_STEPS="${MAX_STEPS:-20}"
NUM_GENERATIONS="${NUM_GENERATIONS:-4}"
PER_DEVICE_TRAIN_BATCH_SIZE="${PER_DEVICE_TRAIN_BATCH_SIZE:-2}"
GRADIENT_ACCUMULATION_STEPS="${GRADIENT_ACCUMULATION_STEPS:-1}"
LEARNING_RATE="${LEARNING_RATE:-5e-6}"
MAX_PROMPT_TOKENS="${MAX_PROMPT_TOKENS:-768}"
MAX_COMPLETION_LENGTH="${MAX_COMPLETION_LENGTH:-64}"
TEMPERATURE="${TEMPERATURE:-0.8}"
TOP_P="${TOP_P:-0.95}"
CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0,1}"
NPROC_PER_NODE="${NPROC_PER_NODE:-2}"
RUN_NAME="${RUN_NAME:-qwen3-docagent-trl-grpo-ng${NUM_GENERATIONS}-$(date +%Y%m%d_%H%M%S)}"
OUTPUT_DIR="${OUTPUT_DIR:-outputs/checkpoints/${RUN_NAME}}"
SUMMARY_OUTPUT="${SUMMARY_OUTPUT:-outputs/eval/${RUN_NAME}_summary.json}"
LOG_FILE="${LOG_FILE:-outputs/logs/${RUN_NAME}.log}"

mkdir -p outputs/checkpoints outputs/eval outputs/logs

export OMP_NUM_THREADS="${OMP_NUM_THREADS:-4}"
export MKL_NUM_THREADS="${MKL_NUM_THREADS:-4}"
export TOKENIZERS_PARALLELISM="${TOKENIZERS_PARALLELISM:-false}"

CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES}" \
PYTHONUNBUFFERED=1 \
torchrun --standalone --nproc_per_node="${NPROC_PER_NODE}" scripts/train_trl_grpo.py \
  --model "${MODEL}" \
  --adapter "${ADAPTER}" \
  --dataset "${DATASET}" \
  --output-dir "${OUTPUT_DIR}" \
  --summary-output "${SUMMARY_OUTPUT}" \
  --limit "${LIMIT}" \
  --max-steps "${MAX_STEPS}" \
  --num-generations "${NUM_GENERATIONS}" \
  --per-device-train-batch-size "${PER_DEVICE_TRAIN_BATCH_SIZE}" \
  --gradient-accumulation-steps "${GRADIENT_ACCUMULATION_STEPS}" \
  --learning-rate "${LEARNING_RATE}" \
  --max-prompt-tokens "${MAX_PROMPT_TOKENS}" \
  --max-completion-length "${MAX_COMPLETION_LENGTH}" \
  --temperature "${TEMPERATURE}" \
  --top-p "${TOP_P}" \
  2>&1 | tee "${LOG_FILE}" || {
    tail -80 "${LOG_FILE}"
    exit 1
  }

python scripts/summarize_grpo_run.py --input "${SUMMARY_OUTPUT}" --log-file "${LOG_FILE}"

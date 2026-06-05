#!/usr/bin/env bash
set -euo pipefail

MODEL="${MODEL:-/root/autodl-tmp/models/Qwen3-1.7B}"
ADAPTER="${ADAPTER:?Set ADAPTER to a LoRA checkpoint directory.}"
INPUT="${INPUT:-data/benchmark/tatqa_sft_audited.jsonl}"
OUTPUT="${OUTPUT:-outputs/eval/checkpoint_eval_parallel.jsonl}"
SUMMARY_OUTPUT="${SUMMARY_OUTPUT:-outputs/eval/checkpoint_eval_parallel_summary.json}"
LIMIT="${LIMIT:-100}"
MAX_NEW_TOKENS="${MAX_NEW_TOKENS:-512}"
TEMPERATURE="${TEMPERATURE:-0.0}"
BATCH_SIZE="${BATCH_SIZE:-4}"
NUM_SHARDS="${NUM_SHARDS:-2}"
STRICT_EXTRACTION="${STRICT_EXTRACTION:-0}"

extra_args=()
if [[ "${STRICT_EXTRACTION}" == "1" || "${STRICT_EXTRACTION}" == "true" ]]; then
  extra_args+=(--strict-extraction)
fi

mkdir -p outputs/eval outputs/logs

base="${OUTPUT%.jsonl}"
summary_base="${SUMMARY_OUTPUT%.json}"
shard_outputs=()
pids=()

for shard in $(seq 0 $((NUM_SHARDS - 1))); do
  shard_output="${base}.shard${shard}.jsonl"
  shard_summary="${summary_base}.shard${shard}.json"
  shard_log="outputs/logs/eval_parallel_shard${shard}.log"
  shard_outputs+=("${shard_output}")
  CUDA_VISIBLE_DEVICES="${shard}" python scripts/eval_sft_checkpoint.py \
    --model "${MODEL}" \
    --adapter "${ADAPTER}" \
    --input "${INPUT}" \
    --output "${shard_output}" \
    --summary-output "${shard_summary}" \
    --limit "${LIMIT}" \
    --max-new-tokens "${MAX_NEW_TOKENS}" \
    --temperature "${TEMPERATURE}" \
    --batch-size "${BATCH_SIZE}" \
    --num-shards "${NUM_SHARDS}" \
    --shard-index "${shard}" \
    "${extra_args[@]}" \
    > "${shard_log}" 2>&1 &
  pids+=("$!")
done

for pid in "${pids[@]}"; do
  wait "${pid}"
done

python scripts/merge_eval_shards.py \
  --inputs "${shard_outputs[@]}" \
  --output "${OUTPUT}" \
  --summary-output "${SUMMARY_OUTPUT}" \
  --model "${MODEL}" \
  --adapter "${ADAPTER}" \
  --input-name "${INPUT}"

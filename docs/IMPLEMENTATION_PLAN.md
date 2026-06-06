# DocAgent Implementation Plan

This plan converts DocAgent 3.0 into staged engineering milestones. Each stage
has a concrete verification target before the next stage starts.

## Assumptions

- Local code lives in `D:\Projects\docagent`.
- GPU experiments will run on the lab server through git/ssh.
- Model and raw dataset files are downloaded manually on AutoDL. Scripts read
  local paths by default and should not silently fetch full model/data files.
- The first training target is local Qwen3-1.7B at
  `/root/autodl-tmp/models/Qwen3-1.7B`.
- `Qwen3-4B` is an optional SFT comparison, not the first GRPO target.
- `Qwen2.5-VL` is only used as a visual review branch.
- MP-DocVQA is a multi-page document image QA dataset, not a PDF dataset. It
  remains the primary document-image source because it has page-level answers
  and real page images.
- MinerU is required for real uploaded documents and may also be used for image
  documents when practical. PaddleOCR is the current lightweight parser for
  MP-DocVQA image pages.

## Stage 0: MVP scaffold

Status: done.

Verification:

```bash
python scripts/smoke_test.py
```

Expected:

- BM25 retrieves the gold evidence.
- Workflow returns structured JSON.
- Location check passes.
- Combined reward is greater than 0.5.
- SQLite trace is written to `outputs/traces/smoke.sqlite`.

## Stage 1: Dataset schema conversion

Goal:

- Convert small subsets from MP-DocVQA and TAT-QA.
- Normalize them into `DocAgentSample`.
- Create document-level train/dev/test splits.

Initial target:

- 50-100 samples per dataset.
- `data/benchmark/train_sft.jsonl`
- `data/benchmark/dev_sft.jsonl`
- `data/benchmark/test_eval.jsonl`

Verification:

- Every sample has `qid`, `source`, `doc_id`, `question`, `answer`,
  `answer_type`, `evidence`, `verifiable`, and `split`.
- Every evidence block has `doc_id`, `block_id`, `block_type`, and `location`.

Smoke commands:

```bash
python scripts/build_smoke_benchmark.py
python scripts/eval_retrieval.py --input data/benchmark/smoke_eval.jsonl
```

## Stage 2: Retrieval evaluation

Goal:

- Implement retrieval ablations:
  - BM25-only
  - Query Rewrite + BM25
  - BM25 + Dense
  - BM25 + Dense + Reranker

Initial target:

- Use BM25-only first.
- Add dense/reranker only after schema is stable.

Metrics:

- Recall@5
- MRR@5

Verification:

- Evaluation script produces a JSON or CSV report under `outputs/eval/`.

## Stage 3: Traceable QA workflow

Goal:

- Replace the current heuristic answer policy with a Qwen3 inference adapter.
- Keep the local heuristic fallback for tests.
- Store workflow trace in SQLite.

Nodes:

- query_rewrite
- retrieve_evidence
- table_parse_and_calculate
- visual_review
- generate_answer
- check_format
- check_location
- repair_answer

Verification:

- A single sample can replay its full trace.
- Error cases can be categorized by retrieval, table, visual, generation,
  location, or format failure.

## Stage 4: MinerU integration

Goal:

- Parse real uploaded documents with MinerU.
- Parse MP-DocVQA image pages with PaddleOCR first, then optionally compare
  MinerU image parsing if installation and output quality are practical.
- Convert `content_list.json` or equivalent output into EvidenceBlock.

Verification:

- Parsed evidence blocks include text/table/image types.
- At least 20-30 real documents can pass the parse -> index -> QA flow.

## Stage 5: Qwen3 LoRA-SFT

Goal:

- Train the answer policy to use retrieved evidence and output structured JSON.

First run:

- Model: `/root/autodl-tmp/models/Qwen3-1.7B`
- Precision: `fp16` on RTX 3090 unless bf16 support is confirmed.
- Dataset: 200-500 examples for smoke test.

Metrics:

- JSON Pass Rate
- EM/F1
- Numeric Accuracy
- Location Accuracy
- Refusal Accuracy

Verification:

- Training logs and checkpoint exist.
- RAG-only vs SFT comparison is available.

Dataset construction smoke:

```bash
python scripts/build_sft_dataset.py \
  --input data/benchmark/tatqa_dev_subset.jsonl \
  --output data/benchmark/tatqa_sft_smoke.jsonl

python scripts/inspect_jsonl.py --input data/benchmark/tatqa_sft_smoke.jsonl --head 1
```

Before launching GPU training, inspect the installed ms-swift CLI in no-card
mode:

```bash
python scripts/inspect_swift_cli.py
python scripts/check_local_model.py --model /root/autodl-tmp/models/Qwen3-1.7B
```

First GPU smoke:

```bash
# Single GPU
CUDA_VISIBLE_DEVICES=0 bash scripts/train_sft_smoke.sh 2>&1 | tee outputs/logs/sft_smoke.log

# Two GPUs
CUDA_VISIBLE_DEVICES=0,1 bash scripts/train_sft_smoke.sh 2>&1 | tee outputs/logs/sft_smoke.log
```

The smoke script expects `config.json` under
`/root/autodl-tmp/models/Qwen3-1.7B` and runs transformers in offline mode.
Training scripts derive `NPROC_PER_NODE` from `CUDA_VISIBLE_DEVICES`, so
`0` means one process and `0,1` means two distributed processes.

## Stage 6: GRPO post-training

Goal:

- Optimize answer correctness, location correctness, and format compliance under
  the same retrieved evidence setting.

Rewards:

- `format_reward`
- `answer_reward`
- `location_reward`
- For samples with a gold evidence location, answer reward is gated by
  `location_reward`: a correct answer with the wrong cited evidence does not
  receive answer credit.

First run:

- 20-step smoke on 200 verifiable examples first.
- 100-step candidate run after reward variance and completion clipping are
  confirmed acceptable.
- Expand to 800+ only after reward code and ms-swift integration are stable.

Verification:

- SFT vs SFT+GRPO comparison is available.
- Reward hacking cases are logged.

Current MP-DocVQA retrieved-reader smoke:

```bash
python scripts/build_grpo_from_sft_dataset.py \
  --input data/benchmark/mp_docvqa_train_sft_retrieved_clean.jsonl \
  --output data/benchmark/mp_docvqa_train_grpo_retrieved_clean.jsonl

python scripts/audit_training_data.py \
  --input data/benchmark/mp_docvqa_train_grpo_retrieved_clean.jsonl \
  --output outputs/eval/mp_docvqa_train_grpo_retrieved_audit.json \
  --print-mode summary

python scripts/profile_sft_lengths.py \
  --input data/benchmark/mp_docvqa_train_grpo_retrieved_clean.jsonl \
  --thresholds 1024,2048,3072,4096

ADAPTER="outputs/checkpoints/qwen3-docagent-sft-mpdocvqa-retrieved-20260605_180454/v0-20260605-180519/checkpoint-155" \
DATASET="data/benchmark/mp_docvqa_train_grpo_retrieved_clean.jsonl" \
LIMIT=200 \
MAX_STEPS=20 \
MAX_PROMPT_TOKENS=4096 \
MAX_COMPLETION_LENGTH=256 \
bash scripts/train_trl_grpo_dual.sh
```

Current 100-step candidate:

```bash
ADAPTER="outputs/checkpoints/qwen3-docagent-sft-mpdocvqa-retrieved-20260605_180454/v0-20260605-180519/checkpoint-155" \
DATASET="data/benchmark/mp_docvqa_train_grpo_retrieved_clean.jsonl" \
LIMIT=200 \
MAX_STEPS=100 \
MAX_PROMPT_TOKENS=4096 \
MAX_COMPLETION_LENGTH=384 \
RUN_NAME="qwen3-docagent-trl-grpo-mpdocvqa-retrieved-100step-$(date +%Y%m%d_%H%M%S)" \
bash scripts/train_trl_grpo_dual.sh

ADAPTER="outputs/checkpoints/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-100step-20260606_100045" \
INPUT="data/benchmark/mp_docvqa_dev_sft_retrieved_clean.jsonl" \
OUTPUT="outputs/eval/sft_mpdocvqa_retrieved_grpo100_eval_1024.jsonl" \
SUMMARY_OUTPUT="outputs/eval/sft_mpdocvqa_retrieved_grpo100_eval_1024_summary.json" \
LIMIT=393 \
MAX_NEW_TOKENS=1024 \
bash scripts/eval_checkpoint_parallel.sh
```

Observed dev result for the 100-step candidate before the grounding gate:

- JSON/schema pass rate: 1.0 / 1.0
- Answer EM/F1: 0.5344 / 0.6127
- Location accuracy: 0.8906
- Mean reward under the pre-gated reward: 0.7458

After reward semantics change, recompute existing eval metrics before comparing
reward deltas:

```bash
python scripts/recompute_sft_eval_metrics.py \
  --input outputs/eval/sft_mpdocvqa_retrieved_full_eval_1024.jsonl \
  --output outputs/eval/sft_mpdocvqa_retrieved_full_eval_1024_grounded_reward.jsonl \
  --summary-output outputs/eval/sft_mpdocvqa_retrieved_full_eval_1024_grounded_reward_summary.json \
  --summary-template outputs/eval/sft_mpdocvqa_retrieved_full_eval_1024_summary.json
```

Current grounded 100-step candidate:

- Checkpoint:
  `outputs/checkpoints/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-grounded-100step-20260606_105535`
- JSON/schema pass rate: 1.0 / 1.0
- Answer EM/F1: 0.5369 / 0.6122
- Location accuracy: 0.9033
- Mean reward under the grounded reward: 0.7221
- Compared with SFT under the grounded reward: reward delta +4.23,
  17 improved, 9 regressed, 38 changed answers.

This candidate passes the current acceptance gate: location accuracy is above
the SFT retrieved-reader baseline while answer F1 and grounded mean reward also
improve.

Full-500 confirmation run:

- Checkpoint:
  `outputs/checkpoints/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-grounded-full500-100step-20260606_113406`
- Training used all 500 cleaned retrieved GRPO records with 100 steps.
- JSON/schema pass rate: 1.0 / 1.0
- Answer EM/F1: 0.5242 / 0.5999
- Location accuracy: 0.8957
- Mean reward under the grounded reward: 0.7114
- Compared with SFT under the grounded reward: reward delta +0.05,
  10 improved, 13 regressed, 40 changed answers.

This run does not replace the current grounded 100-step candidate because its
location accuracy is below the SFT baseline and below the selected 200-record
grounded GRPO run. Do not continue scaling or sweeping GRPO until the next stage
requires broader robustness experiments.

## Stage 7: VLM visual review ablation

Goal:

- Compare OCR-only vs OCR + VLM visual review on MP-DocVQA image pages first.
- Add TAT-DQA or M3DocVQA after the MP-DocVQA flow is complete.

Verification:

- Report Answer EM/F1 and visual subset accuracy.
- Keep failure cases for interview discussion.

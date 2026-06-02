# DocAgent Implementation Plan

This plan converts DocAgent 3.0 into staged engineering milestones. Each stage
has a concrete verification target before the next stage starts.

## Assumptions

- Local code lives in `D:\Projects\docagent`.
- GPU experiments will run on the lab server through git/ssh.
- The first training target is `Qwen/Qwen3-1.7B`.
- `Qwen3-4B` is an optional SFT comparison, not the first GRPO target.
- `Qwen2.5-VL` is only used as a visual review branch.
- MinerU is required for real uploaded documents and ScenarioSet, but public
  training datasets can use their own OCR/table annotations when sufficient.

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

- Convert small subsets from MP-DocVQA, TAT-QA, and InfographicVQA.
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

- Parse ScenarioSet and a small public subset with MinerU.
- Convert `content_list.json` or equivalent output into EvidenceBlock.

Verification:

- Parsed evidence blocks include text/table/image types.
- At least 20-30 real documents can pass the parse -> index -> QA flow.

## Stage 5: Qwen3 LoRA-SFT

Goal:

- Train the answer policy to use retrieved evidence and output structured JSON.

First run:

- Model: `Qwen/Qwen3-1.7B`
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

## Stage 6: GRPO post-training

Goal:

- Optimize answer correctness, location correctness, and format compliance under
  the same retrieved evidence setting.

Rewards:

- `format_reward`
- `answer_reward`
- `location_reward`

First run:

- 100-200 verifiable examples for smoke test.
- Expand to 800+ only after reward code and ms-swift integration are stable.

Verification:

- SFT vs SFT+GRPO comparison is available.
- Reward hacking cases are logged.

## Stage 7: VLM visual review ablation

Goal:

- Compare OCR-only vs OCR + VLM visual review on InfographicVQA.

Verification:

- Report Answer EM/F1 and visual subset accuracy.
- Keep failure cases for interview discussion.

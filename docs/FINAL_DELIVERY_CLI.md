# DocAgent Final Delivery CLI Guide

Updated: 2026-07-02

This guide describes the current local, CLI-only delivery surface for the
Phase 5 personal-use DocAgent MVP. It is the practical entry point for running
the implemented system without UI, cloud storage, VLM, new training, or formal
benchmark claims.

## Scope

Current delivery target:

```text
local file or existing doc_id
-> question / request
-> parser or persisted document lookup
-> Router
-> deterministic tool or local_fact_qa
-> answer, reasoning_summary, evidence_used, citations, tools_used, trace_path
```

Implemented local capabilities:

- CLI entry point: `scripts/docagent_cli.py`
- text file ingestion through `TextParserBackend`
- existing MinerU output ingestion through `--parser mineru_existing`
- MinerU API ingestion through `--parser mineru_api --live-api`
- MinerU output preservation for ordinary `*_content_list.json`,
  `*_content_list_v2.json` fallback, Markdown/resource inventory metadata,
  table HTML, table/image resource paths, captions, and nearby OCR text
- deterministic document statistics and page lookup
- deterministic extractive `document_summary`
- deterministic persisted-evidence `structured_extraction`
- deterministic `table_lookup` and traceable simple table calculations
- `local_fact_qa` wrapper around retrieval and AnswerPolicy
- AnswerPolicy compatibility for both the legacy
  `answer/evidence_location/evidence/reason` output schema and the candidate
  `answer/reasoning_summary/citation_block_ids/evidence_used` schema
- shared AnswerPolicy prompt v2 asks Qwen-style policies to return candidate
  citation block ids directly
- citation allowlist filtering for model-selected evidence block ids
- local final-evaluation subset preparation for TAT-QA dev and MP-DocVQA val
- local subset diagnostic report with JSON and Markdown summaries
- final subset AnswerPolicy baseline runner for server Qwen prompt-v2 smoke
- diagnostic AnswerPolicy baseline review gate for full artifacts or compact
  sync bundles
- diagnostic SFT candidate data builder from real-Qwen baseline failures
- single-command AnswerPolicy training-gate orchestration for server runs

Not included in the current local delivery:

- UI, FastAPI, Gradio, cloud storage, multi-user service
- multi-document QA beyond reserved `doc_id` / `source_document` fields
- multi-turn memory
- multilingual QA acceptance
- pixel-level VLM chart/image interpretation
- local MinerU CLI execution path
- accepted MP-DocVQA/TAT-QA final answer benchmark
- new SFT/GRPO training or training-quality claims

## Local Storage

Default local paths:

```text
SQLite database: outputs/docagent.db
CLI artifacts: outputs/cli/<run_id>/
Document cache: data/documents/
Final eval subset artifacts: outputs/final_eval/
```

All of these paths are local to the user machine. Generated outputs, raw
datasets, model weights, databases, logs, secrets, and document caches are not
intended for Git commits.

Each CLI run writes an artifact directory containing:

```text
result.json
summary.json
router_plan.json
trace.json
```

The top-level CLI JSON also includes `trace_path`, pointing to the local
`trace.json` artifact.

## CLI Contract

Main command:

```powershell
python scripts\docagent_cli.py --file <path> --question "<question>"
python scripts\docagent_cli.py --doc-id <doc_id> --question "<question>"
```

Required output fields for normal question runs:

```json
{
  "answer": "...",
  "reasoning_summary": "...",
  "evidence_used": [],
  "citations": [],
  "tools_used": [],
  "trace_path": "outputs/cli/<run_id>/trace.json"
}
```

Citation objects are normalized around these fields when available:

```json
{
  "doc_id": "...",
  "source_document": "...",
  "page": 1,
  "block_id": "...",
  "block_type": "text|table|image|page",
  "text_preview": "...",
  "table_id": "...",
  "image_id": "..."
}
```

`reasoning_summary` is a short user-facing explanation. It is not a hidden
chain-of-thought field.

When an AnswerPolicy returns candidate `citation_block_ids`, DocAgent filters
those ids to the retrieved evidence allowlist before constructing final
citations. Invalid model-selected ids are recorded in `citation_validation` and
are not emitted as final citations.

The prompt and local training-data builders now use the candidate citation
contract. Runtime output remains canonicalized by code before CLI artifacts are
written.

## Common Commands

List persisted documents:

```powershell
python scripts\docagent_cli.py --list-documents --db-path outputs\docagent.db
```

Ask an already ingested document:

```powershell
python scripts\docagent_cli.py `
  --db-path outputs\docagent.db `
  --doc-id <doc_id> `
  --question "What is the main conclusion?" `
  --output-dir outputs\cli
```

Ingest and ask a UTF-8 text file:

```powershell
python scripts\docagent_cli.py `
  --file data\example.txt `
  --question "Summarize the document." `
  --output-dir outputs\cli
```

Ingest a PDF using existing MinerU output:

```powershell
python scripts\docagent_cli.py `
  --file data\example.pdf `
  --parser mineru_existing `
  --mineru-output-dir outputs\mineru\example `
  --question "Which table supports the answer?" `
  --output-dir outputs\cli
```

Ingest a PDF through MinerU API:

```powershell
python scripts\docagent_cli.py `
  --file data\example.pdf `
  --parser mineru_api `
  --live-api `
  --mineru-env-file .secrets\mineru.env `
  --question "What is reported on page 1?" `
  --output-dir outputs\cli
```

The secret file is optional when `MINERU_TOKEN` is already exported in the
current shell. If `.secrets/mineru.env` exists, the CLI uses it by default.
The file should contain `MINERU_TOKEN=...`; `API_TOKEN=...` is also accepted
inside this MinerU-specific env file for compatibility. The file must stay
uncommitted.

Run the raw-PDF delivery smoke through MinerU API:

```powershell
python scripts\run_final_raw_pdf_smoke.py `
  --pdf-path data\example.pdf `
  --parser mineru_api `
  --live-api `
  --mineru-env-file .secrets\mineru.env `
  --run-id final_raw_pdf_mineru_api_cli_smoke
```

This smoke validates parser-to-CLI execution and artifact/citation contracts.
It is not a final answer-quality benchmark.

Materialize MP-DocVQA final-subset PDFs into MinerU-backed evidence:

```powershell
python scripts\prepare_mpdocvqa_evidence.py `
  --subset-root outputs\final_eval\mpdocvqa_val_subset `
  --output-dir outputs\final_eval\mpdocvqa_val_evidence `
  --live-api `
  --mineru-env-file .secrets\mineru.env `
  --sync-output-dir outputs\sync `
  --run-id mpdocvqa_evidence_smoke
```

This writes a local SQLite database plus `sample_evidence_manifest.jsonl`
mapping MP-DocVQA sample ids to the actual ingested DocAgent `doc_id` and
gold-page evidence blocks. The generated `summary.json` records `db_path`,
`document_root`, and `sample_evidence_manifest_path` for later AnswerPolicy
baseline runs. It is a MinerU/evidence-readiness diagnostic, not final
answer-quality benchmark acceptance.

If a batch run has transient MinerU/API download failures, retry only failed
documents while reusing the previous database and document root:

```powershell
python scripts\prepare_mpdocvqa_evidence.py `
  --subset-root outputs\final_eval\mpdocvqa_val_subset `
  --output-dir outputs\final_eval\mpdocvqa_val_evidence `
  --live-api `
  --mineru-env-file .secrets\mineru.env `
  --mineru-api-max-attempts 5 `
  --mineru-api-retry-delay-seconds 20 `
  --previous-run-dir outputs\final_eval\mpdocvqa_val_evidence\<previous_run_id> `
  --retry-failed-only `
  --sync-output-dir outputs\sync `
  --run-id mpdocvqa_evidence_retry_failed
```

Run the final subset AnswerPolicy baseline locally with the heuristic policy:

```powershell
python scripts\run_final_answer_policy_baseline.py `
  --answer-policy heuristic `
  --max-samples 5 `
  --output-dir outputs\final_eval\answer_policy_baseline_local `
  --sync-output-dir outputs\sync `
  --preserve-input-order
```

On a GPU server with Qwen available, use `--answer-policy base` and
`--base-model-path /root/autodl-tmp/models/Qwen3-1.7B`. This runner is a
diagnostic prompt-v2 baseline, not formal benchmark acceptance. With
`--sync-output-dir`, it writes a compact `outputs/sync/<run_id>/` bundle with
`result.json`, summaries, previews, failure samples, manifest, and log-tail
placeholders suitable for server result return.
TAT-QA table/calculation cases run deterministic table tools first and pass
the compact tool result into the AnswerPolicy prompt. MP-DocVQA manifest cases
remain skipped unless `--mpdocvqa-evidence-manifest` and `--mpdocvqa-db-path`
point to artifacts from `scripts\prepare_mpdocvqa_evidence.py`.

Recommended server-side single command for the Qwen baseline gate:

```powershell
python scripts\run_final_answer_policy_training_gate.py `
  --answer-policy base `
  --base-model-path /root/autodl-tmp/models/Qwen3-1.7B `
  --mpdocvqa-evidence-manifest outputs/final_eval/mpdocvqa_val_evidence/<run_id>/sample_evidence_manifest.jsonl `
  --mpdocvqa-db-path outputs/final_eval/mpdocvqa_val_evidence/mpdocvqa_evidence_api_full_subset_20260630/docagent.db `
  --sync-output-dir outputs\sync `
  --preserve-input-order
```

This runs the baseline, review, and optional SFT candidate-data generation in
one command. It only builds candidate SFT records when the review gate
recommends `sft_data_design_candidate`; it does not start training.

Review a full AnswerPolicy baseline artifact directory or compact sync bundle:

```powershell
python scripts\review_answer_policy_baseline.py `
  --run-dir outputs\sync\<run_id> `
  --output-dir outputs\final_eval\answer_policy_baseline_review
```

The review writes `review.json` and `review.md` with a diagnostic
`training_gate` recommendation. It does not start SFT/GRPO and does not mark
Qwen prompt quality or benchmark acceptance.

Build candidate SFT records after a real Qwen baseline has been reviewed:

```powershell
python scripts\build_answer_policy_sft_candidates.py `
  --baseline-run-dir outputs\sync\<run_id> `
  --output-dir outputs\final_eval\answer_policy_sft_candidates
```

The builder reconstructs prompt-v2 records for failed TAT-QA AnswerPolicy rows
using prepared local subset samples and compact tool results. It blocks
heuristic/fake non-Qwen baselines and writes candidate data only; it does not
start training.

Enable optional query planning:

```powershell
python scripts\docagent_cli.py `
  --doc-id <doc_id> `
  --question "What date is mentioned in the notice?" `
  --enable-query-planning `
  --query-planner-mode hybrid
```

Use the full model path only on a machine with the required model stack:

```powershell
python scripts\docagent_cli.py `
  --doc-id <doc_id> `
  --question "What is the answer and evidence?" `
  --full-model-path `
  --answer-policy base `
  --base-model-path /root/autodl-tmp/models/Qwen3-1.7B
```

The full model path is server/model-dependent. Local heuristic or dry-run
behavior must not be reported as real Qwen answer quality.

## Dataset Subset Preparation

Expected local inputs for the current final-evaluation subset workflow:

```text
data/benchmark/tatqa/tatqa_dataset_dev.json
data/benchmark/mp_docvqa/val/val-00001-of-00029.parquet
data/benchmark/mp_docvqa/val/val-00002-of-00029.parquet
```

Prepare both local subsets:

```powershell
python scripts\prepare_final_eval_subset.py `
  --dataset all `
  --tatqa-limit 80 `
  --mpdocvqa-target-qa-count 50 `
  --mpdocvqa-min-qa-count 30 `
  --mpdocvqa-max-qa-count 70 `
  --overwrite
```

Outputs:

```text
outputs/final_eval/tatqa_dev_subset/
outputs/final_eval/mpdocvqa_val_subset/
```

Run the local diagnostic report:

```powershell
python scripts\run_final_eval_subset.py `
  --dataset all `
  --run-id local_subset_full_diagnostic_report `
  --output-dir outputs\final_eval\local_subset_diagnostic
```

Diagnostic outputs:

```text
results.jsonl
summary.json
summary.md
preview.json
manual_review.md
```

The diagnostic report separates:

- evidence readiness
- deterministic tool answer quality
- attribution quality
- format quality
- failure taxonomy

This is local subset diagnostics only. It is not a formal MP-DocVQA/TAT-QA
benchmark and does not evaluate Qwen final answer quality.

## Current Diagnostic Snapshot

Latest local diagnostic run:

```text
run_id = local_subset_full_diagnostic_report
case_count = 135
passed_count = 85
failed_count = 50
pass_rate = 0.6296
answer_hit_rate = 0.1667
numeric_accuracy_rate = 0.2
citation_block_hit_rate = 1.0
failure_stage_distribution = tool_execution:23, answer_quality:27
failure_reason_distribution = table_lookup_unsupported:23, answer_miss:50
quality_status = diagnostic_only
benchmark_evaluation_status = not_started
```

Interpretation:

- evidence and citation packaging are locally inspectable;
- table attribution is stable on evaluated deterministic-tool cases;
- deterministic table answer quality is still weak;
- text and MP-DocVQA samples still require retrieval/MinerU evidence packs and
  model answer evaluation;
- formal benchmark status remains `not_started`.

## Image and Table Boundaries

Images:

- current baseline uses MinerU/OCR text, captions, nearby text, image metadata,
  and page/block location;
- no pixel-level VLM interpretation is implemented or accepted;
- if an answer requires visual pixels not present in OCR/caption/nearby text,
  the system should return a limitation or insufficient-evidence result.

Tables:

- table EvidenceBlocks keep `table_html`, caption/nearby text when available,
  page, block id, and table id;
- deterministic `table_lookup` and `simple_calculation` support simple
  row/column/value extraction, difference, sum, percentage change, and average
  where inputs can be traced;
- complex TAT-QA reasoning remains outside the current accepted quality claim.

## Status Rules

Use these status meanings for the final delivery track:

```text
implemented = code exists and local verification passed where applicable
accepted = required tests, server smoke, artifacts, and status updates are done
benchmark_evaluated = formal accepted-scope benchmark has run
not_started = no accepted implementation for this capability
```

Do not report:

- local diagnostics as `benchmark_evaluated`;
- mock/hash/heuristic tests as real BGE/Qwen evidence;
- existing MinerU output ingestion as accepted online raw-PDF OCR;
- dry-run output as final answer quality.

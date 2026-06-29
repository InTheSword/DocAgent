# DocAgent Final Delivery CLI Guide

Updated: 2026-06-29

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
- raw PDF MinerU local CLI wrapper with structured failure artifacts
- deterministic document statistics and page lookup
- deterministic extractive `document_summary`
- deterministic persisted-evidence `structured_extraction`
- deterministic `table_lookup` and traceable simple table calculations
- `local_fact_qa` wrapper around retrieval and AnswerPolicy
- local final-evaluation subset preparation for TAT-QA dev and MP-DocVQA val
- local subset diagnostic report with JSON and Markdown summaries

Not included in the current local delivery:

- UI, FastAPI, Gradio, cloud storage, multi-user service
- multi-document QA beyond reserved `doc_id` / `source_document` fields
- multi-turn memory
- multilingual QA acceptance
- pixel-level VLM chart/image interpretation
- accepted online MinerU OCR smoke from raw PDF
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

Attempt raw PDF parsing through an installed local MinerU CLI:

```powershell
python scripts\docagent_cli.py `
  --file data\example.pdf `
  --parser mineru `
  --parser-mode local_cli `
  --mineru-command mineru `
  --mineru-timeout-seconds 600 `
  --question "What is reported on page 1?" `
  --output-dir outputs\cli
```

This path requires a working MinerU executable outside the current project. If
MinerU is missing, times out, or exits nonzero, DocAgent writes a structured
`mineru_cli_result.json` failure artifact. That failure artifact is implemented
locally; it is not an accepted online OCR capability by itself.

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

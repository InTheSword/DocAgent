# DocAgent Final Delivery CLI Guide

Updated: 2026-07-02

This guide describes the current local, CLI-only delivery surface for the
Phase 5 personal-use DocAgent MVP. It is the practical entry point for running
the implemented system without UI, cloud storage, VLM, new training, or formal
benchmark claims.

For the current delivery status table and accepted evidence boundaries, see
`docs/FINAL_DELIVERY_REPORT.md`.

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
- audited AnswerPolicy SFT/GRPO training-pack preprocessing from train-split
  `DocAgentSample` JSONL input
- single-command AnswerPolicy training-gate orchestration for server runs
- local final-delivery readiness check for required files, CLI options, output
  fields, citation/evidence location fields, documentation boundaries, and
  deprecated PM handoff cleanup
- final delivery benchmark gate in `scripts/run_final_delivery_benchmark_gate.py`
  for server-side readiness, AnswerPolicy baseline, and MP-DocVQA full-workflow
  diagnostics with hash-checked local/sync manifests and without claiming
  formal benchmark acceptance

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

Run the local final-delivery readiness check:

```powershell
python scripts\check_final_delivery_readiness.py --run-id local_readiness
```

This check does not call MinerU, Qwen, BGE-M3, reranker, datasets, or training.
It verifies the local delivery pack contract: required files, user-facing CLI
options, required output fields, citation/evidence location fields for
text/table/image evidence, documentation boundaries, and removal of the
deprecated PM handoff document.

Run the final-delivery benchmark gate on a prepared server:

```powershell
python scripts\run_final_delivery_benchmark_gate.py `
  --run-id final_delivery_benchmark_gate_probe
```

The gate safely orchestrates the local readiness check, the final AnswerPolicy
baseline runner, and the MP-DocVQA full-workflow diagnostic runner. It writes
compact artifacts and sync bundles, keeps `formal_benchmark_acceptance=false`,
and does not start SFT/GRPO training.

Inspect a completed final-delivery benchmark gate artifact directory:

```powershell
python scripts\inspect_final_delivery_benchmark_gate.py `
  --run-dir outputs\final_eval\final_delivery_benchmark_gate\<run_id> `
  --sync-bundle-dir outputs\sync\<run_id> `
  --run-id final_delivery_benchmark_gate_review
```

This read-only check validates local and sync manifest hashes, summarizes step
statuses, extracts child-step metrics, reviews MP-DocVQA workflow component-use
signals, and verifies that benchmark/training safety flags remain false. It
does not call MinerU, Qwen, BGE-M3, reranker, datasets, or training. The review
itself writes `result.json`, `summary.json`, `summary.md`, and `manifest.json`.

Run the Phase 5I-B small-scenario final-answer-quality artifact contract:

Before running a model-backed answer-quality probe, inspect candidate document
contexts without calling models:

```powershell
python scripts\inspect_phase5i_document_contexts.py `
  --run-id phase5ib_context_inventory `
  --db-path outputs\docagent.db `
  --max-documents 20 `
  --sync-output-dir outputs\sync
```

This read-only inventory checks whether candidate `db_path` / `doc_id` pairs
have persisted retrievable EvidenceBlocks and whether the configured Phase
5I-B cases have basic page/keyword context support. It writes compact result,
summary, row, preview, manifest, and optional sync artifacts. It does not call
`docagent_cli.py`, MinerU, Qwen, BGE-M3, reranker, VLM, or training.

```powershell
python scripts\run_phase5i_answer_quality_benchmark.py `
  --run-id phase5ib_answer_quality_probe `
  --evaluate-final-answer `
  --full-model-path `
  --retriever-mode hybrid_rerank `
  --dense-backend bge `
  --dense-model-path /root/autodl-tmp/models/bge-m3 `
  --dense-device cuda:0 `
  --build-dense-index-if-missing `
  --reranker-backend cross_encoder `
  --reranker-model-path /root/autodl-tmp/models/bge-reranker-v2-m3 `
  --reranker-device cpu `
  --answer-policy base
```

This runner writes both the historical Phase 5I files and the Phase 5I-B
contract files: `metrics.json`, `predictions.jsonl`, `case_reports.jsonl`,
`failure_analysis.md`, `acceptance_report.json`, and
`training_candidates_raw.jsonl`, plus `manifest.json` with file sizes and
hashes for artifact review. Real Qwen/BGE/reranker execution is
server-required. The acceptance report keeps `formal_benchmark_acceptance=false`
and `validation_subset_used_for_training=false`; it is a small-scenario
answer-quality review contract, not leaderboard acceptance or training.
For `--full-model-path` or `--evaluate-final-answer`, the specified `--db-path`
and `--doc-id` must point to a persisted document with retrievable
EvidenceBlocks. If that document context is missing or empty, the runner writes
`status=blocked` artifacts and stops before calling `docagent_cli.py`, Qwen, or
the retrieval models.

Inspect a Phase 5I-B answer-quality artifact directory:

```powershell
python scripts\inspect_phase5i_answer_quality_artifacts.py `
  --run-dir outputs\benchmark\phase5i_answer_quality\<run_id> `
  --run-id phase5ib_answer_quality_review
```

This read-only check validates `manifest.json` hashes, required artifact
presence, safety flags, metrics/report consistency, and that
`training_candidates_raw.jsonl` is empty. It does not call models, create
training data, or claim formal benchmark acceptance.

Compare two Phase 5I-B answer-quality artifact directories, for example base
versus a candidate adapter, before promoting a checkpoint:

```powershell
python scripts\compare_phase5i_answer_quality_runs.py `
  --base-run-dir outputs\benchmark\phase5i_answer_quality\<base_run_id> `
  --candidate-run-dir outputs\benchmark\phase5i_answer_quality\<candidate_run_id> `
  --base-label base `
  --candidate-label adapter480 `
  --run-id phase5i_answer_quality_compare `
  --sync-output-dir outputs\sync
```

This read-only guard compares existing `phase5i_summary.json`, `metrics.json`,
and `case_reports.jsonl` files, writes case-level movement rows, and keeps
`used_training=false`, `validation_subset_used_for_training=false`, and
`formal_benchmark_acceptance=false`. It does not call Qwen, retrieval models,
or training. A candidate checkpoint should not be promoted from this comparison
alone; use it as a controlled contract signal before broader clean heldout or
workflow evaluation.

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

Build an audited train-split AnswerPolicy training-format pack:

```powershell
python scripts\build_answer_policy_training_pack.py `
  --input data\benchmark\my_training_samples.jsonl `
  --output-root outputs\training_prep\answer_policy_training_pack `
  --run-id answer_policy_training_pack_candidate
```

This writes `sft_train.jsonl`, `grpo_train.jsonl`, audit files, preview,
summary, and a hash manifest. By default it blocks non-train sample splits and
validation-like input paths such as `final_eval`; it does not start SFT/GRPO,
call Qwen, or promote validation subsets to training data.

Build a small AnswerPolicy v3 SFT-contract trial from TAT-QA train data:

```powershell
python scripts\build_answer_policy_v3_training_data.py `
  --tatqa-raw data\benchmark\tatqa\tatqa_dataset_train.json `
  --run-id answer_policy_v3_tatqa_trial
```

This writes `aligned_records.jsonl`, `sft_train.jsonl`, rejected-bucket JSONL
files, `preview.json`, `summary.json`, `summary.md`, and `manifest.json` under
`outputs\training_prep\answer_policy_v3\<run_id>\`. The assistant target uses
only `answer`, `supporting_refs`, `support_status`, and `reasoning_summary`.
Temporary `E#` refs are mapped back to internal citation metadata through
`EvidenceRefMap`; `block_id`, `doc_id`, and file paths are not model-generation
targets. The command does not start SFT/GRPO or use validation/final-eval data.

Build train-only TAT-QA insufficient-evidence records for Stage 2 mixing:

```powershell
python scripts\build_answer_policy_v3_insufficient_data.py `
  --tatqa-raw data\benchmark\tatqa\tatqa_dataset_train.json `
  --run-id answer_policy_v3_tatqa_insufficient `
  --limit 100
```

This writes the same v3 artifact shape, with `insufficient_evidence.jsonl` and
`sft_train.jsonl` containing `insufficient_confirmed` records. Each record pairs
a source question with a different-document decoy evidence board whose candidate
text does not contain the gold answer string, and the assistant target uses
`support_status=insufficient` with empty `supporting_refs`. It does not call
Qwen, start SFT/GRPO, or use validation/final-eval data.

For MP-DocVQA train data, first prepare a train-labeled page-window subset,
materialize evidence with MinerU API, then build v3 records from the evidence
manifest and SQLite DB:

```bash
python scripts/prepare_final_eval_subset.py \
  --dataset mpdocvqa \
  --mpdocvqa-parquet-dir /root/autodl-tmp/datasets/mp_docvqa/parquet_train \
  --mpdocvqa-parquet /root/autodl-tmp/datasets/mp_docvqa/parquet_train/train-00009-of-00029.parquet \
  --mpdocvqa-output-root outputs/training_prep/mpdocvqa_train_subset_v3 \
  --mpdocvqa-split train \
  --overwrite

python scripts/prepare_mpdocvqa_evidence.py \
  --subset-root outputs/training_prep/mpdocvqa_train_subset_v3 \
  --output-dir outputs/training_prep/mpdocvqa_train_evidence_v3 \
  --run-id mpdocvqa_train_evidence_v3 \
  --live-api \
  --mineru-env-file .secrets/mineru.env \
  --mineru-ocr \
  --max-documents 5 \
  --rebuild-evidence-blocks

python scripts/build_answer_policy_v3_training_data.py \
  --source mpdocvqa \
  --mpdocvqa-evidence-manifest outputs/training_prep/mpdocvqa_train_evidence_v3/mpdocvqa_train_evidence_v3/sample_evidence_manifest.jsonl \
  --mpdocvqa-db-path outputs/training_prep/mpdocvqa_train_evidence_v3/mpdocvqa_train_evidence_v3/docagent.db \
  --run-id answer_policy_v3_mpdocvqa_train_trial \
  --split train
```

Run a tiny server-only schema warmup SFT smoke after v3 records exist:

```bash
python scripts/run_answer_policy_v3_sft_warmup.py \
  --sft-input outputs/training_prep/answer_policy_v3/answer_policy_v3_tatqa_train80_20260704/sft_train.jsonl \
  --sft-input outputs/training_prep/answer_policy_v3/answer_policy_v3_mpdocvqa_train_splitfix2_20260704/sft_train.jsonl \
  --output-root outputs/training/answer_policy_v3_sft_warmup \
  --run-id answer_policy_v3_sft_warmup_smoke \
  --base-model-path /root/autodl-tmp/models/Qwen3-1.7B \
  --max-records 16 \
  --max-steps 1 \
  --max-length 1024 \
  --gradient-accumulation-steps 2 \
  --lora-rank 4 \
  --lora-alpha 8 \
  --sync-output-dir outputs/sync
```

This command starts a small PEFT LoRA training smoke. It verifies the v3
schema and training path only; it does not claim final answer-quality
improvement, formal benchmark acceptance, GRPO, or validation-subset training.
The in-repo PEFT runner is a minimal schema-smoke path; use `ms-swift` as the
preferred backend for later expanded SFT experiments after server package
preflight and explicit approval for any installation.

Run a tiny checkpoint diagnostic over the warmup adapter:

```bash
python scripts/eval_answer_policy_v3_sft_checkpoint.py \
  --sft-input outputs/training/answer_policy_v3_sft_warmup/answer_policy_v3_sft_warmup_smoke_20260704/warmup_train.jsonl \
  --adapter-path outputs/training/answer_policy_v3_sft_warmup/answer_policy_v3_sft_warmup_smoke_20260704/adapter \
  --base-model-path /root/autodl-tmp/models/Qwen3-1.7B \
  --output-root outputs/training_eval/answer_policy_v3_sft_checkpoint \
  --run-id answer_policy_v3_checkpoint_eval_smoke \
  --limit 4 \
  --sync-output-dir outputs/sync
```

This checks JSON/schema validity, `support_status`, legal `supporting_refs`,
positive evidence-ref hits, and answer exact match on a small smoke set. It
does not start training or claim final checkpoint quality.

Prepare ms-swift SFT artifacts from the same v3 records:

```bash
python scripts/run_answer_policy_v3_msswift_sft.py \
  --sft-input outputs/training_prep/answer_policy_v3/answer_policy_v3_tatqa_train80_20260704/sft_train.jsonl \
  --sft-input outputs/training_prep/answer_policy_v3/answer_policy_v3_mpdocvqa_train_splitfix2_20260704/sft_train.jsonl \
  --output-root outputs/training/answer_policy_v3_msswift_sft \
  --run-id answer_policy_v3_msswift_dry_run \
  --base-model-path /root/autodl-tmp/models/Qwen3-1.7B \
  --max-records 16 \
  --max-steps 1 \
  --max-length 1024 \
  --gradient-accumulation-steps 2 \
  --lora-rank 4 \
  --lora-alpha 8 \
  --sync-output-dir outputs/sync
```

The command above does not start training. It validates v3 records, writes
`swift_train.jsonl`, records the exact `swift sft` command, and preserves the
same train-only / no-validation-subset safety flags. Add `--execute` only for a
controlled server smoke.

Build an audited Stage 2 mixed pack before a short SFT run:

```bash
python scripts/build_answer_policy_v3_mixed_sft_pack.py \
  --tatqa-sft outputs/training_prep/answer_policy_v3/answer_policy_v3_tatqa_train80_20260704/sft_train.jsonl \
  --mpdocvqa-sft outputs/training_prep/answer_policy_v3/answer_policy_v3_mpdocvqa_train_splitfix2_20260704/sft_train.jsonl \
  --insufficient-sft outputs/training_prep/answer_policy_v3/answer_policy_v3_tatqa_insufficient/sft_train.jsonl \
  --output-root outputs/training_prep/answer_policy_v3_mixed_sft \
  --run-id answer_policy_v3_mixed_stage2 \
  --target-records 64 \
  --mpdocvqa-ratio 0.5 \
  --tatqa-ratio 0.4 \
  --insufficient-ratio 0.1 \
  --sync-output-dir outputs/sync
```

The mixed pack builder never duplicates records to force ratios. If MP-DocVQA
or insufficient records are unavailable, it records `shortage_counts` and
`backfill_counts` in `summary.json` before writing `sft_train.jsonl`.

Run a controlled short ms-swift SFT smoke from the mixed pack:

```bash
python scripts/run_answer_policy_v3_msswift_sft.py \
  --sft-input outputs/training_prep/answer_policy_v3_mixed_sft/answer_policy_v3_mixed_stage2/sft_train.jsonl \
  --output-root outputs/training/answer_policy_v3_msswift_sft \
  --run-id answer_policy_v3_msswift_stage2_short \
  --base-model-path /root/autodl-tmp/models/Qwen3-1.7B \
  --max-records 64 \
  --max-steps 3 \
  --max-length 1024 \
  --gradient-accumulation-steps 4 \
  --lora-rank 8 \
  --lora-alpha 16 \
  --sync-output-dir outputs/sync \
  --execute
```

This is still a short training-chain smoke. It does not claim benchmark
acceptance, final model quality, or GRPO readiness.

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

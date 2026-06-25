# Phase 5 MVP Acceptance

## MVP Scope

Phase 5 targets a personal-use DocAgent MVP:

```text
PDF or already ingested document
-> question
-> task routing
-> deterministic document tool or local_fact_qa workflow
-> structured answer
-> citations
-> trace path
```

The MVP should support job-search demonstration and personal document QA. It is
not a formal benchmark phase.

## Non-goals

Do not include these unless explicitly approved later:

- Candidate-ID Reader.
- Full GRPO E2E by default.
- Model training.
- AnswerPolicy prompt changes as the main solution.
- Candidate answer extraction rule tuning.
- External VLM or local VLM image understanding.
- Heavy UI or multi-user service.
- Large framework migration.
- Cloud vector database integration.
- Formal benchmark optimization.

## Required CLI Behavior

Future CLI path:

```text
scripts/docagent_cli.py
```

Target command for already ingested documents:

```bash
python scripts/docagent_cli.py \
  --doc-id some_doc_id \
  --question "How many tables are in this document?"
```

Target command for file input:

```bash
python scripts/docagent_cli.py \
  --file path/to/document.pdf \
  --question "How many tables are in this document?"
```

Minimum CLI behavior:

- accept `--doc-id` for already ingested documents;
- accept `--file` as a CLI contract; Phase 5F-2 supports new UTF-8 `.txt`
  file ingestion through `DocumentIngestionService`, reuses an
  already-ingested SQLite document by file SHA when possible, and returns
  structured ingestion errors for unsupported or unavailable parser backends;
- classify the question into a supported task type;
- call deterministic document tools for deterministic tasks;
- call the existing local fact QA workflow for specific fact questions;
- write a trace artifact;
- print one JSON object to stdout;
- return non-zero status only for real execution errors.

Phase 5A does not implement this CLI.

## Required Output JSON Shape

Target success output:

```json
{
  "status": "success",
  "doc_id": "some_doc_id",
  "task_type": "document_statistics",
  "answer": "The document contains 12 pages, 5 tables, and 3 image or figure regions.",
  "citations": [
    {
      "page": 1,
      "block_id": "optional",
      "text_preview": "optional"
    }
  ],
  "tools_used": ["count_pages", "count_tables", "count_images"],
  "trace_path": "outputs/traces/..."
}
```

Target failure output:

```json
{
  "status": "failed",
  "doc_id": "some_doc_id",
  "task_type": "local_fact_qa",
  "answer": "",
  "citations": [],
  "tools_used": [],
  "trace_path": "outputs/traces/...",
  "error": {
    "type": "tool_unavailable",
    "message": "Required tool is not available."
  }
}
```

Required top-level fields:

```text
status
doc_id
task_type
answer
citations
tools_used
trace_path
```

Optional fields:

```text
router
supporting_evidence_ids
structured_result
warnings
error
```

## Required Trace Behavior

Trace artifacts must record:

- input `doc_id` and question;
- router decision and confidence;
- selected tools;
- deterministic tool inputs and compact outputs;
- retrieval mode and selected evidence ids for `local_fact_qa`;
- final answer JSON;
- error details when failed.

SQLite trace reuse:

- existing `TraceRepository` can persist `qa_runs` and `tool_traces`;
- Phase 5 may add a JSON trace artifact wrapper if needed, but should not
  replace existing SQLite trace without a reason.

Trace output must not store full documents or sensitive absolute local paths by
default.

## Required Supported Question Types

Initial MVP support:

```text
local_fact_qa
document_statistics
page_lookup
structured_extraction
document_summary
```

`table_lookup_or_calculation` may be classified by the router before a mature
table tool exists. Until the tool exists, it may fall back to `local_fact_qa`
with a warning.

Phase 5C implements the rule-first single-step Router / Planner for:

```text
local_fact_qa
table_lookup_or_calculation
document_statistics
page_lookup
structured_extraction
document_summary
```

The router returns schema-valid planning decisions only. It does not execute
tools, generate summaries, wrap `local_fact_qa`, or write final CLI trace
artifacts.

## Minimum Smoke Tests

Phase 5B/P0 implementation should add or reuse smoke tests for:

- count pages on an ingested fixture;
- count blocks on an ingested fixture;
- count tables on an ingested fixture containing a table block;
- count images on an ingested fixture containing image/chart blocks;
- get page text for a known page;
- list pages for an ingested fixture;
- JSON output schema validity;

Trace artifact creation is not part of Phase 5B P0 deterministic document
tools. It is deferred to Router / CLI / MVP integration unless an existing
wrapper is reused without functional expansion.

## Minimum Regression Categories

Phase 5 MVP regression should cover:

```text
document_statistics
page_lookup
structured_extraction
local_fact_qa
document_summary
unsupported visual_pixel_qa boundary
```

Useful existing tests to keep green:

- `tests/test_document_registry.py`
- `tests/test_document_ingestion.py`
- `tests/test_mineru_converter.py`
- `tests/test_ingestion_quality_report.py`
- `tests/test_sqlite_trace.py`
- `tests/test_query_document_smoke_backends.py`
- `tests/test_evidence_packing.py`

## Known Limitations

- No VLM or pixel-level visual reasoning in Phase 5.
- Image/chart answers only use OCR, captions, nearby text, and metadata.
- Table lookup is not yet a typed row/column engine.
- `document_summary` needs a bounded summarization strategy before acceptance.
- `scripts/query_document.py` is a useful existing QA entrypoint, but it is not
  the final unified MVP CLI.
- Existing local fact QA quality is limited by candidate answer extraction and
  candidate span construction, as shown by Phase 4D-C.

## Exit Criteria For Phase 5A

Phase 5A is complete when:

- `docs/PHASE5_ACTIVE_PLAN.md` exists and preserves the provided plan;
- `docs/PHASE5_ROUTER_CONTRACT.md` exists;
- `docs/PHASE5_TOOL_INVENTORY.md` exists;
- `docs/PHASE5_MVP_ACCEPTANCE.md` exists;
- Phase 4D-C is recorded as accepted;
- Phase 4D-D is recorded as deferred;
- Phase 5 is recorded as active;
- no behavior-changing code is modified;
- lightweight documentation or existing tests pass.

## Exit Criteria For Phase 5B

Phase 5B P0 deterministic document tools are complete when:

- `docagent/tools/document_tools.py` exposes `count_pages`, `count_blocks`,
  `count_tables`, `count_images`, `get_page_text`, and `list_pages`;
- tools read from `DocumentRepository`, `documents.page_count`, and persisted
  `EvidenceBlock` payloads;
- tool outputs are JSON-serializable dicts;
- missing documents and missing pages return structured errors;
- page inputs and outputs use 1-based page numbers;
- text previews are capped;
- focused tests cover normal counts, page lookup, list pages, JSON
  serialization, and structured errors;
- Router, `scripts/docagent_cli.py`, final trace artifacts, `document_summary`,
  `table_lookup`, and `simple_calculation` remain deferred.

Next implementation target:

```text
Phase 5C Router / Planner -> accepted
```

## Exit Criteria For Phase 5C

Phase 5C Router / Planner is complete when:

- `docagent/router/rule_router.py` provides a rule-first single-step planner;
- `docagent/router/schemas.py` validates supported task types, selected tools,
  confidence range, warning fields, and the Phase 5 visual boundary;
- router input supports `doc_id`, `question`, `available_tools`, optional
  `document_profile`, and optional `options`;
- router output includes `task_type`, `selected_tools`, retrieval/full-scan
  flags, table/calculation flags, `requires_visual_understanding`,
  `target_evidence_types`, `query_rewrite`, `confidence`, `reason`,
  `fallback_used`, and `warnings`;
- external LLM fallback is disabled by default and no external API is called;
- unsupported `visual_pixel_qa` questions fall back to OCR/caption
  `local_fact_qa` when available, otherwise return a structured router error;
- complex query decomposition is explicitly deferred via warning;
- at least 30 fixed router cases pass.

Current next targets:

```text
Phase 5D local_fact_qa wrapper -> accepted
Phase 5D-S local_fact_qa smoke runner -> accepted
Phase 5D-S server real-model smoke -> accepted
Phase 5F-1 unified CLI MVP -> accepted
Phase 5F-1 server CLI smoke -> accepted
Phase 5F-2 file-to-answer ingestion integration -> accepted
Phase 5F-2 server file-to-answer smoke -> accepted
Phase 5F-3 MinerU-backed file-to-answer implementation -> accepted
Phase 5F-3 server smoke -> accepted
Phase 5C-2 LLM-assisted Router fallback -> not_started
Phase 5F full CLI acceptance -> not_started
```

## Exit Criteria For Phase 5D

Phase 5D local_fact_qa tool wrapper is complete when:

- `docagent/tools/local_fact_qa.py` exposes a callable `local_fact_qa` tool;
- the tool accepts `doc_id`, `question`, optional `router_plan`, and optional
  options such as `top_k`, `dry_run`, and `trace_path`;
- the real path reuses `run_qa_workflow`, `DocumentRepository`, AnswerPolicy,
  retrieval/evidence context logic, and optional `TraceRepository`;
- the default local path uses `HeuristicAnswerPolicy` and does not load a large
  model unless the caller injects one;
- dry-run mode does not generate an answer and is marked with
  `dry_run_no_answer_generated`;
- fake workflow injection is supported for wrapper-level tests without
  pretending to validate real QA quality;
- outputs are JSON-serializable and include `citations`,
  `supporting_evidence_ids`, `tools_used`, and `trace_path`;
- missing document, empty question, missing evidence, and workflow failure
  return structured errors;
- no CLI, external LLM API, VLM, training, table lookup, calculation, or
  document summary is implemented in Phase 5D.

## Exit Criteria For Phase 5D-S

Phase 5D-S local fact QA smoke support is complete when:

- `scripts/run_phase5d_local_fact_qa_smoke.py` can run `local_fact_qa` over an
  already-ingested SQLite document;
- it supports `--db-path`, `--doc-id`, `--question` or `--questions-jsonl`,
  `--output-dir`, `--dry-run`, `--limit`, `--answer-policy`,
  `--retrieval-config`, `--workflow-config`, and `--evidence-packing`;
- it writes `summary.json`, `summary.md`, `results.jsonl`, and `preview.json`
  under `outputs/smoke/phase5d_local_fact_qa/<run_id>/`;
- output rows include `doc_id`, `question`, `status`, `answer`, `citations`,
  `supporting_evidence_ids`, `tools_used`, `run_id`, `trace_path`, warnings,
  and structured errors;
- missing db paths, missing doc ids, missing questions, and tool errors are
  recorded as structured failures rather than hidden by empty SQLite creation;
- dry-run and fixture tests are explicitly documented as not validating real QA
  quality;
- server real-model smoke has passed on server artifacts and is accepted as
  execution stability evidence, not benchmark-level answer quality.

Phase 5D-S does not implement final CLI trace artifact creation. Trace artifact
creation is deferred to Router / CLI / MVP integration unless an existing
wrapper is reused without functional expansion.

Accepted Phase 5D-S server smoke evidence:

```text
db_path = outputs/docagent.db
doc_id = c1fc1c5e040ec894
dry_run_run_id = phase5d_local_fact_qa_20260624_155343_e1eac210
real_model_run_id = phase5d_local_fact_qa_20260624_155345_4076f226
real_model_summary = outputs/smoke/phase5d_local_fact_qa/phase5d_local_fact_qa_20260624_155345_4076f226/summary.json
real_model_results = outputs/smoke/phase5d_local_fact_qa/phase5d_local_fact_qa_20260624_155345_4076f226/results.jsonl
real_model_preview = outputs/smoke/phase5d_local_fact_qa/phase5d_local_fact_qa_20260624_155345_4076f226/preview.json
status = success
question_count = 3
completed_count = 3
failed_count = 0
used_dry_run = false
used_real_workflow = true
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
warning = evidence_packing_option_deferred_to_workflow
```

The warning does not block smoke acceptance; it only records that the
`evidence_packing` option is handled by the existing workflow path.

Real-model result preview:

```text
Q1: What is this document about?
A1: The Cigarette Industry in India
citations_count = 3
supporting_evidence_ids_count = 3

Q2: What date is mentioned in this document?
A2: 2000-01
citations_count = 5
supporting_evidence_ids_count = 5

Q3: What amount or total is mentioned in this document?
A3: 10
citations_count = 5
supporting_evidence_ids_count = 5
```

Current next targets:

```text
Phase 5E document_summary -> not_started
Phase 5F-1 unified CLI MVP -> accepted
Phase 5F-1 server CLI smoke -> accepted
Phase 5F-2 file-to-answer ingestion integration -> accepted
Phase 5F-2 server file-to-answer smoke -> accepted
Phase 5F-3 MinerU-backed file-to-answer implementation -> accepted
Phase 5F-3 server smoke -> accepted
Phase 5C-2 LLM-assisted Router fallback -> not_started
Phase 5F full CLI acceptance -> not_started
Phase 5G multi-task regression -> not_started
```

## Exit Criteria For Phase 5F-1

Phase 5F-1 Unified CLI MVP is implemented when:

- `scripts/docagent_cli.py` exists;
- CLI supports `--db-path`, `--doc-id`, `--file`, `--question`,
  `--output-dir`, `--dry-run`, `--list-documents`, and `--limit`;
- `--list-documents` prints one JSON object and includes `doc_id`,
  original name or file path, `page_count`, parse/index status, and timestamps
  when present;
- `--doc-id + --question` checks document existence, calls the Phase 5C Router,
  dispatches deterministic document tools for `document_statistics`, dispatches
  page tools for `page_lookup`, and dispatches Phase 5D `local_fact_qa`;
- `--file + --question` is part of the CLI contract. Current support is
  partial: already-ingested files can be reused by SHA; otherwise the CLI
  returns structured `file_ingestion_unavailable` and points users to
  `scripts/ingest_document.py`;
- unsupported task types return structured errors:
  `document_summary_not_implemented`, `table_lookup_not_implemented`, or
  `structured_extraction_not_implemented`;
- stdout is a single JSON object and every QA run writes
  `result.json`, `summary.json`, `router_plan.json`, and `trace.json` under
  `outputs/cli/<run_id>/`;
- summary artifacts record that external API, VLM, training, and full E2E are
  not used.

Phase 5F-1 does not implement Phase 5E document_summary, LLM-assisted Router
fallback, table lookup, simple calculation, VLM, training, full GRPO E2E,
AnswerPolicy prompt changes, or candidate answer extraction changes.

Phase 5F-1 is accepted after the server CLI smoke below. This acceptance
validates execution stability, not benchmark-level answer quality.

Accepted Phase 5F-1 server CLI smoke evidence:

```text
branch = codex/phase5f1-unified-cli-mvp
commit = b7e92c89908ce57517f145e18cd6ca1b702a300e
db_path = outputs/docagent.db
doc_id = c1fc1c5e040ec894
list_documents_run_id = docagent_cli_20260625_035337_52161dae
list_documents_status = success
list_documents_document_count = 2
document_statistics_run_id = docagent_cli_20260625_035423_8cea1735
document_statistics_status = success
document_statistics_task_type = document_statistics
document_statistics_tools_used = count_pages
document_statistics_answer = The document contains 5 pages.
page_lookup_run_id = docagent_cli_20260625_035527_52de8e1f
page_lookup_status = success
page_lookup_task_type = page_lookup
page_lookup_tools_used = get_page_text
page_lookup_citations_count = 1
local_fact_qa_dry_run_id = docagent_cli_20260625_035552_54cc8822
local_fact_qa_dry_run_status = success
local_fact_qa_dry_run_warning = dry_run_no_answer_generated
local_fact_qa_real_run_id = docagent_cli_20260625_035621_145b69a9
local_fact_qa_real_status = success
local_fact_qa_real_tool_run_id = 341437e6-7976-4a2f-a7b5-2dac762960d0
file_missing_run_id = docagent_cli_20260625_035702_766dcb4a
file_missing_status = error
file_missing_error = file_not_found
artifact_root = outputs/cli_smoke
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
acceptance_boundary = execution stability, not benchmark-level answer quality
```

Known Phase 5F-1 limitations:

```text
--file + --question is partial for non-text inputs: CLI contract and
existing-file SHA reuse exist, and Phase 5F-2 adds new .txt ingestion, but
new PDF/MinerU ingestion through docagent_cli remains not_started.
local_fact_qa real workflow executed successfully, but answer quality is
unstable. The server date question returned an irrelevant evidence text prefix
instead of a date.
Page metadata consistency needs audit: list-documents reports page_count = 5
for doc_id c1fc1c5e040ec894 while local_fact_qa citations include page 24.
This may reflect a documents.page_count vs evidence block page-number mismatch
or source/page-window metadata semantics.
```

## Exit Criteria For Phase 5F-2

Phase 5F-2 File-to-answer ingestion integration is accepted when:

- `scripts/docagent_cli.py --file <path> --question <question>` can ingest a
  new lightweight UTF-8 `.txt` file through `DocumentIngestionService`;
- ingestion reuses `DocumentRegistry`, `DocumentRepository`, and existing
  SQLite / EvidenceBlock persistence;
- successful file ingestion returns a generated `doc_id` plus
  `source.was_ingested = true` and `source.reused_existing = false`;
- a second run over the same file reuses the existing SHA-matched document and
  returns `source.was_ingested = false` and `source.reused_existing = true`;
- after ingestion, the CLI calls the Phase 5C Router and dispatches to
  deterministic document tools or Phase 5D `local_fact_qa`;
- failed file ingestion returns structured errors such as `file_not_found`,
  `parser_backend_unavailable`, `unsupported_file_type`, or
  `file_ingestion_failed`;
- stdout remains one JSON object and QA runs still write `result.json`,
  `summary.json`, `router_plan.json`, and `trace.json`;
- `summary.json` records `used_file_ingestion`,
  `reused_existing_document`, `ingestion_status`, `ingestion_error`,
  `used_router`, `used_external_api`, `used_vlm`, `used_training`, and
  `used_full_e2e`;
- `page_metadata_inconsistent` is a non-blocking warning when citation pages
  exceed `documents.page_count`.

Phase 5F-2 does not implement MinerU-backed PDF ingestion inside
`docagent_cli.py`; PDF/image inputs without a configured CLI parser backend
return structured `parser_backend_unavailable`. Phase 5E document_summary,
LLM-assisted Router fallback, table lookup, simple calculation, VLM, training,
full GRPO E2E, AnswerPolicy prompt changes, and candidate answer extraction
changes remain out of scope.

Accepted Phase 5F-2 server file-to-answer smoke evidence:

```text
branch = codex/phase5f2-file-ingestion-cli
implementation_commit = 0c9d0842d7a9ac3d949f3fa990cb91dd0ab4c092
db_path = outputs/docagent_phase5f2_smoke.db
doc_id = b108d4d188313393
source_file = /tmp/docagent_phase5f2_smoke.txt
stats_log = outputs/logs/phase5f2_file_stats.json
stats_run_id = docagent_cli_20260625_071021_e8424977
stats_status = success
stats_task_type = document_statistics
stats_tools_used = count_pages
stats_answer = The document contains 1 pages.
stats_was_ingested = true
stats_reused_existing = false
stats_ingestion_status = parsed
stats_page_count = 1
stats_block_count = 1
stats_index_status = not_started
stats_structure_quality = passed
fact_dry_run_log = outputs/logs/phase5f2_file_fact_dry_run.json
fact_dry_run_id = docagent_cli_20260625_071021_4e422db6
fact_status = success
fact_task_type = local_fact_qa
fact_tools_used = local_fact_qa
fact_was_ingested = false
fact_reused_existing = true
fact_warning = dry_run_no_answer_generated
artifact_root = outputs/cli_smoke
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
acceptance_boundary = lightweight .txt execution stability, not benchmark answer quality
```

Known accepted limitations:

```text
Server smoke validates lightweight UTF-8 .txt file-to-answer execution
stability, not benchmark answer quality.
Current accepted file ingestion support covers UTF-8 .txt through
TextParserBackend.
At Phase 5F-2 acceptance time, PDF/MinerU-backed file-to-answer through
docagent_cli was not yet accepted; Phase 5F-3 later accepted existing MinerU
output-backed execution.
local_fact_qa answer quality remains a separate known limitation.
Dense index is not built in the lightweight smoke; index_status may remain
not_started.
Phase 5E document_summary, Phase 5C-2 LLM-assisted Router fallback, and
Phase 5G multi-task regression remain not_started.
```

## Exit Criteria For Phase 5F-3

Phase 5F-3 MinerU-backed file-to-answer full-chain smoke is accepted when:

- `scripts/docagent_cli.py --file <document> --question <question>` can use
  existing MinerU output through `--parser mineru_existing` and
  `--mineru-output-dir` / `--mineru-output`;
- ingestion reuses `DocumentRegistry`, `DocumentIngestionService`,
  `DocumentRepository`, SQLite EvidenceBlocks, and page documents;
- successful file ingestion returns a generated or reused `doc_id`,
  `source.type = file`, `source.was_ingested`, `source.reused_existing`, and
  `source.ingestion_status`;
- after ingestion, the CLI calls the Phase 5C Router and dispatches to
  deterministic document tools, page lookup, or `local_fact_qa` dry-run;
- summary-like dry-run fallback may execute `local_fact_qa` when
  `document_summary` is unavailable; the top-level `task_type` records
  `local_fact_qa` while `router_plan.task_type` preserves
  `document_summary`;
- missing parser/MinerU support returns structured errors such as
  `parser_backend_unavailable`, `file_ingestion_failed`,
  `unsupported_file_type`, or `document_registration_failed`;
- stdout remains one JSON object and artifacts are written under
  `outputs/cli/<run_id>/`;
- metadata consistency records `documents.page_count`, page document count,
  max evidence page, and max citation page, with
  `page_metadata_inconsistent` as a warning only.

Local implementation evidence:

```text
branch = codex/phase5f3-mineru-file-cli-smoke
tested_file_type = pdf
tested_sample_path = data/real_documents/globocan_africa_2022/source/original.pdf
tested_mineru_output = data/real_documents/globocan_africa_2022/mineru_raw
tested_doc_id = fe3465edd3da60d2
tested_status = success
tested_task_type = document_statistics
tested_tools_used = count_pages
tested_answer = The document contains 2 pages.
tested_page_count = 2
tested_block_count = 57
tested_metadata_consistency = ok
tested_local_fact_qa_dry_run_task_type = local_fact_qa
tested_local_fact_qa_dry_run_router_task_type = document_summary
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
```

Accepted server smoke evidence:

```text
status = success
implementation_commit = 3eaf488cd7870af2e64dcd74f0f807edd8a1cb01
sample_path = data/real_documents/globocan_africa_2022/source/original.pdf
mineru_output = data/real_documents/globocan_africa_2022/mineru_raw
doc_id = fe3465edd3da60d2
stats_artifact = outputs/logs/phase5f3_file_stats.json
stats_status = success
stats_task_type = document_statistics
stats_answer = The document contains 2 pages.
stats_tools_used = count_pages
stats_was_ingested = true
stats_reused_existing = false
stats_ingestion_status = parsed
stats_parser = mineru_existing
stats_parser_mode = parse_existing
stats_page_count = 2
stats_block_count = 57
stats_block_type_counts = image:6, table:5, text:46
stats_structure_quality = passed_with_warnings
stats_metadata_consistency = ok
page_lookup_artifact = outputs/logs/phase5f3_file_page_lookup.json
page_lookup_status = success
page_lookup_task_type = page_lookup
page_lookup_tools_used = get_page_text
page_lookup_was_ingested = false
page_lookup_reused_existing = true
page_lookup_ingestion_status = reused_existing
page_lookup_metadata_consistency = ok
fact_dry_run_artifact = outputs/logs/phase5f3_file_fact_dry_run.json
fact_dry_run_status = success
fact_dry_run_task_type = local_fact_qa
fact_dry_run_router_task_type = document_summary
fact_dry_run_tools_used = local_fact_qa
fact_dry_run_was_ingested = false
fact_dry_run_reused_existing = true
fact_dry_run_ingestion_status = reused_existing
fact_dry_run_metadata_consistency = ok
fact_dry_run_warnings = file_reused_existing_doc_id, tool_unavailable, fallback_to_local_fact_qa, router_plan_task_type_not_local_fact_qa, dry_run_no_answer_generated
artifact_root = outputs/cli_smoke
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
acceptance_boundary = existing MinerU output-backed execution smoke, not online MinerU OCR execution or benchmark answer quality
```

Phase 5F-3 does not implement Phase 5E document_summary, LLM-assisted Router
fallback, table lookup, simple calculation, VLM, training, full GRPO E2E,
AnswerPolicy prompt changes, or candidate answer extraction changes.

Accepted limitations:

```text
Phase 5F-3 accepts existing MinerU output-backed file-to-answer execution.
Online MinerU OCR/parser execution from raw PDF remains a later task.
Router correctly classifies "What is this document about?" as document_summary,
but Phase 5E document_summary is not implemented, so CLI falls back to
local_fact_qa dry-run.
local_fact_qa answer quality is not benchmark-validated by this smoke.
The GLOBOCAN sample structure_quality is passed_with_warnings.
```

## Exit Criteria For Phase 5 MVP

The MVP is accepted when:

- `scripts/docagent_cli.py` exists;
- CLI supports `--doc-id` for already ingested documents;
- deterministic P0 tools work without LLM;
- router supports the initial task taxonomy;
- local_fact_qa path reuses existing hybrid RAG and trace infrastructure;
- outputs match the required JSON shape;
- citations are assembled from document/page/block metadata;
- trace artifacts are written;
- minimum smoke tests and multi-task regression pass;
- known limitations are documented.

## Phase 5B Minimal Implementation Plan

Phase 5B should implement only deterministic P0 tools:

```text
count_pages
count_blocks
count_tables
count_images
get_page_text
list_pages
```

Recommended implementation shape:

- add a small document tools module under `docagent/tools/` or a focused
  `docagent/document_tools/` package;
- read from `DocumentRepository` and existing `EvidenceBlock` payloads;
- return JSON-serializable objects;
- add focused unit tests using current MinerU fixtures;
- do not add router, summary, table lookup, VLM, or model changes in Phase 5B.

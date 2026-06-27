# Phase 5 Tool Inventory

## Audit Scope

This inventory is based on current repository files. Phase 5A does not
implement document tools; it records what can be reused and what still needs
code.

## Phase 5B Accepted Status

Phase 5B P0 deterministic document tools are accepted in:

```text
docagent/tools/document_tools.py
```

The functions read from `DocumentRepository`, `documents.page_count`, and
SQLite-backed `EvidenceBlock` payloads. They do not call Router, CLI, external
LLM, VLM, retrieval, or model code.

Implemented P0 tools:

```text
count_pages
count_blocks
count_tables
count_images
get_page_text
list_pages
```

Known Phase 5B limitations:

- `get_page_text` uses page aggregate blocks when available and otherwise
  joins same-page child block retrieval text.
- `count_images` counts image/figure-like evidence blocks and chart metadata
  from MinerU-derived block metadata; it does not perform pixel reasoning.
- `table_lookup`, `simple_calculation`, `document_summary`, Router, CLI, and
  trace artifact integration remain deferred.

Current implementation target:

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
Phase 5C-2 LLM-assisted Router fallback -> accepted
Phase 5C-3 Query Planning + Multi-Query Retrieval -> accepted
Phase 5H Full Workflow Validation Baseline -> accepted
```

## Phase 5C-2 LLM-assisted Router Fallback Status

Phase 5C-2 optional Router LLM fallback is accepted in:

```text
docagent/router/llm_client.py
docagent/router/llm_router.py
scripts/docagent_cli.py
```

The deterministic rule router remains the default baseline. The LLM fallback
is disabled unless the caller explicitly passes `--allow-llm-router` or sets
`allow_external_llm_router = true` in the wrapper input.

Configuration sources:

```text
DOCAGENT_ROUTER_LLM_API_KEY
DOCAGENT_ROUTER_LLM_BASE_URL
DOCAGENT_ROUTER_LLM_MODEL
DOCAGENT_ROUTER_LLM_TIMEOUT_SECONDS
--router-llm-env-file .secrets/router_llm.env
```

Planning data visible to the LLM:

```text
question
available_tools
initial rule_plan
lightweight document_profile fields
```

Planning data not sent to the LLM:

```text
full document text
retrieved evidence
OCR full text
image pixels
user file contents
local_fact_qa outputs
```

Fallback validation:

```text
LLM-facing output is a minimal routing decision: task_type, optional
query_rewrite, optional selected_tools, and optional diagnostics.
llm_router.py canonicalizes the minimal decision into the full internal
RouterDecision schema.
selected_tools must exist in available_tools or be safely inferred.
requires_visual_understanding must remain false.
invalid JSON, canonicalization / validation failure, missing config, or API
failure falls back to the rule plan.
```

Accepted server real API smoke evidence:

```text
command = phase5c2_router_llm_schema_smoke
status = success
artifact = outputs/logs/phase5c2_router_llm_schema_smoke.json
cli_artifact_dir = /root/autodl-tmp/docagent/outputs/cli_smoke/docagent_cli_20260626_093156_bbb1c380
cli_status = success
task_type = local_fact_qa
router_source = llm_fallback
llm_router_status = used
llm_router_error_type = null
validation_errors = []
normalization_warnings = []
warnings = llm_router_used, dry_run_no_answer_generated, page_metadata_inconsistent
```

This does not implement `document_summary`, `table_lookup`,
`simple_calculation`, VLM, local_fact_qa answer-quality fixes, training, or
full GRPO E2E.

## Phase 5C-3 Query Planning and Multi-Query Retrieval Status

Phase 5C-3 query planning is accepted in:

```text
docagent/retrieval/query_planner.py
docagent/retrieval/query_generator_rule.py
docagent/retrieval/query_generator_llm.py
docagent/retrieval/query_fusion.py
docagent/retrieval/fusion.py
docagent/retrieval/hybrid_retriever.py
docagent/retrieval/index_manager.py
scripts/docagent_cli.py
scripts/run_phase5c3_query_rewriter_smoke.py
```

Purpose:

```text
question -> Router task_type -> Rule Query Extractor + LLM Query Rewriter
         -> query fusion -> multi-query retrieval -> existing pipeline
```

This is retrieval preprocessing, not a document-answering tool and not a
Router replacement. It currently supports:

- deterministic rule query extraction for page/table/image/statistics and
  keyword-style queries;
- optional LLM semantic query rewriting that reuses the Phase 5C-2 Router LLM
  API client/configuration but receives only the user question;
- query fusion with deduplication, maximum 8 final queries, and rule-query
  priority plus `query_sources` source tracking;
- multi-query BM25 retrieval and dense/hybrid retrieval when query embeddings
  are available for each final query;
- optional CLI exposure via `--enable-query-planning` and
  `--query-planner-mode {rule,llm,hybrid}`.

The LLM Query Rewriter:

```text
role = semantic Query Rewriter
first_attempt_input = {"question": "..."}
retry_input = {"question": "...", "avoid_exact_queries": [...]}
recommended_output_schema = {"queries": ["...", "..."]}
fallback = rule queries when config/API/output is unavailable, invalid, empty, or echoes input payload
```

The parser remains backward compatible with top-level JSON arrays, fenced JSON
arrays, `queries` / `final_queries` / `retrieval_queries` objects, and safe
loose query objects. The recommended LLM-facing schema is now
`{"queries": [...]}` because it proved more stable with the configured
OpenAI-compatible chat model.

The LLM Query Rewriter does not receive task_type, document_profile,
rule_queries, RouterPlan, full document text, retrieved evidence, OCR full
text, image pixels, user file contents, or local_fact_qa results. It does not
answer questions, generate citations, select tools, call tools, or override
the Phase 5 visual boundary.

Hybrid mode combines `rule_queries + llm_queries -> fusion -> final_queries`.
`query_sources.rule` and `query_sources.llm` record the queries that actually
enter `final_queries`. Retrieval runs each query in `final_queries`, then
merges retrieved candidates with reciprocal-rank fusion in the existing
retrieval stack.

Accepted server smoke evidence:

```text
single_case_command = phase5c3_query_retry_smoke
single_case_status = success
single_case_doc_id = c1fc1c5e040ec894
single_case_question = What date or financial year is mentioned in the shareholder notice about unclaimed dividend?
single_case_query_planner_mode = hybrid
single_case_llm_status = used
single_case_llm_added_unique_query_count = 5
single_case_query_sources_llm = non_empty

multi_question_command = phase5c3_query_rewriter_multi_smoke
multi_question_status = success
multi_question_run_id = phase5c3_query_rewriter_20260627_080409_7bc51dc6
multi_question_artifact_dir = outputs/smoke/phase5c3_query_rewriter/phase5c3_query_rewriter_20260627_080409_7bc51dc6
multi_question_case_count = 10
multi_question_passed_count = 10
multi_question_failed_count = 0
multi_question_semantic_case_count = 7
multi_question_semantic_passed_count = 7
multi_question_task_type_distribution = local_fact_qa:8, page_lookup:1, document_statistics:1
```

Phase 5C-3 does not implement `document_summary`, `table_lookup`,
`simple_calculation`, VLM, AnswerPolicy changes, ingestion changes,
local_fact_qa answer-quality changes, training, or full GRPO E2E. Full
business workflow validation, non-dry-run validation for Router + Query
Planning + Retrieval + local_fact_qa, and answer-quality benchmarking remain
not completed.

## Phase 5D local_fact_qa Wrapper Status

The accepted Phase 5D callable local fact QA wrapper is implemented in:

```text
docagent/tools/local_fact_qa.py
```

The wrapper reuses:

- `DocumentRepository` for document existence and EvidenceBlock loading;
- `run_qa_workflow` for retrieval, evidence context construction,
  AnswerPolicy execution, format/location checks, and answer repair;
- `HeuristicAnswerPolicy` as the local default AnswerPolicy when no policy is
  injected;
- optional injected retriever / workflow runner for real hybrid retrieval,
  smoke tests, or controlled fake workflow tests;
- optional `TraceRepository` for SQLite trace persistence.

Phase 5D output is a JSON-serializable dict with `answer`, `citations`,
`supporting_evidence_ids`, `tools_used`, `trace_path`, `run_id`, warnings, and
structured errors. `trace_path` remains empty unless the caller explicitly
passes a trace path; the wrapper does not invent trace artifact locations.

Local tests cover wrapper behavior, structured errors, dry-run behavior, fake
workflow injection, default heuristic workflow reuse, citation fields, and
SQLite trace persistence. They do not verify server real-model QA quality.

## Phase 5D-S local_fact_qa Smoke Runner Status

Phase 5D-S adds a reusable smoke runner in:

```text
scripts/run_phase5d_local_fact_qa_smoke.py
```

The runner calls the Phase 5D `local_fact_qa` wrapper over an existing SQLite
database and already-ingested `doc_id`. It is not the final MVP CLI and does
not implement Router, document summary, table lookup, calculation, trace
artifact wrapping, training, VLM, or external LLM API calls.

Supported inputs:

```text
--db-path
--doc-id
--question
--questions-jsonl
--output-dir
--dry-run
--limit
--answer-policy {heuristic,base,sft,grpo}
--retrieval-config
--workflow-config
--evidence-packing
```

Additional AnswerPolicy options mirror the existing Qwen policy configuration
for server smoke use. `--retrieval-config` and `--workflow-config` are recorded
in smoke artifacts for reproducibility; this runner does not replace the
future unified CLI configuration layer.

Output artifacts are written under:

```text
outputs/smoke/phase5d_local_fact_qa/<run_id>/
  summary.json
  summary.md
  results.jsonl
  preview.json
```

`results.jsonl` rows include `doc_id`, `question`, `status`, `answer`,
`citations`, `supporting_evidence_ids`, `tools_used`, `run_id`, `trace_path`,
`warnings`, and `error`. `summary.json` records dry-run / real-workflow flags
and confirms that the runner does not use external API, VLM, training, or full
E2E execution.

Data sources:

- `DocumentRepository` and SQLite `documents` / `evidence_blocks`;
- existing `local_fact_qa` wrapper;
- optional SQLite `TraceRepository` on non-dry-run paths;
- existing `run_qa_workflow` and AnswerPolicy path.

Known limitations:

- dry-run validates wrapper shape and evidence access only; it does not verify
  answer quality;
- local heuristic workflow smoke is not server real-model QA validation;
- accepted server real-model smoke validates execution stability, not
  benchmark-level answer quality.

Accepted server smoke evidence:

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

The warning does not block acceptance; it records that `evidence_packing` is
handled by the existing workflow path.

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

Deferred:

```text
Phase 5E document_summary -> not_started
Phase 5F-1 unified CLI MVP -> accepted
Phase 5F-1 server CLI smoke -> accepted
Phase 5F-2 file-to-answer ingestion integration -> accepted
Phase 5F-2 server file-to-answer smoke -> accepted
Phase 5F-3 MinerU-backed file-to-answer implementation -> accepted
Phase 5F-3 server smoke -> accepted
Phase 5C-2 LLM-assisted Router fallback -> accepted
Phase 5F full CLI acceptance -> not_started
Phase 5G CLI regression baseline -> accepted
Phase 5G server regression -> accepted
```

## Phase 5G CLI Regression Runner

The Phase 5G multi-task CLI regression baseline is implemented in:

```text
scripts/run_phase5g_cli_regression.py
```

The runner reuses the accepted CLI surface instead of reimplementing routing or
tools. Each regression case invokes `scripts/docagent_cli.py` through a
subprocess, parses stdout as a single JSON object, validates expected status,
task type, tools used, warnings, errors, and artifact writing, then records a
per-case result.

Default case coverage:

```text
list_documents
document_statistics
page_lookup
local_fact_qa dry-run
.txt file-to-answer
MinerU existing-output-backed file-to-answer
document_summary not implemented path
table_lookup_or_calculation not implemented path
visual_pixel_qa unsupported / fallback boundary
file_not_found structured error
```

Artifact output:

```text
outputs/regression/phase5g_cli/<run_id>/
  regression_cases.jsonl
  regression_results.jsonl
  regression_summary.json
  regression_summary.md
  preview.json
```

Known limitations:

- This runner is an execution stability baseline, not a benchmark answer
  quality evaluation.
- If the local GLOBOCAN PDF or existing MinerU output directory is absent, the
  MinerU file-to-answer case is marked skipped instead of fabricated.
- `document_summary`, table lookup, simple calculation, VLM, training, and
  full GRPO E2E remain out of scope.

Accepted server regression:

```text
run_id = phase5g_cli_20260626_022925_9eca480b
status = success
case_count = 10
completed_count = 8
failed_count = 0
skipped_count = 0
unsupported_count = 2
json_valid_count = 10
artifact_write_count = 9
task_type_distribution = document_statistics:3, document_summary:1, local_fact_qa:2, page_lookup:1, table_lookup_or_calculation:1
tools_used_distribution = count_pages:3, get_page_text:1, local_fact_qa:2
failure_taxonomy = {}
unsupported_taxonomy = document_summary_not_implemented:1, table_lookup_not_implemented:1
skipped_taxonomy = {}
known_limitation_counts = document_summary_not_implemented:1, dry_run_no_answer_generated:2, fallback_to_local_fact_qa:3, table_lookup_not_implemented:1, visual_understanding_unsupported:1
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
artifact_dir = /root/autodl-tmp/docagent/outputs/regression/phase5g_cli/phase5g_cli_20260626_022925_9eca480b
```

## Reusable Code Paths

Ingestion and document cache:

- `docagent/ingestion/document_registry.py`
  - `DocumentRegistry.register`
  - `DocumentRecord`
- `docagent/ingestion/service.py`
  - `DocumentIngestionService.ingest`
  - `IngestionResult`
- `docagent/parser/mineru_converter.py`
  - `find_content_list`
  - `content_list_to_blocks`
  - `build_page_blocks`
  - `raw_content_list_stats`
- `docagent/ingestion/quality.py`
  - `build_structure_quality_report`

Storage and trace:

- `docagent/storage/db.py`
  - `connect`
  - migration helpers
- `docagent/storage/repositories.py`
  - `DocumentRepository`
  - `TraceRepository`
- `docagent/storage/schema.sql`

Schemas:

- `docagent/schemas.py`
  - `EvidenceLocation`
  - `EvidenceBlock`
  - `DocAgentSample`
  - `QAState`

Retrieval and local fact QA:

- `docagent/retrieval/bm25_index.py`
- `docagent/retrieval/dense_encoder.py`
- `docagent/retrieval/dense_index.py`
- `docagent/retrieval/fusion.py`
- `docagent/retrieval/hybrid_retriever.py`
- `docagent/retrieval/index_manager.py`
- `docagent/retrieval/reranker.py`
- `docagent/retrieval/evidence_packing.py`
- `docagent/workflow/graph.py`
- `docagent/workflow/prompts.py`
- `docagent/workflow/output_adapter.py`
- `docagent/models/base.py`
- `docagent/models/qwen_answer_policy.py`

Existing script entrypoints:

- `scripts/ingest_document.py`: ingest a file with MinerU existing/local/API
  modes, optionally build dense index, and persist into SQLite.
- `scripts/query_document.py`: query an already ingested `doc_id` through
  retrieval and `run_qa_workflow`.
- `scripts/inspect_document.py`: list documents, inspect document metadata,
  blocks, and indexes from SQLite.
- `scripts/run_phase4b_mpdocvqa_ingestion.py`: Phase 4 window ingestion,
  acceptance report, portability/path scans, and `docagent.sqlite`.
- `scripts/run_phase4b_mpdocvqa_e2e.py`: retrieval-only/full E2E runner,
  `page_children` and `candidate_spans` evidence packing, fixed evidence,
  candidate evidence, metrics, and trace SQLite.
- `scripts/analyze_phase4d_candidate_answer_coverage.py`: candidate answer
  diagnostics over `candidate_evidence.jsonl`.
- `scripts/export_phase4d_failure_inspection.py`: C/D/E failure inspection and
  candidate span gap review artifacts.
- `scripts/eval_retrieval_phase2.py`, `scripts/eval_workflow_phase2.py`, and
  `scripts/run_workflow_smoke.py`: earlier retrieval/workflow evaluation and
  smoke paths.

## Current Ingestion Artifact Paths

Generic local ingestion writes under:

```text
data/documents/<doc_id>/
  source/original.<ext>
  mineru/
  evidence_blocks.jsonl
  page_documents.jsonl
  structure_quality.json
  ingestion_report.json
  index_metadata.json
  index_metadata_<model_id>.json
```

Phase 4 MP-DocVQA ingestion writes under run-specific roots such as:

```text
outputs/phase4/mpdocvqa_ingestion/<doc_id>/
outputs/evaluation/.../<run_id>/
```

Phase 4 ingestion also uses a per-work directory SQLite path:

```text
docagent.sqlite
```

Generic local scripts default to:

```text
outputs/docagent.db
```

## Artifact Formats

`evidence_blocks.jsonl`:

- one JSON object per `EvidenceBlock`;
- excludes page aggregate blocks;
- records text/table/image evidence blocks converted from MinerU content list.

`page_documents.jsonl`:

- one JSON object per page aggregate `EvidenceBlock`;
- `block_type = "page"`;
- `text` is the joined retrieval text from page child blocks;
- `metadata.child_block_ids` links to page children.

`structure_quality.json`:

- quality summary built from MinerU `layout.json`, `*_content_list.json`,
  converted blocks, and page documents.

`ingestion_report.json`:

- compact result from `IngestionResult.to_dict()`.

SQLite:

- `documents`
- `evidence_blocks`
- `document_indexes`
- `qa_logs`
- `qa_runs`
- `tool_traces`
- `eval_results`

## Existing Document Metadata Fields

From `DocumentRecord`, `DocumentRepository`, and `schema.sql`:

```text
doc_id
sha256
original_name
mime_type
file_size
file_path
document_dir
page_count
parser_backend
parse_status
index_status
created_at
updated_at
```

`documents.source` currently receives `record.original_name` in
`DocumentRepository.upsert_document`.

## Existing Page-level Fields

Page aggregate blocks from `build_page_blocks` use:

```text
doc_id
page_id
block_id = <doc_id>_pNNN_page
block_type = page
text
location.page
location.block_id
metadata.parser = mineru
metadata.child_block_ids
metadata.excluded_child_block_ids
```

Page count is also stored on `DocumentRecord.page_count` and the `documents`
SQLite table after ingestion.

## Existing Block-level Fields

`EvidenceBlock` supports:

```text
doc_id
block_id
block_type
text
page_id
table_html
image_path
visual_summary
location.page
location.block_id
location.table_id
location.image_id
location.bbox
metadata
```

MinerU conversion metadata includes:

```text
parser
reading_order
raw_item_index
raw_mineru_type
is_boilerplate
exclude_from_retrieval
mineru_provenance
mineru_page_idx
text_level
previous_block_id
next_block_id
parent_block_id
unknown_raw_type
resource_exists
```

## Existing Table-related Fields

For table raw types, `mineru_converter` maps blocks to:

```text
block_type = table
text = caption + table text/body + footnote
table_html
image_path
location.bbox
metadata.table_caption
metadata.table_footnote
metadata.table_body
metadata.raw_mineru_type
metadata.resource_exists
```

Table counts already appear in `structure_quality.json`:

```text
table_count
table_html_count
```

## Existing Image / Figure-related Fields

For image, figure, and chart raw types, `mineru_converter` maps blocks to:

```text
block_type = image
text = caption / image_caption / nearby_text / text / content
image_path
location.bbox
metadata.raw_mineru_type
metadata.img_path
metadata.resource_exists
metadata.chart_caption
metadata.chart_footnote
```

The schema also supports `visual_summary`, but current Phase 5 must not add VLM
image understanding.

Image/figure counts already appear in `structure_quality.json`:

```text
chart_count
image_reference_count
missing_image_reference_count
```

## Current Table / Image Processing Capability

Current deterministic support:

- preserve table text and `table_html` when MinerU provides it;
- preserve table/image resource paths as relative paths when possible;
- preserve captions, footnotes, nearby text, and chart metadata;
- include table/image blocks in retrieval text and candidate evidence;
- sanitize unsafe absolute image paths in `candidate_spans` output.

Current limitations:

- no table grid normalization API;
- no deterministic row/column lookup tool yet;
- no simple calculation tool yet;
- no visual pixel reasoning;
- figure/chart answers depend on OCR/caption/nearby text, not image pixels.

## P0 Deterministic Tool Plan

These tools can be implemented deterministically from existing artifacts and
SQLite with small new wrapper code.

| Tool | Current source | Needs new code? | Notes |
|---|---|---:|---|
| `count_pages` | `documents.page_count`, page blocks, block page ids | Implemented | Prefer SQLite document metadata, then page blocks, then block page ids. |
| `count_blocks` | `evidence_blocks` table | Implemented | Counts non-page blocks by default and returns `by_block_type`. |
| `count_tables` | `EvidenceBlock.block_type == "table"` | Implemented | Returns `table_count`, `table_html_count`, and compact table block metadata. |
| `count_images` | `block_type in {"image", "figure"}` and chart/image metadata | Implemented | Counts image/figure/chart regions from converted blocks. |
| `get_page_text` | page aggregate block text or blocks filtered by `page_id` | Implemented | Returns 1-based page number, full text, capped preview, block ids, and source. |
| `list_pages` | page aggregate blocks / page ids | Implemented | Returns 1-based pages, child block counts, page block ids, and capped previews. |

## P1 Tool Plan

These are feasible from current artifacts, but require more output contract work.

| Tool | Current source | Needs new code? | Notes |
|---|---|---:|---|
| `extract_all_tables` | table `EvidenceBlock`s | Yes | Return table id/block id, page, text, html, bbox, preview. |
| `extract_all_images` | image/chart `EvidenceBlock`s | Yes | Return image id/block id, page, path, caption/OCR text, bbox. |
| `list_sections` | `raw_mineru_type`, `text_level`, title-like blocks | Yes | Heuristic only until section hierarchy is formalized. |
| `document_outline` | section/title blocks plus page ordering | Yes | Should clearly mark heuristic confidence. |

## P2 Tool Plan

These should wait until P0/P1 contracts and tests are accepted.

| Tool | Current source | Needs new code? | Reason to defer |
|---|---|---:|---|
| `table_lookup` | table blocks and `table_html` | Yes | Needs row/column parsing and result citations. |
| `simple_calculation` | table lookup outputs or extracted numeric spans | Yes | Needs typed numeric normalization and traceable calculation inputs. |
| `document_summary` | page text and outline/page previews | Yes | Needs summary strategy and citation policy; external LLM use must be bounded. |

## Tools To Defer

```text
visual_pixel_qa
chart color / spatial reasoning
external VLM fallback
multi-document comparison
multi-turn memory
cloud vector database integration
Candidate-ID Reader
candidate answer extraction rule tuning
```

## Reusable Tests

Likely reusable for Phase 5:

- `tests/test_document_registry.py`
- `tests/test_document_ingestion.py`
- `tests/test_mineru_converter.py`
- `tests/test_ingestion_quality_report.py`
- `tests/test_sqlite_trace.py`
- `tests/test_query_document_smoke_backends.py`
- `tests/test_evidence_packing.py`
- `tests/test_phase4b_mpdocvqa_e2e.py`
- `tests/test_phase4b_mpdocvqa_ingestion.py`
- `tests/test_answer_policy.py`
- `tests/test_workflow_model_node.py`

## Reusable Config Files

- `configs/document_workflow.yaml`
- `configs/parser_mineru.yaml`
- `configs/retrieval_hybrid.yaml`
- `configs/answer_policy.yaml`
- `configs/workflow_mpdocvqa.yaml`

`configs/grpo_qwen3.yaml`, `configs/sft_qwen3_lora.yaml`, and training scripts
remain out of Phase 5A scope.

## Phase 5F-1 Unified CLI MVP Status

The Phase 5F-1 unified MVP entrypoint is accepted in:

```text
scripts/docagent_cli.py
```

Supported parameters:

```text
--db-path
--doc-id
--file
--question
--output-dir
--dry-run
--list-documents
--limit
```

Implemented paths:

- `--list-documents` reads SQLite through `DocumentRepository` and returns
  recent documents with `doc_id`, original name or file path, `page_count`,
  parse/index status, and timestamps when present.
- `--doc-id + --question` checks document existence, calls the Phase 5C Router,
  then dispatches `document_statistics`, `page_lookup`, or `local_fact_qa`.
- `--file + --question` is part of the CLI contract. Current support is
  partial: the CLI reuses an existing SQLite document when file SHA matches;
  otherwise it returns structured `file_ingestion_unavailable` instead of
  pretending ingestion succeeded.

Accepted server CLI smoke:

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
document_statistics_tools_used = count_pages
page_lookup_run_id = docagent_cli_20260625_035527_52de8e1f
page_lookup_status = success
page_lookup_tools_used = get_page_text
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
acceptance_boundary = execution stability, not benchmark-level answer quality
```

Known limitations:

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

Artifact output:

```text
outputs/cli/<run_id>/
  result.json
  summary.json
  router_plan.json
  trace.json
```

Deferred from Phase 5F-1:

```text
Phase 5E document_summary
table_lookup
simple_calculation
structured extraction tools
LLM-assisted Router fallback (accepted later in Phase 5C-2)
external LLM API
VLM
training
full GRPO E2E
```

## Phase 5F-2 File-to-answer Ingestion CLI Status

Phase 5F-2 adds lightweight file ingestion to the unified CLI:

```text
scripts/docagent_cli.py
docagent/parser/text_backend.py
```

Implemented ingestion path:

```text
--file <utf8_txt> + --question
-> DocumentRegistry
-> TextParserBackend
-> DocumentIngestionService
-> DocumentRepository / SQLite EvidenceBlocks
-> Phase 5C Router
-> deterministic tools or local_fact_qa
-> unified JSON output and outputs/cli/<run_id>/ artifacts
```

Supported CLI file-ingestion behavior:

- new UTF-8 `.txt` files are ingested and return a generated `doc_id`;
- already-ingested files are reused by `sha256` and do not repeat ingestion;
- `source.was_ingested` and `source.reused_existing` are returned in CLI
  output;
- `summary.json` records `used_file_ingestion`,
  `reused_existing_document`, `ingestion_status`, and `ingestion_error`;
- `--document-root` is available for directing the existing document cache,
  defaulting to `data/documents`;
- `page_metadata_inconsistent` is emitted as a warning when citation pages
  exceed `documents.page_count`.

Structured file-ingestion errors:

```text
file_not_found
parser_backend_unavailable
unsupported_file_type
file_ingestion_failed
document_not_found
```

Current limitations:

```text
PDF/image ingestion inside docagent_cli is not implemented in Phase 5F-2.
MinerU-backed PDF ingestion should still use scripts/ingest_document.py until
a configured CLI MinerU path is explicitly added.
Phase 5E document_summary, table_lookup, simple_calculation, VLM, training,
and full GRPO E2E remain not_started. LLM-assisted Router fallback was
accepted later in Phase 5C-2.
```

Accepted server smoke evidence:

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

## Phase 5F-3 MinerU-backed File-to-answer CLI Status

Phase 5F-3 extends the unified CLI file ingestion path to existing MinerU
parser output:

```text
scripts/docagent_cli.py
docagent/parser/mineru_backend.py
docagent/ingestion/service.py
docagent/storage/repositories.py
docagent/tools/document_tools.py
docagent/tools/local_fact_qa.py
```

Implemented ingestion path:

```text
--file <document> + --parser mineru_existing + --mineru-output-dir <mineru_output> + --question
-> DocumentRegistry
-> copy existing MinerU output into the document cache
-> MinerUParserBackend(mode=parse_existing)
-> DocumentIngestionService
-> DocumentRepository / SQLite EvidenceBlocks and page documents
-> Phase 5C Router
-> deterministic tools, page lookup, or local_fact_qa dry-run
-> unified JSON output and outputs/cli/<run_id>/ artifacts
```

For summary-like dry-run questions where `document_summary` is unavailable,
the Router plan is preserved with `router_plan.task_type = document_summary`,
while the top-level CLI `task_type` records the executed
`local_fact_qa` dry-run path. This is a smoke fallback and does not implement
Phase 5E document_summary.

Supported CLI parser options:

```text
--parser auto
--parser text
--parser mineru_existing
--parser mineru
--parser-mode parse_existing
--parser-mode local_cli
--mineru-output-dir / --mineru-output
--mineru-command
--mineru-timeout-seconds
```

Structured file-ingestion errors:

```text
file_not_found
parser_backend_unavailable
unsupported_file_type
file_ingestion_failed
document_registration_failed
document_not_found
```

Local implementation evidence:

```text
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
```

Accepted server smoke evidence:

```text
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

Current limitations:

```text
Phase 5F-3 accepts existing MinerU output-backed file-to-answer execution.
Online MinerU OCR/parser execution from raw PDF remains a later task.
document_summary is not implemented; summary-like questions may fall back to
local_fact_qa dry-run with warnings.
local_fact_qa answer quality is not benchmark-validated by this smoke.
The GLOBOCAN sample structure_quality is passed_with_warnings.
Phase 5E document_summary, table_lookup, simple_calculation, VLM, training,
and full GRPO E2E remain not_started. LLM-assisted Router fallback was
accepted later in Phase 5C-2.
```

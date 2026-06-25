# Decisions

## Status Vocabulary Note

`DECISIONS.md` is a chronological decision log. The canonical current status
is maintained in `docs/ACTIVE_PLAN.md` and `CURRENT_STATUS.md` using the
repository status vocabulary. Older entries may quote transient historical
phrases such as gate-specific blockers; those snapshots are preserved as
history and are not the current canonical project state.

## 2026-06-25: Phase 5F-3 Server MinerU File-to-answer Smoke Accepted

Decision: accept Phase 5F-3 MinerU-backed file-to-answer implementation after
server smoke verified existing MinerU output-backed `--file + --question`
execution through `DocumentIngestionService`, SQLite EvidenceBlocks/page
documents, Router, deterministic document tools, and `local_fact_qa` dry-run.
This validates execution stability, not online MinerU OCR execution or
benchmark answer quality.

Evidence:

```text
implementation_branch = codex/phase5f3-mineru-file-cli-smoke
implementation_commit = 3eaf488cd7870af2e64dcd74f0f807edd8a1cb01
sample_path = data/real_documents/globocan_africa_2022/source/original.pdf
mineru_output = data/real_documents/globocan_africa_2022/mineru_raw
doc_id = fe3465edd3da60d2
overall_status = success
stats_artifact = outputs/logs/phase5f3_file_stats.json
stats_status = success
stats_question = How many pages are in this document?
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
page_lookup_question = Show the text from page 1.
page_lookup_task_type = page_lookup
page_lookup_tools_used = get_page_text
page_lookup_was_ingested = false
page_lookup_reused_existing = true
page_lookup_ingestion_status = reused_existing
page_lookup_metadata_consistency = ok
fact_dry_run_artifact = outputs/logs/phase5f3_file_fact_dry_run.json
fact_dry_run_status = success
fact_dry_run_question = What is this document about?
fact_dry_run_task_type = local_fact_qa
fact_dry_run_router_task_type = document_summary
fact_dry_run_tools_used = local_fact_qa
fact_dry_run_was_ingested = false
fact_dry_run_reused_existing = true
fact_dry_run_ingestion_status = reused_existing
fact_dry_run_metadata_consistency = ok
fact_dry_run_warnings = file_reused_existing_doc_id, tool_unavailable, fallback_to_local_fact_qa, router_plan_task_type_not_local_fact_qa, dry_run_no_answer_generated
artifact_logs = outputs/logs/phase5f3_file_stats.json, outputs/logs/phase5f3_file_page_lookup.json, outputs/logs/phase5f3_file_fact_dry_run.json
artifact_cli_dirs = /root/autodl-tmp/docagent/outputs/cli_smoke/docagent_cli_20260625_113113_45d75c97, /root/autodl-tmp/docagent/outputs/cli_smoke/docagent_cli_20260625_113113_3888da94, /root/autodl-tmp/docagent/outputs/cli_smoke/docagent_cli_20260625_113113_7ef9e062
metadata_consistency = ok, ok, ok
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
```

Boundary:

- Existing MinerU output-backed execution is accepted; online MinerU
  OCR/parser execution from raw PDF remains a later task.
- Router correctly classifies "What is this document about?" as
  `document_summary`, but Phase 5E `document_summary` is not implemented, so
  CLI falls back to `local_fact_qa` dry-run with warnings. This does not block
  execution-smoke acceptance.
- `local_fact_qa` answer quality is not benchmark-validated by this smoke.
- GLOBOCAN `structure_quality` is `passed_with_warnings`.
- No Phase 5E document_summary, LLM-assisted Router fallback, Phase 5G
  regression, table lookup, simple calculation, VLM, training, full GRPO E2E,
  AnswerPolicy prompt change, or candidate answer extraction change is
  included.

Current status:

```text
Phase 5F-3 MinerU-backed file-to-answer implementation -> accepted
Phase 5F-3 server smoke -> accepted
Phase 5E document_summary -> not_started
Phase 5C-2 LLM-assisted Router fallback -> not_started
Phase 5G multi-task regression -> not_started
```

## 2026-06-25: Phase 5F-3 MinerU-backed File-to-answer CLI Implemented

Decision: implement Phase 5F-3 by extending `scripts/docagent_cli.py` from
UTF-8 `.txt` ingestion to existing MinerU/parser-backed file ingestion, while
reusing `MinerUParserBackend`, `DocumentIngestionService`,
`DocumentRegistry`, `DocumentRepository`, the Phase 5C Router, deterministic
document tools, and `local_fact_qa` dry-run.

Implementation:

- `scripts/docagent_cli.py`
- `tests/test_phase5f_mineru_file_cli.py`

Behavior:

- `--file <document> --parser mineru_existing --mineru-output-dir <dir>
  --question <question>` copies existing MinerU output into the document cache
  and ingests it through the existing `DocumentIngestionService`;
- `--mineru-output` is accepted as an alias for `--mineru-output-dir`;
- `--parser auto` preserves the accepted `.txt` behavior and returns
  structured `parser_backend_unavailable` for PDF/image files without a
  configured MinerU output;
- `--parser mineru --parser-mode local_cli` is wired to
  `MinerUParserBackend` for server environments with an isolated MinerU CLI;
- metadata consistency now records `documents.page_count`, page document
  count, max evidence page, and max citation page, and emits
  `page_metadata_inconsistent` only as a warning.

Local evidence:

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
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
```

Boundary:

- Phase 5F-3 was implemented locally and later accepted after server smoke.
- Existing MinerU output is consumed; this change does not install MinerU,
  call MinerU API, call VLM, or mutate the stable `docagent` environment.
- `local_fact_qa` dry-run validates evidence shape, not generated answer
  quality.
- No Phase 5E document_summary, LLM-assisted Router fallback, Phase 5G
  regression, table lookup, simple calculation, training, full GRPO E2E,
  AnswerPolicy prompt change, or candidate answer extraction change is
  included.

Current status:

```text
Phase 5F-3 MinerU-backed file-to-answer implementation -> accepted
Phase 5F-3 server smoke -> accepted
Phase 5E document_summary -> not_started
Phase 5C-2 LLM-assisted Router fallback -> not_started
Phase 5G multi-task regression -> not_started
```

## 2026-06-25: Phase 5F-2 Server File-to-answer Smoke Accepted

Decision: accept Phase 5F-2 file-to-answer ingestion integration after server
smoke verified a lightweight UTF-8 `.txt` file can be ingested, assigned a
`doc_id`, routed, dispatched to tools, and reused by SHA on a second run. This
acceptance validates execution stability, not benchmark-level answer quality.

Evidence:

```text
implementation_branch = codex/phase5f2-file-ingestion-cli
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
```

Boundary:

- Current accepted file ingestion support covers UTF-8 `.txt` through
  `TextParserBackend`.
- PDF/MinerU-backed file-to-answer through `docagent_cli.py` is not yet
  accepted.
- `local_fact_qa` answer quality remains a separate known limitation.
- Dense index is not built in the lightweight smoke; `index_status` may remain
  `not_started`.
- No Phase 5E document_summary, LLM-assisted Router fallback, Phase 5G
  regression, table lookup, simple calculation, VLM, training, full GRPO E2E,
  AnswerPolicy prompt change, or candidate answer extraction change is
  included.

Current status:

```text
Phase 5F-2 file-to-answer ingestion integration -> accepted
Phase 5F-2 server file-to-answer smoke -> accepted
Phase 5E document_summary -> not_started
Phase 5C-2 LLM-assisted Router fallback -> not_started
Phase 5G multi-task regression -> not_started
```

## 2026-06-25: Phase 5F-2 File-to-answer Ingestion CLI Implemented

Decision: implement Phase 5F-2 by adding lightweight `.txt` file ingestion to
the unified CLI while reusing the existing document registry, ingestion
service, SQLite repository, Router, deterministic tools, and `local_fact_qa`
wrapper.

Implementation:

- `scripts/docagent_cli.py`
- `docagent/parser/text_backend.py`
- focused tests in `tests/test_phase5f_file_ingestion_cli.py`

Behavior:

- `--file <utf8_txt> --question <question>` now registers the file through
  `DocumentRegistry`, parses it through `TextParserBackend`, persists it
  through `DocumentIngestionService` / `DocumentRepository`, then routes and
  dispatches the question through the existing Phase 5 CLI path;
- SHA-matched files reuse the existing `doc_id` and do not repeat ingestion;
- CLI output returns generated or reused `doc_id`, `source.was_ingested`, and
  `source.reused_existing`;
- `summary.json` records `used_file_ingestion`,
  `reused_existing_document`, `ingestion_status`, and `ingestion_error`;
- file ingestion errors are structured: `file_not_found`,
  `parser_backend_unavailable`, `unsupported_file_type`, and
  `file_ingestion_failed`;
- `page_metadata_inconsistent` is emitted as a warning when citation pages
  exceed `documents.page_count`.

Boundary:

- PDF/image ingestion inside `docagent_cli.py` is not implemented in Phase
  5F-2. MinerU-backed PDF ingestion remains a later explicit integration path
  or can be performed through `scripts/ingest_document.py`.
- No Phase 5E document_summary, LLM-assisted Router fallback, table lookup,
  simple calculation, VLM, training, full GRPO E2E, AnswerPolicy prompt
  change, or candidate answer extraction change is included.

Current status:

```text
Phase 5F-2 file-to-answer ingestion integration -> accepted
Phase 5F-2 server file-to-answer smoke -> accepted
Phase 5E document_summary -> not_started
Phase 5C-2 LLM-assisted Router fallback -> not_started
Phase 5G multi-task regression -> not_started
```

## 2026-06-25: Phase 5F-1 Server CLI Smoke Accepted

Decision: accept Phase 5F-1 unified CLI MVP after server CLI smoke verified
`scripts/docagent_cli.py` execution over an existing SQLite document. This
acceptance validates CLI execution stability, routing/dispatch wiring, JSON
output, and artifact writing. It does not validate benchmark-level answer
quality.

Evidence:

```text
implementation_branch = codex/phase5f1-unified-cli-mvp
implementation_commit = b7e92c89908ce57517f145e18cd6ca1b702a300e
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
```

Known limitations:

- `--file + --question` remains partial. The CLI contract exists and
  existing-file SHA reuse exists, but new-file ingestion through
  `docagent_cli.py` remains `not_started` and is deferred to Phase 5F-2.
- `local_fact_qa` real workflow execution succeeded, but answer quality is
  unstable. The server date question returned an irrelevant evidence text
  prefix instead of a date.
- Page metadata consistency needs audit: list-documents reported
  `page_count = 5` for `doc_id = c1fc1c5e040ec894`, while `local_fact_qa`
  citations included page 24. This may reflect a `documents.page_count` vs
  evidence block page-number mismatch or source/page-window metadata
  semantics.

Current status:

```text
Phase 5F-1 unified CLI MVP -> accepted
Phase 5F-1 server CLI smoke -> accepted
Phase 5F-2 file-to-answer ingestion integration -> not_started
Phase 5E document_summary -> not_started
Phase 5C-2 LLM-assisted Router fallback -> not_started
Phase 5G multi-task regression -> not_started
```

## 2026-06-25: Phase 5F-1 Unified CLI MVP Implemented

Decision: implement the first unified CLI MVP in `scripts/docagent_cli.py`
before Phase 5E document summary, because the accepted deterministic tools,
Router, local_fact_qa wrapper, and server smoke evidence now need a single user
entrypoint.

Implementation:

- `scripts/docagent_cli.py`
- focused tests in `tests/test_phase5f_cli.py`

Supported CLI parameters:

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

Implemented behavior:

- `--list-documents` returns a single JSON object with recent SQLite documents
  and includes `doc_id`, original name or file path, page count, parse/index
  status, and timestamps when present;
- `--doc-id + --question` checks document existence, calls the Phase 5C Router,
  and dispatches supported task types;
- `document_statistics` uses Phase 5B deterministic tools;
- `page_lookup` uses `get_page_text` or `list_pages`;
- `local_fact_qa` uses the accepted Phase 5D wrapper and supports `--dry-run`;
- every QA run writes `result.json`, `summary.json`, `router_plan.json`, and
  `trace.json` under `outputs/cli/<run_id>/`;
- stdout is a single JSON object.

File-entry contract:

- `--file + --question` is part of the CLI contract;
- current ingestion support is partial: an already-ingested SQLite document can
  be reused when the input file SHA matches `documents.sha256`;
- if no matching document exists, the CLI returns structured
  `file_ingestion_unavailable` and tells the user to run
  `scripts/ingest_document.py` first;
- the CLI does not call MinerU, MinerU API, or local parser backends directly
  in Phase 5F-1.

Boundary:

- Phase 5E document_summary remains `not_started`;
- table lookup, simple calculation, structured extraction tools, LLM-assisted
  Router fallback, external LLM API, VLM, training, full GRPO E2E,
  AnswerPolicy prompt changes, and candidate answer extraction changes remain
  out of scope.

Current status:

```text
Phase 5F-1 Unified CLI MVP -> implemented
Phase 5E document_summary -> not_started
Phase 5F server CLI smoke / full CLI acceptance -> not_started
Phase 5G Multi-task Regression -> not_started
```

## 2026-06-25: Phase 5D-S Server Smoke Accepted

Decision: accept Phase 5D-S as an execution-stability smoke milestone after
server dry-run and real-model smoke both completed successfully on an existing
SQLite document.

Evidence:

```text
branch = codex/phase5d-local-fact-qa-smoke
runner_commit = 53b9d1000ce8389c9dd1a574072f61bdb6407eb7
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

Real-model preview:

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

Boundary:

- this acceptance validates execution stability, not benchmark-level answer
  quality;
- `evidence_packing_option_deferred_to_workflow` does not block acceptance and
  only records that the option is handled by the existing workflow path;
- no `local_fact_qa` core logic, smoke runner behavior, Router, final CLI,
  document summary, table lookup, calculation, external LLM API, VLM, training,
  full GRPO E2E, AnswerPolicy prompt, or candidate answer extraction change is
  included.

Current status:

```text
Phase 5A architecture audit and contracts -> accepted
Phase 5B deterministic P0 document tools -> accepted
Phase 5C Router / Planner -> accepted
Phase 5D local_fact_qa wrapper -> accepted
Phase 5D-S local_fact_qa smoke runner -> accepted
Phase 5D-S server real-model smoke -> accepted
Phase 5E document_summary -> not_started
Phase 5F Unified CLI -> not_started
Phase 5G Multi-task Regression -> not_started
```

## 2026-06-24: Phase 5D-S local_fact_qa Smoke Runner Implemented

Decision: add a reusable server-smoke runner for the Phase 5D `local_fact_qa`
tool wrapper, without turning it into the final unified CLI.

Implementation:

- `scripts/run_phase5d_local_fact_qa_smoke.py`
- focused tests in `tests/test_phase5d_local_fact_qa_smoke.py`

Reused components:

- `DocumentRepository` and SQLite evidence blocks for document access;
- Phase 5D `local_fact_qa` wrapper;
- optional `TraceRepository` on non-dry-run workflow paths;
- existing `run_qa_workflow` and AnswerPolicy implementations.

Artifacts:

```text
outputs/smoke/phase5d_local_fact_qa/<run_id>/summary.json
outputs/smoke/phase5d_local_fact_qa/<run_id>/summary.md
outputs/smoke/phase5d_local_fact_qa/<run_id>/results.jsonl
outputs/smoke/phase5d_local_fact_qa/<run_id>/preview.json
```

Boundary:

- dry-run mode validates wrapper shape and evidence access only;
- local heuristic workflow smoke does not validate server real-model QA
  quality;
- missing db paths, missing doc ids, missing questions, and tool failures are
  written as structured smoke failures;
- no Router, final CLI, trace artifact wrapper, document summary, table lookup,
  calculation, external LLM API, VLM, training, full GRPO E2E, AnswerPolicy
  prompt change, or candidate answer extraction change is included.

Current status:

```text
Phase 5D local_fact_qa wrapper -> implemented
Phase 5D-S local_fact_qa smoke runner -> implemented
Phase 5D-S server real-model smoke -> ready
Phase 5E document_summary -> not_started
Phase 5F Unified CLI -> not_started
Phase 5G Multi-task Regression -> not_started
```

## 2026-06-24: Phase 5D local_fact_qa Tool Wrapper Implemented

Decision: implement `local_fact_qa` as a callable tool wrapper around the
existing local QA workflow, without building the final CLI or changing model,
prompt, retrieval, or candidate extraction behavior.

Implementation:

- `docagent/tools/local_fact_qa.py`
- focused tests in `tests/test_phase5_local_fact_qa_tool.py`

Reused components:

- `DocumentRepository` for document lookup and EvidenceBlock loading;
- `run_qa_workflow` for retrieval, evidence context construction,
  AnswerPolicy execution, format/location checks, answer repair, and trace
  callbacks;
- `HeuristicAnswerPolicy` as the default local policy when no AnswerPolicy is
  injected;
- optional injected retriever, AnswerPolicy, workflow runner, and
  `TraceRepository`.

Boundary:

- dry-run mode returns wrapper-shaped success without generating an answer and
  emits `dry_run_no_answer_generated`;
- fake workflow injection is only for wrapper tests and is not real QA quality
  validation;
- server real-model smoke was not run in this round;
- `trace_path` is only returned when explicitly supplied by the caller;
- no external LLM API, VLM, CLI, document summary, table lookup, calculation,
  training, full GRPO E2E, AnswerPolicy prompt change, or candidate answer
  extraction change is included.

Current status:

```text
Phase 5D local_fact_qa wrapper -> implemented
Phase 5E document_summary -> not_started
Phase 5F Unified CLI -> not_started
Phase 5G Multi-task Regression -> not_started
```

## 2026-06-24: Phase 5C Rule-first Router / Planner Implemented

Decision: implement the Phase 5C router as a deterministic rule-first
single-step planner, not a simple classifier and not a tool executor.

Implementation:

- `docagent/router/schemas.py`
- `docagent/router/rule_router.py`
- `docagent/router/__init__.py`
- focused tests in `tests/test_phase5_router.py`

Supported task types:

```text
local_fact_qa
table_lookup_or_calculation
document_statistics
page_lookup
structured_extraction
document_summary
```

Router behavior:

- input supports `doc_id`, `question`, `available_tools`, optional
  `document_profile`, and optional `options`;
- output includes selected tools, retrieval/full-scan flags, table/calculation
  flags, target evidence types, lightweight deterministic `query_rewrite`,
  confidence, reason, fallback status, and warnings;
- selected tools are validated against `available_tools`;
- external LLM fallback is disabled by default and no external API client is
  implemented;
- `requires_visual_understanding` is always false;
- unsupported visual pixel questions fall back to OCR/caption-based
  `local_fact_qa` when available, otherwise return a structured router error;
- complex query decomposition is deferred and reported with
  `complex_query_decomposition_deferred`.

Current status:

```text
Phase 5C Router / Planner -> implemented
Phase 5D local_fact_qa wrapper -> not_started
Phase 5F Unified CLI -> not_started
```

## 2026-06-24: Phase 5B P0 Deterministic Document Tools Implemented

Decision: implement the Phase 5B P0 deterministic document tools as direct,
testable Python functions without Router, CLI, external LLM, VLM, or trace
artifact expansion.

Implementation:

- `docagent/tools/document_tools.py`
- exported from `docagent/tools/__init__.py`
- focused tests in `tests/test_phase5_document_tools.py`

Implemented tools:

```text
count_pages
count_blocks
count_tables
count_images
get_page_text
list_pages
```

Data sources:

- `DocumentRepository.get_document`
- `documents.page_count`
- SQLite-backed `EvidenceBlock` payloads loaded via
  `DocumentRepository.load_evidence_blocks`
- page aggregate blocks when present, with same-page child block fallback

Known limitations:

- `count_images` uses MinerU-derived image/figure/chart block metadata and
  does not perform pixel reasoning.
- `get_page_text` is deterministic page text assembly, not summarization.
- `table_lookup`, `simple_calculation`, `document_summary`, Router,
  `scripts/docagent_cli.py`, and final MVP trace artifact creation remain
  deferred.

Current status:

```text
Phase 5B deterministic P0 document tools -> implemented
Phase 5C Router / Planner -> not_started
```

## 2026-06-23: Phase 5 Personal-use DocAgent MVP Activated

Decision: defer Phase 4D-D candidate answer board generalized improvement and
start Phase 5 as the active personal-use DocAgent MVP track.

Rationale:

- Phase 4D-C identified candidate answer extraction and candidate span
  construction as the larger bottlenecks, with only 5 cases attributed to
  reader selection.
- The current project priority has shifted to a product-like personal document
  assistant suitable for job-search demonstration.
- Candidate answer board improvement should be revisited after the MVP
  entrypoint, router, deterministic document tools, and multi-task regression
  are accepted.

Phase 5A scope:

- Preserve the provided `docs/PHASE5_ACTIVE_PLAN.md` as the master Phase 5
  plan, allowing only lightweight formatting and repository-style alignment.
- Add router, deterministic tool inventory, and MVP acceptance contracts.
- Audit existing ingestion, retrieval, E2E, evaluation, trace, schema, test,
  and config paths.
- Do not implement `scripts/docagent_cli.py`, router code, document tools,
  AnswerPolicy prompt changes, candidate answer extraction changes, VLM, model
  training, or full GRPO E2E.

Current status:

```text
Phase 4D-C expanded unseen validation -> accepted
Phase 4D-D candidate answer board generalized improvement -> deferred
Phase 5 Personal-use DocAgent MVP -> active
Phase 5A architecture audit and contracts -> implemented
```

Next implementation target:

- Phase 5B deterministic P0 document tools:
  `count_pages`, `count_blocks`, `count_tables`, `count_images`,
  `get_page_text`, and `list_pages`.

## 2026-06-23: Phase 4D-C Expanded Unseen Validation Accepted

Decision: accept Phase 4D-C expanded unseen validation and move the next
recommended milestone to Phase 4D-D candidate answer board generalized
improvement.

Scope:

- MP-DocVQA validation shards 5-8.
- Accepted default pipeline:
  `evidence_packing = candidate_spans`,
  `rank_aware_context = false`,
  `table_index_enhancement_enabled = false`,
  `enable_table_index_packing = false`.
- No Candidate-ID Reader, no prompt tuning, no training, and no full GRPO E2E
  by default.

Accepted strict set:

```text
raw_sample = 85 document windows / 250 QA
excluded_failed_ingestion = 6 windows / 29 QA
excluded_qa_mapping_mismatch = 2 windows / 3 QA
strict_accepted_sample = 77 document windows / 572 pages / 218 QA
strict_sample_root = outputs/phase4/mpdocvqa_raw_phase4d_c_shards5_8_strict_accepted
```

Evidence:

- Candidate evidence completeness passed:
  `candidate_evidence_count = 218 / 218`, `qid_set_match = true`, zero missing,
  extra, or duplicate qids.
- `table_index_enhancement_enabled = false`.
- `no_gold_leakage = true`.
- Candidate retrieval remained usable:
  `Recall@1/3/5 = 0.7248 / 0.8945 / 0.9128`, `MRR = 0.8099`.
- Candidate span answer coverage was `0.7523`.
- Candidate answer coverage was limited:
  `candidate_answer_coverage_all = 0.4266`,
  `candidate_answer_coverage_top20 = 0.3991`.
- Failure attribution:
  `extraction_rule_gap = 72`,
  `candidate_span_or_normalization_gap = 38`,
  `reader_selection_gap = 5`.
- Candidate span gap subtypes:
  `table_or_index_span_gap = 14`,
  `candidate_span_selection_gap = 10`,
  `candidate_span_partial_context_gap = 9`,
  `page_number_or_content_lookup_gap = 5`,
  `normalization_or_metric_gap = 0`,
  `ocr_or_parsing_gap = 0`.

Interpretation:

- Phase 4D-C validates that the accepted default `candidate_spans` pipeline can
  run stably on a larger unseen strict set.
- The main bottleneck is not Candidate-ID Reader. Candidate answer extraction
  and candidate span construction dominate the failure distribution.
- The 90-sample probe observation generalized: candidate answer coverage
  dropped from `0.5222` to `0.4266`, and top20 coverage dropped from `0.4556`
  to `0.3991`.
- Candidate-ID Reader remains postponed.
- Optional full GRPO E2E remains postponed until candidate answer board quality
  improves.

Next milestone:

- Phase 4D-D: Candidate Answer Extraction & Span Gap Generalized Improvement.
- First action should be a failure pattern audit before writing new rules.
- Do not patch specific qids, documents, titles, entities, or answers.
- Do not re-open 90-sample probe tuning.
- Do not enable `--enable-table-index-packing` or `--rank-aware-context` by
  default.

Engineering notes:

- Expanded shard validation commands must preflight required parquet files.
- Accepted-only ingestion reports are insufficient before E2E; strict QA
  mapping checks are required.
- Failure inspection only supports C/D/E buckets. A is retrieval-side miss; G
  means candidate answer covered but no Reader/full E2E output.
- Compact metric readers must handle nested retrieval metric structures.

## 2026-06-22: Phase 4D-C Scaffold and Command Preparation Started

Decision: start Phase 4D-C scaffold / command preparation on branch
`codex/phase4d-c-expanded-unseen-validation`, created from `origin/main`, and
do not run server validation in this round.

Goal:

- Phase 4D-C is expanded unseen validation, not another 90-sample probe tuning
  round.
- First target remains MP-DocVQA validation shards 5-8 with 200-300 QA and
  page-count bucket coverage.
- The default pipeline remains accepted `candidate_spans` with
  `rank_aware_context = false`, `table_index_enhancement_enabled = false`,
  `enable_table_index_packing = false`, no Candidate-ID Reader, no prompt
  tuning, and no training.

Capability check:

- Existing scripts are sufficient for Step A-E command preparation.
- Step A: `scripts/build_phase4b_expanded_sample.py`.
- Step B: `scripts/run_phase4b_mpdocvqa_ingestion.py`.
- Step C: `scripts/run_phase4b_mpdocvqa_e2e.py --retrieval-only
  --evidence-packing candidate_spans`.
- Step D: `scripts/analyze_phase4d_candidate_answer_coverage.py`.
- Step E: `scripts/export_phase4d_failure_inspection.py`, including
  `--candidate-span-gap-review`.

Boundary:

- No code changes are required for this scaffold round.
- Do not enable `--enable-table-index-packing`.
- Do not enable `--rank-aware-context`.
- Do not enter Candidate-ID Reader, AnswerPolicy prompt changes, training,
  full GRPO E2E by default, CDC, Demo, or further 90-sample probe tuning.
- Candidate-ID Reader remains postponed until expanded unseen diagnostics show
  reader-selection failures dominate after candidate coverage issues are
  resolved.

## 2026-06-22: Phase 4D-B1.3 Default Pipeline Sanity Accepted

Decision: accept Phase 4D-B1.3 default pipeline sanity, close tuning on the
90-sample probe, and move next to Phase 4D-C expanded unseen validation.

Evidence:

- Candidate evidence completeness passed with `qa_count = 90`,
  `candidate_evidence_count = 90`, exact qid-set match, and zero missing,
  extra, or duplicate candidate qids.
- `table_index_enhancement_enabled = false`, confirming the default
  `candidate_spans` path does not run the B1 table/index enhancement.
- Default coverage reproduced the accepted Phase 4C baseline:
  `candidate_span_answer_coverage = 0.7444444444444445`,
  `candidate_answer_coverage_all = 0.5222222222222223`,
  `candidate_answer_coverage_top1 = 0.23333333333333334`,
  `candidate_answer_coverage_top5 = 0.3888888888888889`, and
  `candidate_answer_coverage_top20 = 0.45555555555555555`.
- `candidate_answer_no_gold_leakage = true`.

Current conclusion:

- Phase 4C `candidate_spans` is accepted.
- Phase 4D-A diagnostics and failure attribution tooling are accepted as
  diagnostic infrastructure.
- Phase 4D-B1.1 candidate evidence completeness fix is accepted and retained.
- Phase 4D-B1 table/index enhancement is not accepted as default and remains
  experimental behind `--enable-table-index-packing`.
- Candidate-ID Reader remains postponed.

Next phase:

- Phase 4D-C: Expanded Unseen Validation with Accepted Default Pipeline.
- Use the default pipeline: `evidence_packing = candidate_spans`,
  `rank_aware_context = false`, `table_index_enhancement_enabled = false`,
  `enable_table_index_packing = false`, no Candidate-ID Reader, no full GRPO
  training, and no prompt tuning.
- First unseen target: MP-DocVQA validation shards 5-8, 200-300 QA, with
  page-count bucket coverage; do not run all 29 validation shards at once.

## 2026-06-22: Phase 4D-B1.2 Disable Table / Index Enhancement by Default

Decision: retain the Phase 4D-B1.1 candidate evidence completeness fix, but do
not accept the B1 table/index scoring and neighbor-context enhancement as a
default `candidate_spans` behavior.

Evidence:

- B1.1 server validation restored candidate evidence completeness:
  `qa_count = 90`, `candidate_evidence_count = 90`, `qid_set_match = true`,
  `missing_qid_count = 0`, and `extra_qid_count = 0`.
- Overall coverage did not improve:
  `candidate_span_answer_coverage = 0.7444`,
  `candidate_answer_coverage_all = 0.5222`, and
  `candidate_answer_coverage_top20 = 0.4556`.
- The table/index enhancement reduced `table_or_index_span_gap` only from 10
  to 8 and shifted `page_number_or_content_lookup_gap` from 1 to 4.

Implementation boundary:

- Keep candidate evidence completeness checks and metrics.
- Disable table/index scoring bonus and table/index neighbor-context expansion
  by default.
- Keep the enhancement only behind the experimental
  `--enable-table-index-packing` flag.
- Continue writing table/index diagnostics with
  `table_index_enhancement_enabled`.

Next action:

- Stop further per-case tuning on the 90-sample probe.
- Run larger unseen validation using the accepted pipeline and diagnostics.
- Keep Candidate-ID Reader postponed until reader-selection failures dominate
  after candidate coverage issues are resolved.

Constraints:

- Do not modify Reader prompts, AnswerPolicy integration, retrieval models,
  checkpoints, reward, training split, training data, CDC, Demo, or the global
  `candidate_spans` default.

## 2026-06-22: Phase 4D-B1.1 Candidate Evidence Completeness Regression Fix

Decision: block B1 diagnostics until candidate evidence completeness is
restored, then add fail-fast completeness checks to the retrieval-only
`candidate_spans` path.

Evidence:

- B1 server sanity triage showed `qa_qid_count = 90` but `b1_qid_count = 9`.
- `qa_missing_from_b1 = 81`.
- B1 `candidate_evidence.jsonl` and candidate packing metrics had
  `sample_count = 9`, so B1 coverage metrics were invalid.

Root cause:

- The server validation command did not pass a Gate 4 doc-id manifest.
- With no explicit `--doc-id` or `--doc-id-file`, the runner fell back to the
  three historical default documents instead of using the active sample
  `qa.jsonl` doc set.

Implementation boundary:

- Infer document scope from `sample_root/qa.jsonl` when no explicit doc scope
  is provided.
- Add `candidate_evidence_completeness` to run summary and candidate packing
  metrics.
- Fail before writing candidate evidence when candidate record qids do not
  exactly match the loaded QA qid set.
- Preserve B1 table/index diagnostics as additive metrics only.

Constraints:

- Do not change Reader prompts, AnswerPolicy integration, retrieval models,
  checkpoints, reward, training split, training data, CDC, Demo, or the global
  `candidate_spans` default.
- Do not run full GRPO for B1.1.

## 2026-06-22: Phase 4D-B1 Generic Table / Index Candidate Span Fix

Decision: after the accepted Phase 4D-A.4 final diagnostic, implement exactly
one narrow generic repair: table/index candidate span selection.

Evidence:

- A.4 split 21 `candidate_span_or_normalization_gap` cases.
- `table_or_index_span_gap = 10` was the dominant subtype.
- Other subtypes were smaller: `candidate_span_selection_gap = 5`,
  `candidate_span_partial_context_gap = 5`,
  `page_number_or_content_lookup_gap = 1`,
  `normalization_or_metric_gap = 0`, `ocr_or_parsing_gap = 0`, and
  `unclear_mixed_gap = 0`.

Interpretation:

- A.4 is the final diagnostic stage for the 90-sample probe.
- The table/index gap is concentrated enough to justify one generic fix.
- Candidate-ID Reader remains postponed because candidate coverage issues still
  dominate the next action.

Implementation boundary:

- Add generic table/index question detection for index/share/rate/segment,
  percentage/percent/%, table/row/column, and field/value wording.
- Add scoring bonuses for field-label overlap, percentage values,
  parenthesized index values, field-value rows, table/list-like rows, and
  same-line label/value/parenthesized-index evidence.
- Preserve table/index row context by keeping adjacent rows and table
  header-like blocks.
- Add aggregate table/index candidate span diagnostics.

Constraints:

- Do not add qid-, document-, title-, entity-, or answer-specific rules.
- Do not modify Reader prompts, AnswerPolicy, retrieval models, MinerU,
  checkpoints, reward, training split, training data, CDC, Demo, or the global
  `candidate_spans` default.
- Do not run full GRPO for Phase 4D-B1.

## 2026-06-22: Phase 4D-A.4 Final Candidate Span / Normalization Gap Split

Decision: after the accepted Phase 4D-A.3.1 server refined inspection, split
`candidate_span_or_normalization_gap` into final diagnostic subtypes before any
candidate-span or normalization repair.

Evidence:

- A.3.1 showed `candidate_span_or_normalization_gap = 21`, the largest refined
  failure source.
- Other refined sources were smaller: `extraction_rule_gap = 10`,
  `reader_selection_gap = 7`, `normalization_or_metric_gap = 5`, and
  `topk_filtering_gap = 3`.
- The coarse gap can mix true span selection misses, normalization/metric
  issues, table/index structure, page/content lookup, partial context, and
  OCR/parsing boundaries.

Interpretation:

- Candidate-ID Reader remains postponed while candidate coverage gaps dominate.
- A.4 is the final diagnostic split for this 90-sample probe.
- After A.4, the project should implement one narrow generic fix only if one
  subtype dominates and has a generic repair path; otherwise it should stop
  tuning this probe and run the same diagnostics on a larger unseen validation
  sample.

Implementation boundary:

- Export `candidate_span_gap_cases.jsonl`,
  `candidate_span_gap_preview.json`, `candidate_span_gap_summary.json`, and
  `candidate_span_gap_summary.md`.
- Keep every case marked `should_not_patch_specific_qid = true`.
- Do not patch specific qids, documents, or answers.

Constraints:

- Do not modify candidate span main logic, candidate answer extraction main
  logic, Reader prompts, AnswerPolicy, retrieval models, MinerU, checkpoints,
  reward, training split, training data, CDC, Demo, or the global
  `candidate_spans` default.
- Do not run full GRPO for Phase 4D-A.4.

## 2026-06-22: Phase 4D-A.3.1 Refined Action Attribution

Decision: after the accepted Phase 4D-A.3 server inspection, refine the
failure inspection summary before starting Candidate-ID Grounded Reader work.

Evidence:

- Inspection artifacts showed that C/D/E buckets are candidate-layer
  diagnostics, not equivalent to final QA failures.
- Some C and D examples already had `phase4c_prediction.answer_hit = true`.
- Some E examples had the gold answer at top rank but the final answer was
  wrong, indicating Reader/candidate selection rather than candidate coverage.

Interpretation:

- Bucket labels alone overstate the number of primary candidate-layer repair
  targets.
- Action attribution should combine bucket, final answer hit, candidate answer
  coverage, top-k coverage, and simple normalization-overlap checks.
- Final-answer-correct cases should be separated into a no-action bucket for
  current QA behavior.

Implementation boundary:

- Add refined cases and refined summary artifacts to the existing failure
  inspection exporter.
- Keep inspection/refined artifacts audit-only; they may contain gold debug but
  must not become Reader input.
- Keep `candidate_answers.jsonl` and `candidate_answers_topk.jsonl` free of
  gold answer/page fields.

Constraints:

- Do not modify Reader prompt defaults, AnswerPolicy, retrieval models, MinerU,
  checkpoints, reward, training split, training data, CDC, Demo, or the global
  `candidate_spans` default.
- Do not run full GRPO for Phase 4D-A.3.1.

## 2026-06-21: Phase 4D-A.3 Case-level Inspection Before Reader

Decision: after the accepted Phase 4D-A.2 server filtering audit, export
case-level C/D/E failure inspection artifacts before starting Candidate-ID
Grounded Reader work or continuing broad extraction-rule tuning.

Evidence:

- `candidate_answer_coverage_all = 0.5222`, unchanged from A.1.
- `candidate_answer_coverage_top1 = 0.2333`, up from 0.2222.
- `candidate_answer_coverage_top5 = 0.3889`, up from 0.3778.
- `candidate_answer_coverage_top20 = 0.4556`, down from 0.5000.
- `topk_retention_ratio = 0.1293`.
- `topk_numeric_ratio = 0.3902`.
- Error buckets remained unchanged: `C=22`, `D=21`, `E=14`, `F=29`.

Interpretation:

- A.2 produced a cleaner top-k board, but did not improve all coverage or move
  C/D/E buckets enough to justify Candidate-ID Reader integration.
- The next useful work is targeted case inspection to separate candidate span
  gaps, extraction/normalization gaps, ranking gaps, and Reader selection gaps.
- Inspection artifacts may contain gold answer debug fields because they are
  audit/debug reports, not Reader inputs.

Implementation boundary:

- Add an exporter for `failure_inspection_cases.jsonl`, preview, summary, and
  C/D/E bucket-specific JSONL files.
- Keep `candidate_answers.jsonl` and `candidate_answers_topk.jsonl` free of
  gold answer/page fields.
- Generate diagnosis hints only for analysis and planning.

Constraints:

- Do not modify Reader prompt defaults, AnswerPolicy, retrieval models, MinerU,
  checkpoints, reward, training split, training data, CDC, Demo, or the global
  `candidate_spans` default.
- Do not run full GRPO for Phase 4D-A.3.

## 2026-06-21: Phase 4D-A.2 Filtering Before Candidate-ID Reader

Decision: after the accepted Phase 4D-A.1 refined server audit, continue with
candidate answer filtering, reranking, and a type-aware top-k board before
starting Candidate-ID Grounded Reader work.

Evidence:

- `candidate_answer_coverage_all = 0.5222`, up from 0.4556.
- `candidate_answer_coverage_top1 = 0.2222`, up from 0.1111 implied by the
  previous `rank_1=10/90`.
- `candidate_answer_coverage_top5 = 0.3778`.
- `candidate_answer_coverage_top20 = 0.5000`.
- `mean_candidate_answer_count = 105.2889`, up from 79.5889.
- `mean_unique_candidate_answer_count = 52.2333`, up from 49.9889.
- `mean_numeric_distractor_count = 73.7444`, up from 60.4444.
- Error buckets: `D=21`, `F=29`.

Interpretation:

- A.1 extraction improvements worked, but the candidate board became noisier.
- Top-k candidate coverage and numeric flooding are now the main bottlenecks
  before any Candidate-ID Reader input format should be designed.
- All candidate answers must remain available for coverage audit, while the
  future Reader-facing board should use a separate filtered top-k artifact.

Implementation boundary:

- Preserve `candidate_answers.jsonl` as the full audit artifact.
- Produce `candidate_answers_topk.jsonl` through type-aware selection instead
  of simple global rank truncation.
- Add top-k filtering metrics and a `refinement_comparison.json` artifact
  against the accepted A.1 baseline.

Constraints:

- Do not modify Reader prompt defaults, AnswerPolicy, retrieval models, MinerU,
  checkpoints, reward, training split, training data, CDC, Demo, or the global
  `candidate_spans` default.
- Do not run full GRPO for Phase 4D-A.2.

## 2026-06-21: Phase 4D-A.1 Refinement Before Candidate-ID Reader

Decision: after the Phase 4D-A server audit, refine candidate answer extraction,
normalization, ranking, and top-k coverage metrics before starting any
Candidate-ID Grounded Reader work.

Evidence:

- `candidate_span_answer_coverage = 0.7444`.
- `candidate_answer_coverage = 0.4556`.
- `mean_candidate_answer_count = 79.5889`.
- `mean_unique_candidate_answer_count = 49.9889`.
- Error buckets: `A=4`, `C=22`, `D=25`, `E=13`, `F=26`.
- `candidate_answer_no_gold_leakage = true`.

Interpretation:

- The immediate bottleneck is not Reader prompt design.
- `D=25` means many answers are present in candidate spans but not extracted as
  candidate answers.
- `C=22` means candidate span coverage still needs later improvement.
- The candidate answer board is too noisy for direct Reader use without ranking
  and top-k analysis.

Implementation boundary:

- Improve heading/title, city/state/location, quarter short-form,
  key-value/field-value, organization/company/board, and source/footer
  extraction.
- Preserve all candidate answers while adding ranking scores, duplicate
  penalties, generic numeric penalties, top-k flags, and top-k artifacts.
- Add all/top1/top3/top5/top10/top20 coverage metrics and bucket transition
  estimates.

Constraints:

- Do not modify Reader prompt defaults, AnswerPolicy, retrieval models, MinerU,
  checkpoints, reward, training split, training data, CDC, Demo, or the global
  `candidate_spans` default.
- Do not run full GRPO for Phase 4D-A.1.

## 2026-06-21: Phase 4D-A Candidate Answer Coverage Audit Boundary

Decision: implement a deterministic candidate answer coverage audit before
changing Reader prompts, AnswerPolicy protocol, retrieval models, or training.

Rationale:

- Phase 4C showed that query-aware / structure-aware `candidate_spans` improves
  Reader input quality while retrieval metrics stayed unchanged.
- Remaining misses need to be separated into evidence coverage, answer
  extraction, Reader selection, and distractor/ranking issues before introducing
  another Reader or prompt change.
- A rule-based audit can be validated for no-gold leakage and can run over
  existing Phase 4C artifacts without rerunning full GRPO.

Implementation boundary:

- Extract typed candidate answers from Phase 4C `candidate_spans`.
- Write candidate answer board artifacts separately from metrics and buckets.
- Use gold answers only for coverage metrics and error bucket analysis.
- Keep `candidate_answers.jsonl` and preview free of gold answer/page fields.

Constraints:

- Do not modify Reader prompt defaults, AnswerPolicy, retrieval models, MinerU,
  checkpoints, SFT/GRPO reward, training split, or training data in Phase 4D-A.
- Do not make `candidate_spans` the global default.
- Do not enter CDC, Demo, TAT-QA, VLM, or full server E2E from this audit
  implementation alone.
- Server coverage audit results are required before Phase 4D-A can be marked
  `accepted`.

## 2026-06-21: Phase 4C Candidate Spans Acceptance

Decision: accept Phase 4C `candidate_spans` as an experimental and
recommended evidence packing mode for the Gate 4 style MP-DocVQA raw-input E2E
path, while keeping `page_children` as the default.

Evidence:

- Retrieval-only / packing-only completed on the accepted Gate 4 sample:
  `outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_retrieval_only`.
- Full GRPO E2E completed on the same sample:
  `outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_full_grpo`.
- Candidate fixed evidence hash:
  `75a0fcb3f7e0c847d64a767a6a7116ec975a88b7c4ec3c48f54d70bd2f164bba`.
- Hybrid retrieval metrics stayed unchanged from the Phase 4B Gate 4 baseline:
  Recall@1/3/5 = 0.7333 / 0.9222 / 0.9556 and MRR = 0.8257.
- `no_gold_leakage=true`, `gold_page_in_candidate_pages_rate=0.9556`, and
  `gold_page_has_candidate_span_rate=0.9556`.
- Full E2E improved normalized exact match from 0.3333 to 0.4111, answer hit
  from 0.3444 to 0.4556, character F1 from 0.5235 to 0.6341, and
  gold-page-location hit from 0.4889 to 0.6778.
- Failure counts improved from `answer_miss=59` to 49 and
  `gold_page_location_miss=46` to 29, while `retrieval_gold_miss_top5=4`
  remained unchanged.

Interpretation:

The observed improvement comes from query-aware / structure-aware evidence
packing between page retrieval and Reader input. It is not evidence that the
retrieval model improved, that GRPO was retrained, that the AnswerPolicy prompt
changed, or that the system reached formal benchmark status.

Constraints:

- Keep `--evidence-packing page_children` as the default until additional
  shard and document-type validation supports a global default change.
- Do not change retrieval models, default AnswerPolicy prompt, checkpoints,
  SFT/GRPO training, or gold labels as part of this acceptance.
- Do not treat Phase 4C as a formal MP-DocVQA benchmark.
- Do not enter CDC, Demo, productization, TAT-QA, or VLM work from this
  acceptance alone.
- Detailed report:
  `docs/PHASE4C_CANDIDATE_SPANS_REPORT.md`.

## 2026-06-20: Phase 4C Candidate Evidence Packing Boundary

Decision: add query-aware, structure-aware candidate evidence packing as an
experimental A/B mode named `candidate_spans`, while keeping the accepted
Phase 4B `page_children` evidence packing as the default.

Rationale:

- Phase 4B Gate 4 showed usable Hybrid Top-5 page recall but low reader answer
  and gold-page-location quality.
- The next local change should reduce noisy evidence passed to AnswerPolicy
  without changing retrieval models, default prompts, checkpoints, training
  data, or raw-document ingestion.
- A deterministic rule-based selector is easier to audit for no-gold leakage
  than an LLM evidence selector at this stage.

Constraints:

- `candidate_spans` may only select from Hybrid Top-k pages for the same QA
  document window.
- Candidate selection must not read answers, gold page ids, answer page idx,
  gold page ordinals, or gold page mappings.
- Candidate artifacts are separate from metrics artifacts; metrics may use
  gold page mappings only after candidate artifacts have been built.
- `page_children` remains the default until a real Gate 4 A/B run justifies a
  default change.
- CDC, Demo, model training, retrieval-model changes, and default AnswerPolicy
  prompt changes remain out of scope.

## 2026-06-08: Phase 1 Workflow Integration Scope

Decision: integrate the trained Qwen Answer Policy into the workflow before expanding retrieval or multimodal branches.

Rationale:

- The project already has MP-DocVQA retrieved-reader SFT and grounded GRPO checkpoints.
- The main workflow still used a heuristic answer generator, so checkpoint quality was not represented in the traceable QA chain.
- Prompt construction, JSON parsing, validation, repair, and trace persistence need to be shared by eval and workflow paths before larger retrieval changes.

Constraints:

- `heuristic_answer` remains available only as an explicit local/mock backend.
- Workflow callers must pass an `AnswerPolicy`.
- Repair is bounded to one deterministic pass and cannot access gold answers or gold locations.
- Qwen model paths are configurable through CLI/config/environment usage and are not hard-coded into Python source.
- SQLite stores run summaries and node traces, but full prompts and chain-of-thought are not persisted.

## 2026-06-08: Phase 1 Acceptance

Decision: treat Phase 1 Qwen Answer Policy workflow integration as accepted and move next implementation effort to retrieval enhancement preparation.

Evidence:

- Base, SFT, and GRPO modes run through the same workflow CLI.
- SFT 50-sample workflow eval reached workflow success 1.0, raw JSON 1.0, schema 1.0, Answer F1 0.6715, location accuracy 0.92, and trace persist 1.0.
- GRPO 50-sample workflow eval reached workflow success 1.0, raw JSON 1.0, schema 1.0, Answer F1 0.6769, location accuracy 0.94, and trace persist 1.0.
- SQLite trace inspection successfully recovered the run and ordered node traces.

Follow-up:

- Do not tune prompts around individual low-answer examples in this phase.
- Track remaining answer mistakes as reader extraction errors for later answer-specific supervision or reward refinement.
- The next system-level implementation branch should start retrieval enhancement ablations, beginning with BGE-M3 dense retrieval and fusion design.

## 2026-06-11: Phase 2 MVP Boundary

Decision: start Phase 2 with real-document ingestion, MinerU conversion, and
hybrid retrieval infrastructure before running additional model training.

Rationale:

- Phase 1 already validated that Base/SFT/GRPO answer policies can run through
  the traceable workflow.
- The main project gap is now system shape: accepting real documents, caching
  parsed blocks, building retrievable indexes, and passing top-k evidence into
  the existing answer workflow.
- Dense and reranker model wrappers must fail loudly when model paths or
  packages are missing. A run must not be labeled `hybrid_rerank` unless the
  reranker executed.

Constraints:

- No new SFT/GRPO training in this stage.
- No reward changes or MP-DocVQA split changes.
- BM25 remains available as a baseline.
- The default Phase 1 workflow path remains compatible; the new retriever is
  opt-in through `run_qa_workflow(..., retriever=...)`.
- Local tests use mock/parse-existing fixtures. Real MinerU, BGE-M3, and
  reranker validation must run on AutoDL.

## 2026-06-13: Phase 2A Reranker Backend

Decision: in the current Transformers 5.x server environment, the real
`bge-reranker-v2-m3` path uses `AutoTokenizer` plus
`AutoModelForSequenceClassification` and raw logits for ranking. It does not
default to `FlagReranker.compute_score()`.

Rationale:

- `FlagEmbedding==1.4.0` reranker scoring calls tokenizer APIs that are not
  compatible with the installed `Transformers==5.8.1` tokenizer behavior.
- The sequence-classification path loads the local reranker model with
  `local_files_only=True`, supports explicit devices such as `cuda:1`, and
  records backend, model path, device, dtype, and max length in trace metadata.
- The server real model API smoke and real workflow smoke passed with backend
  `transformers_sequence_classification`.

Constraints:

- Do not silently fall back to keyword reranking for real-model runs.
- Do not downgrade Transformers or patch site-packages to make
  `FlagReranker.compute_score()` work.
- `FlagReranker` may only be revisited as an explicit optional backend after
  compatibility is proven.

## 2026-06-15: Phase 2B-2 Real Document E2E Acceptance

Decision: accept Phase 2B-2 as a real-document scenario integration milestone,
with scenario quality measured and formal benchmark evaluation still deferred.

Evidence:

- The fixed verifier `scripts/verify_phase2b_real_e2e.py` completed on the
  GLOBOCAN Africa 2022 PDF with real MinerU output, BGE-M3, FAISS, BM25, RRF,
  Transformers sequence-classification reranker, Qwen3 GRPO AnswerPolicy, JSON
  validation, location validation, and SQLite trace.
- `sample_count=8`, `completed_count=8`, `no_gold_leakage=true`,
  `no_mock_fallback=true`, `qa_runs=8`, and `tool_traces=49`.
- Retrieval metrics were `Recall@1=0.875`, `Recall@3=0.875`,
  `Recall@5=0.875`, and `MRR=0.875`.
- Answer metrics were `normalized_exact_match=0.625`, `token_f1=0.675`,
  `character_f1=0.7842548076923077`, and `answer_hit=0.625`.
- Location metrics were `block_location_hit=0.875`, `page_location_hit=1.0`,
  `final_location_in_retrieved_top_k=1.0`, and `location_valid_rate=1.0`.

Boundary:

- This is a real-document scenario acceptance result, not a formal DocVQA,
  MP-DocVQA, or general PDF-QA benchmark.
- Do not describe the current metrics as benchmark performance or model-quality
  sufficiency.
- Defer quality optimization. Current known failures are two reader table-column
  selection errors and one large-table retrieval / partial-answer / location
  error.

## 2026-06-15: Phase 3A Focused Evaluation Boundary

Decision: implement a focused fixed-subset evaluation layer instead of
expanding product features or creating a broad ablation matrix.

Rationale:

- Phase 2B-2 accepted the real-document integration path but did not produce a
  formal benchmark.
- The next evidence needed for project presentation is narrow: BM25 vs Hybrid
  retrieval, and SFT vs GRPO over identical fixed evidence.
- Existing retrieval, workflow, AnswerPolicy, metrics, and validators are
  sufficient; Phase 3A should orchestrate them rather than alter algorithms or
  prompts.

Constraints:

- The retrieval comparison must use the same qids, corpus, gold evidence,
  document scope, top-k, query input, and metric code.
- SFT and GRPO must consume the same fixed Hybrid evidence artifact; they must
  not retrieve independently.
- `deterministic_keyword_v1` is recorded only as deterministic query
  normalization, not as a full query-rewrite strategy.
- Local tests may use explicit mock backends, but real focused evaluation
  remains `not_started` until AutoDL runs real BGE-M3, reranker, SFT, and GRPO.
- The result is a fixed-subset evaluation unless an official complete split and
  official scoring protocol are used.

## 2026-06-15: Phase 3A Retrieval Corpus Contract

Decision: do not treat per-QA MP-DocVQA evidence arrays as a legal retrieval
benchmark corpus.

Rationale:

- `scripts/build_mpdocvqa_imdb_subset.py` builds each QA record from IMDb
  `image_name` and `ocr_tokens`, then stores those pages as that record's
  `evidence`.
- `metadata.imdb_doc_pages` and `metadata.total_doc_pages` are retained as
  metadata; the script does not emit a separate canonical per-document OCR
  corpus.
- Server audit found repeated `doc_id` values with multiple evidence
  signatures and partial page coverage, so simply unioning per-QA evidence
  would not be a proven query-independent corpus.

Constraints:

- BM25 vs Hybrid Recall/MRR requires an explicit `--corpus-input` containing
  stable query-independent `EvidenceBlock` records.
- Without that corpus, retrieval evaluation is `blocked` and must fail
  validation with a non-zero exit code.
- Valid reader artifacts may still be used for SFT vs GRPO through
  `--answer-only`, but that path is an AnswerPolicy comparison only and must
  not report retrieval metrics.

## 2026-06-15: Phase 3A MP-DocVQA Corpus Construction

Decision: construct the Phase 3A MP-DocVQA retrieval benchmark as separate
QA, corpus, and manifest artifacts.

Rationale:

- The QA artifact should carry qid, doc_id, question, answer, answer_type, and
  existing `metadata.gold_block_ids`, but no embedded candidate evidence.
- The corpus artifact should carry one stable official-OCR page block per
  canonical document page, using the existing `{page_id}_official_ocr` block ID
  rule.
- Gold mapping must be reused from the source QA artifact when available, or
  from explicit IMDb answer-page metadata; it must not be inferred by searching
  the answer string.

Constraints:

- Server-specific IMDb/OCR paths must be CLI inputs, not tracked constants.
- The generated corpus must pass the Phase 3 runner validator with
  `corpus_is_query_independent=true`, one corpus per doc, no duplicate block
  IDs, non-empty retrieval text, and complete gold block coverage before
  retrieval evaluation can move from `blocked` to `ready`.
- The builder does not run BGE-M3, the reranker, Qwen, or AnswerPolicy smoke.

## 2026-06-16: Unified Training-Inference Answer Protocol

Decision: route SFT dataset construction, GRPO dataset construction,
heuristic AnswerPolicy, Qwen AnswerPolicy, and workflow answer generation
through one evidence-context builder and one checkpoint-compatible prompt
compiler.

Rationale:

- Phase 3 comparisons require the training and inference paths to share prompt
  semantics, evidence ordering, block serialization, and truncation metadata.
- The workflow must persist enough trace data to audit whether a real retrieved
  block reached the model prompt and whether validation or repair changed the
  final answer.

Constraints:

- Do not change retrieval algorithms, top-k, query normalization, reward code,
  checkpoints, or training splits as part of this unification.
- Keep the core answer prompt semantics compatible with the existing SFT/GRPO
  checkpoints.
- Do not persist full prompts, credentials, signed URLs, or private artifacts in
  Git.

## 2026-06-16: Real-Document Acceptance Entry Point

Decision: add a single server acceptance entry point that performs compact
preflight, real-document contract construction, retrieval-only regression, and
optional focused-eval orchestration without loading answer models unless that
stage is explicitly selected.

Rationale:

- The server worktree may contain large untracked data and temporary notebook
  artifacts, so acceptance should reject tracked dirty changes but ignore
  untracked `data/`, `.ipynb_checkpoints`, and scratch files.
- GLOBOCAN is a real-document regression/scenario corpus and should be emitted
  as explicit QA, corpus, document manifest, and benchmark manifest artifacts.
- CDC should be handled as a real-document parsing dependency: ready when
  parsed MinerU output exists, otherwise blocked until server-side MinerU API
  ingestion is run with a runtime token.

Constraints:

- The server command must not install packages, download models, or commit
  generated artifacts.
- It must write long logs under `outputs/`, emit compact JSON, and avoid
  printing or persisting API tokens.
- Real metrics remain `not_started` until AutoDL runs the selected real-model
  stages.

## 2026-06-16: GLOBOCAN Scenario Regression Acceptance

Decision: accept the GLOBOCAN real-document server regression as a scenario
regression acceptance result, while keeping formal benchmark status
`not_started`.

Evidence:

- AutoDL ran `scripts/run_phase3_server_acceptance.py --stage
  real-document-regression` at commit
  `3390bcde1c703c7bd95c567e6da3bdb04591c0d8` with exit code 0.
- The contract remained `evaluation_scope=scenario_regression` and
  `formal_benchmark=false`.
- The run used 1 real PDF, 8 verified scenario QA, and 35 query-independent
  EvidenceBlocks.
- Retrieval compared BM25 against BM25 + BGE-M3 + RRF +
  bge-reranker-v2-m3.
- AnswerPolicy compared SFT and GRPO over identical fixed evidence
  `04536f8fdbd3ea2e6c4a8ef93befd6aa270eb5c5ae700f1edcdacf2eed35adee`.

Retrieval conclusion:

```text
在 GLOBOCAN 8 条真实文档场景回归中，Hybrid + Reranker
主要改善正确证据的首位排序：
Recall@1 从 0.375 提升至 0.875，MRR 从 0.604 提升至 0.875。
Recall@3/5 未提升，说明当前收益主要来自重排，而不是扩大候选覆盖。
```

AnswerPolicy conclusion:

```text
真实文档回归验证了 SFT 与 GRPO adapter 均可通过统一
Training–Inference Contract、Canonical Output 和验证链路运行。

8 条 GLOBOCAN 场景中未观察到 GRPO 相对 SFT 的回答指标提升。
该结果只证明兼容性和无明显回归，不能用于宣称 GRPO 优于 SFT。
```

Constraints:

- Do not describe this result as a formal benchmark.
- Do not claim GRPO is better than SFT from this 8-question scenario result.
- Keep MP-DocVQA retrieval evaluation blocked until a query-independent corpus
  is accepted.
- GRPO vs SFT has now been measured on a larger MP-DocVQA fixed-evidence
  reader artifact; next add CDC as a second real document scenario after
  MinerU output is available.

## 2026-06-16: MP-DocVQA Fixed-Evidence Reader Evaluation Closeout

Decision: record the 150-sample MP-DocVQA SFT vs GRPO run as a
fixed-evidence reader evaluation, not as a formal benchmark and not as a
retrieval evaluation.

Evidence:

- The fixed-evidence safety hotfix at
  `1ef68838210d56e8624b7ef0c0633b705e8ccfe5` passed the server 5-sample
  smoke; the earlier OCR body URL/path false positive did not recur.
- AutoDL then completed 150/150 SFT and 150/150 GRPO samples on
  `data/benchmark/mp_docvqa_imdb_ocr_5000_split/dev.jsonl`.
- Both policies used identical fixed evidence with SHA256
  `8c4d60a189675a4ba52fa61d47db68c070f2f13218b5e73b1a18ded6fceeb940`.
- `evaluation_scope=mpdocvqa_fixed_evidence_reader` and
  `formal_benchmark=false`.

Metrics:

| Metric | SFT | GRPO | Delta |
|---|---:|---:|---:|
| Normalized EM | 0.380000 | 0.386667 | +0.006667 |
| Answer hit | 0.406667 | 0.406667 | 0.000000 |
| Token F1 | 0.483865 | 0.484643 | +0.000778 |
| Character F1 | 0.615299 | 0.625152 | +0.009853 |
| Valid JSON | 1.000000 | 1.000000 | 0.000000 |
| Format valid | 1.000000 | 1.000000 | 0.000000 |
| Block location hit | 0.866667 | 0.893333 | +0.026667 |
| Page location hit | 0.880000 | 0.900000 | +0.020000 |
| Final location in evidence | 1.000000 | 1.000000 | 0.000000 |
| Repair attempted/success | 0.086667 | 0.086667 | 0.000000 |
| Mean latency | 4289.27 ms | 4237.41 ms | -51.86 ms |

Conclusion:

```text
在 150 条相同 fixed evidence 的 MP-DocVQA reader 样本上，
GRPO 相比 SFT 在 block/page 证据定位和 character F1 上有轻微提升，
Normalized EM 仅提高约 0.67 个百分点，Answer Hit 不变。

结果说明 GRPO 没有破坏结构化输出，并表现出有限的 grounding 改善；
不能据此宣称 GRPO 在答案正确率上存在显著优势。
```

Constraints:

- `top_k=20` is only the fixed-evidence reader-evaluation evidence budget over
  the existing reader artifact. It is not an online Retrieval top-k setting and
  must not be used to compute Retrieval Recall/MRR.
- The earlier `top_k=5` smoke failure was not a code defect; qid `64253` had
  its gold block at source-evidence rank 8, so Top-5 truncated gold evidence.
- Do not describe the 150-sample result as a formal benchmark.
- Do not run all 453 MP-DocVQA AnswerPolicy samples for this closeout; the
  150-sample run is sufficient for the current project closure.
- Keep MP-DocVQA retrieval evaluation blocked until an accepted independent
  corpus artifact exists.
- Next priority is the CDC PDF real-document path: MinerU parsing,
  EvidenceBlock ingest, structure-quality acceptance, and candidate scenario
  QA.

## 2026-06-16: Single-GPU Phase 3 Evaluation Default

Decision: default current inference, retrieval, and document-evaluation server
runs to one RTX 4090D 24GB GPU.

Rationale:

- The completed Phase 3 server runs used `cuda:0`; the second GPU did not
  automatically accelerate Qwen3-1.7B fixed-evidence inference.
- Average utilization was limited by single-sample autoregressive generation,
  CPU preprocessing, and serial SFT/GRPO execution.
- The server has been reduced to 1 x RTX 4090D 24GB for current evaluation
  work.

Constraints:

- Do not assume two GPUs improve current inference or retrieval runs.
- Use two GPUs only for heavier training, or after implementing explicit
  SFT/GRPO dual-process parallelism with separate GPU assignment.

## 2026-06-17: Phase 4A Raw MP-DocVQA Foundation

Decision: switch the active milestone to a local raw-document foundation for
MP-DocVQA parquet shards before any MinerU, retrieval, CDC, or model work.

Rationale:

- Phase 3 closed without an accepted raw MP-DocVQA document asset layer, so
  there is still no clean path from original shard rows to standard page
  images, multi-page PDFs, or later parsing inputs.
- The real local shard audit shows that `page_ids`, `answers`, and
  `answer_page_idx` are stored as strings, while images are stored as
  `struct<bytes, path>`, so the raw builder must parse real storage rather than
  rely on nominal schema assumptions.
- The same source `doc_id` may appear with multiple ordered page windows
  because each parquet row carries at most 20 page images; the builder must
  distinguish source-document identity from page-window identity.

Constraints:

- Do not run MinerU, retrieval, Qwen, SFT/GRPO, or CDC in this phase.
- Do not restore all 29 shards in this round.
- Do not let training-overlap concerns block the raw document foundation; a
  light overlap audit is sufficient.
- Keep generated parquet-derived assets under ignored `outputs/` paths and do
  not commit restored images, PDFs, or sample QA outputs.

## 2026-06-17: MP-DocVQA Page-Window Identity

Decision: define the Phase 4A document instance as
`source_doc_id + canonical ordered_page_ids`, not as `source_doc_id` alone.

Rationale:

- ModelScope/Hugging Face previews and the local parquet audit show that the
  same source document may be split into multiple page windows across QA rows.
- Treating `source_doc_id` as the only identity incorrectly turns valid
  windows into false conflicts and drops usable QA/document assets.
- A stable window signature derived from canonical JSON
  `{source_doc_id, ordered_page_ids}` remains reproducible across shards and
  independent of row order.

Constraints:

- Same `source_doc_id` plus different ordered page windows must be preserved as
  separate valid document instances, even when windows overlap.
- Only same `source_doc_id` plus same ordered page window plus different page
  image hashes is a true conflict.
- Do not attempt source-document window union or full-document reconstruction
  in this phase.

## 2026-06-17: Phase 4A Server Acceptance and Phase 4B Entry Boundary

Decision: accept Phase 4A as the raw MP-DocVQA page-window document
foundation, and start Phase 4B as a small-scale MinerU/E2E milestone over a
small accepted window set.

Evidence:

- AutoDL server branch `codex/phase4-mpdocvqa-raw-foundation` ran the accepted
  implementation commit `f3d6237b9f7f53cd9f2a8e21d4441e7f911a7979`.
- The real input shard
  `/root/autodl-tmp/datasets/mp_docvqa/parquet/val-00001-of-00029.parquet`
  had `sha256=493d31bb7b99da676876e4350b27f15ca3e4273518493a09fc799f31d5a3609b`.
- `builder --help`, `py_compile`, real-shard `validate-only`, 5-window sample
  build, and sample self-check all passed with
  `phase4_mpdocvqa_raw_server_smoke_shell_exit_code=0`.
- Real shard audit reached `row_count=179`, `unique_source_doc_count=44`,
  `unique_window_count=61`, `different_window_same_source_doc_count=23`, and
  `conflicting_window_count=0`.
- Accepted sample build reached `document_window_count=5`, `qa_count=12`, and
  `absolute_path_hit_count=0`.

Boundary:

- The accepted Phase 4A artifact is a `page_window` document, not a proven full
  original source document reconstruction.
- `source_doc_id + ordered_page_ids` remains the stable document-window
  identity, and different windows from the same source document remain legal
  independent inputs.
- Cross-shard identity design is implemented, but full multi-shard validation
  is still deferred.

Phase 4B scope:

- Start with only 3-5 accepted page-window documents.
- Cover 1-page, 2-5-page, and 10-20-page windows.
- Prefer the already accepted server sample assets.
- Target flow:
  `page-window PDF -> MinerU -> EvidenceBlock -> page aggregate -> gold page mapping -> page-level retrieval -> AnswerPolicy -> answer / evidence page / trace`.

Constraints:

- Do not process all 29 shards at Phase 4B start.
- Do not redefine page-window artifacts as full source-document ground truth.
- Do not change training, retrieval-model, prompt, or AnswerPolicy code as part
  of the Phase 4A acceptance closeout.

## 2026-06-17: Phase 4B Gate 1 Local Runner Boundary

Decision: implement Gate 1 as a reusable MP-DocVQA page-window ingestion runner
that wraps existing MinerU API, `DocumentIngestionService`, EvidenceBlock,
page aggregate, structure-quality, SQLite, and JSONL utilities.

Status:

```text
Phase 4A -> accepted
Phase 4B -> active
Gate 1 local implementation -> implemented
Gate 1 real MinerU smoke -> not_started
Gate 2 -> blocked_by_gate1
Gate 3 -> blocked_by_gate2
Gate 4 -> blocked_by_gate3
CDC -> not_started
Router/tools -> not_started
Demo/closure -> not_started
```

Rationale:

- Phase 4A already defines page-window identity and deterministic PDF assets.
- Gate 1 only needs to validate the first raw-input path:
  `document.pdf -> MinerU -> EvidenceBlock -> page_documents -> gold page mapping`.
- The runner must not reimplement the MinerU HTTP client, ingestion service,
  EvidenceBlock schema, or SQLite schema.

Constraints:

- `validate-only` must not call MinerU.
- Local tests may use fixture/fake MinerU outputs only.
- Gate 1 is not accepted until the AutoDL live MinerU smoke succeeds.
- Gate 2/3/4, retrieval, Qwen, and expanded windows remain blocked until the
  prior gate returns.
- Continue Phase 4B in the same Codex thread and feature branch:
  `codex/phase4b-mpdocvqa-e2e`.

## 2026-06-17: MinerU Signed Upload Client

Decision: use streaming `requests.put(upload_url, data=file, timeout=(connect,
read))` for MinerU OSS signed URL uploads instead of `urllib.request.Request`
with `data=file_path.read_bytes()`.

Rationale:

- Gate 1 live execution reached MinerU upload URL generation, proving the API
  token and `/api/v4/file-urls/batch` request were valid.
- The existing urllib PUT returned HTTP 403 at the OSS signed URL upload step.
- Independent server diagnosis in the same environment, with the same token,
  same PDF, and same signed URL contract, succeeded with streaming
  `requests.put(..., data=file)`.
- The failure is scoped to the signed upload client implementation, not
  Phase 4A sample assets, upload URL generation, networking, or the PDF.

Constraints:

- Do not send Authorization, MinerU API headers, or explicit Content-Type to
  the signed upload URL.
- Do not modify signed URLs or persist signed URL query parameters.
- Do not load large PDFs into memory for upload.
- Upload failures may report HTTP status, safe OSS `Code`, a truncated OSS
  `Message`, and whether a RequestId existed, but must not include signed URLs,
  tokens, Authorization headers, temporary credentials, or full cloud response
  bodies.

Current status:

```text
Gate 1 real MinerU smoke -> blocked_by_signed_upload_client
Gate 2 -> blocked_by_gate1
Gate 3 -> blocked_by_gate2
Gate 4 -> blocked_by_gate3
```

## 2026-06-17: Phase 4B SQLite JSON Path Audit and Existing Artifact Revalidation

Decision: persisted path audits must parse SQLite JSON columns before scanning
their values, and Gate 2 may revalidate already-ingested artifacts without
calling MinerU.

Rationale:

- Gate 1 single-page ingestion is accepted, and the Gate 2 four-page window is
  accepted from live MinerU output.
- The Gate 2 twenty-page window completed MinerU parsing, EvidenceBlock
  conversion, page document creation, and QA page mapping.
- Its only failed acceptance item was a portability scan hit in
  `sqlite.evidence_blocks.payload_json`.
- The inspected values were OCR text such as `\$34.20`, not local filesystem
  paths. The prior scanner searched serialized JSON strings directly, so JSON
  escaping could make ordinary OCR text look like a UNC prefix.

Constraints:

- Do not modify OCR text, EvidenceBlock content, answers, or source gold labels.
- For SQLite JSON columns, first `json.loads()` valid JSON and recursively scan
  the parsed dict/list/string values. Invalid JSON may use the safe plain-string
  fallback.
- Treat absolute paths as complete string values after trimming, not arbitrary
  substrings inside semantic text.
- Keep path examples compact: where, reason, and a truncated value preview only.
- Existing-artifact revalidation must read current JSON/JSONL/SQLite artifacts,
  recompute portability and acceptance failures, update `acceptance_report.json`,
  and must not upload files, poll MinerU, or re-run ingestion.

Current status:

```text
Gate 1 -> accepted
Gate 2 -> accepted
Gate 3 local implementation -> implemented
Gate 3 server real E2E -> not_started
Gate 4 -> blocked_by_gate3
```

## 2026-06-19: Phase 4B Gate 4 Expanded Regression Accepted

Decision: accept Phase 4B Gate 4 as an expanded MP-DocVQA raw-input E2E
regression over validation shards 1-4, while keeping it explicitly out of the
formal benchmark category.

Accepted scope:

```text
sample_root = outputs/phase4/mpdocvqa_raw_gate4_expanded
ingestion_root = outputs/phase4/mpdocvqa_ingestion
document_count = 26
page_count = 197
qa_count = 90
source_shards = MP-DocVQA val shards 1-4
```

Accepted retrieval-only artifact:

```text
run = outputs/evaluation/phase4b_mpdocvqa_gate4/gate4c_retrieval_only_empty_page_fix
fixed_evidence_hash = 723160441137a42a3cf3b7775f94ffd6dd681cb15ac67bc2c5d2d0bfdc9feab3
BM25 Recall@1/3/5 = 0.6111 / 0.8667 / 0.9111
BM25 MRR = 0.7259
Hybrid Recall@1/3/5 = 0.7333 / 0.9222 / 0.9556
Hybrid MRR = 0.8257
retrieval_gold_miss_top5 = 4
```

Accepted full GRPO E2E artifact:

```text
run = outputs/evaluation/phase4b_mpdocvqa_gate4/gate4_full_grpo
completed_count = 90
failed_count = 0
normalized_exact_match = 0.3333
answer_hit = 0.3444
token_f1 = 0.3689
character_f1 = 0.5235
valid_json_rate = 1.0
format_valid_rate = 1.0
gold_page_location_hit = 0.4889
page_location_hit = 0.4889
block_location_hit = 0.9667
final_location_in_evidence_rate = 1.0
trace_counts.qa_runs = 90
trace_counts.tool_traces = 613
failure_taxonomy = answer_miss:59, gold_page_location_miss:46, retrieval_gold_miss_top5:4
```

Rationale:

- Gate 4 verifies raw-input system stability across document restoration,
  live MinerU ingestion, page mapping, page-level retrieval, fixed evidence,
  GRPO AnswerPolicy execution, validation, and SQLite trace persistence.
- Hybrid retrieval is usable for the expanded sample; Top-5 page recall is
  0.9556 and only 4 QA miss the gold page in Top-5.
- The answer metrics are not high enough to frame this as a quality win.
  Remaining work is mainly Reader answer selection and page-location behavior,
  represented by `answer_miss` and `gold_page_location_miss`.

Constraints:

- Gate 4 is not a formal independent benchmark.
- Do not change retrieval models, AnswerPolicy prompt, checkpoints, or training
  data as part of Gate 4 acceptance.
- `--rank-aware-context` remains diagnostic only; default remains false.
- Future ingestion skip-existing logic must compare current sample QA count
  with both `acceptance_report.qa_count` and `qa_page_mapping.jsonl` row count
  before reusing an existing artifact. Mismatches must revalidate or reingest.
- Future Gate 4 runs must write Gate 4 metadata in summaries/manifests rather
  than retaining the Gate 3 default label.

Current status:

```text
Gate 1 -> accepted
Gate 2 -> accepted
Gate 3 real-model E2E -> accepted
Gate 3A instrumentation -> accepted
Gate 3A default prompt rollback -> accepted
Gate 4A sample manifest -> accepted
Gate 4B ingestion -> accepted
Gate 4C validate-only -> accepted
Gate 4C retrieval-only -> accepted
Gate 4D full GRPO E2E -> accepted
Phase 4B -> accepted
CDC -> not_started
```

## 2026-06-18: Phase 4B Gate 3A Failure Review and Page-Rank Context

Decision: keep Gate 3 active after the first real E2E run and add failure
review instrumentation plus page-rank-aware evidence context before any Gate 4
expansion.

Rationale:

- AutoDL run `gate3_mpdocvqa_20260618_155135` completed the 3-window /
  25-page / 8-QA chain with 8/8 completed samples, valid JSON rate 1.0, format
  valid rate 1.0, and SQLite trace persistence.
- Hybrid page retrieval improved over BM25 and put every gold page into Top-3
  and Top-5, but the reader still often cited a non-gold page or a similar
  wrong field from selected evidence.
- The accepted instrumentation evidence is a compact review artifact showing
  prediction, retrieval top pages, gold page rank, and selected evidence
  context.
- The first attempt to make rank-aware prompt/context the default regressed
  answer quality, so rank-aware context is retained only as an explicit
  diagnostic flag.

Constraints:

- Do not change MinerU ingestion, Phase 4A assets, retrieval model choices,
  training data, checkpoints, or AnswerPolicy output schema.
- Do not add gold labels or reference answers to fixed evidence.
- Keep fixed evidence child blocks ordered by page retrieval rank, parsed page
  number, reading order, and block id.
- Keep retrieval rank/page metadata in fixed evidence artifacts for review, but
  do not inject it into the default AnswerPolicy prompt/context.
- Gate 4 remains blocked until the Gate 3A default full GRPO rerun returns.

Current status:

```text
Gate 1 -> accepted
Gate 2 -> accepted
Gate 3 server real E2E -> accepted
Gate 3A failure review instrumentation -> accepted
Gate 3A rank-aware context/prompt -> implemented
Gate 4 -> blocked
```

## 2026-06-18: Gate 3A Rank-Aware Prompt Default Rollback

Decision: preserve Gate 3A instrumentation and fixed-evidence rank metadata,
but restore the default AnswerPolicy prompt/context shape to Gate 3 behavior.
Rank-aware prompt/context is available only with `--rank-aware-context`.

Rationale:

- Server artifact checks accepted `retrieval_preview.json`,
  `answer_results_preview.json`, compact `failure_cases.jsonl`, summary
  location aliases, and fixed-evidence rank/page metadata.
- The default rank-aware prompt/context rerun reduced normalized exact match
  and answer hit from 0.25 to 0.125, while page location quality did not
  improve.
- The instrumentation is useful for diagnosis, but changing the default prompt
  is not accepted as a quality fix.

Constraints:

- Default full E2E must not add rank-aware extraction rules or rank/page
  metadata to model-facing evidence headers.
- Fixed evidence may retain retrieval rank, parsed page number, and page
  aggregate metadata for artifact review.
- `--rank-aware-context` is a separate diagnostic path and must not be treated
  as the default Gate 3 path.
- Do not change retrieval models, checkpoints, MinerU artifacts, or sample
  scope.

## 2026-06-19: Phase 4B Gate 4 Expanded Raw-Input Regression

Decision: unblock Gate 4 as an expanded MP-DocVQA raw-input E2E regression
after Gate 3A instrumentation and default prompt rollback were accepted on
AutoDL.

Rationale:

- The rollback server run restored the original Gate 3 default metrics while
  preserving accepted instrumentation artifacts.
- The remaining evidence needed is not another prompt tweak on the 8-QA slice,
  but a larger raw-input stability run covering additional page-window
  documents and QA from MP-DocVQA validation shards 1-4.
- Gate 4 should measure whether document-window PDF creation, MinerU ingestion,
  page mapping, page retrieval, fixed evidence, GRPO AnswerPolicy, JSON/format
  validation, and SQLite trace remain stable over 80-100 QA.

Constraints:

- Gate 4 is an expanded raw-input E2E regression, not a formal benchmark.
- Default `rank_aware_context` remains false.
- Do not retrain, change retrieval models, modify OCR text, alter gold labels,
  merge main, start CDC, or process all 29 shards.
- Server execution must be staged: sample manifest, ingestion, validate-only,
  retrieval-only, full GRPO E2E, then compact comparison.

Current status:

```text
Gate 1 -> accepted
Gate 2 -> accepted
Gate 3 real-model E2E -> accepted
Gate 3A instrumentation -> accepted
Gate 3A default prompt rollback -> accepted
Gate 4 local implementation -> implemented
Gate 4A sample manifest -> accepted
Gate 4B ingestion -> accepted
Gate 4C validate-only -> accepted
Gate 4C retrieval-only -> accepted
Gate 4D full GRPO E2E -> accepted
Phase 4B -> accepted
CDC -> not_started
```

## 2026-06-18: Phase 4B Gate 3 Page-Level Retrieval and E2E Boundary

Decision: implement Gate 3 as a selected-document-window page retrieval and
AnswerPolicy regression over the accepted 1/4/20-page MP-DocVQA artifacts.

Rationale:

- The user interaction being modeled is a selected/uploaded document-window QA
  request, so retrieval is scoped to the QA's own document window.
- The primary retrieval unit is `page_document`, not arbitrary child blocks.
- Gold supervision is page-level only and comes from `qa_page_mapping.jsonl`.
- The necessary comparison is BM25 page retrieval versus Hybrid page retrieval
  using BGE-M3 dense retrieval, RRF, and the bge reranker. Both modes share the
  same QA, document-scoped page corpus, query, page IDs, and metrics.
- AnswerPolicy receives only child EvidenceBlocks from Hybrid top-k pages. The
  fixed evidence artifact must not contain gold labels or reference answers.

Constraints:

- `query_rewrite=none` for Gate 3.
- Do not use answer text, gold page labels, or reference answers to select
  context.
- Child evidence ordering is deterministic:
  page retrieval rank, parsed page number, reading order, block id.
- The server run must stage GPU resources: retrieval models run first, retrieval
  results and fixed evidence are persisted, retrieval models are released, then
  Qwen3 GRPO AnswerPolicy is loaded.
- Server commands for Gate 3 are short foreground Bash blocks for Git sync,
  environment preflight, and actual evaluation. Do not use `nohup`, `setsid`,
  background jobs, `tmux`, `kill`, `pkill`, or `exec`.

Current status:

```text
Gate 1 -> accepted
Gate 2 -> accepted
Gate 3 local implementation -> implemented
Gate 3 server real E2E -> not_started
Gate 4 -> blocked_by_gate3
```

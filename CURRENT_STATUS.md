# Current Status

Updated: 2026-06-26

## Phase 4D-C Accepted / Phase 5 Active

Phase 4D-C expanded unseen validation is accepted on MP-DocVQA validation
shards 5-8 using the accepted default `candidate_spans` pipeline. The strict
accepted set contains 77 document windows, 572 pages, and 218 QA. The main
bottleneck is candidate answer extraction and candidate span construction, not
Reader selection. Phase 4D-D candidate answer board generalized improvement is
deferred while Phase 5 starts the personal-use DocAgent MVP track.

Phase 5B P0 deterministic document tools are accepted in
`docagent/tools/document_tools.py`. The tools read from
`DocumentRepository`, `documents.page_count`, and persisted `EvidenceBlock`
payloads. They do not implement Router, `scripts/docagent_cli.py`, final CLI
trace artifact creation, `document_summary`, `table_lookup`, or
`simple_calculation`.

Phase 5C rule-first Router / Planner is accepted in `docagent/router/`.
It returns schema-valid single-step planning decisions from question,
`available_tools`, and optional `document_profile`. It does not execute tools,
call external LLM/VLM APIs, wrap `local_fact_qa`, implement summary/table/
calculation tools, or write final CLI trace artifacts.

Phase 5D local_fact_qa tool wrapper is accepted in
`docagent/tools/local_fact_qa.py`. It reuses `DocumentRepository`,
`run_qa_workflow`, AnswerPolicy, retrieval/evidence context logic, and optional
`TraceRepository`. Local tests cover wrapper behavior, dry-run/fake workflow
boundaries, default heuristic workflow reuse, citation/supporting evidence
fields, SQLite trace persistence, and the accepted Phase 5D-S server smoke.

Phase 5D-S local fact QA smoke support is accepted in
`scripts/run_phase5d_local_fact_qa_smoke.py`. It runs the Phase 5D
`local_fact_qa` wrapper against an existing SQLite `doc_id`, supports dry-run
and non-dry workflow smoke, and writes `summary.json`, `summary.md`,
`results.jsonl`, and `preview.json` under
`outputs/smoke/phase5d_local_fact_qa/<run_id>/`. The accepted server smoke
validates execution stability, not benchmark-level answer quality.

Phase 5F-1 Unified CLI MVP is accepted in `scripts/docagent_cli.py`. The
CLI supports `--db-path`, `--doc-id`, `--file`, `--question`, `--output-dir`,
`--dry-run`, `--list-documents`, and `--limit`. It calls the Phase 5C Router
before dispatching supported tasks, uses Phase 5B deterministic tools for
`document_statistics`, uses page tools for `page_lookup`, and uses Phase 5D
`local_fact_qa` for fact QA. `--file + --question` is now a CLI contract, but
Phase 5F-1 only provided SHA reuse and structured unavailable behavior. The
accepted server CLI smoke validates execution stability only, not
benchmark-level answer quality.

Phase 5F-2 file-to-answer ingestion integration is accepted in
`scripts/docagent_cli.py` with `docagent/parser/text_backend.py`. The CLI can
ingest new UTF-8 `.txt` files through `DocumentIngestionService`, reuse
existing SHA-matched documents, return generated or reused `doc_id`, and
continue through Router dispatch to deterministic tools or `local_fact_qa`.
The accepted server file-to-answer smoke validates lightweight `.txt`
execution stability and SHA reuse, not benchmark-level answer quality.
PDF/image inputs without a configured CLI parser backend return structured
`parser_backend_unavailable`; new-file MinerU-backed PDF ingestion inside
`docagent_cli.py` remains not_started.

Phase 5F-3 MinerU-backed file-to-answer support is accepted in
`scripts/docagent_cli.py` by reusing `MinerUParserBackend`,
`DocumentIngestionService`, `DocumentRegistry`, `DocumentRepository`, Router,
deterministic tools, and `local_fact_qa` dry-run. The implemented path consumes
existing MinerU output through `--parser mineru_existing` and
`--mineru-output-dir` / `--mineru-output`, then writes the same unified JSON
and CLI artifacts. The accepted server smoke validates existing MinerU
output-backed execution, not online MinerU OCR execution or benchmark answer
quality.

Phase 5G CLI regression baseline is accepted in
`scripts/run_phase5g_cli_regression.py`. The runner reads default or JSONL
regression cases, calls `scripts/docagent_cli.py`, validates stdout JSON,
task type, tools used, artifact writing, structured errors, skipped cases, and
known limitations, then writes `regression_cases.jsonl`,
`regression_results.jsonl`, `regression_summary.json`,
`regression_summary.md`, and `preview.json` under
`outputs/regression/phase5g_cli/<run_id>/`. This is an execution stability
baseline, not a benchmark answer-quality report. The accepted server
regression run `phase5g_cli_20260626_022925_9eca480b` completed 8 cases,
recorded 2 unsupported known-limitations cases, failed 0 cases, emitted valid
JSON for all 10 cases, and wrote 9 CLI artifacts without external API, VLM,
training, or full E2E execution.

Phase 5C-2 LLM-assisted Router fallback is accepted in
`docagent/router/llm_client.py`, `docagent/router/llm_router.py`, and
`scripts/docagent_cli.py`. The accepted rule router remains the deterministic
baseline; LLM fallback is disabled by default and requires explicit
`--allow-llm-router` plus environment or `--router-llm-env-file` configuration.
The Router LLM only receives the question, available tools, initial rule plan,
and lightweight document profile. It does not receive full document text,
retrieved evidence, OCR full text, image pixels, user file contents, or
`local_fact_qa` outputs. The LLM-facing output schema is intentionally narrow:
`task_type`, optional `query_rewrite`, optional `selected_tools`, and optional
diagnostics such as confidence / intent labels. `llm_router.py` canonicalizes
that minimal decision into the full internal RouterPlan. Missing or
non-standard confidence is normalized or warned about, but does not by itself
fail validation. Invalid JSON, illegal task type, unavailable tool selection
with no safe fallback, visual-understanding requests, missing config, and API
errors fall back to the rule plan.

Phase 5C-3 Query Planning + Multi-Query Retrieval is implemented in
`docagent/retrieval/query_planner.py`,
`docagent/retrieval/query_generator_rule.py`,
`docagent/retrieval/query_generator_llm.py`, and
`docagent/retrieval/query_fusion.py`, with retrieval integration in
`docagent/retrieval/hybrid_retriever.py`,
`docagent/retrieval/index_manager.py`, and optional CLI exposure in
`scripts/docagent_cli.py`. The rule extractor always produces deterministic
retrieval queries from task type, page/table/image/statistics signals, and
keywords. The LLM expander reuses the Phase 5C-2 OpenAI-compatible Router LLM
configuration and client only for query expansion; it must output a JSON array
of strings and does not answer document questions. Query fusion deduplicates
rule and LLM queries, caps the final list at 8, and preserves rule-query
priority. If LLM config is missing, the API fails, or the LLM output is
invalid, retrieval falls back to rule queries. This phase does not change
Router task classification, `local_fact_qa` answer logic, AnswerPolicy,
ingestion, VLM logic, training, or full GRPO E2E.

Phase 5C-2 accepted server real API smoke evidence:

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
acceptance_boundary = router fallback execution stability, not answer quality
```

Phase 5G accepted server regression evidence:

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
cases_path = /root/autodl-tmp/docagent/outputs/regression/phase5g_cli/phase5g_cli_20260626_022925_9eca480b/regression_cases.jsonl
results_path = /root/autodl-tmp/docagent/outputs/regression/phase5g_cli/phase5g_cli_20260626_022925_9eca480b/regression_results.jsonl
summary_path = /root/autodl-tmp/docagent/outputs/regression/phase5g_cli/phase5g_cli_20260626_022925_9eca480b/regression_summary.json
summary_md_path = /root/autodl-tmp/docagent/outputs/regression/phase5g_cli/phase5g_cli_20260626_022925_9eca480b/regression_summary.md
preview_path = /root/autodl-tmp/docagent/outputs/regression/phase5g_cli/phase5g_cli_20260626_022925_9eca480b/preview.json
```

Status:

```text
Phase 4B -> accepted
Phase 4C local implementation -> accepted
Phase 4C server retrieval-only / packing-only -> accepted
Phase 4C server full GRPO E2E -> accepted
Phase 4D-A local implementation -> implemented
Phase 4D-A server coverage audit -> accepted
Phase 4D-A.1 local implementation -> implemented
Phase 4D-A.1 server refined audit -> accepted
Phase 4D-A.2 local implementation -> implemented
Phase 4D-A.2 server filtering audit -> accepted
Phase 4D-A.3 local implementation -> implemented
Phase 4D-A.3 server failure inspection -> accepted
Phase 4D-A.3.1 local implementation -> implemented
Phase 4D-A.3.1 server refined summary -> accepted
Phase 4D-A.4 local implementation -> implemented
Phase 4D-A.4 server final gap review -> accepted
Phase 4D-B1 local implementation -> implemented
Phase 4D-B1.1 local implementation -> implemented
Phase 4D-B1.1 server validation -> accepted
Phase 4D-B1.2 closeout -> implemented
Phase 4D-B1.3 default pipeline sanity -> accepted
Phase 4D-C expanded unseen validation -> accepted
Phase 4D-C scaffold / command preparation -> ready
Phase 4D-D candidate answer board generalized improvement -> deferred
Phase 5 Personal-use DocAgent MVP -> active
Phase 5A architecture audit and contracts -> accepted
Phase 5B deterministic P0 document tools -> accepted
Phase 5C Router / Planner -> accepted
Phase 5D local_fact_qa wrapper -> accepted
Phase 5D-S local_fact_qa smoke runner -> accepted
Phase 5D-S server real-model smoke -> accepted
Phase 5F-1 Unified CLI MVP -> accepted
Phase 5F-1 server CLI smoke -> accepted
Phase 5F-2 file-to-answer ingestion integration -> accepted
Phase 5F-2 server file-to-answer smoke -> accepted
Phase 5F-3 MinerU-backed file-to-answer implementation -> accepted
Phase 5F-3 server smoke -> accepted
Phase 5G CLI regression baseline -> accepted
Phase 5G server regression -> accepted
Phase 5C-2 LLM-assisted Router fallback -> accepted
Phase 5C-3 Query Planning + Multi-Query Retrieval -> implemented
Phase 5E Document Summary MVP -> not_started
Phase 5F full CLI acceptance -> not_started
CDC -> not_started
MVP CLI / trace integration -> not_started
Demo/closure -> not_started
```

Phase 4D-B1.3 accepted server sanity:

```text
candidate_evidence_completeness.qa_count = 90
candidate_evidence_completeness.candidate_evidence_count = 90
candidate_evidence_completeness.qid_set_match = true
candidate_evidence_completeness.missing_qid_count = 0
candidate_evidence_completeness.extra_qid_count = 0
candidate_evidence_completeness.duplicate_candidate_qid_count = 0
table_index_enhancement_enabled = false
candidate_span_answer_coverage = 0.7444444444444445
candidate_answer_coverage_all = 0.5222222222222223
candidate_answer_coverage_top1 = 0.23333333333333334
candidate_answer_coverage_top5 = 0.3888888888888889
candidate_answer_coverage_top20 = 0.45555555555555555
candidate_answer_no_gold_leakage = true
completeness_ok = true
table_index_enhancement_default_disabled_ok = true
coverage_matches_phase4c_baseline = true
accepted = true
```

Phase 5D-S accepted server smoke evidence:

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

The warning does not block smoke acceptance. It records that the
`evidence_packing` option is deferred to the existing workflow path.

Real-model smoke result preview:

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

Phase 5F-1 accepted server CLI smoke evidence:

```text
branch = codex/phase5f1-unified-cli-mvp
commit = b7e92c89908ce57517f145e18cd6ca1b702a300e
db_path = outputs/docagent.db
doc_id = c1fc1c5e040ec894
list_documents_run_id = docagent_cli_20260625_035337_52161dae
list_documents_status = success
list_documents_document_count = 2
list_documents_key_doc_page_count = 5
list_documents_key_doc_parse_status = parsed
list_documents_key_doc_index_status = ready
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
local_fact_qa_dry_run_citations_count = 5
local_fact_qa_dry_run_supporting_evidence_ids_count = 5
local_fact_qa_dry_run_warning = dry_run_no_answer_generated
local_fact_qa_real_run_id = docagent_cli_20260625_035621_145b69a9
local_fact_qa_real_status = success
local_fact_qa_real_tool_run_id = 341437e6-7976-4a2f-a7b5-2dac762960d0
local_fact_qa_real_citations_count = 5
local_fact_qa_real_supporting_evidence_ids_count = 5
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

Phase 5F-2 implemented local file-to-answer ingestion:

```text
branch = codex/phase5f2-file-ingestion-cli
entrypoint = scripts/docagent_cli.py
parser_backend = docagent/parser/text_backend.py
new_lightweight_file_ingestion = .txt
ingestion_service_reused = DocumentIngestionService
document_registry_reused = DocumentRegistry
sqlite_repository_reused = DocumentRepository
sha256_reuse_supported = true
generated_or_reused_doc_id_returned = true
source_was_ingested_returned = true
source_reused_existing_returned = true
summary_used_file_ingestion = true
summary_reused_existing_document = true
summary_ingestion_status = true
summary_ingestion_error = true
structured_errors = file_not_found, parser_backend_unavailable, unsupported_file_type, file_ingestion_failed
page_metadata_inconsistent_warning = implemented
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
```

Phase 5F-2 accepted server file-to-answer smoke evidence:

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

Known Phase 5F-2 limitations:

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
```

Phase 5F-3 accepted MinerU-backed file-to-answer smoke:

```text
branch = codex/phase5f3-mineru-file-cli-smoke
implementation_commit = 3eaf488cd7870af2e64dcd74f0f807edd8a1cb01
entrypoint = scripts/docagent_cli.py
parser_backend = docagent/parser/mineru_backend.py
supported_parser_mode = mineru_existing / parse_existing
optional_parser_mode = mineru / local_cli when MinerU CLI is installed separately
existing_mineru_output_arg = --mineru-output-dir / --mineru-output
server_status = success
tested_file_type = pdf
tested_sample_path = data/real_documents/globocan_africa_2022/source/original.pdf
tested_mineru_output = data/real_documents/globocan_africa_2022/mineru_raw
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
metadata_consistency_fields = documents.page_count, page_documents count, max evidence page, max citation page
metadata_consistency_warning = page_metadata_inconsistent
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
acceptance_boundary = existing MinerU output-backed execution smoke, not online MinerU OCR execution or benchmark answer quality
```

Known Phase 5F-3 limitations:

```text
Phase 5F-3 accepts existing MinerU output-backed file-to-answer execution.
Online MinerU OCR/parser execution from raw PDF remains a later task.
document_summary is not implemented; summary-like questions may fall back to
local_fact_qa dry-run with warnings.
local_fact_qa answer quality is not benchmark-validated by this smoke.
The GLOBOCAN sample structure_quality is passed_with_warnings.
```

Current conclusion:

- Phase 4C `candidate_spans` is accepted.
- Phase 4D-A diagnostics and failure attribution tooling are accepted as
  diagnostic infrastructure.
- Phase 4D-B1.1 candidate evidence completeness fix is accepted and retained.
- Phase 4D-B1 table/index enhancement is not accepted as default; it remains
  experimental behind `--enable-table-index-packing`.
- Phase 4D-B1.3 default pipeline sanity is accepted.
- Phase 4D-C expanded unseen validation is accepted.
- Candidate-ID Reader remains postponed.
- Phase 4D-D candidate answer board generalized improvement is deferred.
- Phase 5 Personal-use DocAgent MVP is active.
- Phase 5A architecture audit and contracts are accepted.
- Phase 5B P0 deterministic tools are accepted from SQLite document
  metadata and EvidenceBlock payloads.
- Phase 5C rule-first Router / Planner is accepted without external LLM API
  calls or tool execution.
- Phase 5D `local_fact_qa` wrapper is accepted as a callable tool interface.
- Phase 5D-S smoke runner and server real-model smoke are accepted as execution
  stability evidence, not as a benchmark-level answer-quality result.
- Phase 5F-1 unified CLI MVP is accepted with Router dispatch,
  deterministic tools, page lookup, local_fact_qa, list-documents, and a
  structured `--file` contract.
- Phase 5F-1 server CLI smoke is accepted as execution-stability evidence, not
  as benchmark-level answer-quality evidence.
- Phase 5F-2 file-to-answer ingestion integration and server smoke are
  accepted for UTF-8 `.txt` files and SHA reuse, with structured failures for
  unsupported parser paths.
- Phase 5F-3 MinerU-backed file-to-answer implementation and server smoke are
  accepted for existing MinerU output-backed execution.
- Phase 5G CLI regression baseline and server regression are accepted as
  execution-stability evidence, not benchmark answer-quality evidence.
- Phase 5C-2 LLM-assisted Router fallback is accepted after real API smoke.
- Phase 5C-3 Query Planning + Multi-Query Retrieval is implemented with
  rule-first query extraction, optional LLM query expansion, multi-query BM25 /
  dense retrieval fusion, and CLI opt-in via `--enable-query-planning`.
- Phase 5E document_summary, table lookup, simple calculation, online MinerU
  OCR execution, and local_fact_qa answer quality improvement remain
  not_started.

Phase 4D-C accepted server result:

```text
source_shards = MP-DocVQA validation shards 5-8
raw_sample = 85 document windows / 250 QA
strict_accepted_sample = 77 document windows / 572 pages / 218 QA
strict_sample_root = outputs/phase4/mpdocvqa_raw_phase4d_c_shards5_8_strict_accepted
output_root = outputs/evaluation/phase4d_c_expanded_unseen_strict
retrieval_run = phase4d_c_retrieval_candidate_spans
candidate_answer_run = phase4d_c_candidate_answer_coverage
failure_inspection_run = phase4d_c_failure_inspection_refined_cd
candidate_span_gap_review_run = phase4d_c_candidate_span_gap_review_cd
```

Step C accepted retrieval-only / candidate_spans:

```text
candidate_evidence_count = 218 / 218
qid_set_match = true
table_index_enhancement_enabled = false
no_gold_leakage = true
gold_page_has_candidate_span_rate = 0.9128
candidate Recall@1/3/5 = 0.7248 / 0.8945 / 0.9128
candidate MRR = 0.8099
```

Step D accepted candidate answer diagnostics:

```text
candidate_span_answer_coverage = 0.7523
candidate_answer_coverage_all = 0.4266
candidate_answer_coverage_top20 = 0.3991
candidate_answer_no_gold_leakage = true
bucket_A = 19
bucket_C = 43
bucket_D = 72
bucket_G = 84
```

Step E accepted failure attribution:

```text
extraction_rule_gap = 72
candidate_span_or_normalization_gap = 38
reader_selection_gap = 5
table_or_index_span_gap = 14
candidate_span_selection_gap = 10
candidate_span_partial_context_gap = 9
page_number_or_content_lookup_gap = 5
```

Phase 4D-C interpretation:

- The accepted default `candidate_spans` path remains stable on the strict
  unseen set.
- Candidate answer coverage is lower than the 90-sample probe
  (`all: 0.5222 -> 0.4266`, `top20: 0.4556 -> 0.3991`), so candidate board
  quality is a real expanded-set bottleneck.
- Candidate-ID Reader remains postponed because reader/reranking attribution
  is only 5 cases versus 72 extraction cases and 38 span cases.
- Optional full GRPO E2E remains postponed until candidate answer board quality
  improves.

Phase 4D-C scaffold / command preparation:

- Branch started from `origin/main`:
  `codex/phase4d-c-expanded-unseen-validation`.
- Goal is expanded unseen validation on MP-DocVQA validation shards 5-8, not
  further 90-sample probe tuning.
- Existing scripts are sufficient for Step A-E command preparation:
  `build_phase4b_expanded_sample.py`, `run_phase4b_mpdocvqa_ingestion.py`,
  `run_phase4b_mpdocvqa_e2e.py`,
  `analyze_phase4d_candidate_answer_coverage.py`, and
  `export_phase4d_failure_inspection.py`.
- No code changes were required for this scaffold round.
- Default pipeline remains accepted `candidate_spans` with
  `rank_aware_context = false`, table/index enhancement disabled, no
  Candidate-ID Reader, no prompt tuning, and no training.
- Candidate-ID Reader remains postponed until expanded unseen diagnostics show
  reader-selection failures dominate after candidate coverage issues are
  resolved.

Phase 4D-A accepted server audit:

```text
sample_count = 90
candidate_span_answer_coverage = 0.7444
candidate_answer_coverage = 0.4556
mean_candidate_answer_count = 79.5889
mean_unique_candidate_answer_count = 49.9889
mean_same_type_distractor_count = 22.7444
mean_numeric_distractor_count = 60.4444
no_candidate_answer_count = 0
candidate_answer_no_gold_leakage = true
bucket_A_retrieval_gold_miss_top5 = 4
bucket_C_gold_answer_not_in_candidate_spans = 22
bucket_D_gold_answer_in_candidate_spans_but_not_extracted = 25
bucket_E_gold_answer_in_candidate_answers_but_model_answer_wrong = 13
bucket_F_gold_answer_in_candidate_answers_and_model_answer_correct = 26
```

Interpretation:

- Do not enter Candidate-ID Grounded Reader directly from this result.
- Improve candidate answer extraction, normalization, ranking, and top-k
  coverage metrics first.
- `D=25` is the main extraction-improvement opportunity.
- `C=22` still requires candidate span improvement.
- `E=13` remains later Reader or candidate-selection work.

Phase 4D-A.1 implemented boundary:

- heading/title, city/state/location, quarter short-form, key-value,
  organization/company/board, and source/footer extraction improvements;
- rank, top-k flags, duplicate penalty, generic numeric penalty, and long-text
  penalty on candidate answers;
- all/top1/top3/top5/top10/top20 coverage metrics;
- limited top-k board artifacts for future Candidate-ID Reader design;
- `bucket_transition_estimate.json` for D-bucket extraction-improvement
  potential.

Phase 4D-A.1 accepted server audit:

```text
sample_count = 90
candidate_span_answer_coverage = 0.7444
candidate_answer_coverage = 0.5222
candidate_answer_coverage_all = 0.5222
candidate_answer_coverage_top1 = 0.2222
candidate_answer_coverage_top3 = 0.3333
candidate_answer_coverage_top5 = 0.3778
candidate_answer_coverage_top10 = 0.4556
candidate_answer_coverage_top20 = 0.5000
mean_candidate_answer_count = 105.2889
mean_unique_candidate_answer_count = 52.2333
mean_top20_candidate_answer_count = 17.5222
mean_same_type_distractor_count = 26.0556
mean_numeric_distractor_count = 73.7444
bucket_A = 4
bucket_B = 0
bucket_C = 22
bucket_D = 21
bucket_E = 14
bucket_F = 29
bucket_G = 0
candidate_answer_no_gold_leakage = true
```

Phase 4D-A.2 implemented boundary:

- preserve all candidates for `candidate_answer_coverage_all`;
- add top-k eligibility, filter reasons, and stronger penalties for generic
  numeric, type mismatch, duplicate, near-duplicate, long text, and noisy text;
- select `candidate_answers_topk.jsonl` through type-aware top-k selection;
- add top-k filtering metrics and `refinement_comparison.json`.

Phase 4D-A.2 accepted server audit:

```text
sample_count = 90
candidate_span_answer_coverage = 0.7444
candidate_answer_coverage_all = 0.5222
candidate_answer_coverage_top1 = 0.2333
candidate_answer_coverage_top3 = 0.3111
candidate_answer_coverage_top5 = 0.3889
candidate_answer_coverage_top10 = 0.4333
candidate_answer_coverage_top20 = 0.4556
mean_candidate_answer_count = 105.2889
mean_unique_candidate_answer_count = 52.2333
mean_ranked_candidate_answer_count = 68.9222
mean_top20_candidate_answer_count = 13.6111
mean_topk_numeric_candidate_count = 5.3111
topk_retention_ratio = 0.1293
topk_numeric_ratio = 0.3902
bucket_A = 4
bucket_B = 0
bucket_C = 22
bucket_D = 21
bucket_E = 14
bucket_F = 29
bucket_G = 0
```

Phase 4D-A.3 implemented boundary:

- export `failure_inspection_cases.jsonl`, preview, summary, and C/D/E
  bucket-specific JSONL files;
- include gold answers only in the inspection debug artifact;
- keep `candidate_answers.jsonl` and `candidate_answers_topk.jsonl` gold-field
  free;
- add automatic diagnosis hints for candidate span, extraction, and
  Reader/candidate-selection gaps.

Phase 4D-A.3 accepted server inspection:

```text
artifacts = failure_inspection_cases.jsonl,
            bucket_C_cases.jsonl,
            bucket_D_cases.jsonl,
            bucket_E_cases.jsonl,
            failure_inspection_summary.json,
            failure_inspection_summary.md
```

Phase 4D-A.3.1 implemented boundary:

- add `bucket_answer_hit_breakdown` and
  `bucket_candidate_coverage_breakdown` to `failure_inspection_summary.json`;
- add `true_failure_action_counts`;
- add `failure_inspection_refined_cases.jsonl`,
  `failure_inspection_refined_summary.json`, and
  `failure_inspection_refined_summary.md`;
- keep refined artifacts audit-only and out of Reader input.

Phase 4D-A.3.1 accepted server refined inspection:

```text
candidate_span_or_normalization_gap = 21
extraction_rule_gap = 10
no_final_failure = 11
normalization_or_metric_gap = 5
reader_selection_gap = 7
topk_filtering_gap = 3
inspect_candidate_spans_or_normalization = 21
improve_candidate_answer_extraction = 10
candidate_id_reader_or_deterministic_selection = 7
improve_type_aware_topk_filtering = 3
inspect_answer_normalization = 5
no_action_final_answer_already_correct = 11
```

Phase 4D-A.4 implemented boundary:

- export only statistics, subtype labels, preview, summary, and decision
  guidance for `candidate_span_or_normalization_gap` cases;
- write `candidate_span_gap_cases.jsonl`,
  `candidate_span_gap_preview.json`, `candidate_span_gap_summary.json`, and
  `candidate_span_gap_summary.md`;
- split cases into the allowed subtypes:
  `normalization_or_metric_gap`, `candidate_span_selection_gap`,
  `candidate_span_partial_context_gap`, `table_or_index_span_gap`,
  `page_number_or_content_lookup_gap`, `ocr_or_parsing_gap`, and
  `unclear_mixed_gap`;
- mark all cases `should_not_patch_specific_qid = true`.

Phase 4D-A.4 decision boundary:

- No per-qid or per-document repairs are allowed.
- If one subtype dominates and has a generic repair path, implement one narrow
  generic fix.
- If subtypes are dispersed, stop tuning this 90-sample probe and expand
  validation coverage.
- Candidate-ID Reader remains postponed.

Phase 4D-A.4 accepted server final diagnostic:

```text
total_candidate_span_or_normalization_gap = 21
normalization_or_metric_gap = 0
candidate_span_selection_gap = 5
candidate_span_partial_context_gap = 5
table_or_index_span_gap = 10
page_number_or_content_lookup_gap = 1
ocr_or_parsing_gap = 0
unclear_mixed_gap = 0
```

Phase 4D-B1 implemented boundary:

- add generic table/index question hint detection;
- add table/index span scoring bonuses for field-label overlap, percentage
  values, parenthesized index values, field-value rows, table/list-like rows,
  and same-line label/value/parenthesized-index evidence;
- retain table/index neighbor context, including adjacent rows and table
  header-like blocks;
- add aggregate diagnostics for table/index candidate span counts, answer
  coverage, top-span field-value presence, neighbor context, and
  parenthesized-index span counts.

Phase 4D-B1 server sanity triage:

```text
qa_qid_count = 90
baseline_qid_count = 90
b1_qid_count = 9
qa_missing_from_b1 = 81
baseline_b1_qid_overlap = 9
baseline row_count = 90
b1 row_count = 9
baseline sample_count = 90
b1 sample_count = 9
```

Root cause:

- The server validation command did not pass an explicit Gate 4 doc-id
  manifest.
- The runner fell back to `DEFAULT_DOC_IDS`, the three historical Gate 3
  documents, instead of inferring all document windows from the active
  expanded `sample_root/qa.jsonl`.

Phase 4D-B1.1 accepted boundary:

- infer doc scope from `sample_root/qa.jsonl` when no explicit doc scope is
  provided;
- preserve original candidate_spans fallback for non-table/index questions;
- add `candidate_evidence_completeness` to summary and candidate packing
  metrics;
- fail before writing candidate evidence if candidate records do not exactly
  match the loaded QA qid set.

Phase 4D-B1.1 server validation:

```text
candidate_evidence_completeness.qa_count = 90
candidate_evidence_completeness.candidate_evidence_count = 90
candidate_evidence_completeness.qid_set_match = true
candidate_evidence_completeness.missing_qid_count = 0
candidate_evidence_completeness.extra_qid_count = 0
candidate_span_answer_coverage = 0.7444
candidate_answer_coverage_all = 0.5222
candidate_answer_coverage_top20 = 0.4556
candidate_answer_no_gold_leakage = true
```

Phase 4D-B1.2 closeout:

- B1 table/index enhancement failed acceptance on the 90-sample probe: it
  reduced `table_or_index_span_gap` only from 10 to 8, did not improve overall
  candidate coverage, and shifted `page_number_or_content_lookup_gap` from 1
  to 4.
- The B1.1 completeness fix is retained.
- Table/index scoring and neighbor-context enhancement are disabled by default
  and kept experimental behind `--enable-table-index-packing`.
- A.4 remains the final diagnostic split for the 90-sample probe. No further
  per-case tuning on this probe is allowed.
- Next step: larger unseen validation using the accepted pipeline and existing
  diagnostics.
- Candidate-ID Reader remains postponed.

Unchanged boundary:

- Reader prompts, AnswerPolicy, retrieval models, MinerU, checkpoints, reward,
  training data, CDC, Demo, and global `candidate_spans` default remain
  unchanged.
- Phase 4D-B1.1 server validation is accepted.

## Phase 4D-A Local Implementation

Phase 4D-A adds an audit layer after the accepted Phase 4C
`candidate_spans` evidence packing path. It extracts typed candidate answers
from candidate spans and measures whether gold answers are covered by spans,
extracted answers, ranks, and error buckets.

Status:

```text
Phase 4B -> accepted
Phase 4C local implementation -> accepted
Phase 4C server retrieval-only / packing-only -> accepted
Phase 4C server full GRPO E2E -> accepted
Phase 4D-A local implementation -> implemented
Phase 4D-A server coverage audit -> accepted
Phase 4D-A.1 local implementation -> implemented
Phase 4D-A.1 server refined audit -> accepted
Phase 4D-A.2 local implementation -> implemented
Phase 4D-A.2 server filtering audit -> accepted
Phase 4D-A.3 local implementation -> implemented
Phase 4D-A.3 server failure inspection -> accepted
Phase 4D-A.3.1 local implementation -> implemented
Phase 4D-A.3.1 server refined summary -> accepted
Phase 4D-A.4 local implementation -> implemented
Phase 4D-A.4 server final gap review -> accepted
Phase 4D-B1 local implementation -> implemented
Phase 4D-B1.1 local implementation -> implemented
Phase 4D-B1.1 server validation -> accepted
Phase 4D-B1.2 closeout -> implemented
Phase 4D-B1.3 default pipeline sanity -> accepted
Phase 4D-C expanded unseen validation -> accepted
CDC -> not_started
Router/tools -> not_started
Demo/closure -> not_started
```

Implemented boundary:

- deterministic rule-based extraction for date, percentage, index, source,
  heading, numeric, and short text candidates;
- candidate answer board artifacts and preview;
- coverage metrics for candidate spans, candidate answers, rank distribution,
  and distractor counts;
- error buckets A-G separating retrieval miss, span coverage miss, extraction
  miss, Reader wrong, Reader correct, and unclear cases;
- automatic no-gold-leakage checks for candidate answer artifacts.

Unchanged boundary:

- default `--evidence-packing page_children` remains unchanged;
- Phase 4C `candidate_spans` remains an accepted experimental and recommended
  mode, not a global default;
- Reader prompts, AnswerPolicy, retrieval models, MinerU, checkpoints, reward,
  training data, CDC, and Demo remain unchanged;
- Phase 4D-A diagnostics and failure attribution tooling through Phase
  4D-A.4 are accepted as diagnostic infrastructure.

## Phase 4C Accepted

Phase 4C adds an experimental multi-granularity evidence packing path on top
of the accepted Phase 4B Gate 4 page-level retrieval chain.

Status:

```text
Phase 4B -> accepted
Phase 4C local implementation -> accepted
Phase 4C server retrieval-only / packing-only -> accepted
Phase 4C server full GRPO E2E -> accepted
Phase 4D-A local implementation -> implemented
Phase 4D-A server coverage audit -> accepted
Phase 4D-A.1 local implementation -> implemented
Phase 4D-A.1 server refined audit -> accepted
Phase 4D-A.2 local implementation -> implemented
Phase 4D-A.2 server filtering audit -> accepted
Phase 4D-A.3 local implementation -> implemented
Phase 4D-A.3 server failure inspection -> accepted
Phase 4D-A.3.1 local implementation -> implemented
Phase 4D-A.3.1 server refined summary -> accepted
Phase 4D-A.4 local implementation -> implemented
Phase 4D-A.4 server final gap review -> accepted
Phase 4D-B1 local implementation -> implemented
Phase 4D-B1.1 local implementation -> implemented
Phase 4D-B1.1 server validation -> accepted
Phase 4D-B1.2 closeout -> implemented
Phase 4D-B1.3 default pipeline sanity -> accepted
Phase 4D-C expanded unseen validation -> accepted
CDC -> not_started
Router/tools -> not_started
Demo/closure -> not_started
```

Accepted boundary:

- default `--evidence-packing page_children` keeps the accepted Phase 4B fixed
  evidence behavior;
- `--evidence-packing candidate_spans` is an accepted experimental and
  recommended evidence packing mode for the Gate 4 style raw-input E2E path;
- candidate artifacts and metrics are written separately from answer/gold
  metrics;
- server retrieval-only / packing-only reached `no_gold_leakage=true`;
- retrieval models, AnswerPolicy prompt defaults, checkpoints, and training
  data are unchanged;
- Phase 4C is not a formal MP-DocVQA benchmark;
- setting `candidate_spans` as a global default requires more shard and
  document-type validation.

Accepted server artifacts:

```text
baseline_run = outputs/evaluation/phase4b_mpdocvqa_gate4/gate4_full_grpo
candidate_retrieval_only_run = outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_retrieval_only
candidate_full_grpo_run = outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_full_grpo
candidate_fixed_evidence_hash = 75a0fcb3f7e0c847d64a767a6a7116ec975a88b7c4ec3c48f54d70bd2f164bba
```

Compact A/B result:

| Metric | page_children | candidate_spans | Delta |
|---|---:|---:|---:|
| normalized_exact_match | 0.3333 | 0.4111 | +0.0778 |
| answer_hit | 0.3444 | 0.4556 | +0.1111 |
| token_f1 | 0.3689 | 0.4628 | +0.0939 |
| character_f1 | 0.5235 | 0.6341 | +0.1106 |
| gold_page_location_hit | 0.4889 | 0.6778 | +0.1889 |
| block_location_hit | 0.9667 | 1.0000 | +0.0333 |
| answer_miss | 59 | 49 | -10 |
| gold_page_location_miss | 46 | 29 | -17 |
| retrieval_gold_miss_top5 | 4 | 4 | 0 |

Interpretation:

Phase 4C shows that query-aware / structure-aware candidate evidence packing
improves Reader grounding and answer extraction under the same retrieval and
AnswerPolicy setting. Hybrid retrieval metrics stayed unchanged, so the gain
comes from reorganizing Reader input evidence rather than retrieval-model
changes, prompt changes, or retraining.

Detailed report:

```text
docs/PHASE4C_CANDIDATE_SPANS_REPORT.md
```

## Phase 4B Accepted

Phase 4A remains accepted. Phase 4B expanded raw-input regression is accepted
on `main` after the single feature branch `codex/phase4b-mpdocvqa-e2e` was
fast-forwarded.

Canonical status labels in this file use the repository vocabulary:
`not_started`, `implemented`, `ready`, `mock_verified`,
`server_dependency_ready`, `real_model_verified`, `benchmark_evaluated`,
`accepted`, `frozen`, `blocked`, and `blocked_by_missing_mineru_output`.
Historical metric descriptions below are evidence summaries, not current
canonical status labels.

Current Phase 4 status:

```text
Phase 4A -> accepted
Phase 4B -> accepted
Gate 1 local implementation -> implemented
Gate 1 -> accepted
Gate 2 -> accepted
Gate 3 local implementation -> implemented
Gate 3 server real E2E -> accepted
Gate 3A failure review instrumentation -> accepted
Gate 3A rank-aware context/prompt -> implemented
Gate 3A default prompt rollback -> accepted
Gate 4 local implementation -> implemented
Gate 4A sample manifest -> accepted
Gate 4B ingestion -> accepted
Gate 4C validate-only -> accepted
Gate 4C retrieval-only -> accepted
Gate 4D full GRPO E2E -> accepted
Phase 4C local implementation -> accepted
Phase 4C server retrieval-only / packing-only -> accepted
Phase 4C server full GRPO E2E -> accepted
Phase 4D-A local implementation -> implemented
Phase 4D-A server coverage audit -> accepted
Phase 4D-A.1 local implementation -> implemented
Phase 4D-A.1 server refined audit -> accepted
Phase 4D-A.2 local implementation -> implemented
Phase 4D-A.2 server filtering audit -> accepted
Phase 4D-A.3 local implementation -> implemented
Phase 4D-A.3 server failure inspection -> accepted
Phase 4D-A.3.1 local implementation -> implemented
Phase 4D-A.3.1 server refined summary -> accepted
Phase 4D-A.4 local implementation -> implemented
Phase 4D-A.4 server final gap review -> accepted
Phase 4D-B1 local implementation -> implemented
Phase 4D-B1.1 local implementation -> implemented
Phase 4D-B1.1 server validation -> accepted
Phase 4D-B1.2 closeout -> implemented
Phase 4D-B1.3 default pipeline sanity -> accepted
Phase 4D-C expanded unseen validation -> accepted
CDC -> not_started
Router/tools -> not_started
Demo/closure -> not_started
```

Gate 1 local implementation adds a reusable MP-DocVQA page-window ingestion
runner for:

```text
Phase 4A sample assets
-> existing MinerU API client
-> existing DocumentIngestionService
-> EvidenceBlock
-> page_documents
-> structure quality
-> QA page mapping
-> compact acceptance report
```

Gate 1 single-page live MinerU ingestion is accepted. Gate 2 accepted the
representative 1/4/20-page windows after existing-artifact revalidation fixed
the SQLite JSON path-scan false positive. Gate 3 real E2E completed on AutoDL
for 3 windows / 25 pages / 8 QA with valid JSON and trace persistence, but
Reader quality remains under review because the model often selects a non-gold
page or similar field from the retrieved top-k pages. Gate 3A local
instrumentation was accepted after artifact checks. The rank-aware prompt and
context default changed reader behavior and is now opt-in only via
`--rank-aware-context`; default full E2E returns to the Gate 3 prompt/context
shape. Gate 4 expanded raw-input E2E regression is now accepted. Gate 4 is not
a formal benchmark and should be read as stability, retrieval, answer, trace,
and failure distribution evidence over the expanded sample.

Gate 4 accepted sample:

```text
sample_root = outputs/phase4/mpdocvqa_raw_gate4_expanded
ingestion_root = outputs/phase4/mpdocvqa_ingestion
source_shards = MP-DocVQA val shards 1-4
document_count = 26
page_count = 197
qa_count = 90
```

Gate 4C retrieval-only:

```text
run = outputs/evaluation/phase4b_mpdocvqa_gate4/gate4c_retrieval_only_empty_page_fix
fixed_evidence_hash = 723160441137a42a3cf3b7775f94ffd6dd681cb15ac67bc2c5d2d0bfdc9feab3
BM25 Recall@1/3/5 = 0.6111 / 0.8667 / 0.9111
BM25 MRR = 0.7259
Hybrid Recall@1/3/5 = 0.7333 / 0.9222 / 0.9556
Hybrid MRR = 0.8257
retrieval_gold_miss_top5 = 4
```

Gate 4D full GRPO E2E:

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

Interpretation:

- Gate 4 is an expanded raw-input regression, not a strict independent
  benchmark.
- Flow stability is accepted: ingestion, page mapping, page retrieval, fixed
  evidence, GRPO AnswerPolicy JSON/format validation, and SQLite trace all ran
  through.
- Hybrid retrieval is usable on the expanded sample, with Top-5 page recall
  0.9556.
- Answer quality remains limited by `answer_miss` and
  `gold_page_location_miss`.
- `--rank-aware-context` remains diagnostic only and defaults to false.
- Gate 4 artifacts are server-side acceptance outputs. Missing local mirrors
  under `outputs/phase4/mpdocvqa_raw_gate4_expanded`,
  `outputs/phase4/mpdocvqa_ingestion`, or
  `outputs/evaluation/phase4b_mpdocvqa_gate4/` are an artifact sync boundary,
  not a missing main-branch code path.

## Phase 4A Accepted

Phase 3 is accepted and frozen. Its evaluation implementation, metrics, and
conclusions remain historical and unchanged.

Phase 4A server acceptance is complete at commit
`f3d6237b9f7f53cd9f2a8e21d4441e7f911a7979` on branch
`codex/phase4-mpdocvqa-raw-foundation`.

Accepted server input:

- shard:
  `/root/autodl-tmp/datasets/mp_docvqa/parquet/val-00001-of-00029.parquet`
- `size_bytes=255412525`
- `sha256=493d31bb7b99da676876e4350b27f15ca3e4273518493a09fc799f31d5a3609b`
- long-lived untracked server paths `data/`, `tmp.py`, `.ipynb_checkpoints/`,
  and `scripts/.ipynb_checkpoints/` were explicitly treated as non-blocking
  because they are not tracked modifications

Accepted server results:

- `builder --help`, `py_compile`, real-shard `validate-only`, 5-window sample
  build, and sample artifact self-check all passed
- `phase4_mpdocvqa_raw_server_smoke_shell_exit_code=0`
- real shard audit:
  `row_count=179`, `unique_source_doc_count=44`, `unique_window_count=61`,
  `different_window_same_source_doc_count=23`,
  `conflicting_window_count=0`
- sample build:
  `document_window_count=5`, `qa_count=12`, `absolute_path_hit_count=0`

Accepted document/window boundary:

- The restored artifact is an MP-DocVQA `page_window` document, not
  necessarily a complete original source document.
- Stable document-window identity is defined by:
  `source_doc_id + ordered_page_ids`.
- Different ordered page windows under the same `source_doc_id` are valid
  independent inputs, not conflicts.

Accepted sample windows:

- `rzbj0037__e09400dd12a9c549`: `source_doc_id=rzbj0037`, `page_count=4`,
  `qa_count=6`
- `hqvw0217__bc714cf4181a5632`: `source_doc_id=hqvw0217`, `page_count=1`,
  `qa_count=1`
- `jrcy0227__558596710c584b02`: `source_doc_id=jrcy0227`, `page_count=20`,
  `qa_count=1`
- `mxxj0037__3e113e49e156e47c`: `source_doc_id=mxxj0037`, `page_count=2`,
  `qa_count=2`
- `hljn0226__2583bb36ed16bec4`: `source_doc_id=hljn0226`, `page_count=2`,
  `qa_count=2`

All accepted sample windows satisfy:

- `input_scope=page_window`
- `document.pdf` exists
- `document_manifest.json` exists
- `source_shards` are recorded correctly
- persistent paths remain relative

Overlap audit:

- Historical SFT/GRPO source artifacts were not present in the checked local
  repo paths, so overlap status remains `not_available`.
- The MP-DocVQA raw document path is intended for integration, page retrieval,
  and system E2E, not as strict independent generalization evidence.

Status:

```text
Phase 3 -> accepted
Phase 3 evaluation implementation -> frozen
Phase 4A implementation -> accepted
MP-DocVQA raw Parquet schema audit -> accepted
page-window identity model -> accepted
multi-page image restoration -> accepted
deterministic document asset builder -> accepted
Linux PDF generation -> accepted
cross-shard identity design -> implemented
Phase 4B -> accepted
Gate 1 local implementation -> implemented
Gate 1 -> accepted
Gate 2 -> accepted
Gate 3 local implementation -> implemented
Gate 3 server real E2E -> accepted
Gate 3A failure review instrumentation -> accepted
Gate 3A rank-aware context/prompt -> implemented
Gate 3A default prompt rollback -> accepted
Gate 4 local implementation -> implemented
Gate 4A sample manifest -> accepted
Gate 4B ingestion -> accepted
Gate 4C validate-only -> accepted
Gate 4C retrieval-only -> accepted
Gate 4D full GRPO E2E -> accepted
CDC -> not_started
Router/tools -> not_started
Demo/closure -> not_started
```

## Phase 1 Complete

The current implementation stage connects a configurable answer policy to the traceable QA workflow.

Completed in this phase:

- Added shared AnswerPolicy abstractions under `docagent/models/`.
- Added Qwen answer policy wrapper for `base`, `sft`, and `grpo` modes.
- Added shared workflow prompt builder and structured output parser.
- Updated `run_qa_workflow` to require an explicit answer policy instead of silently using `heuristic_answer`.
- Added bounded repair routing after format/location checks.
- Added run-level SQLite trace persistence through `TraceRepository`.
- Added CLI smoke/eval/trace inspection scripts for workflow-level testing.
- Aligned workflow Qwen generation default with the standalone checkpoint eval `MAX_NEW_TOKENS=1024` setting to avoid truncating valid JSON outputs.
- Verified Base/SFT/GRPO policy switching through the same workflow CLI.

Validation on AutoDL:

| Mode | Samples | Workflow Success | Raw JSON | Schema | Answer EM | Answer F1 | Location | Trace Persist |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 10 | 1.0 | 1.0 | 1.0 | 0.50 | 0.5562 | 0.90 | 1.0 |
| sft | 50 | 1.0 | 1.0 | 1.0 | 0.58 | 0.6715 | 0.92 | 1.0 |
| grpo | 50 | 1.0 | 1.0 | 1.0 | 0.56 | 0.6769 | 0.94 | 1.0 |

The GRPO workflow run also passed SQLite trace inspection. A persisted run can be replayed through `scripts/inspect_workflow_trace.py`, with ordered nodes for `retrieve_evidence`, `generate_answer`, `check_format`, `check_location`, and `finalize`.

Current boundary:

- No new SFT/GRPO training.
- No reward changes.
- No data split changes.
- No Dense Retriever, Reranker, MinerU, TAT-QA, InfographicVQA, VLM, API, or Demo expansion in this phase.

Known limitation:

- Remaining low-answer examples are mostly reader extraction errors inside the correct OCR block, such as neighboring entities, abbreviation expansion ambiguity, or numeric row selection. This matches the earlier SFT/GRPO reader error analysis and is not a workflow integration failure.

## Phase 2A Accepted

Phase 2A real hybrid retrieval and workflow integration is accepted.

Server validation:

- BGE-M3 model API smoke passed with dense embeddings on `cuda:1`.
- bge-reranker-v2-m3 smoke passed through the Transformers sequence-classification backend on `cuda:1`.
- Real hybrid retrieval smoke passed:
  `BGE-M3 -> FAISS save/reload -> BM25 + Dense + RRF -> Transformers reranker`.
- Real Qwen3 GRPO workflow smoke passed:
  `hybrid_rerank -> top-k EvidenceBlock -> GRPO AnswerPolicy -> JSON parse -> format/location validation -> SQLite trace`.
- The accepted workflow smoke used `doc_id=smoke_invoice`, retrieved `smoke_invoice_p1_b1`, generated answer `March 12, 2020`, and persisted run
  `1d88ec99-1f62-4746-9ae2-c0616fa924e7`.

Status:

```text
BGE-M3 -> real_model_verified
FAISS index save/reload -> real_model_verified
BM25 + Dense + RRF -> real_model_verified
Transformers Reranker -> real_model_verified
real hybrid retrieval -> accepted
real Qwen3 workflow integration -> accepted
Phase 2A -> accepted
```

Boundary:

```text
Phase 2A implementation/integration -> accepted
formal retrieval and QA benchmark -> not_started
```

The single successful smoke is integration evidence, not a performance metric.

## Phase 2B First Milestone Accepted

The current implementation stage has accepted the first real structured PDF
parsing milestone. It preserves Phase 1 AnswerPolicy and trace behavior while
adding a real MinerU output conversion path.

Completed before Phase 2B:

- Added document registration with SHA256-based `doc_id`, source caching, and
  supported PDF/PNG/JPG input checks.
- Added MinerU `parse_existing` backend and converter for text/table/image
  content-list records into stable `EvidenceBlock` IDs.
- Added page-level aggregate blocks for future page-first retrieval while
  keeping block-level retrieval as the default.
- Extended SQLite with document, evidence block, and document index metadata
  persistence without removing Phase 1 `qa_runs` or `tool_traces`.
- Added unified retrieval candidates with BM25, Dense, RRF, and reranker score
  fields.
- Added BGE-M3 dense encoder wrapper, DenseIndex save/load, RRF fusion, and a
  real bge-reranker-v2-m3 wrapper with explicit errors when models are missing.
- Switched the default real reranker path to Transformers
  `AutoModelForSequenceClassification` for Transformers 5.x compatibility.
- Added `IndexedDocumentRetriever` and injected it into `run_qa_workflow`
  without changing the default Phase 1 path.
- Added CLI entry points:
  `scripts/ingest_document.py`, `scripts/inspect_document.py`,
  `scripts/query_document.py`, `scripts/eval_retrieval_phase2.py`, and
  `scripts/eval_workflow_phase2.py`.
- Added `scripts/build_phase2_parse_existing_fixture.py` to create
  MinerU-like `content_list.json` fixtures from existing DocAgent JSONL
  records, so Phase 2 can be smoke-tested without installing MinerU.
- Added explicit no-download smoke backends for Phase 2 retrieval:
  `HashDenseEncoder` and `KeywordOverlapReranker`. These are for wiring tests
  only and must not be reported as BGE-M3 or bge-reranker-v2-m3 results.
- `scripts/eval_retrieval_phase2.py` and `scripts/eval_workflow_phase2.py`
  now support the same `hash` dense and `keyword` reranker smoke backends for
  no-download batch validation.

Local no-card validation:

- `python -m pytest -q`: 41 passed.
- Temporary parse-existing smoke completed:
  register dummy PDF -> parse mock MinerU content list -> save blocks ->
  inspect document -> query with BM25 + heuristic answer policy.

Phase 2B first milestone:

- one real public PDF: `903-africa-fact-sheet.pdf`;
- data directory: `data/real_documents/globocan_africa_2022/`;
- `doc_id=fe3465edd3da60d2`;
- source SHA256:
  `fe3465edd3da60d26b2020ab751d75bfba26a465a9d66c43eff5dce12f4db37a`;
- MinerU API batch:
  `56a4776f-aa1c-47d0-8901-99038de6a851`;
- real MinerU `parse_existing` converted 57 raw content-list records into
  57 `EvidenceBlock` records;
- structure-quality status: `passed_with_warnings`;
- only warning: MinerU `_origin.pdf` SHA256 differs from the submitted source
  PDF, so the submitted PDF remains the document identity source.

Validation:

- `python -m pytest -q`: 72 passed before merge-prep hardening.
- Real GLOBOCAN `mineru_existing` smoke persisted SQLite document/block records.
- Existing-batch MinerU API read-only smoke returned `state=done`, downloaded a
  ZIP under `outputs/mineru_api/live_smoke/`, and safely extracted an ordinary
  `*_content_list.json`.

Merge-prep hardening:

- Persisted MinerU artifact paths are document-directory-relative POSIX paths
  in EvidenceBlocks, page documents, ingestion report, structure-quality report,
  source manifest, and SQLite `payload_json`.
- `image_path` is the EvidenceBlock resource reference; duplicate
  `metadata.normalized_resource_path` and `metadata.source_content_list` are no
  longer written.
- Structure quality now reports `missing_retrieval_content_count`,
  `empty_boilerplate_count`, and `empty_boilerplate_block_ids` separately, so
  retained empty boilerplate does not fail quality status.
- Added fixed verifier `scripts/verify_phase2b_real_pdf.py`.
- Local validation after hardening:
  `python -m pytest -q`: 74 passed.
- Real GLOBOCAN verifier:
  `outputs/verification/phase2b_globocan/verification_report.json`;
  `raw_block_count=57`, `converted_block_count=57`, `page_document_count=2`,
  `table_count=5`, `chart_count=6`, `empty_boilerplate_count=2`,
  `missing_retrieval_content_count=0`, `persisted_absolute_path_count=0`,
  `overall_status=passed_with_warnings`.

Status:

```text
Real MinerU output -> accepted
Phase 2B first milestone -> accepted
```

## Phase 2B-2 Accepted

Phase 2B-2 real-document scenario acceptance is complete. This is a
real-document scenario acceptance result, not a formal benchmark.

Accepted integration:

- Real GLOBOCAN PDF and existing MinerU output were ingested through
  `mineru_existing`.
- 57 raw records converted to 57 EvidenceBlocks; 22 boilerplate blocks were
  excluded, leaving 35 retrieval blocks.
- Real BGE-M3, FAISS, BM25, RRF, Transformers sequence-classification reranker,
  and Qwen3 GRPO AnswerPolicy ran end to end.
- JSON, format, and location validation completed through the existing workflow.
- SQLite trace persisted 8 `qa_runs` and 49 `tool_traces`.
- `no_gold_leakage=true`, `no_mock_fallback=true`, and
  `persisted_absolute_path_count=0`.

Scenario metrics:

- Scenario samples: 8/8 completed.
- Retrieval: `Recall@1=0.875`, `Recall@3=0.875`, `Recall@5=0.875`,
  `MRR=0.875`, `gold_page_hit_rate=1.0`.
- Answer: `normalized_exact_match=0.625`, `token_f1=0.675`,
  `character_f1=0.7842548076923077`, `answer_hit=0.625`,
  `valid_json_rate=1.0`, `format_valid_rate=1.0`.
- Location: `block_location_hit=0.875`, `page_location_hit=1.0`,
  `final_location_in_retrieved_top_k=1.0`, `location_valid_rate=1.0`.

Failure taxonomy:

- 2 reader table-column selection errors: q001 and q002 selected the Males
  column instead of Both sexes while retrieval and location were correct.
- 1 retrieval / partial-answer / location error: q008 missed the large table
  gold block, returned a partial liver cases answer, and cited the wrong block.

Status:

```text
Phase 2B-2 -> accepted
implementation/integration -> accepted
scenario quality evidence -> accepted
formal benchmark -> not_started
quality optimization -> not_started
```

## Phase 3A Implemented

Phase 3A local focused-evaluation framework is implemented. Real focused
evaluation on AutoDL has not started.

Implemented locally:

- benchmark validity contract for corpus-backed records with
  `metadata.gold_block_ids`;
- deterministic qid-hash subset sampling;
- BM25 vs Hybrid retrieval runner using shared retrieval code;
- fixed Hybrid evidence artifact generation for shared SFT/GRPO reader input;
- SFT vs GRPO AnswerPolicy runner over identical evidence order;
- comparison JSON and Markdown summary outputs;
- fixture tests using explicit mock backends only.

Status:

```text
Phase 3A -> implemented
real focused evaluation -> not_started
retrieval evaluation -> blocked
answer policy evaluation -> implemented
formal benchmark -> not_started
```

Boundary:

- Local validation does not load real BGE-M3, reranker, SFT, or GRPO models.
- Mock fixture output must not be reported as real focused-evaluation results.
- The current `mp_docvqa_imdb_ocr_5000_split/dev.jsonl` artifact is not an
  accepted retrieval corpus because its evidence is stored per QA record and no
  independent canonical per-doc corpus artifact has been verified.
- `scripts/build_phase3_mpdocvqa_retrieval_benchmark.py` can build the required
  QA/corpus/manifest artifacts from real RRC IMDb / official OCR data, but the
  server has not yet produced and validated those artifacts.
- SFT vs GRPO can still run through `--answer-only` when a reader evidence
  artifact passes the reader contract, but that path must not report retrieval
  Recall/MRR.
- Do not modify retrieval algorithms, query normalization, prompts,
  AnswerPolicy, reward code, checkpoints, or training data in Phase 3A.

## Phase 3 Local Closure Implemented

The local Phase 3 closure now separates model-facing protocol, real-document
contracts, and server acceptance orchestration. No real model evaluation has
been run for this update.

Implemented locally:

- Added a shared evidence-context builder and checkpoint-compatible answer
  prompt compiler used by SFT dataset construction, GRPO dataset construction,
  heuristic policy, Qwen AnswerPolicy, and the workflow model node.
- Added a canonical output adapter so workflow traces can store raw model
  output, canonical output, validation status, and repair status consistently.
- Extended workflow traces with `prompt_version`, `task_type`, selected and
  dropped block ids, `evidence_context_hash`, prompt token count, truncation,
  raw output, canonical output, validation, and repair metadata.
- Added real-document QA/corpus/document-manifest/benchmark-manifest contract
  construction for the existing GLOBOCAN scenario corpus.
- Added one fixed server acceptance entry point:
  `scripts/run_phase3_server_acceptance.py`.
- Added `--retrieval-only` to the Phase 3 focused runner so retrieval contract
  checks and real-document retrieval regression can run without loading SFT or
  GRPO adapters.

Status:

```text
training-inference contract -> implemented
real-document evaluation framework -> implemented
server real evaluation -> accepted
GLOBOCAN regression -> accepted
fixed-evidence safety hotfix -> accepted
MP-DocVQA retrieval evaluation -> blocked
MP-DocVQA AnswerPolicy evaluation -> accepted
CDC -> not_started
```

Boundary:

- Local tests use fixtures or help startup only; they do not load BGE-M3,
  reranker, Qwen, SFT adapter, or GRPO adapter.
- CDC is the next priority and still requires server-side MinerU output or
  MinerU API ingestion before it can become a second accepted real-document
  scenario.
- GLOBOCAN regression is accepted as a real-document scenario contract, not a
  formal benchmark result.

## Phase 3 GLOBOCAN Server Regression Accepted

The GLOBOCAN real-document scenario regression passed on AutoDL at commit
`3390bcde1c703c7bd95c567e6da3bdb04591c0d8`.

Server environment for that historical GLOBOCAN run:

```text
Python -> /root/miniconda3/envs/docagent/bin/python
Conda environment -> docagent
GPU -> 2 x NVIDIA GeForce RTX 4090 D
PyTorch -> 2.12.0+cu130
Transformers -> 5.8.1
PEFT -> 0.19.1
FlagEmbedding -> import passed
```

Run scope:

```text
evaluation_scope = scenario_regression
formal_benchmark = false
verified_qa_count = 8
query_independent_block_count = 35
document_count = 1
```

Retrieval scenario comparison:

| Metric | BM25 | Hybrid | Absolute Delta | Relative Delta |
|---|---:|---:|---:|---:|
| Recall@1 | 0.375 | 0.875 | +0.500 | +1.3333 |
| Recall@3 | 0.875 | 0.875 | 0.000 | 0.0000 |
| Recall@5 | 0.875 | 0.875 | 0.000 | 0.0000 |
| MRR | 0.6041666667 | 0.875 | +0.2708333333 | +0.4482758621 |
| Gold page hit rate | 1.0 | 1.0 | 0.000 | 0.0000 |

```text
在 GLOBOCAN 8 条真实文档场景回归中，Hybrid + Reranker
主要改善正确证据的首位排序：
Recall@1 从 0.375 提升至 0.875，MRR 从 0.604 提升至 0.875。
Recall@3/5 未提升，说明当前收益主要来自重排，而不是扩大候选覆盖。
```

AnswerPolicy scenario comparison:

```text
fixed_evidence_sha256 = 04536f8fdbd3ea2e6c4a8ef93befd6aa270eb5c5ae700f1edcdacf2eed35adee
normalized EM = 0.625
answer hit = 0.625
token F1 = 0.675
character F1 = 0.7842548077
valid JSON rate = 1.0
format valid rate = 1.0
block location hit = 0.875
page location hit = 0.875
final location in evidence rate = 1.0
repair attempted rate = 0.0
repair success rate = 0.0
```

SFT and GRPO used the same fixed evidence and produced identical metrics.

```text
真实文档回归验证了 SFT 与 GRPO adapter 均可通过统一
Training–Inference Contract、Canonical Output 和验证链路运行。

8 条 GLOBOCAN 场景中未观察到 GRPO 相对 SFT 的回答指标提升。
该结果只证明兼容性和无明显回归，不能用于宣称 GRPO 优于 SFT。
```

Status:

```text
training-inference contract -> accepted
real-document evaluation framework -> accepted
fixed-evidence safety hotfix -> accepted
GLOBOCAN regression contract -> accepted
GLOBOCAN server real regression -> accepted
Hybrid retrieval scenario evidence -> accepted
AnswerPolicy scenario compatibility -> accepted
MP-DocVQA AnswerPolicy evaluation -> accepted
MP-DocVQA AnswerPolicy sample_count -> 150
SFT/GRPO fixed-evidence parity -> accepted
GRPO grounding evidence -> accepted
GRPO answer accuracy evidence -> accepted
formal benchmark -> not_started
MP-DocVQA retrieval evaluation -> blocked
CDC -> not_started
```

Boundary:

- This is a real-document scenario regression result, not a formal benchmark.
- GRPO effectiveness remains unproven beyond compatibility on this scenario.
- GRPO vs SFT has now been evaluated on a larger MP-DocVQA fixed-evidence
  reader artifact; CDC should next be added as a second real document scenario.

## Phase 3 MP-DocVQA AnswerPolicy Evaluation Measured

MP-DocVQA fixed-evidence reader evaluation completed on AutoDL at commit
`1ef68838210d56e8624b7ef0c0633b705e8ccfe5`. This is not a formal benchmark
and does not report retrieval Recall/MRR.

Run scope:

```text
server_gpu = 1 x NVIDIA GeForce RTX 4090D 24GB
dataset = data/benchmark/mp_docvqa_imdb_ocr_5000_split/dev.jsonl
evaluation_scope = mpdocvqa_fixed_evidence_reader
formal_benchmark = false
sample_limit = 150
seed = 42
top_k = 20
fixed_evidence_sha256 = 8c4d60a189675a4ba52fa61d47db68c070f2f13218b5e73b1a18ded6fceeb940
output_dir = outputs/evaluation/phase3_focused_eval/mpdocvqa_answer_policy_150_top20_20260616_131117/
```

The `top_k=20` setting is only the fixed-evidence reader-evaluation evidence
budget over the existing reader artifact. It is not an online Retrieval top-k
setting and must not be used to compute Retrieval Recall/MRR. The earlier
`top_k=5` smoke failure was not a code defect because qid `64253` had its gold
block at source-evidence rank 8.

Metrics:

| Metric | SFT | GRPO | Delta |
|---|---:|---:|---:|
| Completed | 150/150 | 150/150 | 0 |
| Failed | 0 | 0 | 0 |
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

Current status:

```text
fixed-evidence safety hotfix -> accepted
MP-DocVQA AnswerPolicy evaluation -> accepted
MP-DocVQA AnswerPolicy sample_count -> 150
SFT/GRPO fixed-evidence parity -> accepted
GRPO grounding evidence -> accepted
GRPO answer accuracy evidence -> accepted
formal benchmark -> not_started
MP-DocVQA retrieval evaluation -> blocked
GLOBOCAN regression -> accepted
CDC -> not_started
```

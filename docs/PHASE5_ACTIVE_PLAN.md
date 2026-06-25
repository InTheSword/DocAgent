# Phase 5 Active Plan: Personal-use DocAgent MVP

## 0. Current Status

Phase 4D-C has been accepted and recorded.

Current Phase 5 status after Phase 5F-3 local MinerU-backed file-to-answer implementation:

```text
Phase 5A architecture audit and contracts -> accepted
Phase 5B deterministic P0 document tools -> accepted
Phase 5C Router / Planner -> accepted
Phase 5D local_fact_qa wrapper -> accepted
Phase 5D-S local_fact_qa smoke runner -> accepted
Phase 5D-S server real-model smoke -> accepted
Phase 5F-1 unified CLI MVP -> accepted
Phase 5F-1 server CLI smoke -> accepted
Phase 5F-2 file-to-answer ingestion integration -> accepted
Phase 5F-2 server file-to-answer smoke -> accepted
Phase 5F-3 MinerU-backed file-to-answer smoke -> implemented
Phase 5F-3 server smoke -> ready
Phase 5C-2 LLM-assisted Router fallback -> not_started
Phase 5E document_summary -> not_started
Phase 5F full CLI acceptance -> not_started
Phase 5G multi-task regression -> not_started
```

Phase 5D-S validates execution stability, not benchmark-level answer quality.

Current accepted Phase 4D-C result:

```text
Phase 4D-C expanded unseen validation = accepted
Branch: codex/phase4d-c-expanded-unseen-validation
Latest documentation commit: 41a2d7b62a0b2b94b631f10457a39dbe134b5fd1
```

Phase 4D-C strict accepted evaluation set:

```text
77 document windows
572 pages
218 QA samples
```

Key retrieval / candidate evidence results:

```text
candidate_evidence_count = 218 / 218
qid_set_match = true
no_gold_leakage = true
table_index_enhancement_enabled = false
candidate Recall@1/3/5 = 0.7248 / 0.8945 / 0.9128
candidate MRR = 0.8099
```

Key candidate answer coverage results:

```text
candidate_span_answer_coverage = 0.7523
candidate_answer_coverage_all = 0.4266
candidate_answer_coverage_top20 = 0.3991
candidate_answer_no_gold_leakage = true
```

Failure attribution:

```text
extraction_rule_gap = 72
candidate_span_or_normalization_gap = 38
reader_selection_gap = 5
```

Interpretation:

```text
The dominant bottleneck in Phase 4D-C is not Reader selection.
The larger bottleneck is candidate answer extraction and candidate span construction.
Candidate-ID Reader and optional full GRPO E2E remain deferred.
```

## 1. Why Phase 5

Phase 4 mainly focused on MP-DocVQA raw-input E2E validation, evidence packing, retrieval diagnostics, candidate answer board analysis, and failure attribution.

However, the current project priority has shifted from benchmark-side optimization to building a usable personal document QA system.

Current priority order:

```text
1. Job-search project demonstration
2. Product-like personal document assistant
3. Algorithm evaluation system
4. Paper-style experiment
```

Therefore, Phase 5 should not continue local metric tuning as the main track. The next stage should focus on system-level usability:

```text
Unified entrypoint
Task routing
Document tools
Hybrid RAG reuse
Traceable output
Minimal personal-use workflow
```

Phase 4D-D candidate answer board generalized improvement is not abandoned, but it is deferred.

```text
Phase 4D-D = deferred
Reason:
Phase 4D-C already identified the local_fact_qa candidate answer bottleneck,
but the current project priority is to build a personal-use DocAgent MVP.
Candidate answer board improvement should be revisited after the MVP entrypoint,
router, document tools, and multi-task regression are accepted.
```

## 2. Phase 5 Goal

Phase 5 aims to build a personal-use DocAgent MVP.

Minimum goal:

```text
Given a PDF file or an already ingested document,
the user can ask a question,
the system can classify the task type,
select the appropriate document tool or local_fact_qa workflow,
and return an answer with citations, tools used, and trace path.
```

The system should be usable for personal testing and job-search demonstration. It does not need to match commercial document AI products, but its design should follow the same general principles:

```text
Query understanding
Task routing
Tool selection
Evidence retrieval
Citation assembly
Traceable execution
```

## 3. Phase 5 Non-goals

Do not work on the following in Phase 5 unless explicitly approved later:

```text
Do not enter Candidate-ID Reader.
Do not run optional full GRPO E2E by default.
Do not retrain models.
Do not change the AnswerPolicy prompt as the main solution.
Do not continue tuning extraction regex rules before an audit.
Do not implement VLM API or local VLM image understanding in this phase.
Do not build a heavy UI or multi-user service.
Do not migrate to a large multi-agent framework.
Do not introduce a cloud vector database unless explicitly approved.
Do not optimize for formal benchmark ranking.
```

## 4. External LLM API Boundary

External LLM API is allowed, but only for small, high-level reasoning and planning modules.

Allowed use:

```text
Query Planner / Router
Low-confidence planning fallback
Optional difficult extraction fallback after audit
```

Not allowed by default:

```text
Do not use external LLM API to answer every document question.
Do not send full documents to external LLM API by default.
Do not use external LLM API for batch evaluation by default.
Do not use external VLM API or local VLM for image understanding in Phase 5.
```

Recommended implementation principle:

```text
Rule-based routing first.
External LLM router only when rule confidence is low or the question is ambiguous.
```

## 5. Visual Understanding Boundary

Phase 5 should not call VLM API or local VLM for image understanding.

Supported:

```text
MinerU OCR text
MinerU layout text
image / figure block metadata
OCR-derived text from figures
caption text if available from parsing artifacts
```

Not supported in Phase 5:

```text
Pixel-level chart reasoning
Color / spatial relationship reasoning
Complex visual question answering
Image-only answer extraction
```

The implementation should preserve image block metadata and image paths so that VLM fallback can be added later.

## 6. Target Architecture

The current local_fact_qa RAG flow should remain useful, but it should no longer be the only path.

Old implicit architecture:

```text
Question
-> Retrieval
-> Evidence packing
-> AnswerPolicy
```

Target Phase 5 architecture:

```text
Question
-> Task Router / Planner
-> Document Tool or local_fact_qa
-> Evidence / citation assembler
-> Structured answer
-> Trace and logs
```

The local_fact_qa path should reuse the Phase 4 hybrid RAG work:

```text
Query Rewrite
BM25
Dense Retriever
RRF / hybrid merge
Reranker
candidate_spans or page_children evidence packing
AnswerPolicy
location validation
SQLite trace
```

But the following task types should not be forced through top-k retrieval:

```text
Document statistics
Full table extraction
Full image / figure listing
Specified page lookup
Document outline
Document summary
```

## 7. Task Taxonomy

Phase 5 should initially support the following task types:

```text
local_fact_qa
table_lookup_or_calculation
document_statistics
page_lookup
structured_extraction
document_summary
```

Deferred task types:

```text
visual_pixel_qa
multi_document_comparison
long_horizon_agent_task
multi_turn_memory_task
```

### 7.1 local_fact_qa

Use when the user asks for a specific answer likely supported by a small number of text/table evidence blocks.

Examples:

```text
What is the invoice date?
What is the total amount?
Which organization issued the report?
```

Execution path:

```text
Router
-> local_fact_qa
-> hybrid retrieval
-> evidence packing
-> AnswerPolicy
-> citations
-> trace
```

### 7.2 table_lookup_or_calculation

Use when the question requires table lookup, row/column identification, or simple calculation.

Examples:

```text
What was the revenue in 2020?
What is the difference between 2020 and 2021 values?
Which row has the highest amount?
```

Initial implementation may reuse local_fact_qa if table-specific tools are not ready, but the router should classify it separately.

### 7.3 document_statistics

Use for deterministic document metadata questions.

Examples:

```text
How many pages are in this document?
How many tables are detected?
How many images or figures are detected?
```

This path should use deterministic tools, not retrieval.

### 7.4 page_lookup

Use when the user explicitly asks about a page.

Examples:

```text
What is on page 3?
Show the text from page 5.
Summarize page 2.
```

This path should use page-level lookup tools.

### 7.5 structured_extraction

Use when the user asks to list or extract all instances of a structure.

Examples:

```text
Extract all tables.
List all figures.
List all section headings.
Extract all dates mentioned in the document.
```

This path should use full-scan tools and structured outputs.

### 7.6 document_summary

Use when the user asks for a global document summary.

Examples:

```text
Summarize this document.
What is this PDF about?
Give me the key points.
```

This should not rely on random top-k retrieval. It should use page summaries, outline, section summaries, or deterministic page sampling.

## 8. Router Contract Draft

Router input:

```json
{
  "doc_id": "string",
  "question": "string",
  "document_profile": {
    "page_count": 12,
    "block_count": 340,
    "table_count": 5,
    "image_count": 3,
    "has_ocr": true,
    "has_tables": true,
    "has_images": true
  },
  "available_tools": [
    "local_fact_qa",
    "count_pages",
    "count_tables",
    "count_images",
    "get_page_text",
    "extract_all_tables",
    "extract_all_images",
    "document_summary"
  ]
}
```

Router output:

```json
{
  "task_type": "local_fact_qa",
  "selected_tools": ["local_fact_qa"],
  "requires_retrieval": true,
  "requires_full_scan": false,
  "requires_table_tool": false,
  "requires_calculation": false,
  "requires_visual_understanding": false,
  "target_evidence_types": ["text", "table"],
  "query_rewrite": "rewritten query if useful",
  "confidence": 0.86,
  "reason": "The user asks for a specific field value likely supported by local evidence."
}
```

Router implementation policy:

```text
Use deterministic rules for obvious tasks.
Use external LLM API only for ambiguous planning.
Fallback to local_fact_qa when routing fails.
All router outputs must be JSON-serializable and schema-validated.
```

## 9. Document Tool Inventory Target

Phase 5 should audit and then implement or expose deterministic tools where possible.

P0 tools:

```text
count_pages
count_blocks
count_tables
count_images
get_page_text
list_pages
```

P1 tools:

```text
extract_all_tables
extract_all_images
list_sections
document_outline
```

P2 tools:

```text
table_lookup
simple_calculation
document_summary
```

Principle:

```text
Do not use retrieval for deterministic metadata questions.
Do not use LLM for simple counts.
Do not make the LLM guess document structure when parsing artifacts already contain it.
```

## 10. Unified CLI Target

Phase 5 should eventually provide a unified CLI entrypoint.

Target command:

```bash
python scripts/docagent_cli.py \
  --file path/to/document.pdf \
  --question "How many tables are in this document?"
```

Alternative command for already ingested documents:

```bash
python scripts/docagent_cli.py \
  --doc-id some_doc_id \
  --question "Summarize this document."
```

Expected output:

```json
{
  "status": "success",
  "doc_id": "some_doc_id",
  "task_type": "document_statistics",
  "answer": "The document contains 12 pages, 5 tables, and 3 image or figure regions.",
  "citations": [
    {
      "page": 1,
      "block_id": "optional"
    }
  ],
  "tools_used": ["count_pages", "count_tables", "count_images"],
  "trace_path": "outputs/traces/..."
}
```

Minimum CLI acceptance:

```text
It can run on an already ingested document.
It can answer document_statistics questions deterministically.
It can answer page_lookup questions.
It can call local_fact_qa for specific fact questions.
It saves a trace artifact.
It returns structured JSON.
```

## 11. Citation / Evidence Output Direction

Long-term direction:

```text
The model should not freely invent citation locations.
The system should assemble citations from supporting evidence ids, page ids, block ids, and metadata.
```

Current Phase 5 MVP can still return page/block citations from existing evidence artifacts, but the direction should be:

```json
{
  "answer": "...",
  "supporting_evidence_ids": ["doc_p003_b012"],
  "citations": [
    {
      "page": 3,
      "block_id": "doc_p003_b012",
      "text_preview": "..."
    }
  ]
}
```

Candidate-ID Reader remains deferred because Phase 4D-C showed that candidate answer extraction and candidate span construction are larger bottlenecks than Reader selection.

## 12. Phase 5 Stages

### Phase 5A: Architecture Audit and Contracts

Goal:

```text
Read the current codebase and document the existing reusable components.
Do not implement core functionality yet.
```

Deliverables:

```text
docs/PHASE5_ACTIVE_PLAN.md
docs/PHASE5_ROUTER_CONTRACT.md
docs/PHASE5_TOOL_INVENTORY.md
docs/PHASE5_MVP_ACCEPTANCE.md
```

Acceptance:

```text
No behavior-changing code required.
Current reusable entrypoints are listed.
Current ingestion artifacts are described.
Current local_fact_qa reusable path is identified.
Router schema and tool contracts are proposed.
Next minimal implementation plan is limited to small, testable changes.
```

### Phase 5B: Deterministic Document Tools

Goal:

```text
Expose deterministic document tools based on existing ingestion artifacts.
```

P0 tools:

```text
count_pages
count_blocks
count_tables
count_images
get_page_text
list_pages
```

Acceptance:

```text
Unit tests exist.
Tools run without LLM.
Tools return JSON-serializable outputs.
Tools work on at least one existing ingested MP-DocVQA or sample document.
```

### Phase 5C: Router / Planner

Goal:

```text
Implement a rule-first router with optional external LLM fallback.
```

Acceptance:

```text
Router supports local_fact_qa, document_statistics, page_lookup, structured_extraction, table_lookup_or_calculation, document_summary.
Router outputs schema-valid JSON.
At least 30 fixed router test cases pass.
External LLM fallback is optional and disabled by default unless configured.
```

### Phase 5D: Reuse Hybrid RAG as local_fact_qa Tool

Goal:

```text
Wrap the existing hybrid retrieval + evidence packing + AnswerPolicy path as a callable local_fact_qa tool.
```

Acceptance:

```text
The wrapper can run on an already ingested document.
It returns answer, citations, tools_used, and trace_path.
It does not require changing AnswerPolicy prompt.
It does not require retraining.
```

### Phase 5D-S: Local Fact QA Tool Server Smoke

Goal:

```text
Prepare a reusable foreground smoke runner for the Phase 5D local_fact_qa tool.
```

Implementation:

```text
scripts/run_phase5d_local_fact_qa_smoke.py
```

Acceptance:

```text
The runner can execute dry-run wrapper checks and non-dry local_fact_qa workflow smoke over an existing SQLite doc_id.
It writes summary.json, summary.md, results.jsonl, and preview.json under outputs/smoke/phase5d_local_fact_qa/<run_id>/.
It records structured failures for missing db paths, missing doc_id, missing questions, and tool errors.
It records dry-run and real-workflow flags, and confirms no external API, VLM, training, or full E2E execution is used.
Server real-model smoke has passed on server artifacts and is accepted as execution stability evidence, not benchmark-level answer quality.
```

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

### Phase 5E: Document Summary MVP

Goal:

```text
Add a minimal document_summary path.
```

Preferred approach:

```text
page text / page metadata
-> page-level summaries or extractive page previews
-> document-level summary
-> cited page references
```

Acceptance:

```text
Does not use random top-k retrieval as the only context.
Returns summary with page references.
Can run on at least one real PDF or existing ingested document.
```

### Phase 5F: Unified CLI

Goal:

```text
Provide scripts/docagent_cli.py as the personal-use entrypoint.
```

Acceptance:

```text
Supports --doc-id for already ingested documents.
Optionally supports --file if ingestion integration is already stable.
Routes questions to document tools or local_fact_qa.
Outputs structured JSON.
Writes a trace artifact.
```

#### Phase 5F-1: Unified CLI MVP with file-entry contract

Implementation:

```text
scripts/docagent_cli.py
```

Implemented local CLI contract:

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

Supported paths:

```text
--list-documents lists recent SQLite documents with doc_id, original_name/file_path, page_count, parse_status, index_status, created_at, and updated_at.
--doc-id + --question checks the document, calls the Phase 5C Router, then dispatches document_statistics, page_lookup, or local_fact_qa.
--file + --question is part of the CLI contract. The CLI reuses an already-ingested SQLite document when the input file SHA matches an existing document. If no matching document exists, it returns structured file_ingestion_unavailable and tells the user to ingest first.
```

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

Boundary:

```text
document_summary remains Phase 5E not_started.
table_lookup and simple_calculation remain not_started.
structured_extraction returns structured unsupported when current tools are insufficient.
LLM-assisted Router fallback remains future Phase 5C-2 work and is not implemented.
No external LLM API, VLM, training, full GRPO E2E, AnswerPolicy prompt change, or candidate answer extraction change is included.
```

#### Phase 5F-2: File-to-answer ingestion integration

Implementation:

```text
scripts/docagent_cli.py
docagent/parser/text_backend.py
```

Implemented behavior:

```text
--file + --question now supports new UTF-8 .txt file ingestion through DocumentIngestionService.
New .txt files are registered by DocumentRegistry, persisted through DocumentRepository, converted into EvidenceBlocks/page blocks, routed by the Phase 5C Router, and dispatched to deterministic tools or local_fact_qa.
Already-ingested files are still reused by sha256 and do not repeat ingestion.
CLI output returns the generated or reused doc_id and source.was_ingested / source.reused_existing.
summary.json records used_file_ingestion, reused_existing_document, ingestion_status, and ingestion_error.
PDF/image inputs without a configured CLI parser backend return structured parser_backend_unavailable rather than fake success.
Unsupported extensions return unsupported_file_type.
page_metadata_inconsistent is emitted as a non-blocking warning when citation pages exceed documents.page_count.
```

Boundary:

```text
Phase 5F-2 does not implement MinerU-backed PDF ingestion inside docagent_cli.
Phase 5F-2 does not implement Phase 5E document_summary.
Phase 5F-2 does not implement LLM-assisted Router fallback, table lookup, simple calculation, VLM, training, full GRPO E2E, AnswerPolicy prompt changes, or candidate answer extraction changes.
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

Accepted limitations:

```text
Server smoke validates lightweight UTF-8 .txt file-to-answer execution
stability, not benchmark answer quality.
Current accepted file ingestion support covers UTF-8 .txt through
TextParserBackend.
PDF/MinerU-backed file-to-answer through docagent_cli is not yet accepted.
local_fact_qa answer quality remains a separate known limitation.
Dense index is not built in the lightweight smoke; index_status may remain
not_started.
```

#### Phase 5F-3: MinerU-backed file-to-answer full-chain smoke

Implementation:

```text
scripts/docagent_cli.py
docagent/parser/mineru_backend.py
```

Implemented behavior:

```text
--file + --question can use --parser mineru_existing with
--mineru-output-dir / --mineru-output to consume existing MinerU output.
The CLI copies the existing MinerU output into the document cache, then reuses
DocumentIngestionService, DocumentRegistry, DocumentRepository, SQLite
EvidenceBlocks/page documents, Phase 5C Router, deterministic document tools,
and local_fact_qa dry-run.
--parser auto still uses TextParserBackend for .txt files.
PDF/image inputs without --mineru-output-dir still return structured
parser_backend_unavailable rather than fake success.
--parser mineru with --parser-mode local_cli is wired to MinerUParserBackend
for environments where an isolated MinerU CLI is available.
When a summary-like dry-run question falls back to local_fact_qa because
document_summary is unavailable, top-level task_type records the executed
local_fact_qa path while router_plan preserves the original document_summary
decision and warnings.
metadata_consistency records documents.page_count, page_documents count,
max evidence page, and max citation page; inconsistency emits
page_metadata_inconsistent only as a warning.
```

Local smoke evidence:

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
tested_local_fact_qa_dry_run_question = What is this document about?
tested_local_fact_qa_dry_run_task_type = local_fact_qa
tested_local_fact_qa_dry_run_router_task_type = document_summary
tested_local_fact_qa_dry_run_tools_used = local_fact_qa
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
```

Server smoke:

```text
status = ready
sample_path = data/real_documents/globocan_africa_2022/source/original.pdf
mineru_output = data/real_documents/globocan_africa_2022/mineru_raw
commands_cover = document_statistics, page_lookup, local_fact_qa dry-run
acceptance_boundary = execution smoke, not benchmark answer quality
```

Boundary:

```text
Phase 5F-3 does not implement Phase 5E document_summary.
Phase 5F-3 does not implement LLM-assisted Router fallback, table lookup,
simple calculation, VLM, training, full GRPO E2E, AnswerPolicy prompt changes,
or candidate answer extraction changes.
Live MinerU API/installation is not added to the stable docagent environment.
```

### Phase 5G: Multi-task Regression

Goal:

```text
Validate that the MVP works beyond one demo question.
```

Minimum regression categories:

```text
local_fact_qa
document_statistics
page_lookup
structured_extraction
document_summary
```

Acceptance:

```text
Regression report is generated.
Failures are categorized by task type.
Known limitations are documented.
```

## 13. Implementation Discipline

Phase 5 must avoid local trap debugging.

Rules:

```text
Do not spend excessive time fixing one isolated sample unless it blocks the MVP.
Prefer replacing the path when a local fix does not serve the system goal.
Prefer deterministic tools for deterministic tasks.
Prefer routing over forcing all questions through top-k retrieval.
Prefer small auditable modules over large framework migrations.
Prefer existing project components over rewriting from scratch.
```

When a problem is encountered, first ask:

```text
Does fixing this improve the personal-use DocAgent MVP?
Is this a local benchmark artifact or a real product-flow issue?
Can this be solved by routing to a better tool instead of tuning the same path?
Is an external LLM planning call justified here?
```

## 14. Current Priority

Immediate next step:

```text
Phase 5F-1 unified CLI MVP and server CLI smoke are accepted.
Phase 5F-2 file-to-answer ingestion integration and server smoke are accepted for lightweight .txt files.
Phase 5F-3 MinerU-backed file-to-answer support is implemented locally and ready for server smoke.
Next step requires explicit approval/result: Phase 5F-3 server smoke result sync, Phase 5G multi-task regression, Phase 5E document_summary, or Phase 5C-2 LLM-assisted Router fallback.
Do not implement document_summary, LLM Router fallback, table lookup, calculation, VLM, training, or full E2E as part of Phase 5F-3.
```

Phase 4D-D remains deferred until after Phase 5 MVP is accepted.

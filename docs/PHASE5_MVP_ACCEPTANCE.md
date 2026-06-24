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
- optionally accept `--file` only after ingestion integration is stable;
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
Phase 5C Router / Planner -> not_started
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

# Current Status

Updated: 2026-06-11

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

## Phase 2 Started

The current implementation stage starts the real-document ingestion and hybrid
retrieval MVP. It preserves Phase 1 AnswerPolicy and trace behavior while
adding a new optional retriever injection point.

Completed locally in this step:

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
- Added `IndexedDocumentRetriever` and injected it into `run_qa_workflow`
  without changing the default Phase 1 path.
- Added CLI entry points:
  `scripts/ingest_document.py`, `scripts/inspect_document.py`,
  `scripts/query_document.py`, `scripts/eval_retrieval_phase2.py`, and
  `scripts/eval_workflow_phase2.py`.
- Added `scripts/build_phase2_parse_existing_fixture.py` to create
  MinerU-like `content_list.json` fixtures from existing DocAgent JSONL
  records, so Phase 2 can be smoke-tested without installing MinerU.

Local no-card validation:

- `python -m pytest -q`: 41 passed.
- Temporary parse-existing smoke completed:
  register dummy PDF -> parse mock MinerU content list -> save blocks ->
  inspect document -> query with BM25 + heuristic answer policy.

Still requires AutoDL validation:

- Real MinerU CLI parsing on at least one PDF and one page image.
- BGE-M3 dense index build with `/root/autodl-tmp/models/bge-m3`.
- bge-reranker-v2-m3 scoring with
  `/root/autodl-tmp/models/bge-reranker-v2-m3`.
- MP-DocVQA retrieval ablation for BM25, Dense, Hybrid, and Hybrid+Reranker.
- 3 real public document smoke runs.

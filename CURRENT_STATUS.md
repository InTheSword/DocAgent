# Current Status

Updated: 2026-06-13

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
formal retrieval and QA benchmark -> not benchmark_evaluated
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

- `python -m pytest -q`: 72 passed.
- Real GLOBOCAN `mineru_existing` smoke persisted SQLite document/block records.
- Existing-batch MinerU API read-only smoke returned `state=done`, downloaded a
  ZIP under `outputs/mineru_api/live_smoke/`, and safely extracted an ordinary
  `*_content_list.json`.

Status:

```text
Real MinerU output -> accepted
Phase 2B first milestone -> accepted
```

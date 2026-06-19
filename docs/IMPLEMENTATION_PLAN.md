# DocAgent Implementation Plan

> High-level roadmap only.  
> Current canonical status and stop condition are defined in
> `docs/ACTIVE_PLAN.md`.

## 1. Project objective

Build a verifiable complex-document QA assistant that covers:

```text
data and evidence schema
→ structure-aware document parsing
→ sparse/dense retrieval and reranking
→ traceable LangGraph workflow
→ Qwen3 SFT/GRPO AnswerPolicy
→ grounded answer and location validation
→ real-document demo and evaluation
```

## 2. Document map

| Document | Purpose |
|---|---|
| `AGENTS.md` | repository-wide Codex rules and document routing |
| `docs/ACTIVE_PLAN.md` | current canonical milestone, accepted status, and stop condition |
| `docs/PHASE4_ACTIVE_PLAN.md` | accepted Phase 4B working record and Gate 4 evidence summary |
| `docs/PHASE3_ACTIVE_PLAN.md` | completed/historical Phase 3 record |
| `docs/PHASE2_ACTIVE_PLAN.md` | accepted Phase 2 history and stop condition |
| `docs/IMPLEMENTATION_PLAN.md` | high-level roadmap and accepted/deferred phases |
| `docs/SERVER_SETUP.md` | local/server boundary and stable environment facts |
| `docs/DATASETS.md` | dataset sources, roles, split, and download policy |
| `docs/design/phase2/PHASE2_REAL_DOCUMENT_HYBRID_RETRIEVAL_MVP.zh-CN.md` | detailed Phase 2 ingestion/retrieval engineering design |
| `docs/design/phase2/PHASE2_STRUCTURED_PDF_PARSING_SUPPLEMENT.zh-CN.md` | detailed structured-PDF parsing design |
| `docs/DocAgent 技术文档 3.0.pdf` | original architecture blueprint |

Detailed design documents do not define the current active task.

## 3. Status definitions

Use:

```text
not_started
implemented
ready
mock_verified
server_dependency_ready
real_model_verified
benchmark_evaluated
accepted
frozen
blocked
blocked_by_missing_mineru_output
```

## 4. Accepted foundation

### Phase 0: schema and basic QA scaffold

Status: `accepted`

Delivered:

- unified QA/evidence schema;
- BM25 baseline;
- structured answer;
- location validation;
- SQLite trace.

### Phase 1A: MP-DocVQA data and reader training

Status: `accepted`

Delivered:

- document-level split;
- official-OCR retrieved-reader data;
- Qwen3-1.7B LoRA-SFT;
- grounded GRPO;
- answer/location/format evaluation;
- error analysis and experiment reports.

### Phase 1B: real AnswerPolicy workflow

Status: `accepted`

Delivered:

```text
Query Rewrite
→ BM25
→ Base/SFT/GRPO AnswerPolicy
→ JSON parse
→ format check
→ location check
→ bounded repair
→ SQLite trace
```

## 5. Accepted Phase 2A

### Phase 2A: real hybrid retrieval

Status: `accepted`

Delivered:

```text
existing EvidenceBlock
→ real BGE-M3
→ FAISS
→ BM25 + Dense + RRF
→ real reranker
→ existing Qwen3 workflow
→ JSON parse and validation
→ SQLite trace
```

Boundary:

```text
implementation/integration -> accepted
formal retrieval and QA benchmark -> not_started
```

## 6. Accepted Phase 2B

### Phase 2B: real MinerU and real-document QA

Status: `accepted`

Target:

```text
real PDF/image
→ real MinerU structured output
→ structure-aware EvidenceBlock
→ real hybrid retrieval
→ Qwen3 workflow
→ page/block citation
→ trace
```

First milestone:

```text
one real public PDF
→ one real MinerU structured output
→ EvidenceBlock conversion
→ structure quality acceptance
```

Detailed references:

```text
docs/design/phase2/PHASE2_REAL_DOCUMENT_HYBRID_RETRIEVAL_MVP.zh-CN.md
docs/design/phase2/PHASE2_STRUCTURED_PDF_PARSING_SUPPLEMENT.zh-CN.md
```

## 7. Current accepted milestone

### Phase 4B: MP-DocVQA raw-document MinerU ingestion and small-scale E2E

Status: `accepted`

Canonical source:

```text
docs/ACTIVE_PLAN.md
```

Accepted Gate 4 scope:

```text
MP-DocVQA val shards 1-4
-> 26 page-window documents
-> 197 pages
-> 90 QA
-> MinerU ingestion
-> page-level retrieval
-> GRPO AnswerPolicy
-> JSON / format / trace validation
```

Boundary:

```text
Phase 4B Gate 4 expanded raw-input regression -> accepted
formal benchmark -> not_started
CDC -> not_started
Router/tools -> not_started
Demo/closure -> not_started
```

Notes:

- Gate 4 is an expanded raw-input regression, not a formal benchmark.
- The main remaining quality issues are Reader `answer_miss` and
  `gold_page_location_miss`.
- `rank_aware_context` remains diagnostic only; the default is false.
- Gate 4 artifacts are server-side acceptance artifacts. Missing local
  mirrors under `outputs/phase4/mpdocvqa_raw_gate4_expanded`,
  `outputs/phase4/mpdocvqa_ingestion`, or
  `outputs/evaluation/phase4b_mpdocvqa_gate4/` do not indicate missing main
  branch code.

### Historical Phase 3A: focused evaluation and ablation

Status: `accepted`

Historical target:

```text
fixed benchmark subset
→ BM25 vs Hybrid retrieval comparison
→ fixed Hybrid evidence artifact
→ SFT vs GRPO AnswerPolicy comparison
→ summary report
```

Boundary:

```text
local framework -> implemented
real focused evaluation -> not_started
formal benchmark -> not_started
```

## 8. Planned phases

### CDC real-document scenario

Status: `not_started`

CDC is the next-stage candidate after Phase 4B, but it has not started in the
current main branch. Starting it requires an explicit phase switch in
`docs/ACTIVE_PLAN.md`.

### Router/tools

Status: `not_started`

Router/tool work remains after CDC and is not part of the accepted Phase 4B
scope.

### Table and numeric branch

Preferred depth extension:

- TAT-QA or equivalent table QA;
- structured table parser;
- calculator;
- numeric normalization;
- Numeric Accuracy;
- type-aware reward if new training is justified.

### Visual review branch

Optional after the table branch:

- image-region extraction;
- Qwen2.5-VL visual review;
- OCR-only vs OCR+VLM comparison;
- real visual evidence trace.

### Final phase: demo and materials

Status: `not_started`

- FastAPI or Gradio;
- file upload and document selection;
- evidence display and trace replay;
- final benchmark and real-document report;
- README, resume bullets, and interview material.

## 9. Global roadmap constraints

1. Complete one real-component milestone before expanding scope.
2. Mock backends are not project results.
3. Do not restart SFT/GRPO tuning during Phase 2.
4. Do not add datasets before the active system loop is accepted.
5. Do not claim MinerU, Dense, Reranker, table, or VLM capability before real verification.
6. Update this roadmap only when a phase is accepted or priorities change.

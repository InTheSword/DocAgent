# DocAgent Implementation Plan

> High-level roadmap only.  
> Current executable work is defined in `docs/PHASE2_ACTIVE_PLAN.md`.

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
| `docs/PHASE2_ACTIVE_PLAN.md` | current unique milestone and stop condition |
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
mock_verified
server_dependency_ready
real_model_verified
benchmark_evaluated
accepted
frozen
blocked
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

Status: `accepted / frozen`

Delivered:

- document-level split;
- official-OCR retrieved-reader data;
- Qwen3-1.7B LoRA-SFT;
- grounded GRPO;
- answer/location/format evaluation;
- error analysis and experiment reports.

### Phase 1B: real AnswerPolicy workflow

Status: `accepted / frozen`

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

## 5. Active phase

### Phase 2A: real hybrid retrieval

Status: defined in `docs/PHASE2_ACTIVE_PLAN.md`

Target:

```text
existing EvidenceBlock
→ real BGE-M3
→ FAISS
→ BM25 + Dense + RRF
→ real reranker
→ existing Qwen3 workflow
```

## 6. Planned phases

### Phase 2B: real MinerU and real-document QA

Start only after Phase 2A acceptance.

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

Detailed references:

```text
docs/design/phase2/PHASE2_REAL_DOCUMENT_HYBRID_RETRIEVAL_MVP.zh-CN.md
docs/design/phase2/PHASE2_STRUCTURED_PDF_PARSING_SUPPLEMENT.zh-CN.md
```

### Phase 3: table and numeric branch

Preferred depth extension:

- TAT-QA or equivalent table QA;
- structured table parser;
- calculator;
- numeric normalization;
- Numeric Accuracy;
- type-aware reward if new training is justified.

### Phase 4: visual review branch

Optional after the table branch:

- image-region extraction;
- Qwen2.5-VL visual review;
- OCR-only vs OCR+VLM comparison;
- real visual evidence trace.

### Final phase: demo and materials

- FastAPI or Gradio;
- file upload and document selection;
- evidence display and trace replay;
- final benchmark and real-document report;
- README, resume bullets, and interview material.

## 7. Global roadmap constraints

1. Complete one real-component milestone before expanding scope.
2. Mock backends are not project results.
3. Do not restart SFT/GRPO tuning during Phase 2.
4. Do not add datasets before the active system loop is accepted.
5. Do not claim MinerU, Dense, Reranker, table, or VLM capability before real verification.
6. Update this roadmap only when a phase is accepted or priorities change.

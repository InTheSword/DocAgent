# DocAgent Implementation Plan

> Role: high-level project roadmap and milestone status.  
> The current executable task is defined in `docs/PHASE2_ACTIVE_PLAN.md`.  
> Historical training commands and experiment details should remain in experiment reports or Git history, not in this roadmap.

---

## 1. Source of truth

Read project documents in this order:

1. `AGENTS.md`
2. `docs/PHASE2_ACTIVE_PLAN.md`
3. `docs/IMPLEMENTATION_PLAN.md`
4. `docs/SERVER_SETUP.md`
5. `docs/DATASETS.md`
6. `CURRENT_STATUS.md`
7. `DECISIONS.md`
8. Current code, tests, and generated reports

`DocAgent 技术文档 3.0` is the overall blueprint. It does not mean every planned module has already been implemented.

---

## 2. Project objective

DocAgent is a complex-document QA and post-training project that aims to provide:

```text
real document input
→ structured parsing
→ EvidenceBlock construction
→ BM25 + Dense Retrieval + RRF + Reranker
→ Qwen3 Answer Policy
→ format/location validation
→ bounded repair
→ SQLite trace
```

The project prioritizes a complete, verifiable system loop. Model quality and large-scale training optimization are secondary until the real-component workflow is complete.

---

## 3. Status vocabulary

Every module must use one of the following states:

```text
not_started
implemented
mock_verified
server_dependency_ready
real_model_verified
benchmark_evaluated
accepted
frozen
```

Definitions:

- `implemented`: code exists.
- `mock_verified`: unit/mock wiring works, but no real model/tool has been verified.
- `server_dependency_ready`: required package/model/artifact exists on the server.
- `real_model_verified`: the real model or parser completed a server smoke test.
- `benchmark_evaluated`: reproducible evaluation output exists.
- `accepted`: milestone acceptance criteria are satisfied.
- `frozen`: do not modify unless explicitly requested.

Mock verification must never be reported as real-component completion.

---

## 4. Current status snapshot

| Component | Status | Notes |
|---|---|---|
| Unified schema / EvidenceBlock | accepted | Used by Phase 1 and current Phase 2 code |
| MP-DocVQA official OCR pipeline | accepted | Main text-reader training source |
| Query Rewrite + BM25 baseline | accepted | Same-document retrieval baseline |
| Qwen3 LoRA-SFT | accepted / frozen | Selected checkpoint exists |
| Grounded GRPO | accepted / frozen | Selected checkpoint exists |
| LangGraph AnswerPolicy workflow | accepted / frozen | Base/SFT/GRPO switch, validation, repair, trace |
| SQLite QA trace | accepted | Phase 1 workflow replay verified |
| MinerU `parse_existing` fixture | mock_verified | Synthetic/fixture output only |
| Document registry / SHA256 cache | implemented / mock_verified | Awaiting real-document acceptance |
| Hash dense backend | mock_verified / frozen | CI only; not a project result |
| Keyword reranker | mock_verified / frozen | CI only; not a project result |
| BGE-M3 dense retrieval | implemented, not real_model_verified | Current active milestone |
| Real cross-encoder reranker | implemented, not real_model_verified | Current active milestone |
| Real MinerU output | not_started or not real_model_verified | Next milestone after real retrieval |
| Real PDF end-to-end QA | not_started | Depends on real MinerU + real retrieval |
| TAT-QA numeric branch | deferred | Later phase |
| Infographic/VLM branch | deferred | Later phase |
| Gradio/FastAPI demo | deferred | After the core loop is accepted |

---

## 5. Data and parser policy

### MP-DocVQA

Current Phase 1 training and evaluation use MP-DocVQA official QA/OCR-derived artifacts.

Do not describe the current training data as full MinerU-parsed MP-DocVQA.

### Real uploaded documents

MinerU is the target parser for real PDF/image ingestion.

The active parser roles are:

```text
MP-DocVQA training/eval: official OCR
real PDF/image ingestion: MinerU
PaddleOCR: optional fallback or comparison only
```

PaddleOCR is not the default active parser and must not be introduced without an explicit task.

---

## 6. Completed milestones

### Milestone 0: MVP scaffold

Status: `accepted`

Delivered:

- basic schema;
- BM25 smoke;
- structured answer;
- location validation;
- SQLite trace.

### Milestone 1: MP-DocVQA reader data and training

Status: `accepted / frozen`

Delivered:

- document-level split;
- retrieved-reader SFT data;
- Qwen3-1.7B LoRA-SFT;
- grounded GRPO;
- answer/location/format evaluation;
- experiment and error-analysis reports.

Do not continue GRPO scaling or reward sweeps during Phase 2.

### Milestone 2: Phase 1 real AnswerPolicy workflow

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

---

## 7. Active Phase 2 milestone

The only active milestone is defined in:

```text
docs/PHASE2_ACTIVE_PLAN.md
```

Current target:

```text
existing EvidenceBlock
→ real BGE-M3
→ FAISS
→ BM25 + Dense + RRF
→ real bge-reranker-v2-m3
→ existing Qwen3 workflow
```

Do not start real MinerU installation, TAT-QA, VLM, demo, or new training until this milestone is accepted.

---

## 8. Next milestones

### Phase 2B: real MinerU and real-document end-to-end

Start only after Phase 2A real hybrid retrieval is accepted.

Target:

```text
real PDF/image
→ real MinerU structured output
→ heading/text/table/image EvidenceBlock
→ real hybrid retrieval
→ Qwen3 workflow
→ page/block citation
→ SQLite trace
```

Acceptance requires at least one real MinerU output and one real PDF end-to-end query.

### Phase 3A: table/numeric branch

Preferred next depth extension:

- TAT-QA or equivalent structured table QA;
- table parser;
- calculator;
- numeric normalization;
- Numeric Accuracy;
- type-aware reward if new training is needed.

### Phase 3B: visual review branch

Optional after the table branch:

- image region extraction;
- Qwen2.5-VL review;
- OCR-only vs OCR+VLM comparison;
- no claim of visual understanding before real VLM verification.

### Final phase: demo and materials

- FastAPI or Gradio;
- document upload;
- evidence display;
- trace replay;
- README;
- final evaluation report;
- resume and interview materials.

---

## 9. Evaluation policy

### Retrieval

Use:

```text
Recall@1
Recall@3
Recall@5
MRR@5
mean/p95 latency
```

Required ablations:

```text
BM25
Dense
BM25 + Dense + RRF
BM25 + Dense + RRF + real Reranker
```

Mock/hash/keyword results are not formal metrics.

### Answer workflow

Use:

```text
Answer EM/F1
Location Accuracy
raw JSON rate
schema pass rate
workflow success
trace persist rate
```

### Real-document smoke

Each accepted real-document run must save:

- source document hash;
- parser backend;
- parser artifact path;
- retriever backend;
- model IDs;
- top-k block IDs;
- final answer and location;
- SQLite run ID.

---

## 10. Global constraints

1. Do not auto-download large models or datasets.
2. Do not modify the stable `docagent` environment to install MinerU.
3. Do not treat no-card CUDA unavailability as an environment failure.
4. Do not optimize mock backends after wiring smoke passes.
5. Do not report a module as complete before real server verification.
6. Do not pass gold answers or gold locations into inference or repair.
7. Do not change frozen SFT/GRPO checkpoints during Phase 2.
8. Do not add a new phase while the active milestone remains unaccepted.

# Phase 2 Active Plan

> This file defines the only active Codex milestone.  
> It is intentionally short and operational.

## 1. Active milestone

```text
Phase 2A: verify real BGE-M3 and real cross-encoder reranker
```

Target flow:

```text
existing EvidenceBlock
→ real BGE-M3 embeddings
→ FAISS index
→ BM25 + Dense
→ RRF
→ real bge-reranker-v2-m3
→ existing Qwen3 workflow
→ location validation
→ SQLite trace
```

MinerU installation and real PDF parsing are not prerequisites for Phase 2A.

## 2. Current status

| Component | Status | Role |
|---|---|---|
| Query Rewrite + BM25 | accepted / frozen | formal baseline |
| Phase 1 Qwen3 AnswerPolicy workflow | accepted / frozen | downstream reader |
| Hash dense | mock_verified / frozen | CI only |
| Keyword reranker | mock_verified / frozen | CI only |
| BGE-M3 wrapper | implemented | requires server verification |
| FAISS index | implemented / mock_verified | requires real embeddings |
| RRF | implemented / mock_verified | requires real candidates |
| Real reranker wrapper | implemented | requires server verification |
| MinerU fixture | mock_verified | not real parser evidence |
| Real MinerU output | not_started | next milestone |

## 3. Immediate task

The current task is:

```text
run and review Phase 2 preflight
```

Preflight implementation commit:

```text
793eda3280e3efd586233a478be6c9023b6b25aa
```

The preflight must inspect only:

- Git/runtime information;
- required package availability;
- expected model paths;
- existing EvidenceBlock/benchmark artifacts;
- existing dense index artifacts;
- real vs synthetic MinerU artifacts.

It must not:

- install;
- download;
- load full model weights;
- build embeddings;
- run real retrieval;
- invoke MinerU.

## 4. Required references for the current task

Read:

```text
AGENTS.md
docs/PHASE2_ACTIVE_PLAN.md
docs/SERVER_SETUP.md
scripts/preflight_phase2.py
tests/test_preflight_phase2.py
```

Do not read the full Phase 2 design documents or blueprint PDF unless the preflight code exposes an architecture ambiguity.

## 5. Preflight acceptance

Preflight is accepted when:

- targeted tests pass;
- regression tests pass;
- the server generates `outputs/preflight/phase2.json`;
- missing packages/models/artifacts are clearly identified;
- no environment or model mutation occurs.

After the server JSON is obtained:

```text
stop
review the actual missing items
prepare one minimal dependency/model action
```

Do not install or download anything before review.

## 6. Phase 2A implementation after preflight

Only after explicit approval:

1. prepare missing real BGE-M3/Reranker dependencies;
2. load real BGE-M3;
3. build and reload FAISS index;
4. run BM25 and Dense retrieval;
5. fuse with RRF;
6. run real cross-encoder reranking;
7. pass top-k into the existing Qwen3 workflow;
8. persist backend/model IDs, scores, ranks, answer, location, and trace;
9. save one compact server smoke report.

Detailed implementation reference:

```text
docs/design/phase2/PHASE2_REAL_DOCUMENT_HYBRID_RETRIEVAL_MVP.zh-CN.md
```

Read only relevant retrieval/index/workflow sections.

## 7. Phase 2A acceptance

Phase 2A is accepted only when the server verifies:

```text
dense_backend = bge_m3
reranker_backend = bge_reranker_v2_m3
dense_model_loaded = true
reranker_model_loaded = true
```

Also required:

- no hash/keyword fallback;
- FAISS index save/reload works;
- one real query completes;
- candidate scores/ranks are persisted;
- final location belongs to returned top-k;
- SQLite trace exists;
- model/backend IDs are recorded.

Mock success alone cannot mark the milestone accepted.

## 8. Out of scope

Do not start:

- MinerU installation or real MinerU CLI;
- real PDF ingestion;
- TAT-QA;
- InfographicVQA or VLM;
- new SFT/GRPO;
- reward changes;
- AnswerPolicy prompt changes;
- dataset rebuilding;
- Gradio/FastAPI;
- mock-backend optimization.

## 9. Stop conditions

### Current stop condition

After server preflight JSON is returned:

```text
stop and review it before any environment change
```

### Phase 2A stop condition

After one real retrieval smoke and saved report:

```text
stop and request explicit milestone acceptance
```

## 10. Next milestone

Only after Phase 2A is accepted:

```text
Phase 2B:
real MinerU output
→ structure-aware EvidenceBlock
→ real hybrid retrieval
→ real PDF end-to-end QA
```

Phase 2B must use:

```text
docs/design/phase2/PHASE2_REAL_DOCUMENT_HYBRID_RETRIEVAL_MVP.zh-CN.md
docs/design/phase2/PHASE2_STRUCTURED_PDF_PARSING_SUPPLEMENT.zh-CN.md
```

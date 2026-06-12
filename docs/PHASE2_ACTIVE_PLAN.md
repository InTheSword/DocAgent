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
| BGE-M3 wrapper | real_model_verified | server model API smoke passed |
| FAISS index | implemented / mock_verified | requires real embeddings |
| RRF | implemented / mock_verified | requires real candidates |
| Real reranker wrapper | real_model_verified | server model API smoke passed |
| MinerU fixture | mock_verified | not real parser evidence |
| Real MinerU output | not_started | next milestone |

## 3. Immediate task

The current task is:

```text
run real hybrid retrieval component smoke
```

Recent verified checkpoints:

```text
FlagEmbedding -> server_dependency_ready
BGE-M3 -> real_model_verified
bge-reranker-v2-m3 -> real_model_verified
```

The current smoke must validate:

- existing EvidenceBlock input from `data/benchmark/smoke_eval.jsonl`;
- real BGE-M3 embeddings;
- a newly built and reloaded FAISS index with a non-mock model ID;
- BM25 + Dense retrieval;
- RRF candidate fusion;
- real `bge-reranker-v2-m3` scoring through the Transformers sequence-classification backend;
- compact JSON output at `outputs/smoke/phase2_real_retrieval.json`.

It must not:

- install;
- download;
- reuse `hash-dense-256`;
- use keyword reranker fallback;
- run Qwen3 AnswerPolicy or LangGraph;
- run formal retrieval ablation;
- invoke MinerU.

## 4. Required references for the current task

Read:

```text
AGENTS.md
docs/PHASE2_ACTIVE_PLAN.md
docs/SERVER_SETUP.md
docs/design/phase2/PHASE2_REAL_DOCUMENT_HYBRID_RETRIEVAL_MVP.zh-CN.md
current retrieval/index/reranker/smoke code
```

Read only the retrieval/index/reranker/metadata sections of the design document.

## 5. Preflight acceptance

Real retrieval component smoke is accepted when:

- targeted tests pass;
- regression tests pass;
- the server generates `outputs/smoke/phase2_real_retrieval.json`;
- `dense_backend = bge_m3`;
- `reranker_backend = transformers_sequence_classification`;
- FAISS index save/reload is verified;
- BM25, Dense, RRF, reranker score, and final top-k ranks are recorded;
- no hash/keyword fallback occurs.

After the server JSON is obtained:

```text
stop
review the real retrieval smoke result
```

Do not enter Qwen3 workflow smoke before review.

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
reranker_backend = transformers_sequence_classification
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

After server real retrieval smoke JSON is returned:

```text
stop and review it before Qwen3 workflow smoke
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

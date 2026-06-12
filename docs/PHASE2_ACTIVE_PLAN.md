# Phase 2 Active Plan

> This file defines the only active Codex milestone.  
> Broader design remains in `docs/IMPLEMENTATION_PLAN.md`.

---

## 1. Current milestone

```text
Phase 2A: real BGE-M3 + real cross-encoder reranker integration
```

Use existing EvidenceBlock artifacts. Do not make MinerU installation a prerequisite for this milestone.

Target flow:

```text
existing EvidenceBlock
→ real BGE-M3 document/query embeddings
→ FAISS index
→ BM25 + Dense
→ RRF
→ real bge-reranker-v2-m3
→ existing Qwen3 GRPO workflow
→ location validation
→ SQLite trace
```

---

## 2. Current status

| Module | Status | Allowed role |
|---|---|---|
| BM25 | accepted | formal baseline |
| Query Rewrite | accepted / frozen | current rule-based implementation |
| Hash dense | mock_verified / frozen | CI only |
| Keyword reranker | mock_verified / frozen | CI only |
| BGE-M3 wrapper | implemented, not real_model_verified | active |
| FAISS index | implemented/mock_verified | active |
| RRF | implemented/mock_verified | active |
| Real reranker wrapper | implemented, not real_model_verified | active |
| Qwen3 AnswerPolicy | accepted / frozen | downstream workflow |
| MinerU fixture | mock_verified | not sufficient for real parser acceptance |
| Real MinerU output | not active in this milestone | next milestone |

---

## 3. Immediate deliverable

Before any large installation or model download, implement:

```text
scripts/preflight_phase2.py
```

The script must inspect only and output compact JSON.

Required checks:

- git commit;
- Python version;
- Torch version;
- no-card/GPU state;
- package presence:
  - `FlagEmbedding`
  - `faiss`
  - reranker-required package(s);
- expected model paths:
  - Qwen3;
  - BGE-M3;
  - reranker;
- existing benchmark/EvidenceBlock artifact;
- existing dense index artifact;
- existence of real MinerU output.

The script must not:

- install;
- download;
- load full model weights;
- fail with a long traceback because an optional resource is missing.

---

## 4. Milestone implementation requirements

After preflight is reviewed and dependencies/models are explicitly approved:

1. load real BGE-M3;
2. encode existing EvidenceBlock text;
3. build and reload FAISS index;
4. run BM25 top-N and Dense top-N;
5. fuse with RRF;
6. run real bge-reranker-v2-m3;
7. return top-k with real backend/model metadata;
8. pass top-k into the existing Qwen3 GRPO workflow;
9. persist retrieval and QA trace;
10. save a compact server smoke report.

---

## 5. Out of scope

Do not modify or start:

- MinerU installation;
- real MinerU CLI integration;
- TAT-QA;
- InfographicVQA;
- VLM;
- new SFT;
- new GRPO;
- reward;
- AnswerPolicy prompt;
- training split;
- mock backend quality;
- Gradio/FastAPI.

---

## 6. Preflight acceptance

Preflight is accepted when:

- the script is committed;
- targeted tests pass;
- full regression tests pass;
- server outputs one compact JSON;
- missing packages/models are clearly identified;
- no environment change occurs.

---

## 7. Real retrieval acceptance

The milestone is accepted only when the AutoDL server verifies:

```text
dense_backend = bge_m3
reranker_backend = bge_reranker_v2_m3
dense_model_loaded = true
reranker_model_loaded = true
```

Additional requirements:

- no hash/keyword silent fallback;
- FAISS index can be saved and reloaded;
- one real query completes;
- scores/ranks are persisted;
- final location refers to returned top-k;
- SQLite trace exists;
- backend/model IDs are present in the report.

Mock success alone cannot move the milestone to `accepted`.

---

## 8. Server handoff protocol

Codex may provide only one server command group per round.

Success response requested from the user:

```json
{
  "command": "phase2_real_retrieval_smoke",
  "status": "success",
  "backend": {
    "dense": "bge_m3",
    "reranker": "bge_reranker_v2_m3"
  },
  "artifact_paths": [],
  "metrics": {}
}
```

Failure response:

```json
{
  "command": "phase2_real_retrieval_smoke",
  "status": "failed",
  "exit_code": 1,
  "exception": "...",
  "log_tail": "last 60 lines"
}
```

Do not request full blocks/prompts/traces unless debugging a named field.

---

## 9. Stop condition

After preflight implementation, Codex must stop and wait for the server preflight JSON.

After real retrieval smoke, Codex must stop and wait for explicit acceptance before starting real MinerU work.

---

## 10. Next milestone

Only after this plan is accepted:

```text
Phase 2B:
real MinerU output
→ structure-aware EvidenceBlock
→ real PDF end-to-end QA
```

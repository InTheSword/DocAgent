# Phase 2 Active Plan

> This file defines the only active Codex milestone.  
> It is intentionally short and operational.

## 1. Accepted checkpoint

```text
Phase 2A: accepted
```

Accepted implementation/integration scope:

```text
existing EvidenceBlock
→ real BGE-M3 embeddings
→ FAISS index save/reload
→ BM25 + Dense + RRF
→ real bge-reranker-v2-m3 reranking
→ Qwen3 GRPO AnswerPolicy workflow
→ JSON parse
→ format/location validation
→ SQLite trace
```

Server evidence:

```text
BGE-M3 -> real_model_verified
FAISS index save/reload -> real_model_verified
BM25 + Dense + RRF -> real_model_verified
Transformers Reranker -> real_model_verified
real hybrid retrieval -> accepted
real Qwen3 workflow integration -> accepted
```

Workflow smoke artifact:

```text
outputs/smoke/phase2_real_workflow.json
run_id = 1d88ec99-1f62-4746-9ae2-c0616fa924e7
dense_backend = bge_m3
reranker_backend = transformers_sequence_classification
answer_policy = grpo
doc_id = smoke_invoice
top_k = ["smoke_invoice_p1_b1"]
final_location.block_id = smoke_invoice_p1_b1
```

Important boundary:

```text
Phase 2A implementation/integration -> accepted
formal retrieval and QA benchmark -> not benchmark_evaluated
```

The single successful smoke validates the real-component integration path. It is
not a Recall/MRR, answer-quality, latency, or benchmark-performance conclusion.

## 2. Active milestone

```text
Phase 2B: real structured PDF parsing entry milestone
```

Phase 2B target flow:

```text
real PDF
→ real MinerU structured output
→ structure-aware EvidenceBlock
→ real BGE-M3 + RRF + Reranker
→ Qwen3 GRPO AnswerPolicy
→ page/block citation
→ SQLite trace
```

Current Phase 2B first milestone:

```text
one real public PDF
→ one real MinerU output
→ EvidenceBlock conversion
→ structure quality acceptance
```

Do not start the full end-to-end Phase 2B loop until this first milestone is
reviewed and accepted.

## 3. Current status

| Component | Status | Role |
|---|---|---|
| Query Rewrite + BM25 | accepted / frozen | formal baseline |
| Phase 1 Qwen3 AnswerPolicy workflow | accepted / frozen | downstream reader |
| Hash dense | mock_verified / frozen | CI only |
| Keyword reranker | mock_verified / frozen | CI only |
| BGE-M3 wrapper | real_model_verified | server model API smoke passed |
| FAISS index save/reload | real_model_verified | server real retrieval smoke passed |
| BM25 + Dense + RRF | real_model_verified | server real retrieval smoke passed |
| Real reranker wrapper | real_model_verified | Transformers sequence-classification backend |
| Real hybrid retrieval | accepted | server real workflow smoke passed |
| Real Qwen3 workflow integration | accepted | GRPO workflow smoke passed |
| Phase 2A | accepted | integration accepted, benchmark not evaluated |
| MinerU fixture | mock_verified | synthetic fixture only |
| Real MinerU output | not_started | Phase 2B first milestone |

## 4. Immediate task

The next implementation task is:

```text
prepare and validate one real MinerU structured output for one real public PDF
```

The task must validate:

- the selected PDF source and local file identity;
- real MinerU output produced outside the stable `docagent` environment;
- structured output availability, preferably `content_list` or middle JSON;
- conversion to DocAgent `EvidenceBlock`;
- page, block_id, block_type, text/table/image fields where available;
- location metadata such as page and bbox when present;
- reading order and section/context metadata when available;
- one compact structure-quality JSON report.

It must not:

- install MinerU into the stable `docagent` environment;
- start real hybrid retrieval over the new PDF;
- run Qwen3 AnswerPolicy;
- run formal retrieval or QA benchmark;
- modify SFT, GRPO, reward, prompts, or checkpoints;
- add TAT-QA, VLM, Demo, or Phase 3 work.

## 5. Required references for Phase 2B work

Read before planning or implementing Phase 2B work:

```text
AGENTS.md
docs/PHASE2_ACTIVE_PLAN.md
docs/SERVER_SETUP.md
docs/design/phase2/PHASE2_REAL_DOCUMENT_HYBRID_RETRIEVAL_MVP.zh-CN.md
docs/design/phase2/PHASE2_STRUCTURED_PDF_PARSING_SUPPLEMENT.zh-CN.md
current parser, ingestion, storage, retrieval, workflow, scripts, and tests as needed
```

Read only the sections relevant to the active Phase 2B first milestone.

## 6. Acceptance for Phase 2B first milestone

The first Phase 2B milestone is accepted only when:

- a real public PDF is identified and its local path is recorded;
- one real MinerU structured output exists outside Git-managed source files;
- the output is converted into `EvidenceBlock` records;
- structure fields are checked and summarized;
- synthetic MinerU fixtures are not reported as real parser evidence;
- no Qwen, retrieval benchmark, or full E2E claim is made;
- a compact server JSON/report path is returned.

## 7. Stop condition

After one real MinerU output is converted and the structure-quality report is
saved:

```text
stop and review the parser/EvidenceBlock quality before starting full Phase 2B E2E
```


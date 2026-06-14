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
Phase 2B-2: real-document end-to-end scenario acceptance
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

Current Phase 2B-2 milestone:

```text
GLOBOCAN source PDF
-> mineru_existing ingestion
-> retrieval-eligible EvidenceBlocks
-> real BGE-M3 + FAISS + BM25 + RRF + reranker
-> Qwen3 GRPO AnswerPolicy workflow
-> JSON/format/location validation
-> SQLite trace
-> scenario acceptance report
```

This is a real-document scenario acceptance flow, not a formal DocVQA,
MP-DocVQA, or general PDF-QA benchmark.

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
| Real MinerU output | accepted | GLOBOCAN API output converted and quality-checked |
| Phase 2B-2 E2E verifier | accepted | real GLOBOCAN server scenario acceptance passed |

## 4. Immediate task

The completed implementation task is:

```text
run fixed GLOBOCAN real-document E2E verifier on AutoDL
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

Current accepted artifact:

```text
source = data/real_documents/globocan_africa_2022/source/original.pdf
doc_id = fe3465edd3da60d2
source_sha256 = fe3465edd3da60d26b2020ab751d75bfba26a465a9d66c43eff5dce12f4db37a
mineru_batch_id = 56a4776f-aa1c-47d0-8901-99038de6a851
raw_block_count = 57
converted_block_count = 57
page_count = 2
table_count = 5
chart_count = 6
boilerplate_count = 22
empty_boilerplate_count = 2
missing_retrieval_content_count = 0
image_reference_count = 11
missing_image_reference_count = 0
persisted_absolute_path_count = 0
structure_quality = passed_with_warnings
warning = mineru_origin_pdf_sha256_differs_from_source_pdf
verifier = scripts/verify_phase2b_real_pdf.py
verification_report = outputs/verification/phase2b_globocan/verification_report.json
```

Current implemented Phase 2B-2 local artifact contract:

```text
scenario_qa = data/real_documents/globocan_africa_2022/qa/scenario_qa.jsonl
verifier = scripts/verify_phase2b_real_e2e.py
target_report = outputs/verification/phase2b_real_e2e/verification_report.json
local_status = implemented
server_real_model_status = accepted
```

Current Phase 2B-2 server result:

```text
result_type = real-document scenario acceptance
status = success
sample_count = 8
completed_count = 8
retrieval_block_count = 35
sqlite_qa_runs = 8
sqlite_tool_traces = 49
no_gold_leakage = true
no_mock_fallback = true

Retrieval:
Recall@1 = 0.875
Recall@3 = 0.875
Recall@5 = 0.875
MRR = 0.875
gold_page_hit_rate = 1.0

Answer:
normalized_exact_match = 0.625
token_f1 = 0.675
character_f1 = 0.7842548076923077
answer_hit = 0.625
valid_json_rate = 1.0
format_valid_rate = 1.0

Location:
block_location_hit = 0.875
page_location_hit = 1.0
final_location_in_retrieved_top_k = 1.0
location_valid_rate = 1.0

Failure cases:
reader_table_column_selection_error = 2
retrieval_miss_partial_answer_location_miss = 1
```

This is a real-document scenario acceptance result, not a formal benchmark.

It must not:

- install MinerU into the stable `docagent` environment;
- call MinerU API again;
- process CDC PDF;
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

Status:

```text
Phase 2B first milestone: accepted
Phase 2B first milestone merge-prep quality hardening: accepted
Phase 2B-2 real-document E2E verifier: accepted
Phase 2B-2 implementation/integration: accepted
Phase 2B-2 scenario quality: measured
formal benchmark: not benchmark_evaluated
```

## 7. Stop condition

After Phase 2B-2 server scenario acceptance is recorded:

```text
stop before quality optimization, CDC, demo, formal benchmark, or training changes
```

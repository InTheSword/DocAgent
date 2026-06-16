# Current Status

Updated: 2026-06-16

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

- `python -m pytest -q`: 72 passed before merge-prep hardening.
- Real GLOBOCAN `mineru_existing` smoke persisted SQLite document/block records.
- Existing-batch MinerU API read-only smoke returned `state=done`, downloaded a
  ZIP under `outputs/mineru_api/live_smoke/`, and safely extracted an ordinary
  `*_content_list.json`.

Merge-prep hardening:

- Persisted MinerU artifact paths are document-directory-relative POSIX paths
  in EvidenceBlocks, page documents, ingestion report, structure-quality report,
  source manifest, and SQLite `payload_json`.
- `image_path` is the EvidenceBlock resource reference; duplicate
  `metadata.normalized_resource_path` and `metadata.source_content_list` are no
  longer written.
- Structure quality now reports `missing_retrieval_content_count`,
  `empty_boilerplate_count`, and `empty_boilerplate_block_ids` separately, so
  retained empty boilerplate does not fail quality status.
- Added fixed verifier `scripts/verify_phase2b_real_pdf.py`.
- Local validation after hardening:
  `python -m pytest -q`: 74 passed.
- Real GLOBOCAN verifier:
  `outputs/verification/phase2b_globocan/verification_report.json`;
  `raw_block_count=57`, `converted_block_count=57`, `page_document_count=2`,
  `table_count=5`, `chart_count=6`, `empty_boilerplate_count=2`,
  `missing_retrieval_content_count=0`, `persisted_absolute_path_count=0`,
  `overall_status=passed_with_warnings`.

Status:

```text
Real MinerU output -> accepted
Phase 2B first milestone -> accepted
```

## Phase 2B-2 Accepted

Phase 2B-2 real-document scenario acceptance is complete. This is a
real-document scenario acceptance result, not a formal benchmark.

Accepted integration:

- Real GLOBOCAN PDF and existing MinerU output were ingested through
  `mineru_existing`.
- 57 raw records converted to 57 EvidenceBlocks; 22 boilerplate blocks were
  excluded, leaving 35 retrieval blocks.
- Real BGE-M3, FAISS, BM25, RRF, Transformers sequence-classification reranker,
  and Qwen3 GRPO AnswerPolicy ran end to end.
- JSON, format, and location validation completed through the existing workflow.
- SQLite trace persisted 8 `qa_runs` and 49 `tool_traces`.
- `no_gold_leakage=true`, `no_mock_fallback=true`, and
  `persisted_absolute_path_count=0`.

Scenario metrics:

- Scenario samples: 8/8 completed.
- Retrieval: `Recall@1=0.875`, `Recall@3=0.875`, `Recall@5=0.875`,
  `MRR=0.875`, `gold_page_hit_rate=1.0`.
- Answer: `normalized_exact_match=0.625`, `token_f1=0.675`,
  `character_f1=0.7842548076923077`, `answer_hit=0.625`,
  `valid_json_rate=1.0`, `format_valid_rate=1.0`.
- Location: `block_location_hit=0.875`, `page_location_hit=1.0`,
  `final_location_in_retrieved_top_k=1.0`, `location_valid_rate=1.0`.

Failure taxonomy:

- 2 reader table-column selection errors: q001 and q002 selected the Males
  column instead of Both sexes while retrieval and location were correct.
- 1 retrieval / partial-answer / location error: q008 missed the large table
  gold block, returned a partial liver cases answer, and cited the wrong block.

Status:

```text
Phase 2B-2 -> accepted
implementation/integration -> accepted
scenario quality -> measured
formal benchmark -> not benchmark_evaluated
quality optimization -> deferred
```

## Phase 3A Implemented

Phase 3A local focused-evaluation framework is implemented. Real focused
evaluation on AutoDL has not started.

Implemented locally:

- benchmark validity contract for corpus-backed records with
  `metadata.gold_block_ids`;
- deterministic qid-hash subset sampling;
- BM25 vs Hybrid retrieval runner using shared retrieval code;
- fixed Hybrid evidence artifact generation for shared SFT/GRPO reader input;
- SFT vs GRPO AnswerPolicy runner over identical evidence order;
- comparison JSON and Markdown summary outputs;
- fixture tests using explicit mock backends only.

Status:

```text
Phase 3A -> implemented
real focused evaluation -> not_started
retrieval evaluation -> blocked
answer policy evaluation -> implemented
formal benchmark -> not_started
```

Boundary:

- Local validation does not load real BGE-M3, reranker, SFT, or GRPO models.
- Mock fixture output must not be reported as real focused-evaluation results.
- The current `mp_docvqa_imdb_ocr_5000_split/dev.jsonl` artifact is not an
  accepted retrieval corpus because its evidence is stored per QA record and no
  independent canonical per-doc corpus artifact has been verified.
- `scripts/build_phase3_mpdocvqa_retrieval_benchmark.py` can build the required
  QA/corpus/manifest artifacts from real RRC IMDb / official OCR data, but the
  server has not yet produced and validated those artifacts.
- SFT vs GRPO can still run through `--answer-only` when a reader evidence
  artifact passes the reader contract, but that path must not report retrieval
  Recall/MRR.
- Do not modify retrieval algorithms, query normalization, prompts,
  AnswerPolicy, reward code, checkpoints, or training data in Phase 3A.

## Phase 3 Local Closure Implemented

The local Phase 3 closure now separates model-facing protocol, real-document
contracts, and server acceptance orchestration. No real model evaluation has
been run for this update.

Implemented locally:

- Added a shared evidence-context builder and checkpoint-compatible answer
  prompt compiler used by SFT dataset construction, GRPO dataset construction,
  heuristic policy, Qwen AnswerPolicy, and the workflow model node.
- Added a canonical output adapter so workflow traces can store raw model
  output, canonical output, validation status, and repair status consistently.
- Extended workflow traces with `prompt_version`, `task_type`, selected and
  dropped block ids, `evidence_context_hash`, prompt token count, truncation,
  raw output, canonical output, validation, and repair metadata.
- Added real-document QA/corpus/document-manifest/benchmark-manifest contract
  construction for the existing GLOBOCAN scenario corpus.
- Added one fixed server acceptance entry point:
  `scripts/run_phase3_server_acceptance.py`.
- Added `--retrieval-only` to the Phase 3 focused runner so retrieval contract
  checks and real-document retrieval regression can run without loading SFT or
  GRPO adapters.

Status:

```text
training-inference contract -> implemented
real-document evaluation framework -> implemented
server real evaluation -> measured
GLOBOCAN regression -> accepted
fixed-evidence safety hotfix -> server_validated
MP-DocVQA retrieval evaluation -> blocked
MP-DocVQA AnswerPolicy evaluation -> measured
CDC -> next_priority
```

Boundary:

- Local tests use fixtures or help startup only; they do not load BGE-M3,
  reranker, Qwen, SFT adapter, or GRPO adapter.
- CDC is the next priority and still requires server-side MinerU output or
  MinerU API ingestion before it can become a second accepted real-document
  scenario.
- GLOBOCAN regression is accepted as a real-document scenario contract, not a
  formal benchmark result.

## Phase 3 GLOBOCAN Server Regression Accepted

The GLOBOCAN real-document scenario regression passed on AutoDL at commit
`3390bcde1c703c7bd95c567e6da3bdb04591c0d8`.

Server environment for that historical GLOBOCAN run:

```text
Python -> /root/miniconda3/envs/docagent/bin/python
Conda environment -> docagent
GPU -> 2 x NVIDIA GeForce RTX 4090 D
PyTorch -> 2.12.0+cu130
Transformers -> 5.8.1
PEFT -> 0.19.1
FlagEmbedding -> import passed
```

Run scope:

```text
evaluation_scope = scenario_regression
formal_benchmark = false
verified_qa_count = 8
query_independent_block_count = 35
document_count = 1
```

Retrieval scenario comparison:

| Metric | BM25 | Hybrid | Absolute Delta | Relative Delta |
|---|---:|---:|---:|---:|
| Recall@1 | 0.375 | 0.875 | +0.500 | +1.3333 |
| Recall@3 | 0.875 | 0.875 | 0.000 | 0.0000 |
| Recall@5 | 0.875 | 0.875 | 0.000 | 0.0000 |
| MRR | 0.6041666667 | 0.875 | +0.2708333333 | +0.4482758621 |
| Gold page hit rate | 1.0 | 1.0 | 0.000 | 0.0000 |

```text
在 GLOBOCAN 8 条真实文档场景回归中，Hybrid + Reranker
主要改善正确证据的首位排序：
Recall@1 从 0.375 提升至 0.875，MRR 从 0.604 提升至 0.875。
Recall@3/5 未提升，说明当前收益主要来自重排，而不是扩大候选覆盖。
```

AnswerPolicy scenario comparison:

```text
fixed_evidence_sha256 = 04536f8fdbd3ea2e6c4a8ef93befd6aa270eb5c5ae700f1edcdacf2eed35adee
normalized EM = 0.625
answer hit = 0.625
token F1 = 0.675
character F1 = 0.7842548077
valid JSON rate = 1.0
format valid rate = 1.0
block location hit = 0.875
page location hit = 0.875
final location in evidence rate = 1.0
repair attempted rate = 0.0
repair success rate = 0.0
```

SFT and GRPO used the same fixed evidence and produced identical metrics.

```text
真实文档回归验证了 SFT 与 GRPO adapter 均可通过统一
Training–Inference Contract、Canonical Output 和验证链路运行。

8 条 GLOBOCAN 场景中未观察到 GRPO 相对 SFT 的回答指标提升。
该结果只证明兼容性和无明显回归，不能用于宣称 GRPO 优于 SFT。
```

Status:

```text
training-inference contract -> server_validated
real-document evaluation framework -> server_validated
fixed-evidence safety hotfix -> server_validated
GLOBOCAN regression contract -> accepted
GLOBOCAN server real regression -> accepted
Hybrid retrieval scenario effectiveness -> measured
AnswerPolicy scenario compatibility -> measured
MP-DocVQA AnswerPolicy evaluation -> measured
MP-DocVQA AnswerPolicy sample_count -> 150
SFT/GRPO fixed-evidence parity -> verified
GRPO grounding improvement -> small_measured_gain
GRPO answer accuracy improvement -> inconclusive
formal benchmark -> not_started
MP-DocVQA retrieval evaluation -> blocked
CDC -> next_priority
```

Boundary:

- This is a real-document scenario regression result, not a formal benchmark.
- GRPO effectiveness remains unproven beyond compatibility on this scenario.
- GRPO vs SFT has now been evaluated on a larger MP-DocVQA fixed-evidence
  reader artifact; CDC should next be added as a second real document scenario.

## Phase 3 MP-DocVQA AnswerPolicy Evaluation Measured

MP-DocVQA fixed-evidence reader evaluation completed on AutoDL at commit
`1ef68838210d56e8624b7ef0c0633b705e8ccfe5`. This is not a formal benchmark
and does not report retrieval Recall/MRR.

Run scope:

```text
server_gpu = 1 x NVIDIA GeForce RTX 4090D 24GB
dataset = data/benchmark/mp_docvqa_imdb_ocr_5000_split/dev.jsonl
evaluation_scope = mpdocvqa_fixed_evidence_reader
formal_benchmark = false
sample_limit = 150
seed = 42
top_k = 20
fixed_evidence_sha256 = 8c4d60a189675a4ba52fa61d47db68c070f2f13218b5e73b1a18ded6fceeb940
output_dir = outputs/evaluation/phase3_focused_eval/mpdocvqa_answer_policy_150_top20_20260616_131117/
```

The `top_k=20` setting is only the fixed-evidence reader-evaluation evidence
budget over the existing reader artifact. It is not an online Retrieval top-k
setting and must not be used to compute Retrieval Recall/MRR. The earlier
`top_k=5` smoke failure was not a code defect because qid `64253` had its gold
block at source-evidence rank 8.

Metrics:

| Metric | SFT | GRPO | Delta |
|---|---:|---:|---:|
| Completed | 150/150 | 150/150 | 0 |
| Failed | 0 | 0 | 0 |
| Normalized EM | 0.380000 | 0.386667 | +0.006667 |
| Answer hit | 0.406667 | 0.406667 | 0.000000 |
| Token F1 | 0.483865 | 0.484643 | +0.000778 |
| Character F1 | 0.615299 | 0.625152 | +0.009853 |
| Valid JSON | 1.000000 | 1.000000 | 0.000000 |
| Format valid | 1.000000 | 1.000000 | 0.000000 |
| Block location hit | 0.866667 | 0.893333 | +0.026667 |
| Page location hit | 0.880000 | 0.900000 | +0.020000 |
| Final location in evidence | 1.000000 | 1.000000 | 0.000000 |
| Repair attempted/success | 0.086667 | 0.086667 | 0.000000 |
| Mean latency | 4289.27 ms | 4237.41 ms | -51.86 ms |

Conclusion:

```text
在 150 条相同 fixed evidence 的 MP-DocVQA reader 样本上，
GRPO 相比 SFT 在 block/page 证据定位和 character F1 上有轻微提升，
Normalized EM 仅提高约 0.67 个百分点，Answer Hit 不变。

结果说明 GRPO 没有破坏结构化输出，并表现出有限的 grounding 改善；
不能据此宣称 GRPO 在答案正确率上存在显著优势。
```

Current status:

```text
fixed-evidence safety hotfix -> server_validated
MP-DocVQA AnswerPolicy evaluation -> measured
MP-DocVQA AnswerPolicy sample_count -> 150
SFT/GRPO fixed-evidence parity -> verified
GRPO grounding improvement -> small_measured_gain
GRPO answer accuracy improvement -> inconclusive
formal benchmark -> not_started
MP-DocVQA retrieval evaluation -> blocked
GLOBOCAN regression -> accepted
CDC -> next_priority
```

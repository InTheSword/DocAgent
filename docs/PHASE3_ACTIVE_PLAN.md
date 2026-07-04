# Phase 3 Active Plan

> This file defines the only active Codex milestone.

## 1. Accepted Checkpoint

```text
Phase 2B-2: accepted
```

Accepted boundary:

```text
real-document scenario acceptance -> accepted
scenario quality -> measured
formal benchmark -> not benchmark_evaluated
quality optimization -> deferred
```

Do not rewrite Phase 2 history while working on Phase 3A.

## 2. Active Milestone

```text
Phase 3A: Focused Evaluation and Ablation
```

Goal:

```text
fixed benchmark subset
-> BM25 vs Hybrid retrieval comparison
-> fixed Hybrid evidence artifact
-> SFT vs GRPO AnswerPolicy comparison
-> summary report
```

This is a fixed-subset evaluation for project presentation. It is not a
formal benchmark unless a complete official split and official scoring protocol
are used.

## 3. Current Status

| Component | Status | Role |
|---|---|---|
| Phase 2B-2 real-document E2E | accepted | prior integration checkpoint |
| Phase 3A local framework | implemented | contract, runner, report, fixture tests |
| Training-inference contract | server_validated | shared context builder, prompt compiler, output adapter, and validation chain passed server regression |
| Real-document evaluation framework | server_validated | QA/corpus/manifest contract builder and server acceptance entry passed |
| Fixed-evidence safety hotfix | server_validated | OCR body URL/path-like text no longer trips persistence safety scan |
| GLOBOCAN regression contract | accepted | scenario regression contract with 8 verified QA and 35 independent blocks |
| GLOBOCAN server real regression | accepted | real BGE-M3, reranker, SFT, and GRPO run completed |
| Hybrid retrieval scenario effectiveness | measured | scenario-regression retrieval metrics recorded |
| AnswerPolicy scenario compatibility | measured | SFT and GRPO both ran over identical fixed evidence |
| Retrieval evaluation | blocked | MP-DocVQA split lacks an accepted independent corpus artifact |
| MP-DocVQA AnswerPolicy evaluation | measured | 150 fixed-evidence reader samples completed on AutoDL |
| SFT/GRPO fixed-evidence parity | verified | same qids, fixed evidence hash, prompt path, generation settings, validator, and repair bounds |
| GRPO grounding improvement | small_measured_gain | block/page location hit improved slightly on the 150-sample reader run |
| GRPO answer accuracy improvement | inconclusive | normalized EM gain was about 0.67 percentage points and answer hit was unchanged |
| CDC real document | next_priority | process CDC PDF through MinerU, EvidenceBlock ingest, quality checks, and candidate scenario QA |
| Formal benchmark | not_started | out of scope for this milestone |

## 4. Required Local Contract

The local implementation must provide:

- benchmark validity contract;
- deterministic qid-hash subset sampling;
- BM25 baseline metrics;
- BM25 + BGE-M3 + RRF + bge-reranker-v2-m3 metrics;
- absolute and relative Hybrid - BM25 deltas;
- fixed evidence JSONL generated once from Hybrid retrieval;
- SFT and GRPO runs over the same fixed evidence;
- GRPO - SFT absolute metric deltas;
- compact failure taxonomy;
- summary JSON and Markdown.

Local tests may use explicit mock backends:

```text
hash dense
keyword reranker
heuristic AnswerPolicy
```

Mock outputs must not be reported as real focused-evaluation results.

## 5. Server Boundary

Codex may run real BGE-M3, reranker, SFT, or GRPO commands directly on the
configured AutoDL server over SSH when server work is authorized. User-pasted
commands are now a fallback path only. Real server runs still require the same
preflights, compact artifacts, and environment-safety boundaries recorded in
`docs/SERVER_SETUP.md` and `docs/GPU_SERVER_BOUNDARY.md`.

Required server resources:

```text
benchmark artifact with corpus and metadata.gold_block_ids
BGE-M3 model
bge-reranker-v2-m3 model
Qwen3 base model
SFT adapter
GRPO adapter
```

Current corpus audit:

```text
data/benchmark/mp_docvqa_imdb_ocr_5000_split/dev.jsonl
-> QA records include per-record official-OCR evidence
-> no separate canonical per-doc corpus artifact is recorded
-> repeated doc_id evidence signatures may differ
-> retrieval evaluation is blocked unless --corpus-input is supplied
```

If retrieval is blocked, `--answer-only` may run SFT vs GRPO only when the
reader evidence artifact passes its reader contract. That path must not report
BM25/Hybrid Recall or MRR.

MP-DocVQA retrieval corpus builder:

```text
scripts/build_phase3_mpdocvqa_retrieval_benchmark.py
-> reads RRC IMDb records and optional official OCR root
-> reuses source QA qids and metadata.gold_block_ids when provided
-> writes a QA artifact without embedded evidence
-> writes a query-independent EvidenceBlock corpus artifact
-> writes a manifest with qid/corpus hashes, page coverage, and gold coverage
```

Current local status remains:

```text
retrieval evaluation -> blocked
```

It can change to `ready` only after AutoDL builds the corpus from real
MP-DocVQA IMDb / official OCR data and the runner validator accepts
`--qa-input` plus `--corpus-input`.

Real-document closure path:

```text
scripts/build_real_document_benchmark.py
-> reads an already ingested document directory and scenario QA
-> writes QA, corpus, document manifest, and benchmark manifest artifacts
-> validates duplicate qids, duplicate block ids, empty retrieval text, and
   complete gold block coverage

scripts/run_phase3_server_acceptance.py
-> preflight
-> real-document-regression
-> answer-policy-eval
-> focused-eval
```

Current local closure status:

```text
training-inference contract -> server_validated
real-document evaluation framework -> server_validated
fixed-evidence safety hotfix -> server_validated
GLOBOCAN regression contract -> accepted
GLOBOCAN server real regression -> accepted
Hybrid retrieval scenario effectiveness -> measured
AnswerPolicy scenario compatibility -> measured
formal benchmark -> not_started
MP-DocVQA retrieval evaluation -> blocked
MP-DocVQA AnswerPolicy evaluation -> measured
MP-DocVQA AnswerPolicy sample_count -> 150
SFT/GRPO fixed-evidence parity -> verified
GRPO grounding improvement -> small_measured_gain
GRPO answer accuracy improvement -> inconclusive
CDC -> next_priority
```

GLOBOCAN server regression:

```text
commit = 3390bcde1c703c7bd95c567e6da3bdb04591c0d8
evaluation_scope = scenario_regression
formal_benchmark = false
verified_qa_count = 8
query_independent_block_count = 35
fixed_evidence_sha256 = 04536f8fdbd3ea2e6c4a8ef93befd6aa270eb5c5ae700f1edcdacf2eed35adee
```

Retrieval scenario metrics:

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

AnswerPolicy scenario metrics:

```text
SFT = GRPO on all recorded metrics
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

```text
真实文档回归验证了 SFT 与 GRPO adapter 均可通过统一
Training–Inference Contract、Canonical Output 和验证链路运行。

8 条 GLOBOCAN 场景中未观察到 GRPO 相对 SFT 的回答指标提升。
该结果只证明兼容性和无明显回归，不能用于宣称 GRPO 优于 SFT。
```

MP-DocVQA fixed-evidence reader evaluation:

```text
commit = 1ef68838210d56e8624b7ef0c0633b705e8ccfe5
dataset = data/benchmark/mp_docvqa_imdb_ocr_5000_split/dev.jsonl
evaluation_scope = mpdocvqa_fixed_evidence_reader
formal_benchmark = false
sample_limit = 150
seed = 42
top_k = 20
fixed_evidence_sha256 = 8c4d60a189675a4ba52fa61d47db68c070f2f13218b5e73b1a18ded6fceeb940
output_dir = outputs/evaluation/phase3_focused_eval/mpdocvqa_answer_policy_150_top20_20260616_131117/
```

`top_k=20` is only the fixed-evidence reader-evaluation evidence budget over
the existing reader artifact. It is not an online Retrieval top-k setting and
must not be used to compute or report Retrieval Recall/MRR. The earlier
`top_k=5` smoke failure was not a code defect: qid `64253` had its gold block
at source-evidence rank 8, so Top-5 truncated the gold evidence.

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

```text
在 150 条相同 fixed evidence 的 MP-DocVQA reader 样本上，
GRPO 相比 SFT 在 block/page 证据定位和 character F1 上有轻微提升，
Normalized EM 仅提高约 0.67 个百分点，Answer Hit 不变。

结果说明 GRPO 没有破坏结构化输出，并表现出有限的 grounding 改善；
不能据此宣称 GRPO 在答案正确率上存在显著优势。
```

Next priorities:

1. Process the CDC PDF and add a second real document with verified scenario QA
   to broaden real-document regression document and question coverage.
2. Do not run all 453 MP-DocVQA AnswerPolicy samples for this closeout; the
   150-sample fixed-evidence reader result is sufficient for the current
   project closure.

Do not continue restoring the full MP-DocVQA retrieval corpus, and do not start
UI, Memory, multi-document, or multi-format development in this phase.

## 6. Stop Condition

After the following are complete, stop:

```text
benchmark validity contract
+ BM25 vs Hybrid runner
+ fixed evidence artifact
+ SFT vs GRPO runner
+ comparison report
+ local tests
+ one AutoDL command
+ commit/push
```

Do not modify retrieval algorithms, query normalization, prompts,
AnswerPolicy, reward code, checkpoints, or training data in this milestone.

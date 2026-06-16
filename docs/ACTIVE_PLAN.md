# Active Plan

> Stable entry point for the current Codex task. Detailed phase history stays in
> the phase-specific plan files linked below.

## Current Stage

```text
Phase 3: unified model interface and real-document evaluation closure
```

## Current Goal

```text
document file + user question
-> document parsing
-> complete EvidenceBlock corpus
-> retrieval or tool result
-> unified evidence context
-> checkpoint-compatible answer prompt
-> Qwen AnswerPolicy
-> canonical answer output
-> validation, repair, and SQLite trace
```

Evaluation paths are kept separate:

```text
Real-document Retrieval -> BM25 vs Hybrid
Reader / AnswerPolicy -> SFT vs GRPO over identical fixed evidence
Real-document E2E -> PDF -> parse -> retrieve -> GRPO -> canonical output
```

## Current Status

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

## Allowed Scope

- unify prompt/context/output protocol;
- keep checkpoint-compatible prompt semantics;
- build real-document QA/corpus/manifest contracts;
- provide one fixed server acceptance entry point;
- run local fixture tests without loading BGE-M3, reranker, Qwen, or adapters.

## Blockers

- CDC requires MinerU output, or a runtime `MINERU_TOKEN` for server-side MinerU
  API processing.
- MP-DocVQA retrieval evaluation remains blocked unless a query-independent
  corpus artifact is supplied.

## Server Validation

The GLOBOCAN real-document scenario regression passed on AutoDL at commit
`3390bcde1c703c7bd95c567e6da3bdb04591c0d8`.

```text
evaluation_scope = scenario_regression
formal_benchmark = false
verified_qa_count = 8
query_independent_block_count = 35
```

Retrieval conclusion:

```text
在 GLOBOCAN 8 条真实文档场景回归中，Hybrid + Reranker
主要改善正确证据的首位排序：
Recall@1 从 0.375 提升至 0.875，MRR 从 0.604 提升至 0.875。
Recall@3/5 未提升，说明当前收益主要来自重排，而不是扩大候选覆盖。
```

AnswerPolicy conclusion:

```text
真实文档回归验证了 SFT 与 GRPO adapter 均可通过统一
Training–Inference Contract、Canonical Output 和验证链路运行。

8 条 GLOBOCAN 场景中未观察到 GRPO 相对 SFT 的回答指标提升。
该结果只证明兼容性和无明显回归，不能用于宣称 GRPO 优于 SFT。
```

The MP-DocVQA fixed-evidence reader evaluation also completed on AutoDL at
commit `1ef68838210d56e8624b7ef0c0633b705e8ccfe5`.

```text
evaluation_scope = mpdocvqa_fixed_evidence_reader
formal_benchmark = false
sample_limit = 150
seed = 42
top_k = 20
fixed_evidence_sha256 = 8c4d60a189675a4ba52fa61d47db68c070f2f13218b5e73b1a18ded6fceeb940
completed = SFT 150/150, GRPO 150/150
failed = SFT 0, GRPO 0
```

SFT vs GRPO fixed-evidence reader metrics:

| Metric | SFT | GRPO | Delta |
|---|---:|---:|---:|
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

`top_k=20` is only the fixed-evidence reader-evaluation evidence budget over
the existing reader artifact. It is not an online Retrieval top-k setting and
must not be used to compute or report Retrieval Recall/MRR.

## Next Priorities

1. Process the CDC PDF and add a second real document with verified scenario QA
   to broaden real-document regression document and question coverage.
2. Do not run all 453 MP-DocVQA AnswerPolicy samples for this closeout; the
   150-sample fixed-evidence reader result is sufficient for the current
   project closure.

Do not continue restoring the full MP-DocVQA retrieval corpus, and do not start
UI, Memory, multi-document, or multi-format development in this phase.

## Stop Condition

```text
GLOBOCAN real server regression recorded
+ MP-DocVQA fixed-evidence reader evaluation recorded
+ documentation status updated
+ local tests pass
+ commit/push complete
+ stop for user confirmation
```

## Phase Documents

- `docs/PHASE3_ACTIVE_PLAN.md`: detailed Phase 3 working record.
- `docs/PHASE2_ACTIVE_PLAN.md`: completed/archived Phase 2 record.
- `docs/IMPLEMENTATION_PLAN.md`: long-term roadmap only, not current execution
  authority.

## Phase Switch Checklist

Start a new phase:

- update `docs/ACTIVE_PLAN.md`;
- update `CURRENT_STATUS.md`;
- check `AGENTS.md` routing;
- create the feature branch.

End a phase:

- record acceptance results;
- merge main when explicitly approved;
- clean up the feature branch when explicitly approved;
- mark the phase document completed;
- point `docs/ACTIVE_PLAN.md` at the next phase.

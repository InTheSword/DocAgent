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
GLOBOCAN regression contract -> accepted
GLOBOCAN server real regression -> accepted
Hybrid retrieval scenario effectiveness -> measured
AnswerPolicy scenario compatibility -> measured
formal benchmark -> not_started
MP-DocVQA retrieval evaluation -> blocked
MP-DocVQA AnswerPolicy evaluation -> ready
CDC real document -> blocked_by_missing_mineru_output
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

## Next Priorities

1. Run a larger SFT vs GRPO AnswerPolicy evaluation on the MP-DocVQA
   fixed-evidence reader artifact to determine whether post-training has a
   measurable benefit.
2. Process the CDC PDF and add a second real document with verified scenario QA
   to broaden real-document regression document and question coverage.

Do not continue restoring the full MP-DocVQA retrieval corpus, and do not start
UI, Memory, multi-document, or multi-format development in this phase.

## Stop Condition

```text
GLOBOCAN real server regression recorded
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

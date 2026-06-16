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
training-inference contract -> implemented
real-document evaluation framework -> implemented
server real evaluation -> not_started
GLOBOCAN regression -> ready
CDC real document -> blocked_by_missing_mineru_output
```

## Allowed Scope

- unify prompt/context/output protocol;
- keep checkpoint-compatible prompt semantics;
- build real-document QA/corpus/manifest contracts;
- provide one fixed server acceptance entry point;
- run local fixture tests without loading BGE-M3, reranker, Qwen, or adapters.

## Blockers

- AutoDL must run the real-model acceptance entry point before any real metrics
  can be reported.
- CDC requires MinerU output, or a runtime `MINERU_TOKEN` for server-side MinerU
  API processing.
- MP-DocVQA retrieval evaluation remains blocked unless a query-independent
  corpus artifact is supplied.

## Stop Condition

```text
unified protocol implemented
+ real-document contracts implemented
+ GLOBOCAN regression ready
+ CDC handled or explicitly blocked
+ single server entry point implemented
+ local tests pass
+ commit/push complete
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

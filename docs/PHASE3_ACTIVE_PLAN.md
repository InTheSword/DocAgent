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
| Real focused evaluation | not_started | requires AutoDL models and benchmark artifacts |
| Retrieval evaluation | blocked | current MP-DocVQA split lacks an accepted independent corpus artifact |
| AnswerPolicy evaluation | implemented | can run over a valid fixed reader evidence artifact |
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

Codex works locally and does not run real BGE-M3, reranker, SFT, or GRPO
models. AutoDL must run the real model command after the feature branch is
pushed.

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

# Active Plan

> Stable entry point for the current Codex task. Detailed phase history stays in
> the phase-specific plan files linked below.

## Current Stage

```text
Phase 4B: MP-DocVQA raw-document MinerU ingestion and small-scale E2E
```

## Current Goal

```text
page-window PDF
-> MinerU
-> EvidenceBlock
-> page aggregate
-> gold page mapping
-> page-level retrieval
-> AnswerPolicy
-> answer / evidence page / trace
```

## Current Status

```text
Phase 3 historical record -> accepted
Phase 3 evaluation implementation -> frozen
Phase 4A implementation -> accepted
Phase 4B -> accepted
Gate 1 local implementation -> implemented
Gate 1 -> accepted
Gate 2 -> accepted
Gate 3 local implementation -> implemented
Gate 3 server real E2E -> accepted
Gate 3A failure review instrumentation -> accepted
Gate 3A rank-aware context/prompt -> implemented
Gate 3A default prompt rollback -> accepted
Gate 4 local implementation -> implemented
Gate 4A sample manifest -> accepted
Gate 4B ingestion -> accepted
Gate 4C validate-only -> accepted
Gate 4C retrieval-only -> accepted
Gate 4D full GRPO E2E -> accepted
CDC -> not_started
Router/tools -> not_started
Demo/closure -> not_started
```

Phase 3 is historical and frozen. Phase 4A is accepted. Do not rewrite Phase 3
evaluation implementation, metrics, or conclusions in this phase.

## Allowed Scope

- preserve the accepted 26-window / 90-QA Gate 4 expanded regression;
- do not expand to all 29 shards in Phase 4B;
- prioritize the accepted server sample and ingestion assets;
- keep generated assets under ignored `outputs/`.

## Blockers

- No blocker for the accepted Phase 4A foundation.
- Gate 3 real-model E2E and Gate 3A default prompt rollback are accepted for
  the small 3-window regression.
- Gate 4 expanded raw-input regression is accepted; it is not a formal
  benchmark and does not change the default AnswerPolicy prompt/context.

Gate 4 accepted server scope:

```text
sample_root = outputs/phase4/mpdocvqa_raw_gate4_expanded
ingestion_root = outputs/phase4/mpdocvqa_ingestion
document_count = 26
page_count = 197
qa_count = 90
source_shards = MP-DocVQA val shards 1-4
```

Gate 4C retrieval-only:

```text
run = outputs/evaluation/phase4b_mpdocvqa_gate4/gate4c_retrieval_only_empty_page_fix
fixed_evidence_hash = 723160441137a42a3cf3b7775f94ffd6dd681cb15ac67bc2c5d2d0bfdc9feab3
BM25 Recall@1/3/5 = 0.6111 / 0.8667 / 0.9111
BM25 MRR = 0.7259
Hybrid Recall@1/3/5 = 0.7333 / 0.9222 / 0.9556
Hybrid MRR = 0.8257
retrieval_gold_miss_top5 = 4
```

Gate 4D full GRPO E2E:

```text
run = outputs/evaluation/phase4b_mpdocvqa_gate4/gate4_full_grpo
completed_count = 90
failed_count = 0
normalized_exact_match = 0.3333
answer_hit = 0.3444
token_f1 = 0.3689
character_f1 = 0.5235
valid_json_rate = 1.0
format_valid_rate = 1.0
gold_page_location_hit = 0.4889
block_location_hit = 0.9667
final_location_in_evidence_rate = 1.0
trace_counts.qa_runs = 90
trace_counts.tool_traces = 613
failure_taxonomy = answer_miss:59, gold_page_location_miss:46, retrieval_gold_miss_top5:4
```

Interpretation boundary:

- Gate 4 is an expanded raw-input integration regression, not a formal
  benchmark.
- The flow is stable through ingestion, page retrieval, fixed evidence,
  AnswerPolicy JSON/format validation, and SQLite trace persistence.
- Hybrid retrieval is usable over the expanded sample (`Top-5 recall=0.9556`).
- Main remaining issues are Reader `answer_miss` and `gold_page_location_miss`.
- `--rank-aware-context` remains diagnostic only; default is false.

## Local Validation

Local `main` validation covers code and documentation state. The accepted Gate
4 artifacts are server-side outputs; the local absence of these ignored paths
does not indicate missing tracked code:

```text
outputs/phase4/mpdocvqa_raw_gate4_expanded
outputs/phase4/mpdocvqa_ingestion
outputs/evaluation/phase4b_mpdocvqa_gate4/
```

Phase 4A server acceptance is now recorded from real execution:

```text
server_branch = codex/phase4-mpdocvqa-raw-foundation
server_commit = f3d6237b9f7f53cd9f2a8e21d4441e7f911a7979
server_shard = val-00001-of-00029.parquet
server_shard_sha256 = 493d31bb7b99da676876e4350b27f15ca3e4273518493a09fc799f31d5a3609b
phase4_mpdocvqa_raw_server_smoke_shell_exit_code = 0
```

Accepted Phase 4A server audit:

```text
row_count = 179
unique_source_doc_count = 44
unique_window_count = 61
different_window_same_source_doc_count = 23
conflicting_window_count = 0
valid_window_count = 61
document_window_count = 5
qa_count = 12
absolute_path_hit_count = 0
```

## Next Priorities

1. Keep Phase 4B accepted artifacts unchanged unless a reproducibility issue is
   reported.
2. Keep CDC `not_started` until explicitly started.
3. Use Gate 4 failure taxonomy to guide later Reader/error-analysis work, not
   a retrieval model change in this phase.

## Stop Condition

```text
Gate 4 expanded raw-input regression accepted
+ status documents updated
+ stop before CDC
```

## Phase Documents

- `docs/PHASE4_ACTIVE_PLAN.md`: detailed Phase 4B working record.
- `docs/PHASE3_ACTIVE_PLAN.md`: completed/historical Phase 3 record.
- `docs/PHASE2_ACTIVE_PLAN.md`: completed/historical Phase 2 record.

## Phase Switch Checklist

Start a new phase:

- update `docs/ACTIVE_PLAN.md`;
- update `CURRENT_STATUS.md`;
- add or switch the phase-specific plan file;
- create the feature branch.

End a phase:

- record acceptance results;
- merge main only when explicitly approved;
- clean up the feature branch only when explicitly approved;
- point `docs/ACTIVE_PLAN.md` at the next phase.

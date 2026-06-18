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
Phase 4B -> active
Gate 1 local implementation -> implemented
Gate 1 -> accepted
Gate 2 -> accepted
Gate 3 local implementation -> implemented
Gate 3 server real E2E -> real_model_verified
Gate 3A failure review/context instrumentation -> implemented
Gate 4 -> blocked
CDC -> queued after Phase 4B
Router/tools -> queued after CDC
Demo/closure -> final phase
```

Phase 3 is historical and frozen. Phase 4A is accepted. Do not rewrite Phase 3
evaluation implementation, metrics, or conclusions in this phase.

## Allowed Scope

- use a small representative set of accepted MP-DocVQA page-window documents;
- process only 3-5 windows first, not all 29 shards;
- prioritize the existing accepted server sample assets;
- keep generated assets under ignored `outputs/`.

## Blockers

- No blocker for the accepted Phase 4A foundation.
- Gate 3 server real E2E has completed but remains a quality-review target,
  not an accepted expansion signal.
- Gate 4 waits for Gate 3A failure review and page-rank-aware context results.

## Local Validation

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

1. Re-run Gate 3 retrieval-only with the Gate 3A context/review artifacts.
2. Re-run Gate 3 full GRPO E2E and compare against
   `gate3_mpdocvqa_20260618_155135`.
3. Keep CDC queued until Phase 4B completes.

## Stop Condition

```text
Gate 3A local instrumentation/context update committed and pushed
+ short AutoDL Gate 3A rerun command blocks provided
+ stop for server result
```

## Phase Documents

- `docs/PHASE4_ACTIVE_PLAN.md`: detailed Phase 4A working record.
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

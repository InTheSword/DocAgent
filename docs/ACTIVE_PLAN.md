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
MP-DocVQA raw Parquet schema audit -> accepted
page-window identity model -> accepted
multi-page image restoration -> server_validated
deterministic document asset builder -> server_validated
Linux PDF generation -> server_validated
cross-shard identity design -> implemented_not_yet_multi_shard_validated
MinerU ingestion -> not_started
raw-document retrieval evaluation -> not_started
raw-document E2E -> not_started
CDC -> not_started
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
- Phase 4B has not started implementation yet.

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

1. Start Phase 4B with 3-5 accepted page-window documents, covering 1-page,
   2-5-page, and 10-20-page inputs.
2. Prefer the existing accepted server sample assets before expanding scope.
3. Keep CDC queued after the first MP-DocVQA raw-document MinerU/E2E slice.

## Stop Condition

```text
Phase 4A server acceptance recorded
+ documentation updated
+ commit/push complete
+ stop for user confirmation
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

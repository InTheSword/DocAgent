# Active Plan

> Stable entry point for the current Codex task. Detailed phase history stays in
> the phase-specific plan files linked below.

## Current Stage

```text
Phase 4A: MP-DocVQA raw multi-page document foundation
```

## Current Goal

```text
MP-DocVQA parquet shard
-> doc_id-level deduplication
-> ordered page image restoration
-> deterministic multi-page PDF synthesis
-> QA JSONL
-> document/source manifest
-> compact schema/build/overlap audit
```

## Current Status

```text
Phase 3 historical record -> accepted
Phase 3 evaluation implementation -> frozen
MP-DocVQA raw parquet schema audit -> implemented
MP-DocVQA raw document builder -> implemented
MP-DocVQA raw sample package -> implemented
CDC -> not_started
```

Phase 3 is historical and frozen. Do not rewrite its evaluation implementation,
metrics, or conclusions in this phase.

## Allowed Scope

- audit the real local MP-DocVQA parquet shard;
- restore consistent raw multi-page document assets for a small local sample;
- emit compact QA/document/source manifests and audit reports;
- keep all generated sample assets under ignored `outputs/`.

## Blockers

- No blocker for the local Phase 4A foundation.
- MinerU parsing, retrieval, CDC real-document work, and multi-shard recovery
  remain intentionally out of scope for this round.

## Local Validation

This phase requires local validation only:

```text
targeted fixture tests
+ full pytest regression
+ real parquet validate-only audit
+ 3-5 unique document sample build
```

The current real local sample build uses:

```text
source_shard = val-00001-of-00029.parquet
row_count = 179
valid_doc_count = 38
invalid_doc_count = 6
sample_documents = 5
seed = 42
```

## Next Priorities

1. After user confirmation, reuse the Phase 4A builder for the next approved
   local/server shard scope and feed accepted raw documents into the MinerU
   parsing path.
2. Keep CDC queued after the Phase 4A local foundation; do not start CDC
   parsing or evaluation in this round.

## Stop Condition

```text
real parquet audit recorded
+ builder/tests pass
+ local sample package built
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

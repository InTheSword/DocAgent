# Phase 4 Active Plan

> This file defines the only active Codex milestone.

## 1. Historical Checkpoint

```text
Phase 3: accepted
```

Historical boundary:

```text
Phase 3 implementation/evaluation -> frozen
Phase 3 conclusions -> frozen
```

Do not rewrite Phase 3 evaluation code paths, metrics, or conclusions while
working on Phase 4A.

## 2. Active Milestone

```text
Phase 4A: MP-DocVQA raw multi-page document foundation
```

Goal:

```text
parquet shard
-> source document / page-window identity
-> ordered page image restoration
-> multi-page PDF
-> QA JSONL
-> document/source manifest
-> compact audit reports
```

This phase establishes the raw document foundation only. It is not yet MinerU
parsing, retrieval evaluation, reader evaluation, or formal benchmarking.

## 3. Current Status

| Component | Status | Role |
|---|---|---|
| Phase 3 historical record | accepted | prior completed checkpoint |
| Phase 3 evaluation implementation | frozen | historical, unchanged in this phase |
| Raw parquet schema audit | implemented | real local shard audit |
| Raw document builder | implemented | page restore + PDF + QA + manifest + audit |
| Raw sample package | implemented | 5 unique documents restored under `outputs/phase4/mpdocvqa_raw_sample/` |
| CDC real document | not_started | queued after Phase 4A local foundation |

Real local shard audit summary:

```text
source_shard = val-00001-of-00029.parquet
row_count = 179
unique_source_doc_count = 44
unique_window_count = 61
same_source_multiple_window_count = 6
conflicting_window_count = 0
valid_window_count = 61
sample_windows = 5
seed = 42
```

Observed storage contract:

```text
questionId -> string
doc_id -> string
page_ids -> stringified list
answers -> stringified list
answer_page_idx -> stringified zero-based integer
image_1 ... image_20 -> struct<bytes: binary, path: string>
non-null image format -> JPEG
```

Window identity:

```text
window_signature = sha256(canonical JSON {source_doc_id, ordered_page_ids})
window doc_id = source_doc_id + "__" + short(window_signature)
input_scope = page_window
document_is_full_source_document = false
```

Conflict audit:

```text
same source doc with multiple windows = 6
different-window window count under those sources = 23
conflicting windows = 0
```

Different ordered page windows under the same `source_doc_id` are valid and
must not be collapsed or rejected.

## 4. Required Local Contract

The local implementation must provide:

- compact parquet schema audit without printing raw image bytes;
- stable page-window identity and window-level deduplication;
- ordered page image restoration using detected real image format;
- deterministic PDF synthesis from the restored page order;
- QA JSONL with raw `questionId`, zero-based `answer_page_idx`, mapped
  `gold_page_id`, and `gold_page_ordinal`;
- relative POSIX output paths in manifests;
- sample selection by unique document window, not by QA row.

## 5. Out of Scope

Do not do the following in Phase 4A:

- MinerU parsing;
- EvidenceBlock ingestion;
- retrieval model loading or evaluation;
- Qwen/SFT/GRPO/CDC execution;
- full 29-shard restoration;
- training split changes or overlap-based gating.

Training overlap may be audited lightly, but it must not block the raw document
foundation work.

## 6. Local Validation

Required validation for this phase:

```text
python -m py_compile
+ targeted pytest for the new builder
+ full pytest regression
+ git diff --check
+ builder --help
+ real parquet validate-only
+ real 5-document sample build
+ sample package self-check
```

## 7. Server Boundary

This round does not run server commands and does not require AutoDL state
changes. Do not:

- write files to the server repository;
- download additional MP-DocVQA shards;
- run MinerU;
- run retrieval or answer models.

## 8. Next Priorities

1. After user confirmation, reuse the builder on the next approved shard scope.
2. Feed accepted raw document outputs into the later MinerU parsing workflow.
3. Keep CDC queued until the raw foundation handoff is accepted.

## 9. Stop Condition

Stop after the following are complete:

```text
real parquet audit recorded
+ raw builder implemented
+ sample package built
+ tests pass
+ documentation updated
+ commit/push complete
```

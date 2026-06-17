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
-> doc_id-level document deduplication
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
unique_doc_count = 44
valid_doc_count = 38
invalid_doc_count = 6
sample_documents = 5
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

Conflict audit:

```text
invalid conflicting doc_id count = 6
conflicting doc_ids = rzbj0037, ynbx0223, tnbx0223, jrcy0227, trgj0223, fxxj0037
```

Those documents must not be silently merged across rows.

## 4. Required Local Contract

The local implementation must provide:

- compact parquet schema audit without printing raw image bytes;
- doc-level deduplication with conflict rejection;
- ordered page image restoration using detected real image format;
- deterministic PDF synthesis from the restored page order;
- QA JSONL with raw `questionId`, zero-based `answer_page_idx`, mapped
  `gold_page_id`, and `gold_page_ordinal`;
- relative POSIX output paths in manifests;
- sample selection by unique document, not by QA row.

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

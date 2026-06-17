# Phase 4 Active Plan

> This file defines the only active Codex milestone.

## 1. Historical Checkpoints

```text
Phase 3: accepted
Phase 4A: accepted
```

Historical boundary:

```text
Phase 3 implementation/evaluation -> frozen
Phase 3 conclusions -> frozen
Phase 4A implementation -> accepted
Phase 4A builder/tests/contracts -> frozen for this handoff
```

Do not rewrite Phase 3 evaluation code paths, metrics, or conclusions while
working on Phase 4B. Do not change the accepted Phase 4A builder, tests, or
data contract in this handoff round.

## 2. Active Milestone

```text
Phase 4B: MP-DocVQA raw-document MinerU ingestion and small-scale E2E
```

Goal:

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

Phase 4B starts from the accepted Phase 4A page-window document assets. It is
not a full 29-shard rollout.

## 3. Current Status

| Component | Status | Role |
|---|---|---|
| Phase 3 historical record | accepted | prior completed checkpoint |
| Phase 3 evaluation implementation | frozen | historical, unchanged in this phase |
| Phase 4A raw parquet schema audit | accepted | real shard audit accepted |
| Phase 4A page-window identity model | accepted | source document vs window identity accepted |
| Phase 4A image restoration | server_validated | Linux server smoke passed |
| Phase 4A deterministic asset builder | server_validated | help, py_compile, validate-only, build, self-check passed |
| Phase 4A Linux PDF generation | server_validated | `document.pdf` and manifest checks passed |
| Phase 4A cross-shard identity design | implemented_not_yet_multi_shard_validated | multi-shard contract implemented, not yet server-validated |
| Phase 4B | active | current milestone |
| Gate 1 local implementation | implemented | runner and fixture tests added locally |
| Gate 1 | accepted | single-page live MinerU ingestion accepted |
| Gate 2 4-page | accepted | representative 4-page live MinerU ingestion accepted |
| Gate 2 20-page ingestion | completed | MinerU, EvidenceBlock, page documents, and QA mapping completed |
| Gate 2 20-page acceptance | blocked_by_false_positive_path_scan | SQLite JSON path scan misread OCR `\$34.20` text as a UNC path |
| Gate 3 | blocked_by_gate2 | page-level retrieval and AnswerPolicy E2E waits for Gate 2 |
| Gate 4 | blocked_by_gate3 | 10-20 windows / 30-50 QA waits for Gate 3 |
| CDC | queued after Phase 4B | do not start during Phase 4B gates |
| Router/tools | queued after CDC | later phase |
| Demo/closure | final phase | later phase |

Phase 4A accepted server input:

```text
server_repo = /root/autodl-tmp/docagent
server_branch = codex/phase4-mpdocvqa-raw-foundation
server_commit = f3d6237b9f7f53cd9f2a8e21d4441e7f911a7979
server_input = /root/autodl-tmp/datasets/mp_docvqa/parquet/val-00001-of-00029.parquet
server_input_size_bytes = 255412525
server_input_sha256 = 493d31bb7b99da676876e4350b27f15ca3e4273518493a09fc799f31d5a3609b
phase4_mpdocvqa_raw_server_smoke_shell_exit_code = 0
```

Phase 4A accepted real audit:

```text
row_count = 179
unique_source_doc_count = 44
unique_window_count = 61
different_window_same_source_doc_count = 23
conflicting_window_count = 0
valid_window_count = 61
```

Phase 4A accepted sample build:

```text
document_window_count = 5
qa_count = 12
absolute_path_hit_count = 0
```

Accepted sample windows:

```text
rzbj0037__e09400dd12a9c549 -> source_doc_id=rzbj0037, page_count=4, qa_count=6
hqvw0217__bc714cf4181a5632 -> source_doc_id=hqvw0217, page_count=1, qa_count=1
jrcy0227__558596710c584b02 -> source_doc_id=jrcy0227, page_count=20, qa_count=1
mxxj0037__3e113e49e156e47c -> source_doc_id=mxxj0037, page_count=2, qa_count=2
hljn0226__2583bb36ed16bec4 -> source_doc_id=hljn0226, page_count=2, qa_count=2
```

Accepted identity boundary:

```text
current restored artifacts are MP-DocVQA page-window documents,
not necessarily complete original source documents.

source_doc_id + ordered_page_ids
defines the stable document-window identity.

different page windows under the same source_doc_id are valid
independent inputs, not conflicts.
```

## 4. Required Local Contract

Phase 4A accepted contract remains:

- compact parquet schema audit without printing raw image bytes;
- stable page-window identity and window-level deduplication;
- ordered page image restoration using detected real image format;
- deterministic PDF synthesis from the restored page order;
- QA JSONL with raw `questionId`, zero-based `answer_page_idx`, mapped
  `gold_page_id`, and `gold_page_ordinal`;
- relative POSIX output paths in manifests;
- sample selection by unique document window, not by QA row.

## 5. Phase 4B Initial Scope

Gate 1 is accepted. Gate 2 has accepted the representative 4-page window and
completed MinerU ingestion plus page mapping for the 20-page window:

```text
rzbj0037__e09400dd12a9c549 -> accepted
jrcy0227__558596710c584b02 -> ingestion completed, acceptance blocked by false-positive path scan
```

Gate order remains:

```text
Gate 1 -> accepted
Gate 2 4-page -> accepted
Gate 2 20-page ingestion -> completed
Gate 2 20-page acceptance -> blocked_by_false_positive_path_scan
Gate 3 -> blocked_by_gate2
Gate 4 -> blocked_by_gate3
```

Phase 4B must still use one Codex thread and one feature branch:

```text
codex/phase4b-mpdocvqa-e2e
```

Prior Gate 1 signed-upload diagnosis:

```text
MINERU_TOKEN -> set and valid
POST /api/v4/file-urls/batch -> HTTP 200, code=0
existing urllib PUT upload -> HTTP 403
independent requests streaming PUT on the same URL/PDF -> HTTP 200
```

Current Gate 2 diagnosis:

```text
jrcy0227__558596710c584b02 expected/parsed/page_document -> 20/20/20
qa mapping -> 1/1
missing image reference -> 0
no mock fallback -> true
structure quality -> passed_with_warnings
persisted absolute path -> false-positive SQLite JSON scan of OCR `\$34.20`
```

The eventual Phase 4B scope remains:

- 3-5 document windows;
- coverage across 1-page, 2-5-page, and 10-20-page documents;
- existing accepted server sample assets where possible.

Do not do the following in the first Phase 4B slice:

- full 29-shard restoration;
- large-scale window expansion before the small slice is accepted;
- CDC work before the first MP-DocVQA raw-document MinerU/E2E slice is stable.

## 6. Phase 4A Accepted Validation

Recorded successful server checks:

```text
builder --help
+ py_compile
+ real shard validate-only
+ 5-window sample build
+ sample artifact self-check
```

## 7. Server Boundary

Current server boundary:

- run only the Gate 2 existing-artifact revalidation command supplied by Codex;
- do not call MinerU during revalidation;
- do not run retrieval, Qwen, Gate 3, or Gate 4 until Gate 2 returns.

Do not:

- print or persist `MINERU_TOKEN`;
- install packages or modify the stable `docagent` environment;
- run retrieval or answer models during Gate 2 revalidation;
- create per-gate branches.

## 8. Next Priorities

1. Revalidate the existing 20-page Gate 2 artifact after the SQLite JSON path
   scan fix is pushed.
2. If revalidation succeeds, continue Gate 2 handling in the same thread and
   branch.
3. Keep CDC queued after Phase 4B.

## 9. Stop Condition

Stop after the following are complete:

```text
SQLite JSON path scan fix committed and pushed
+ one AutoDL Gate 2 revalidate-existing command provided
+ stop for server result
```

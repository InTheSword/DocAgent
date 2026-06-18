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
| Gate 2 | accepted | representative 1/4/20-page live ingestion accepted |
| Gate 3 local implementation | implemented | page corpus, BM25/Hybrid retrieval, fixed evidence, AnswerPolicy runner, and fixture tests |
| Gate 3 server real E2E | accepted | 3 windows / 25 pages / 8 QA ran through on AutoDL |
| Gate 3A failure review instrumentation | accepted | compact retrieval/answer previews and failure cases accepted by artifact check |
| Gate 3A rank-aware context/prompt | implemented | opt-in only; default prompt/context restored to Gate 3 behavior |
| Gate 3A default prompt rollback | accepted | default full E2E restored Gate 3 behavior |
| Gate 4 local implementation | implemented | expanded sample manifest, manifest doc-id loading, per-shard metrics, and staged commands |
| Gate 4 server expanded regression | not_started | waits for staged AutoDL execution |
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

Gate 1 and Gate 2 are accepted for the representative windows:

```text
baseline windows -> hqvw0217__bc714cf4181a5632, rzbj0037__e09400dd12a9c549, jrcy0227__558596710c584b02
rzbj0037__e09400dd12a9c549 -> accepted
jrcy0227__558596710c584b02 -> accepted after existing-artifact revalidation
```

Gate order remains:

```text
Gate 1 -> accepted
Gate 2 -> accepted
Gate 3 local implementation -> implemented
Gate 3 server real E2E -> accepted
Gate 3A failure review instrumentation -> accepted
Gate 3A rank-aware context/prompt -> implemented
Gate 3A default prompt rollback -> accepted
Gate 4 local implementation -> implemented
Gate 4 server expanded regression -> not_started
```

Gate 3 server run `gate3_mpdocvqa_20260618_155135` completed at commit
`e9ee7bda869cf4b22f0ac577ccd626eab120c7d6` with 8/8 completed samples,
valid JSON rate 1.0, and trace persistence. Retrieval was sufficient for the
small-slice integration review (`Hybrid Recall@3=1.0`, `Recall@5=1.0`), but
Reader output often selected a non-gold page or a similar wrong field from
top-k evidence. Gate 3A instrumentation artifacts were accepted, but the first
rank-aware prompt/context default regressed answer quality. The default full
E2E path must use the Gate 3 prompt/context shape; `--rank-aware-context` is a
separate diagnostic flag. The rollback server run restored Gate 3 answer
metrics, so Gate 4 is unblocked for expanded raw-input E2E regression.

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

Gate 2 final accepted diagnosis:

```text
jrcy0227__558596710c584b02 expected/parsed/page_document -> 20/20/20
qa mapping -> 1/1
missing image reference -> 0
no mock fallback -> true
structure quality -> passed_with_warnings
persisted absolute path -> 0 after SQLite JSON scan fix and existing-artifact revalidation
```

Gate 4 expanded scope:

- build a deterministic expanded sample from MP-DocVQA validation shards 1-4;
- target 80-100 QA with page-window coverage across single, short, medium, and
  long windows;
- reuse accepted baseline ingestion artifacts for the three Gate 1/2/3
  windows;
- run ingestion, validate-only, retrieval-only, and full GRPO E2E as separate
  server phases.

Do not do the following in the first Phase 4B slice:

- full 29-shard restoration;
- all 29 shards;
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

- run only the staged Gate 4 command blocks supplied by Codex;
- keep Git sync, sample build, ingestion, validate-only, retrieval-only, full
  E2E, and comparison as separate foreground Bash blocks;
- do not skip validate-only or retrieval-only before full E2E.

Do not:

- print or persist `MINERU_TOKEN`;
- install packages or modify the stable `docagent` environment;
- use `nohup`, `setsid`, background `&`, `tmux`, `kill`, `pkill`, or `exec` in
  user-pasted Gate 4 commands;
- run all 29 shards;
- create per-gate branches.

## 8. Next Priorities

1. Build Gate 4 expanded sample manifest and raw PDF assets.
2. Ingest missing selected windows in batches.
3. Run expanded validate-only, retrieval-only, and full GRPO E2E.
4. Compare expanded results with `gate3_mpdocvqa_20260618_155135`.
5. Keep CDC queued after Phase 4B.

## 9. Stop Condition

Stop after the following are complete:

```text
Gate 4 local implementation committed and pushed
+ staged AutoDL Gate 4 command blocks provided
+ stop for server result
```

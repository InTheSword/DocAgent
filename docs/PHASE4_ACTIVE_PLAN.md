# Phase 4 Active Plan

> This file records the accepted Phase 4B milestone. The canonical current
> status and stop condition are in `docs/ACTIVE_PLAN.md`.

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
| Phase 4A image restoration | accepted | Linux server smoke passed |
| Phase 4A deterministic asset builder | accepted | help, py_compile, validate-only, build, self-check passed |
| Phase 4A Linux PDF generation | accepted | `document.pdf` and manifest checks passed |
| Phase 4A cross-shard identity design | implemented | multi-shard contract implemented; full multi-shard validation not started |
| Phase 4B | accepted | expanded raw-input regression accepted; CDC remains not_started |
| Gate 1 local implementation | implemented | runner and fixture tests added locally |
| Gate 1 | accepted | single-page live MinerU ingestion accepted |
| Gate 2 | accepted | representative 1/4/20-page live ingestion accepted |
| Gate 3 local implementation | implemented | page corpus, BM25/Hybrid retrieval, fixed evidence, AnswerPolicy runner, and fixture tests |
| Gate 3 server real E2E | accepted | 3 windows / 25 pages / 8 QA ran through on AutoDL |
| Gate 3A failure review instrumentation | accepted | compact retrieval/answer previews and failure cases accepted by artifact check |
| Gate 3A rank-aware context/prompt | implemented | opt-in only; default prompt/context restored to Gate 3 behavior |
| Gate 3A default prompt rollback | accepted | default full E2E restored Gate 3 behavior |
| Gate 4 local implementation | implemented | expanded sample manifest, manifest doc-id loading, per-shard metrics, and staged commands |
| Gate 4A sample manifest | accepted | 26 page-window docs / 197 pages / 90 QA from val shards 1-4 |
| Gate 4B ingestion | accepted | selected windows ingested and validated under `outputs/phase4/mpdocvqa_ingestion` |
| Gate 4C validate-only | accepted | 26 documents / 197 pages / 90 QA / 90 valid gold mappings, no models loaded |
| Gate 4C retrieval-only | accepted | BM25 vs Hybrid page retrieval completed; Hybrid Top-5 recall 0.9556 |
| Gate 4D full GRPO E2E | accepted | 90/90 completed, valid JSON/format 1.0, SQLite trace persisted |
| CDC | not_started | do not start during Phase 4B closeout |
| Router/tools | not_started | later phase |
| Demo/closure | not_started | later phase |

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
Gate 4A sample manifest -> accepted
Gate 4B ingestion -> accepted
Gate 4C validate-only -> accepted
Gate 4C retrieval-only -> accepted
Gate 4D full GRPO E2E -> accepted
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

Phase 4B was completed on one feature branch and then fast-forwarded into
`main`:

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

Gate 4 accepted sample:

```text
sample_root = outputs/phase4/mpdocvqa_raw_gate4_expanded
ingestion_root = outputs/phase4/mpdocvqa_ingestion
source_shards = MP-DocVQA val shards 1-4
document_count = 26
page_count = 197
qa_count = 90
```

Gate 4C retrieval-only accepted result:

```text
run = outputs/evaluation/phase4b_mpdocvqa_gate4/gate4c_retrieval_only_empty_page_fix
fixed_evidence_hash = 723160441137a42a3cf3b7775f94ffd6dd681cb15ac67bc2c5d2d0bfdc9feab3
BM25 Recall@1/3/5 = 0.6111 / 0.8667 / 0.9111
BM25 MRR = 0.7259
Hybrid Recall@1/3/5 = 0.7333 / 0.9222 / 0.9556
Hybrid MRR = 0.8257
retrieval_gold_miss_top5 = 4
```

Gate 4D full GRPO E2E accepted result:

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
page_location_hit = 0.4889
block_location_hit = 0.9667
final_location_in_evidence_rate = 1.0
trace_counts.qa_runs = 90
trace_counts.tool_traces = 613
failure_taxonomy = answer_miss:59, gold_page_location_miss:46, retrieval_gold_miss_top5:4
```

Interpretation:

- Gate 4 is an expanded raw-input E2E regression, not a formal benchmark.
- Flow stability is accepted across deterministic PDFs, MinerU ingestion, page
  mapping, page retrieval, fixed evidence, GRPO AnswerPolicy, JSON/format
  validation, and SQLite trace persistence.
- Hybrid retrieval is usable on this sample, with Top-5 page recall 0.9556.
- Answer quality is still limited; the main remaining issues are
  `answer_miss` and `gold_page_location_miss`.
- `--rank-aware-context` remains diagnostic only and is off by default.
- Gate 4 artifacts are server-side acceptance outputs. Missing local mirrors
  under `outputs/phase4/mpdocvqa_raw_gate4_expanded`,
  `outputs/phase4/mpdocvqa_ingestion`, or
  `outputs/evaluation/phase4b_mpdocvqa_gate4/` are an environment/artifact sync
  issue, not missing tracked Phase 4B logic.

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

1. Phase 4D-D candidate answer board generalized improvement is deferred while
   Phase 5 starts the personal-use DocAgent MVP track.
2. Keep Candidate-ID Reader postponed; expanded unseen validation shows only
   5 reader/reranking-attributed cases versus 72 extraction and 38 span cases.
3. Keep optional full GRPO E2E postponed until candidate answer board quality
   improves.
4. Keep B1 table/index scoring/context enhancement disabled by default and
   available only through `--enable-table-index-packing` as experimental.
5. Keep CDC `not_started` until explicitly started.

## 8.1 Phase 4C Candidate Spans Accepted Result

Status:

```text
Phase 4C local implementation -> accepted
Phase 4C server retrieval-only / packing-only -> accepted
Phase 4C server full GRPO E2E -> accepted
```

Scope:

- default runner behavior remains `--evidence-packing page_children`;
- `--evidence-packing candidate_spans` is an accepted experimental and
  recommended evidence packing mode;
- candidate selection is deterministic and rule-based over Hybrid Top-k pages;
- no gold answers, gold page ids, or gold mappings are used for candidate
  selection or candidate artifacts;
- retrieval models, AnswerPolicy prompt defaults, checkpoints, and training
  data remain unchanged;
- Phase 4C is not a formal MP-DocVQA benchmark;
- setting `candidate_spans` as a global default requires more shard and
  document-type validation.

Accepted server artifacts:

```text
baseline_run = outputs/evaluation/phase4b_mpdocvqa_gate4/gate4_full_grpo
candidate_retrieval_only_run = outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_retrieval_only
candidate_full_grpo_run = outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_full_grpo
candidate_fixed_evidence_hash = 75a0fcb3f7e0c847d64a767a6a7116ec975a88b7c4ec3c48f54d70bd2f164bba
```

Candidate packing accepted signal:

```text
sample_count = 90
mean_original_block_count = 39.8444
mean_candidate_span_count = 7.9111
mean_candidate_block_count = 15.3333
compression_ratio_blocks = 0.3848
compression_ratio_tokens = 0.9468
gold_page_in_candidate_pages_rate = 0.9556
gold_page_has_candidate_span_rate = 0.9556
no_gold_leakage = true
```

A/B outcome:

| Metric | page_children | candidate_spans | Delta |
|---|---:|---:|---:|
| normalized_exact_match | 0.3333 | 0.4111 | +0.0778 |
| answer_hit | 0.3444 | 0.4556 | +0.1111 |
| token_f1 | 0.3689 | 0.4628 | +0.0939 |
| character_f1 | 0.5235 | 0.6341 | +0.1106 |
| gold_page_location_hit | 0.4889 | 0.6778 | +0.1889 |
| page_location_hit | 0.4889 | 0.6778 | +0.1889 |
| block_location_hit | 0.9667 | 1.0000 | +0.0333 |
| answer_miss | 59 | 49 | -10 |
| gold_page_location_miss | 46 | 29 | -17 |
| retrieval_gold_miss_top5 | 4 | 4 | 0 |

Interpretation:

Phase 4C 验证了在相同检索结果和相同 AnswerPolicy 条件下，query-aware /
structure-aware candidate_spans 证据筛选能够降低 Top-k page 展开后的
block 噪声，改善 Reader 的答案抽取和证据页定位稳定性。Hybrid retrieval
metrics 与 Phase 4B Gate 4 baseline 保持一致，说明提升不是来自检索模型、
默认 prompt、AnswerPolicy 或训练改动。

Detailed report:

```text
docs/PHASE4C_CANDIDATE_SPANS_REPORT.md
```

Local artifacts added by candidate mode:

```text
candidate_evidence.jsonl
candidate_evidence_preview.json
candidate_packing_metrics.json
```

## 8.2 Phase 4D-A Candidate Answer Coverage Audit

Status:

```text
Phase 4D-A local implementation -> implemented
Phase 4D-A server coverage audit -> accepted
Phase 4D-A.1 local implementation -> implemented
Phase 4D-A.1 server refined audit -> accepted
Phase 4D-A.2 local implementation -> implemented
Phase 4D-A.2 server filtering audit -> accepted
Phase 4D-A.3 local implementation -> implemented
Phase 4D-A.3 server failure inspection -> accepted
Phase 4D-A.3.1 local implementation -> implemented
Phase 4D-A.3.1 server refined summary -> accepted
Phase 4D-A.4 local implementation -> implemented
Phase 4D-A.4 server final gap review -> accepted
```

Scope:

- add deterministic typed candidate answer extraction over Phase 4C
  `candidate_spans`;
- write `candidate_answers.jsonl`, `candidate_answers_preview.json`,
  `candidate_answer_coverage_metrics.json`,
  `candidate_answer_error_buckets.json`, `summary.json`, and `summary.md`;
- use gold answers only for coverage metrics and bucket analysis;
- keep `candidate_answers.jsonl` and preview free of gold answer/page fields;
- do not modify Reader prompts, AnswerPolicy, retrieval models, MinerU,
  checkpoints, training data, or default `candidate_spans` behavior.

Local implementation:

```text
docagent/retrieval/candidate_answer_extraction.py
scripts/analyze_phase4d_candidate_answer_coverage.py
tests/test_candidate_answer_extraction.py
```

Phase 4D-A through Phase 4D-A.3.1 server audits are accepted. Phase 4D-A.3.1
showed `candidate_span_or_normalization_gap = 21` as the largest refined
failure source, so Phase 4D-A.4 is the final diagnostic subtype split before
any repair decision.

Accepted Phase 4D-A server audit:

```text
sample_count = 90
candidate_span_answer_coverage = 0.7444
candidate_answer_coverage = 0.4556
mean_candidate_answer_count = 79.5889
mean_unique_candidate_answer_count = 49.9889
mean_same_type_distractor_count = 22.7444
mean_numeric_distractor_count = 60.4444
no_candidate_answer_count = 0
candidate_answer_no_gold_leakage = true
bucket_A_retrieval_gold_miss_top5 = 4
bucket_C_gold_answer_not_in_candidate_spans = 22
bucket_D_gold_answer_in_candidate_spans_but_not_extracted = 25
bucket_E_gold_answer_in_candidate_answers_but_model_answer_wrong = 13
bucket_F_gold_answer_in_candidate_answers_and_model_answer_correct = 26
```

Interpretation:

- Do not enter Candidate-ID Grounded Reader directly from Phase 4D-A.
- Primary next work is candidate answer extraction, normalization, ranking, and
  top-k coverage analysis.
- The `D=25` bucket is potentially addressable by extraction improvement.
- The `C=22` bucket still requires candidate span improvement.
- The `E=13` bucket represents later Reader or candidate-selection work.

## 8.3 Phase 4D-A.1 Candidate Answer Extraction and Ranking Refinement

Status:

```text
Phase 4D-A.1 local implementation -> implemented
Phase 4D-A.1 server refined audit -> accepted
```

Scope:

- refine heading/title, city/state/location, quarter short-form,
  key-value/field-value, organization/company/board, and source/footer
  extraction rules;
- preserve all candidate answers while assigning rank, top-k flags, and score
  breakdowns with duplicate, generic numeric, and long-text penalties;
- add all/top1/top3/top5/top10/top20 candidate answer coverage metrics;
- add `candidate_answers_topk.jsonl`,
  `candidate_answers_topk_preview.json`, and
  `bucket_transition_estimate.json`;
- do not modify Reader prompts, AnswerPolicy integration, retrieval models,
  training, CDC, Demo, or the default evidence-packing mode.

Accepted Phase 4D-A.1 server audit:

```text
sample_count = 90
candidate_span_answer_coverage = 0.7444
candidate_answer_coverage = 0.5222
candidate_answer_coverage_all = 0.5222
candidate_answer_coverage_top1 = 0.2222
candidate_answer_coverage_top3 = 0.3333
candidate_answer_coverage_top5 = 0.3778
candidate_answer_coverage_top10 = 0.4556
candidate_answer_coverage_top20 = 0.5000
mean_candidate_answer_count = 105.2889
mean_unique_candidate_answer_count = 52.2333
mean_top20_candidate_answer_count = 17.5222
mean_same_type_distractor_count = 26.0556
mean_numeric_distractor_count = 73.7444
rank_1 = 20
rank_2 = 7
rank_3 = 3
rank_4_5 = 4
rank_6_10 = 7
rank_gt10 = 6
missing = 43
bucket_A = 4
bucket_B = 0
bucket_C = 22
bucket_D = 21
bucket_E = 14
bucket_F = 29
bucket_G = 0
candidate_answer_no_gold_leakage = true
```

Interpretation:

- A.1 improved candidate answer coverage from 0.4556 to 0.5222, reduced
  `D=25` to 21, increased `F=26` to 29, and improved `rank_1=10` to 20.
- A.1 also increased noise: mean candidate answer count rose from 79.5889 to
  105.2889 and numeric distractors rose from 60.4444 to 73.7444.
- Candidate-ID Grounded Reader remains deferred.

## 8.4 Phase 4D-A.2 Candidate Answer Filtering / Reranking / Type-aware Top-k

Status:

```text
Phase 4D-A.2 local implementation -> implemented
Phase 4D-A.2 server filtering audit -> accepted
```

Scope:

- preserve all candidates for `candidate_answer_coverage_all`;
- add top-k eligibility, filter reasons, and stronger penalties for generic
  numeric, type mismatch, duplicate, near-duplicate, long text, and noisy text;
- select `candidate_answers_topk.jsonl` through type-aware top-k selection,
  not simple global truncation;
- limit numeric candidates for heading/source/text/location/name questions
  while retaining numeric/index/percentage candidates for numeric questions;
- add top-k filtering metrics and `refinement_comparison.json`;
- do not modify Reader prompts, AnswerPolicy integration, retrieval models,
  training, CDC, Demo, or the default evidence-packing mode.

Accepted Phase 4D-A.2 server audit:

```text
sample_count = 90
candidate_span_answer_coverage = 0.7444
candidate_answer_coverage_all = 0.5222
candidate_answer_coverage_top1 = 0.2333
candidate_answer_coverage_top3 = 0.3111
candidate_answer_coverage_top5 = 0.3889
candidate_answer_coverage_top10 = 0.4333
candidate_answer_coverage_top20 = 0.4556
mean_candidate_answer_count = 105.2889
mean_unique_candidate_answer_count = 52.2333
mean_ranked_candidate_answer_count = 68.9222
mean_top20_candidate_answer_count = 13.6111
mean_topk_numeric_candidate_count = 5.3111
topk_retention_ratio = 0.1293
topk_numeric_ratio = 0.3902
bucket_A = 4
bucket_B = 0
bucket_C = 22
bucket_D = 21
bucket_E = 14
bucket_F = 29
bucket_G = 0
```

Interpretation:

- A.2 made the top-k board cleaner and slightly improved top1/top5 coverage.
- A.2 did not improve all coverage or C/D/E buckets enough to enter
  Candidate-ID Grounded Reader.
- The next step is case-level failure inspection instead of blind rule tuning.

## 8.5 Phase 4D-A.3 Case-level Failure Inspection

Status:

```text
Phase 4D-A.3 local implementation -> implemented
Phase 4D-A.3 server failure inspection -> accepted
```

Scope:

- export C/D/E failure inspection artifacts from the A.2 run directory;
- include gold answer debug fields only in inspection artifacts, not in
  `candidate_answers.jsonl` or `candidate_answers_topk.jsonl`;
- add automatic diagnosis hints for candidate span gaps, extraction gaps, and
  Reader/candidate-selection gaps;
- do not modify Reader prompts, AnswerPolicy integration, retrieval models,
  training, CDC, Demo, or the default evidence-packing mode.

Accepted Phase 4D-A.3 server inspection:

```text
artifacts = failure_inspection_cases.jsonl,
            bucket_C_cases.jsonl,
            bucket_D_cases.jsonl,
            bucket_E_cases.jsonl,
            failure_inspection_summary.json,
            failure_inspection_summary.md
```

Interpretation:

- C/D/E buckets are candidate-layer diagnostics, not equivalent to final QA
  failures.
- Some C/D cases are already final-answer correct and should not be counted as
  primary repair targets.
- The next attribution layer must combine bucket, final answer hit,
  candidate-answer coverage, and top-k coverage.

## 8.6 Phase 4D-A.3.1 Failure Inspection Summary Refinement

Status:

```text
Phase 4D-A.3.1 local implementation -> implemented
Phase 4D-A.3.1 server refined summary -> accepted
Phase 4D-A.4 local implementation -> implemented
Phase 4D-A.4 server final gap review -> accepted
Phase 4D-B1 local implementation -> implemented
Phase 4D-B1.1 local implementation -> implemented
Phase 4D-B1.1 server validation -> accepted
Phase 4D-B1.2 local implementation -> implemented
Phase 4D-B1.3 default pipeline sanity -> accepted
Phase 4D-C expanded unseen validation -> accepted
```

Scope:

- add refined C/D/E summary breakdowns by final answer hit and candidate/top-k
  coverage;
- add refined cases and refined summary artifacts;
- map cases to refined actions such as no-action, candidate span gap,
  extraction gap, Reader selection gap, ranking gap, top-k filtering gap, and
  normalization/metric gap;
- do not modify Reader prompts, AnswerPolicy integration, retrieval models,
  training, CDC, Demo, or the default evidence-packing mode.

Accepted Phase 4D-A.3.1 server refined inspection:

```text
candidate_span_or_normalization_gap = 21
extraction_rule_gap = 10
no_final_failure = 11
normalization_or_metric_gap = 5
reader_selection_gap = 7
topk_filtering_gap = 3
inspect_candidate_spans_or_normalization = 21
improve_candidate_answer_extraction = 10
candidate_id_reader_or_deterministic_selection = 7
improve_type_aware_topk_filtering = 3
inspect_answer_normalization = 5
no_action_final_answer_already_correct = 11
```

Interpretation:

- `candidate_span_or_normalization_gap` is the largest refined source, but it
  mixes true span miss, normalization/metric issues, table/index structure,
  page/content lookup, partial context, and OCR/parsing boundaries.
- Candidate-ID Reader remains postponed while candidate coverage gaps dominate.

## 8.7 Phase 4D-A.4 Candidate Span / Normalization Gap Final Review

Status:

```text
Phase 4D-A.4 local implementation -> implemented
Phase 4D-A.4 server final gap review -> accepted
```

Scope:

- filter A.3.1 refined cases where
  `refined_failure_source = candidate_span_or_normalization_gap`;
- export `candidate_span_gap_cases.jsonl`,
  `candidate_span_gap_preview.json`, `candidate_span_gap_summary.json`, and
  `candidate_span_gap_summary.md`;
- assign only final diagnostic subtypes:
  `normalization_or_metric_gap`, `candidate_span_selection_gap`,
  `candidate_span_partial_context_gap`, `table_or_index_span_gap`,
  `page_number_or_content_lookup_gap`, `ocr_or_parsing_gap`, and
  `unclear_mixed_gap`;
- keep `should_not_patch_specific_qid = true` for every case;
- do not modify candidate span logic, candidate answer extraction logic,
  Reader prompts, AnswerPolicy integration, retrieval models, training, CDC,
  Demo, or the default evidence-packing mode.

Decision gate:

- If one subtype dominates and has a generic repair path, implement one narrow
  generic fix.
- If subtypes are dispersed, stop tuning the 90-sample probe and run the same
  diagnostics on a larger unseen validation sample.
- Do not proceed to Candidate-ID Reader unless reader-selection gaps become
  dominant after candidate coverage issues are resolved.

Accepted Phase 4D-A.4 server final diagnostic:

```text
total_candidate_span_or_normalization_gap = 21
normalization_or_metric_gap = 0
candidate_span_selection_gap = 5
candidate_span_partial_context_gap = 5
table_or_index_span_gap = 10
page_number_or_content_lookup_gap = 1
ocr_or_parsing_gap = 0
unclear_mixed_gap = 0
```

Interpretation:

- A.4 is the final diagnostic split for the 90-sample probe.
- `table_or_index_span_gap = 10` is the dominant concentrated subtype with a
  generic repair path.
- The only allowed next repair is a narrow generic table/index candidate span
  selection fix.

## 8.8 Phase 4D-B1 Generic Table / Index Candidate Span Selection Fix

Status:

```text
Phase 4D-B1 local implementation -> implemented
Phase 4D-B1.1 local implementation -> implemented
Phase 4D-B1.1 server validation -> accepted
Phase 4D-B1.2 closeout -> implemented
Phase 4D-B1.3 default pipeline sanity -> accepted
```

Scope:

- add generic table/index question hint detection for index/share/rate/segment,
  percentage/percent/%, table/row/column, and field/value wording;
- add table/index span scoring bonuses for field-label overlap, percent
  values, parenthesized index values, field-value rows, table/list-like rows,
  and same-line label/value/parenthesized-index evidence;
- retain table/index neighbor context by including current rows, adjacent rows,
  and table header-like blocks when generic table/index signals are present;
- add table/index diagnostics to candidate packing metrics.
- default candidate_spans does not enable this enhancement; the enhancement is
  experimental behind `--enable-table-index-packing`.

Constraints:

- Do not add qid-, document-, title-, entity-, or answer-specific rules.
- Do not modify Reader prompts, AnswerPolicy integration, retrieval models,
  training, CDC, Demo, or the default evidence-packing mode.
- Candidate-ID Reader remains postponed.

Server sanity triage:

```text
qa_qid_count = 90
baseline_qid_count = 90
b1_qid_count = 9
qa_missing_from_b1 = 81
baseline_b1_qid_overlap = 9
baseline row_count = 90
b1 row_count = 9
baseline sample_count = 90
b1 sample_count = 9
```

Interpretation:

- B1 coverage diagnostics are invalid until candidate evidence completeness is
  restored.
- Root cause is runner scope selection: without explicit `--doc-id` or
  `--doc-id-file`, the runner fell back to the three historical default
  documents instead of the active sample `qa.jsonl` doc set.
- B1.1 restored completeness, but B1 table/index enhancement was not accepted
  as a default improvement.

## 8.9 Phase 4D-B1.1 Candidate Evidence Completeness Regression Fix

Status:

```text
Phase 4D-B1.1 local implementation -> implemented
Phase 4D-B1.1 server validation -> accepted
```

Scope:

- infer document scope from `sample_root/qa.jsonl` when no explicit doc scope
  is provided;
- preserve the accepted candidate evidence completeness behavior;
- keep original candidate_spans fallback behavior for non-table/index
  questions;
- add candidate evidence completeness checks before artifact writing;
- add `candidate_evidence_completeness` to run summary and candidate packing
  metrics.

Acceptance requirement:

- `candidate_evidence_row_count == qa_count`;
- `candidate_evidence_qid_set == loaded_qa_qid_set`;
- `candidate_packing_metrics.sample_count == qa_count`;
- no gold leakage remains true.

Server validation result:

```text
candidate_evidence_completeness.qa_count = 90
candidate_evidence_completeness.candidate_evidence_count = 90
candidate_evidence_completeness.qid_set_match = true
candidate_evidence_completeness.missing_qid_count = 0
candidate_evidence_completeness.extra_qid_count = 0
candidate_span_answer_coverage = 0.7444
candidate_answer_coverage_all = 0.5222
candidate_answer_coverage_top20 = 0.4556
candidate_answer_no_gold_leakage = true
```

## 8.10 Phase 4D-B1.2 B1 Closeout

Status:

```text
Phase 4D-B1.2 local implementation -> implemented
Phase 4D-B1.3 default pipeline sanity -> accepted
```

Decision:

- The B1.1 completeness fix is accepted and retained.
- The B1 table/index enhancement is not accepted as a default improvement.
- The enhancement only reduced `table_or_index_span_gap` from 10 to 8, did not
  improve overall candidate coverage, and shifted
  `page_number_or_content_lookup_gap` from 1 to 4.
- Table/index scoring and neighbor-context enhancement are disabled by default
  and kept experimental behind `--enable-table-index-packing`.
- Diagnostics remain additive and include
  `table_index_enhancement_enabled`.
- A.4 is the final diagnostic split for the 90-sample probe; no further
  per-case tuning on this probe is allowed.
- The next action is larger unseen validation with the accepted pipeline and
  diagnostics.
- Candidate-ID Reader remains postponed.

Accepted Phase 4D-B1.3 server sanity:

```text
candidate_evidence_completeness.qa_count = 90
candidate_evidence_completeness.candidate_evidence_count = 90
candidate_evidence_completeness.qid_set_match = true
candidate_evidence_completeness.missing_qid_count = 0
candidate_evidence_completeness.extra_qid_count = 0
candidate_evidence_completeness.duplicate_candidate_qid_count = 0
table_index_enhancement_enabled = false
candidate_span_answer_coverage = 0.7444444444444445
candidate_answer_coverage_all = 0.5222222222222223
candidate_answer_coverage_top1 = 0.23333333333333334
candidate_answer_coverage_top5 = 0.3888888888888889
candidate_answer_coverage_top20 = 0.45555555555555555
candidate_answer_no_gold_leakage = true
completeness_ok = true
table_index_enhancement_default_disabled_ok = true
coverage_matches_phase4c_baseline = true
accepted = true
```

Interpretation:

- The default `candidate_spans` path reproduced the Phase 4C baseline.
- `--enable-table-index-packing` remains experimental only.
- Candidate evidence completeness checks stay in the accepted default path.
- The 90-sample probe is closed to further tuning.

## 8.11 Phase 4D-C Expanded Unseen Validation with Accepted Default Pipeline

Status:

```text
Phase 4D-C expanded unseen validation -> accepted
Phase 4D-C scaffold / command preparation -> ready
Phase 4D-D candidate answer board generalized improvement -> deferred
```

Goal:

- validate candidate evidence completeness on more unseen MP-DocVQA validation
  samples;
- measure retrieval recall;
- measure `candidate_span_answer_coverage`;
- measure `candidate_answer_coverage_all` and top-k coverage;
- inspect failure attribution distribution;
- check whether table/index gaps remain stable outside the 90-sample probe;
- decide whether Candidate-ID Reader should remain postponed.

Default pipeline:

```text
evidence_packing = candidate_spans
rank_aware_context = false
table_index_enhancement_enabled = false
enable_table_index_packing = false
no Candidate-ID Reader
no full GRPO training
no prompt tuning
```

First unseen validation target:

- MP-DocVQA validation shards 5-8;
- 200-300 QA;
- preserve page-count bucket coverage;
- do not run all 29 validation shards at once.

Validation stages:

1. Step A: expanded sample manifest.
2. Step B: ingest missing windows if needed.
3. Step C: retrieval-only + candidate_spans.
4. Step D: candidate answer diagnostics.
5. Step E: failure attribution diagnostics.
6. Step F: optional full E2E only if retrieval and diagnostics are stable.

Resource notes:

- manifest and diagnostics: CPU;
- retrieval-only: GPU required because it loads BGE-M3 and the reranker;
- full E2E: GPU required because it loads Qwen3 and the GRPO adapter.

Accepted strict validation result:

```text
source_shards = MP-DocVQA validation shards 5-8
raw_sample = 85 document windows / 250 QA
strict_accepted_sample = 77 document windows / 572 pages / 218 QA
strict_sample_root = outputs/phase4/mpdocvqa_raw_phase4d_c_shards5_8_strict_accepted
output_root = outputs/evaluation/phase4d_c_expanded_unseen_strict
retrieval_run = phase4d_c_retrieval_candidate_spans
candidate_answer_run = phase4d_c_candidate_answer_coverage
failure_inspection_run = phase4d_c_failure_inspection_refined_cd
candidate_span_gap_review_run = phase4d_c_candidate_span_gap_review_cd
```

Step A accepted:

```text
manifest_row_count = 85
qa_jsonl_count = 250
selected_window_count = 85
selected_qa_count = 250
page_bucket_distribution = pages_1:22, pages_2_5:22, pages_6_9:20, pages_10_plus:21
shard_distribution = val-00005:23, val-00006:25, val-00007:16, val-00008:23
```

Step B strict accepted set:

```text
initial_ingestion_reports = 85
failed_ingestion_windows = 6
failed_ingestion_qa = 29
accepted_only_windows = 79
accepted_only_qa = 221
strict_excluded_qa_mapping_mismatch_windows = 2
strict_excluded_qa_mapping_mismatch_qa = 3
strict_accepted_windows = 77
strict_accepted_pages = 572
strict_accepted_qa = 218
```

Strict filtering boundary:

```text
acceptance_report.status = success
acceptance_report.failures = []
sample_qa_count == qa_page_mapping_count
report_qa_count == sample_qa_count
page_identity_mapping_invalid_count == 0
gold_page_mapping_invalid_count == 0
page_identity_mapping.jsonl exists
```

Step C accepted retrieval-only + candidate_spans result:

```text
qa_count = 218
document_count = 77
page_count = 572
candidate_evidence_completeness.qa_count = 218
candidate_evidence_completeness.candidate_evidence_count = 218
candidate_evidence_completeness.qid_set_match = true
candidate_evidence_completeness.missing_qid_count = 0
candidate_evidence_completeness.extra_qid_count = 0
candidate_evidence_completeness.duplicate_candidate_qid_count = 0
table_index_enhancement_enabled = false
candidate_packing_sample_count = 218
mean_candidate_span_count = 7.6055
mean_candidate_block_count = 14.9312
gold_page_has_candidate_span_rate = 0.9128
no_gold_leakage = true
candidate Recall@1/3/5 = 0.7248 / 0.8945 / 0.9128
candidate MRR = 0.8099
```

Step D accepted candidate answer diagnostics:

```text
sample_count = 218
candidate_span_answer_coverage = 0.7523
candidate_answer_coverage_all = 0.4266
candidate_answer_coverage_top1 = 0.1468
candidate_answer_coverage_top3 = 0.2477
candidate_answer_coverage_top5 = 0.3073
candidate_answer_coverage_top10 = 0.3716
candidate_answer_coverage_top20 = 0.3991
candidate_answer_no_gold_leakage = true
bucket_A = 19
bucket_B = 0
bucket_C = 43
bucket_D = 72
bucket_E = 0
bucket_F = 0
bucket_G = 84
```

Step E accepted failure attribution:

```text
candidate_span_or_normalization_gap = 38
extraction_rule_gap = 72
reader_selection_gap = 5
improve_candidate_answer_extraction = 72
improve_candidate_spans = 38
candidate_id_reader_or_reranking = 5
table_or_index_span_gap = 14
candidate_span_selection_gap = 10
candidate_span_partial_context_gap = 9
page_number_or_content_lookup_gap = 5
normalization_or_metric_gap = 0
ocr_or_parsing_gap = 0
```

Phase 4D-C interpretation:

- The accepted `candidate_spans` pipeline is stable on the strict unseen set:
  full candidate evidence completeness, exact qid match, no gold leakage, and
  table/index enhancement disabled.
- Candidate answer coverage is lower than the 90-sample probe
  (`all: 0.5222 -> 0.4266`, `top20: 0.4556 -> 0.3991`), so the candidate answer
  extraction/span issue is not a one-sample artifact.
- Current bottleneck is not Candidate-ID Reader. Only 5 cases are attributed
  to reader/reranking, while 72 require candidate answer extraction work and
  38 require candidate span work.
- Optional full GRPO E2E remains postponed because Step C/D/E already identify
  the dominant failure source and full E2E would mostly measure known candidate
  board limitations.

Engineering notes from server execution:

- Expanded shard commands must preflight target parquet files explicitly;
  shards 5-8 were initially absent on the server.
- Wrapper commands should not use `set -e`, outer `exit`, or outer
  `raise SystemExit` behavior that closes an interactive terminal; print JSON
  status and log tails instead.
- Accepted-only ingestion status is insufficient before retrieval; E2E inputs
  need strict QA mapping checks.
- Compact retrieval metric readers must support nested metric structures.
- Failure inspection supports C/D/E buckets only; A is retrieval-side miss, and
  G means no Reader/full E2E output.

Phase 4D-D planned boundary:

```text
Phase 4D-D candidate answer board generalized improvement -> deferred
first_action = failure pattern audit before writing new rules
do_not_patch_specific_qids = true
do_not_enable_candidate_id_reader = true
do_not_run_full_grpo_by_default = true
do_not_tune_90_sample_probe = true
```

Scaffold status:

```text
branch = codex/phase4d-c-expanded-unseen-validation
branch_base = origin/main
initial_server_execution = not_started
server_execution_after_report = accepted
code_changes = none
script_support = existing scripts cover Step A-E
```

Existing script support:

- Step A is covered by `scripts/build_phase4b_expanded_sample.py`. It accepts
  multiple val parquet shards, uses `source_doc_id + ordered_page_ids` for
  window identity, writes `expanded_sample_manifest.jsonl`,
  `selection_summary.json`, `documents.jsonl`, and `qa.jsonl`, and keeps
  page-window `doc_id` separate from the raw source `doc_id`.
- Step B is covered by `scripts/run_phase4b_mpdocvqa_ingestion.py` with
  `--skip-existing` or `--revalidate-existing`. It writes per-window
  `acceptance_report.json` with page counts, QA counts, mapping validity,
  missing image references, persisted absolute path counts, no-mock status,
  warnings, and failures.
- Step C is covered by `scripts/run_phase4b_mpdocvqa_e2e.py --retrieval-only
  --evidence-packing candidate_spans`. It writes `page_corpus.jsonl`,
  `page_retrieval_results.jsonl`, `page_retrieval_metrics.json`,
  `retrieval_preview.json`, `candidate_evidence.jsonl`,
  `candidate_packing_metrics.json`, `summary.json`, and `summary.md`.
- Step D is covered by `scripts/analyze_phase4d_candidate_answer_coverage.py`.
  It writes candidate answer boards, all/top-k coverage metrics, distractor
  metrics, and no-gold-leakage checks.
- Step E is covered by `scripts/export_phase4d_failure_inspection.py`,
  including refined failure summaries and `--candidate-span-gap-review`.

Prepared server commands:

Step A manifest (CPU):

```bash
cd /root/autodl-tmp/docagent
source /root/miniconda3/etc/profile.d/conda.sh
conda activate docagent
git status --short
git fetch origin --prune
git switch codex/phase4d-c-expanded-unseen-validation
mkdir -p outputs/logs/phase4d_c
test -f /root/autodl-tmp/datasets/mp_docvqa/parquet/val-00005-of-00029.parquet
test -f /root/autodl-tmp/datasets/mp_docvqa/parquet/val-00006-of-00029.parquet
test -f /root/autodl-tmp/datasets/mp_docvqa/parquet/val-00007-of-00029.parquet
test -f /root/autodl-tmp/datasets/mp_docvqa/parquet/val-00008-of-00029.parquet
python scripts/build_phase4b_expanded_sample.py \
  --input-parquet \
    /root/autodl-tmp/datasets/mp_docvqa/parquet/val-00005-of-00029.parquet \
    /root/autodl-tmp/datasets/mp_docvqa/parquet/val-00006-of-00029.parquet \
    /root/autodl-tmp/datasets/mp_docvqa/parquet/val-00007-of-00029.parquet \
    /root/autodl-tmp/datasets/mp_docvqa/parquet/val-00008-of-00029.parquet \
  --output-root outputs/phase4/mpdocvqa_raw_phase4d_c_shards5_8 \
  --target-qa-count 250 \
  --min-qa-count 200 \
  --max-qa-count 300 \
  --seed phase4d-c-shards5-8 \
  > outputs/logs/phase4d_c/step_a_manifest.log 2>&1
python - <<'PY'
import json
from pathlib import Path
root = Path("outputs/phase4/mpdocvqa_raw_phase4d_c_shards5_8")
summary = json.loads((root / "selection_summary.json").read_text())
print(json.dumps({"command": "Step A manifest", "status": "success", "artifact_paths": [str(root / "expanded_sample_manifest.jsonl"), str(root / "selection_summary.json"), str(root / "qa.jsonl")], "metrics": summary}, ensure_ascii=False))
PY
```

Step B ingestion missing windows (CPU for existing MinerU API client; use an
isolated MinerU environment only if replacing API ingestion with local MinerU):

```bash
cd /root/autodl-tmp/docagent
source /root/miniconda3/etc/profile.d/conda.sh
conda activate docagent
mkdir -p outputs/logs/phase4d_c
python - <<'PY' > outputs/phase4/phase4d_c_doc_ids.txt
import json
from pathlib import Path
manifest = Path("outputs/phase4/mpdocvqa_raw_phase4d_c_shards5_8/expanded_sample_manifest.jsonl")
for line in manifest.read_text().splitlines():
    if line.strip():
        print(json.loads(line)["doc_id"])
PY
python - <<'PY'
import os
if not os.getenv("MINERU_TOKEN"):
    raise SystemExit("MINERU_TOKEN is missing; set it without printing it.")
print('{"command": "Step B preflight", "status": "success", "artifact_paths": [], "metrics": {"mineru_token_set": true}}')
PY
while read -r doc_id; do
  python scripts/run_phase4b_mpdocvqa_ingestion.py \
    --sample-root outputs/phase4/mpdocvqa_raw_phase4d_c_shards5_8 \
    --doc-id "$doc_id" \
    --output-root outputs/phase4/mpdocvqa_ingestion \
    --gate phase4d_c \
    --live-api \
    --skip-existing \
    > "outputs/logs/phase4d_c/step_b_ingest_${doc_id}.log" 2>&1
done < outputs/phase4/phase4d_c_doc_ids.txt
python - <<'PY'
import json
from pathlib import Path
root = Path("outputs/phase4/mpdocvqa_ingestion")
doc_ids = Path("outputs/phase4/phase4d_c_doc_ids.txt").read_text().splitlines()
reports = [json.loads((root / doc_id / "acceptance_report.json").read_text()) for doc_id in doc_ids]
failures = [r for r in reports if r.get("status") != "success" or r.get("failures")]
print(json.dumps({"command": "Step B ingestion missing windows", "status": "success" if not failures else "failed", "artifact_paths": [str(root / doc_id / "acceptance_report.json") for doc_id in doc_ids], "metrics": {"window_count": len(reports), "failed_window_count": len(failures)}}, ensure_ascii=False))
PY
```

Step C retrieval-only + candidate_spans (GPU required for BGE-M3/reranker):

```bash
cd /root/autodl-tmp/docagent
source /root/miniconda3/etc/profile.d/conda.sh
conda activate docagent
mkdir -p outputs/logs/phase4d_c
test -d /root/autodl-tmp/models/bge-m3
test -d /root/autodl-tmp/models/bge-reranker-v2-m3
python scripts/run_phase4b_mpdocvqa_e2e.py \
  --sample-root outputs/phase4/mpdocvqa_raw_phase4d_c_shards5_8 \
  --ingestion-root outputs/phase4/mpdocvqa_ingestion \
  --output-root outputs/evaluation/phase4d_c_expanded_unseen \
  --run-id phase4d_c_retrieval_candidate_spans \
  --gate phase4d_c \
  --retrieval-only \
  --evidence-packing candidate_spans \
  --top-k-pages 5 \
  --dense-backend bge \
  --dense-model-path /root/autodl-tmp/models/bge-m3 \
  --reranker-backend cross_encoder \
  --reranker-model-path /root/autodl-tmp/models/bge-reranker-v2-m3 \
  --retrieval-device cuda \
  > outputs/logs/phase4d_c/step_c_retrieval_only.log 2>&1
python - <<'PY'
import json
from pathlib import Path
run = Path("outputs/evaluation/phase4d_c_expanded_unseen/phase4d_c_retrieval_candidate_spans")
summary = json.loads((run / "summary.json").read_text())
metrics = {"qa_count": summary["qa_count"], "candidate_evidence_completeness": summary["candidate_evidence_completeness"], "page_retrieval_metrics": summary["page_retrieval_metrics"]}
print(json.dumps({"command": "Step C retrieval-only + candidate_spans", "status": "success", "artifact_paths": [str(run / name) for name in ("page_corpus.jsonl", "page_retrieval_results.jsonl", "page_retrieval_metrics.json", "retrieval_preview.json", "candidate_evidence.jsonl", "candidate_packing_metrics.json", "summary.json", "summary.md")], "metrics": metrics}, ensure_ascii=False))
PY
```

Step D candidate answer diagnostics (CPU):

```bash
cd /root/autodl-tmp/docagent
source /root/miniconda3/etc/profile.d/conda.sh
conda activate docagent
mkdir -p outputs/logs/phase4d_c
python scripts/analyze_phase4d_candidate_answer_coverage.py \
  --candidate-evidence outputs/evaluation/phase4d_c_expanded_unseen/phase4d_c_retrieval_candidate_spans/candidate_evidence.jsonl \
  --qa-jsonl outputs/phase4/mpdocvqa_raw_phase4d_c_shards5_8/qa.jsonl \
  --page-retrieval-results outputs/evaluation/phase4d_c_expanded_unseen/phase4d_c_retrieval_candidate_spans/page_retrieval_results.jsonl \
  --candidate-packing-metrics outputs/evaluation/phase4d_c_expanded_unseen/phase4d_c_retrieval_candidate_spans/candidate_packing_metrics.json \
  --phase4c-summary outputs/evaluation/phase4d_c_expanded_unseen/phase4d_c_retrieval_candidate_spans/summary.json \
  --output-root outputs/evaluation/phase4d_c_expanded_unseen \
  --run-id phase4d_c_candidate_answer_coverage \
  --top-k 20 \
  > outputs/logs/phase4d_c/step_d_candidate_answer_coverage.log 2>&1
python - <<'PY'
import json
from pathlib import Path
run = Path("outputs/evaluation/phase4d_c_expanded_unseen/phase4d_c_candidate_answer_coverage")
summary = json.loads((run / "summary.json").read_text())
print(json.dumps({"command": "Step D candidate answer diagnostics", "status": "success", "artifact_paths": [str(run / name) for name in ("candidate_answer_coverage_metrics.json", "candidate_answers.jsonl", "candidate_answers_topk.jsonl", "summary.md")], "metrics": summary["metrics"]}, ensure_ascii=False))
PY
```

Step E failure attribution diagnostics (CPU; reader-specific attribution remains
provisional until optional full E2E answer results exist):

```bash
cd /root/autodl-tmp/docagent
source /root/miniconda3/etc/profile.d/conda.sh
conda activate docagent
mkdir -p outputs/logs/phase4d_c
python scripts/export_phase4d_failure_inspection.py \
  --run-dir outputs/evaluation/phase4d_c_expanded_unseen/phase4d_c_candidate_answer_coverage \
  --candidate-evidence outputs/evaluation/phase4d_c_expanded_unseen/phase4d_c_retrieval_candidate_spans/candidate_evidence.jsonl \
  --qa-jsonl outputs/phase4/mpdocvqa_raw_phase4d_c_shards5_8/qa.jsonl \
  --output-root outputs/evaluation/phase4d_c_expanded_unseen \
  --run-id phase4d_c_failure_inspection_refined \
  --buckets C,D,E \
  > outputs/logs/phase4d_c/step_e_failure_inspection.log 2>&1
python scripts/export_phase4d_failure_inspection.py \
  --candidate-span-gap-review \
  --source-refined-run-dir outputs/evaluation/phase4d_c_expanded_unseen/phase4d_c_failure_inspection_refined \
  --output-root outputs/evaluation/phase4d_c_expanded_unseen \
  --run-id phase4d_c_candidate_span_gap_review \
  > outputs/logs/phase4d_c/step_e_candidate_span_gap_review.log 2>&1
python - <<'PY'
import json
from pathlib import Path
root = Path("outputs/evaluation/phase4d_c_expanded_unseen")
refined = root / "phase4d_c_failure_inspection_refined"
gap = root / "phase4d_c_candidate_span_gap_review"
summary = json.loads((refined / "failure_inspection_refined_summary.json").read_text())
gap_summary = json.loads((gap / "candidate_span_gap_summary.json").read_text())
print(json.dumps({"command": "Step E failure attribution diagnostics", "status": "success", "artifact_paths": [str(refined / name) for name in ("failure_inspection_refined_cases.jsonl", "failure_inspection_refined_summary.json", "failure_inspection_refined_summary.md")] + [str(gap / name) for name in ("candidate_span_gap_summary.json", "candidate_span_gap_summary.md")], "metrics": {"refined_failure_source_counts": summary["refined_failure_source_counts"], "true_failure_action_counts": summary["true_failure_action_counts"], "gap_subtype_counts": gap_summary["gap_subtype_counts"]}}, ensure_ascii=False))
PY
```

## 9. Stop Condition

Stop after the following are complete:

```text
Phase 4D-B1.3 server sanity accepted
+ Phase 4D-C plan documented
+ targeted and regression tests pass
+ status documents updated
+ branch pushed
+ stop before CDC, Demo, Reader prompt changes, AnswerPolicy integration,
   training, per-qid repairs, further 90-sample probe tuning, and any global
   `candidate_spans` default change
```

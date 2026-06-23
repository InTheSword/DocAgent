# Active Plan

> Stable entry point for the current Codex task. Detailed phase history stays in
> the phase-specific plan files linked below.

## Current Stage

```text
Phase 4D-C accepted -> Phase 4D-D deferred -> Phase 5 active
```

## Current Goal

```text
Phase 5 Personal-use DocAgent MVP
-> Phase 5A architecture audit and contracts
-> preserve provided PHASE5_ACTIVE_PLAN.md as the master plan
-> document router contract
-> document deterministic tool inventory
-> document MVP acceptance criteria
-> stop before functional MVP implementation
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
Phase 4C local implementation -> accepted
Phase 4C server retrieval-only / packing-only -> accepted
Phase 4C server full GRPO E2E -> accepted
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
Phase 4D-B1 local implementation -> implemented
Phase 4D-B1.1 local implementation -> implemented
Phase 4D-B1.1 server validation -> accepted
Phase 4D-B1.2 closeout -> implemented
Phase 4D-B1.3 default pipeline sanity -> accepted
Phase 4D-C expanded unseen validation -> accepted
Phase 4D-C scaffold / command preparation -> ready
Phase 4D-D candidate answer board generalized improvement -> deferred
Phase 5 Personal-use DocAgent MVP -> active
Phase 5A architecture audit and contracts -> implemented
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
- implement deterministic candidate answer extraction and audit artifacts from
  existing Phase 4C candidate_spans outputs.
- use QA gold answers only for coverage metrics and error buckets, not for
  candidate answer extraction or candidate answer artifacts.
- refine candidate answer extraction, ranking, top-k metrics, and limited
  top-k board artifacts without using Reader or AnswerPolicy.
- filter and rerank candidate answers for type-aware top-k boards while
  preserving all candidates for audit coverage.
- export case-level C/D/E failure inspection artifacts for audit and targeted
  planning only. Inspection artifacts may include gold answers for debugging,
  but they must not be used as Reader input.
- refine inspection summary attribution by combining candidate bucket, final
  answer hit, candidate-answer coverage, and top-k coverage.
- split `candidate_span_or_normalization_gap` into final diagnostic subtypes
  for audit and decision guidance only.
- preserve the accepted default `candidate_spans` path for expanded unseen
  validation.
- keep B1 table/index scoring/context enhancement disabled by default and
  available only through the experimental `--enable-table-index-packing` flag.
- do not continue tuning the 90-sample probe.

## Blockers

- No blocker for the accepted Phase 4A foundation.
- Gate 3 real-model E2E and Gate 3A default prompt rollback are accepted for
  the small 3-window regression.
- Gate 4 expanded raw-input regression is accepted; it is not a formal
  benchmark and does not change the default AnswerPolicy prompt/context.
- Phase 4D-A server coverage audit is accepted. Its result shows that the next
  blocker is candidate answer extraction/ranking quality, not a Reader change.
- Phase 4D-A.1 server refined audit is accepted. It improved coverage but
  increased candidate noise, so Candidate-ID Reader remains deferred.
- Phase 4D-A.2 server filtering audit is accepted. It cleaned the top-k board
  but did not improve all coverage or C/D/E buckets enough to enter
  Candidate-ID Reader.
- Phase 4D-A.3 server inspection is accepted. It showed that C/D/E buckets mix
  candidate-layer gaps and final-answer failures.
- Phase 4D-A.3.1 server refined inspection is accepted. Its largest refined
  failure source is `candidate_span_or_normalization_gap = 21`, which is still
  too coarse for a repair decision.
- Phase 4D-A.4 final diagnostic is accepted. It confirmed
  `table_or_index_span_gap = 10` as the dominant generic subtype inside the
  21 `candidate_span_or_normalization_gap` cases.
- Phase 4D-B1.1 candidate evidence completeness fix is accepted.
- Phase 4D-B1.3 default pipeline sanity is accepted; the default
  `candidate_spans` path reproduced the Phase 4C baseline with table/index
  enhancement disabled.
- Phase 4D-C expanded unseen validation is accepted on the strict accepted
  shards 5-8 set. The main bottleneck remains candidate answer extraction and
  candidate span construction, not Reader selection.
- 90-sample probe tuning is closed. Phase 4D-D candidate answer board and span
  gap improvement is deferred while Phase 5 focuses on a personal-use MVP.

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

Phase 4C accepted server A/B:

```text
baseline_run = outputs/evaluation/phase4b_mpdocvqa_gate4/gate4_full_grpo
candidate_retrieval_only_run = outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_retrieval_only
candidate_full_grpo_run = outputs/evaluation/phase4c_candidate_spans/gate4_candidate_spans_full_grpo
fixed_evidence_hash = 75a0fcb3f7e0c847d64a767a6a7116ec975a88b7c4ec3c48f54d70bd2f164bba
```

Phase 4C compact result:

```text
candidate_spans normalized_exact_match = 0.4111 (+0.0778)
candidate_spans answer_hit = 0.4556 (+0.1111)
candidate_spans token_f1 = 0.4628 (+0.0939)
candidate_spans character_f1 = 0.6341 (+0.1106)
candidate_spans gold_page_location_hit = 0.6778 (+0.1889)
candidate_spans block_location_hit = 1.0 (+0.0333)
answer_miss = 49 (-10)
gold_page_location_miss = 29 (-17)
retrieval_gold_miss_top5 = 4 (unchanged)
```

Phase 4C interpretation:

- Hybrid retrieval metrics are unchanged from the Phase 4B Gate 4 baseline:
  Hybrid Recall@1/3/5 = 0.7333 / 0.9222 / 0.9556 and MRR = 0.8257.
- The improvement comes from query-aware / structure-aware evidence packing,
  not from retrieval model changes, AnswerPolicy prompt changes, or retraining.
- `candidate_spans` reduced mean selected block count from 39.8444 to 15.3333
  while preserving `gold_page_has_candidate_span_rate = 0.9556`.
- `candidate_spans` is accepted as an experimental and recommended evidence
  packing mode, but it is not yet the global default.
- Full details are recorded in `docs/PHASE4C_CANDIDATE_SPANS_REPORT.md`.

Phase 4D-A accepted server audit:

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

Phase 4D-A interpretation:

- Do not enter Candidate-ID Grounded Reader directly from this result.
- The immediate bottleneck is candidate answer extraction / normalization /
  ranking noise: 25 samples have the gold answer in candidate spans but not in
  extracted candidate answers, and average candidate answer count is 79.5889.
- 22 samples still require candidate span improvement.
- 13 answer-covered samples require later Reader or candidate-selection work.

Phase 4D-A.1 accepted server audit:

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

Phase 4D-A.1 interpretation:

- Extraction refinement improved `candidate_answer_coverage` from 0.4556 to
  0.5222, reduced `D` from 25 to 21, increased `F` from 26 to 29, and improved
  `rank_1` from 10 to 20.
- Candidate noise also increased: mean candidate answer count rose from 79.5889
  to 105.2889 and mean numeric distractor count rose from 60.4444 to 73.7444.
- Do not enter Candidate-ID Grounded Reader yet; optimize filtering, reranking,
  and type-aware top-k boards first.

Phase 4D-A.2 accepted server audit:

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

Phase 4D-A.2 interpretation:

- Filtering/reranking made the top-k board cleaner and slightly improved
  top1/top5 coverage: `top1=0.2333`, `top5=0.3889`.
- Top20 coverage dropped from 0.5000 to 0.4556, while all coverage stayed at
  0.5222 and C/D/E buckets did not improve.
- Do not enter Candidate-ID Grounded Reader yet. The next step is C/D/E
  case-level failure inspection to identify targeted candidate span,
  extraction, normalization, ranking, or Reader work.

Phase 4D-A.3 accepted server inspection:

```text
artifacts = failure_inspection_cases.jsonl,
            bucket_C_cases.jsonl,
            bucket_D_cases.jsonl,
            bucket_E_cases.jsonl,
            failure_inspection_summary.json,
            failure_inspection_summary.md
```

Phase 4D-A.3 inspection interpretation:

- C/D/E buckets are candidate-layer diagnostics, not equivalent to final QA
  failures.
- Some C/D samples have `phase4c_prediction.answer_hit = true` and should not
  be counted as primary repair targets.
- True next-action attribution must combine bucket, final answer hit,
  candidate-answer coverage, and top-k coverage.
- Phase 4D-A.3.1 refines the summary/action attribution while still avoiding
  Reader prompt, AnswerPolicy, training, CDC, and Demo changes.

Phase 4D-A.3.1 accepted server refined inspection:

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

Phase 4D-A.4 implemented boundary:

- filter A.3.1 refined cases where
  `refined_failure_source = candidate_span_or_normalization_gap`;
- export `candidate_span_gap_cases.jsonl`,
  `candidate_span_gap_preview.json`, `candidate_span_gap_summary.json`, and
  `candidate_span_gap_summary.md`;
- assign only the allowed final subtypes:
  `normalization_or_metric_gap`, `candidate_span_selection_gap`,
  `candidate_span_partial_context_gap`, `table_or_index_span_gap`,
  `page_number_or_content_lookup_gap`, `ocr_or_parsing_gap`, and
  `unclear_mixed_gap`;
- keep every case marked `should_not_patch_specific_qid = true`.

Phase 4D-A.4 decision boundary:

- No per-qid, per-document, or answer-specific repair is allowed.
- After A.4, implement one narrow generic fix only if one subtype dominates
  and has a generic repair path.
- If subtypes are dispersed, stop tuning this 90-sample probe and run the same
  diagnostics on a larger unseen validation sample.
- Candidate-ID Reader remains postponed unless reader-selection gaps become
  dominant after candidate coverage issues are resolved.

Phase 4D-A.4 accepted server final diagnostic:

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

Phase 4D-B1 implemented boundary:

- add generic table/index question hint detection for index/share/rate/segment,
  percentage/percent/%, table/row/column, and field/value wording;
- add table/index span scoring bonuses for field-label overlap, percent
  values, parenthesized index values, field-value rows, table/list-like rows,
  and same-line label/value/parenthesized-index evidence;
- preserve table/index neighbor context by retaining the current row, nearby
  rows, and table header-like blocks when generic table/index signals are
  present;
- add aggregate diagnostics for table/index candidate spans, answer coverage,
  top-span field-value presence, neighbor context, and parenthesized-index
  span counts.

Phase 4D-B1 boundary:

- This is not Candidate-ID Reader.
- Do not add qid-, document-, title-, entity-, or answer-specific rules.
- Do not modify Reader prompts, AnswerPolicy, retrieval models, training, CDC,
  Demo, or the global `candidate_spans` default.

Phase 4D-B1 server sanity triage:

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

Phase 4D-B1.1 accepted boundary:

- when no explicit `--doc-id` or `--doc-id-file` is provided, infer the loaded
  document scope from the active `sample_root/qa.jsonl` instead of falling back
  to the three historical default documents;
- keep `candidate_evidence_count == qa_count`,
  `candidate_evidence_qid_set == qa_jsonl_qid_set`, and
  `candidate_packing_metrics.sample_count == qa_count`;
- keep `candidate_evidence_completeness` in summary and
  `candidate_packing_metrics.json`;
- preserve original candidate_spans fallback behavior for non-table/index
  questions;
- fail before writing candidate evidence if candidate record count or qid set
  does not match the loaded QA qid set.

Phase 4D-B1.2 closeout:

- B1.1 server validation restored completeness with 90 QA records, 90
  candidate evidence records, exact qid-set match, and no gold leakage.
- B1 table/index enhancement is not accepted as a default improvement: it only
  reduced `table_or_index_span_gap` from 10 to 8, did not improve overall
  candidate answer coverage, and shifted `page_number_or_content_lookup_gap`
  from 1 to 4.
- Table/index scoring and neighbor-context enhancement are disabled by default
  and kept only behind the experimental `--enable-table-index-packing` flag.
- A.4 remains the final diagnostic split for the 90-sample probe. No further
  per-case tuning on this probe is allowed.

Phase 4D-B1.3 accepted default pipeline sanity:

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

Phase 4D-C planned default pipeline:

```text
evidence_packing = candidate_spans
rank_aware_context = false
table_index_enhancement_enabled = false
enable_table_index_packing = false
no Candidate-ID Reader
no full GRPO training
no prompt tuning
```

Phase 4D-C first validation target:

- MP-DocVQA validation shards 5-8;
- 200-300 QA;
- keep page-count bucket coverage;
- do not run all 29 shards at once.

Phase 4D-C staged validation:

1. Step A: expanded sample manifest (CPU).
2. Step B: ingestion missing windows if needed (CPU unless MinerU is invoked
   externally).
3. Step C: retrieval-only + candidate_spans (GPU required; loads BGE-M3 and
   reranker).
4. Step D: candidate answer diagnostics (CPU).
5. Step E: failure attribution diagnostics (CPU).
6. Step F: optional full E2E only if retrieval and diagnostics are stable (GPU
   required; loads Qwen3 and the GRPO adapter).

Phase 4D-C accepted server result:

```text
source_shards = MP-DocVQA validation shards 5-8
raw_sample = 85 document windows / 250 QA
strict_accepted_sample = 77 document windows / 572 pages / 218 QA
artifact_root = outputs/evaluation/phase4d_c_expanded_unseen_strict
retrieval_run = phase4d_c_retrieval_candidate_spans
candidate_answer_run = phase4d_c_candidate_answer_coverage
failure_inspection_run = phase4d_c_failure_inspection_refined_cd
candidate_span_gap_review_run = phase4d_c_candidate_span_gap_review_cd
```

Step B strict filtering:

```text
excluded_failed_ingestion = 6 windows / 29 QA
excluded_qa_mapping_mismatch = 2 windows / 3 QA
strict_filter_required = sample_qa_count == qa_page_mapping_count
                       + report_qa_count == sample_qa_count
                       + page_identity_mapping_invalid_count == 0
                       + gold_page_mapping_invalid_count == 0
```

Step C retrieval-only + candidate_spans accepted result:

```text
qa_count = 218
document_count = 77
page_count = 572
candidate_evidence_count = 218
qid_set_match = true
missing_qid_count = 0
extra_qid_count = 0
duplicate_candidate_qid_count = 0
table_index_enhancement_enabled = false
candidate_packing_sample_count = 218
mean_candidate_span_count = 7.6055
mean_candidate_block_count = 14.9312
gold_page_has_candidate_span_rate = 0.9128
no_gold_leakage = true
candidate Recall@1/3/5 = 0.7248 / 0.8945 / 0.9128
candidate MRR = 0.8099
```

Step D candidate answer diagnostics accepted result:

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
bucket_C = 43
bucket_D = 72
bucket_G = 84
```

Step E failure attribution accepted result:

```text
extraction_rule_gap = 72
candidate_span_or_normalization_gap = 38
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

- The accepted default `candidate_spans` path remains stable on the strict
  unseen set, with complete candidate evidence, exact qid-set match, no gold
  leakage, and table/index enhancement disabled.
- Candidate answer coverage drops versus the 90-sample probe
  (`all: 0.5222 -> 0.4266`, `top20: 0.4556 -> 0.3991`), so the candidate
  answer extraction/span issue is not a probe artifact.
- Candidate-ID Reader remains postponed: reader/reranking attribution is only
  5 cases, while extraction/span improvement accounts for 110 cases.
- Optional full GRPO E2E remains postponed until candidate answer board quality
  improves.

Phase 4D-D planned boundary:

```text
goal = Candidate Answer Extraction & Span Gap Generalized Improvement
status = deferred
first_action = failure pattern audit before writing new rules
do_not_patch_specific_qids = true
do_not_enable_candidate_id_reader = true
do_not_run_full_grpo_by_default = true
do_not_tune_90_sample_probe = true
```

Phase 5A active boundary:

```text
goal = Personal-use DocAgent MVP architecture audit and contracts
status = implemented
branch = codex/phase5a-mvp-planning-contracts
deliverables = docs/PHASE5_ACTIVE_PLAN.md,
              docs/PHASE5_ROUTER_CONTRACT.md,
              docs/PHASE5_TOOL_INVENTORY.md,
              docs/PHASE5_MVP_ACCEPTANCE.md
do_not_implement_docagent_cli = true
do_not_implement_router_code = true
do_not_implement_document_tools = true
do_not_modify_answer_policy_prompt = true
do_not_modify_candidate_answer_extraction = true
do_not_run_full_grpo_e2e = true
```

Phase 4D-C scaffold / command preparation:

```text
branch = codex/phase4d-c-expanded-unseen-validation
branch_base = origin/main
status = ready
script_support = existing scripts cover Step A-E
code_changes = none
initial_server_execution = not_started
server_execution_after_report = accepted
```

Existing script support:

- `scripts/build_phase4b_expanded_sample.py` builds the shards 5-8 expanded
  sample manifest, preserves `source_doc_id + ordered_page_ids ->
  window_signature -> doc_id`, writes `expanded_sample_manifest.jsonl`,
  `selection_summary.json`, `documents.jsonl`, and `qa.jsonl`, and keeps
  page-window document identity.
- `scripts/run_phase4b_mpdocvqa_ingestion.py` supports `--skip-existing`,
  `--revalidate-existing`, live MinerU API ingestion, QA page mapping checks,
  portability checks, and per-window `acceptance_report.json`.
- `scripts/run_phase4b_mpdocvqa_e2e.py --retrieval-only --evidence-packing
  candidate_spans` writes retrieval artifacts, candidate evidence, candidate
  packing metrics, gold-page rank distributions, by-doc/by-shard retrieval
  metrics, completeness checks, and no-gold-leakage checks.
- `scripts/analyze_phase4d_candidate_answer_coverage.py` writes candidate
  answer coverage, all/top-k coverage, distractor metrics, and gold-free
  candidate answer boards.
- `scripts/export_phase4d_failure_inspection.py` writes refined failure
  inspection artifacts and `--candidate-span-gap-review` artifacts.

Prepared command defaults:

```text
evidence_packing = candidate_spans
rank_aware_context = false
table_index_enhancement_enabled = false
enable_table_index_packing = false
no Candidate-ID Reader
no prompt tuning
no training
no full GRPO by default
```

CPU/GPU boundary:

```text
Step A manifest = CPU
Step B ingestion missing windows = CPU for the existing MinerU API client;
  isolated MinerU environment required only if local MinerU is substituted
Step C retrieval-only = GPU required for BGE-M3 and reranker
Step D candidate answer diagnostics = CPU
Step E failure attribution diagnostics = CPU
Step F optional full E2E = GPU required for Qwen3 + GRPO adapter
```

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

1. Start Phase 5B with deterministic document tools after Phase 5A contracts
   are accepted.
2. Keep Phase 4D-D deferred until MVP entrypoint, router, deterministic tools,
   and multi-task regression are accepted.
3. Keep Candidate-ID Reader postponed until reader-selection failures dominate
   after candidate coverage issues are resolved.
4. Keep optional full GRPO E2E postponed until candidate answer board quality
   improves.
5. Keep `page_children` as the default until more shard and document-type
   validation supports a global default change.
6. Keep CDC `not_started` until explicitly started.

## Stop Condition

```text
Phase 4D-B1.3 server sanity accepted
+ Phase 4D-C expanded unseen validation accepted
+ Phase 4D-D deferred
+ Phase 5A architecture audit and contract documents implemented
+ targeted and regression tests pass
+ status documents updated
+ branch pushed
+ stop before Reader prompt changes, AnswerPolicy integration, training, CDC,
   Demo, per-qid repairs, further 90-sample probe tuning, and any global
   `candidate_spans` default change
```

## Phase Documents

- `docs/PHASE4_ACTIVE_PLAN.md`: detailed Phase 4 working record.
- `docs/PHASE4C_CANDIDATE_SPANS_REPORT.md`: accepted Phase 4C A/B report.
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

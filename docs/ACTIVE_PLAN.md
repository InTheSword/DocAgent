# Active Plan

> Stable entry point for the current Codex task. Detailed phase history stays in
> the phase-specific plan files linked below.

## Current Stage

```text
Phase 4D-A.1: Candidate answer extraction and ranking refinement
```

## Current Goal

```text
Phase 4C candidate_evidence.jsonl
-> deterministic typed candidate answer extraction
-> candidate answer board artifacts
-> coverage / rank / distractor metrics
-> error bucket analysis
-> extraction/ranking refinement before Candidate-ID Reader
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
Phase 4D-A.1 server refined audit -> not_started
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

## Blockers

- No blocker for the accepted Phase 4A foundation.
- Gate 3 real-model E2E and Gate 3A default prompt rollback are accepted for
  the small 3-window regression.
- Gate 4 expanded raw-input regression is accepted; it is not a formal
  benchmark and does not change the default AnswerPolicy prompt/context.
- Phase 4D-A server coverage audit is accepted. Its result shows that the next
  blocker is candidate answer extraction/ranking quality, not a Reader change.
- Phase 4D-A.1 local implementation has no local blocker. The refined server
  audit requires server-side Phase 4C artifacts, which may be absent from the
  local ignored `outputs/` tree.

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

1. Run Phase 4D-A.1 refined candidate answer audit on the server Phase 4C
   `candidate_spans` artifacts.
2. Compare all/top-k candidate answer coverage and rank distribution against
   the accepted Phase 4D-A audit.
3. Keep `page_children` as the default until more shard and document-type
   validation supports a global default change.
4. Keep CDC `not_started` until explicitly started.

## Stop Condition

```text
Phase 4D-A.1 local implementation implemented
+ targeted and regression tests pass
+ status documents updated
+ branch pushed
+ stop before Reader prompt changes, AnswerPolicy integration, training, CDC, Demo,
   and any global `candidate_spans` default change
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

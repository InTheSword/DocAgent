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
-> Phase 5C-2 LLM-assisted Router fallback accepted
-> Phase 5C-3 Query Planning + Multi-Query Retrieval accepted
-> Phase 5H Full Workflow Validation Baseline accepted
-> Phase 5I-A Pre-LLM Evidence Readiness Benchmark accepted
-> keep the accepted rule router as the deterministic default
-> use external LLM only for explicitly enabled low-confidence routing fallback
-> use the LLM query planner only for query expansion when explicitly enabled
-> Phase 5I-B Full Model-enhanced QA Path accepted after server full-path smoke
   with real Router/Rewriter API, Qwen base AnswerPolicy, and Router trigger probe
-> keep final-answer correctness metrics diagnostic-only until the Qwen input /
   output contract and future training data design are revisited
-> Phase 5E Document Summary MVP implemented locally
-> Phase 5E-A Document Summary Acceptance Pack implemented locally
-> Phase 5F Full CLI Acceptance accepted after AutoDL server smoke
-> Final Delivery Contract local update implemented:
   answer + reasoning_summary + evidence_used + citations + trace_path
-> deterministic table_lookup and simple_calculation implemented locally
-> raw PDF MinerU API accepted as the final raw PDF parser path; local MinerU
   CLI execution is no longer a delivery target
-> final-evaluation subset preparation implemented locally for TAT-QA dev and
   MP-DocVQA val shards 1-2
-> final-evaluation local subset diagnostic runner implemented locally
-> final-delivery CLI guide implemented locally
-> final-delivery report implemented locally for accepted, real_model_verified,
   implemented, and not_started evidence-boundary status
-> final-delivery readiness check implemented locally for required files, CLI
   options, output contract fields, citation/evidence location fields,
   documentation boundaries, and deprecated PM handoff cleanup; it does not
   call MinerU, Qwen, BGE-M3, reranker, datasets, or training
-> final-delivery benchmark gate implemented locally for server-side
   readiness, AnswerPolicy baseline, and MP-DocVQA full-workflow diagnostic
   orchestration; it keeps formal_benchmark_acceptance false and does not
   start training
-> final-delivery benchmark gate server diagnostic accepted: server run
   `final_delivery_benchmark_gate_server_20260702_componentmetrics` completed
   readiness, real-Qwen AnswerPolicy baseline, and MP-DocVQA full-workflow
   diagnostic steps successfully, used Qwen, kept `used_training=false`,
   `formal_benchmark_acceptance=false`, and
   `validation_subset_used_for_training=false`; follow-up review
   `final_delivery_gate_metric_review_componentcountfix_20260702` at commit
   `e289163` verified local/sync manifests, safety flags, and complete
   component-use metrics for the 23 local_fact_qa workflow rows; this accepts
   the diagnostic gate execution and component metric contract, not final
   answer-quality benchmark status
-> Phase 5I-B final-answer-quality artifact contract implemented locally:
   `scripts/run_phase5i_answer_quality_benchmark.py` now writes
   `metrics.json`, `predictions.jsonl`, `case_reports.jsonl`,
   `failure_analysis.md`, `acceptance_report.json`, and
   `training_candidates_raw.jsonl`, plus `manifest.json` with artifact sizes
   and hashes, while preserving
   `formal_benchmark_acceptance=false` and
   `validation_subset_used_for_training=false`; the runner forwards
   retriever/dense/reranker configuration into `docagent_cli.py` so server
   probes can explicitly exercise `hybrid_rerank` with BGE-M3 and the
   cross-encoder reranker; model-backed runs now preflight the requested
   `db_path` + `doc_id` and return blocked artifacts before CLI/Qwen execution
   when the document context has no persisted retrievable EvidenceBlocks;
   server guard validation `phase5ib_answer_quality_context_block_20260702`
   at commit `d980841` confirmed the missing-context path returns
   `benchmark_status=blocked`, keeps `used_qwen_answer_policy=false`, and
   passes artifact review; the selected-context server probe
   `phase5ib_answer_quality_selected_context_20260702` ran with Qwen but
   surfaced metadata-level CLI/evidence failures, and the returned compact
   artifacts were insufficient for direct attribution; the local artifact
   contract now preserves compact CLI status/error/retriever diagnostics and
   avoids counting pre-AnswerPolicy retriever setup failures as Qwen use;
   server rerun `phase5ib_answer_quality_selected_context_artifactfix_20260702`
   at commit `6e4085b` confirmed BGE/reranker initialization succeeds and
   failures are now `workflow_failed` inside the QA workflow; the local error
   contract now preserves workflow exception class names even when exception
   messages are empty; server rerun
   `phase5ib_answer_quality_selected_context_causetype_20260702` at commit
   `03928e3` classified the internal workflow cause as `AssertionError` for
   the seven failed rows; the local error contract now also preserves a compact
   traceback tail in Phase 5I-B case reports so the next server diagnostic can
   locate the assertion without broad log collection; server rerun
   `phase5ib_answer_quality_selected_context_traceback_20260702` at commit
   `9bc8a16` located the assertion in FAISS search
   (`assert d == self.d`), caused by stale legacy dense-index metadata being
   reused with a different current dense encoder; the local CLI now refuses
   mismatched legacy dense-index metadata and rebuilds when
   `--build-dense-index-if-missing` is enabled, while `DenseIndex.search`
   reports dimension mismatches before backend search; server rerun
   `phase5ib_answer_quality_selected_context_densefix_20260702` at commit
   `f3d26fe` validated the repair with 8/8 CLI statuses successful, no
   workflow errors or traceback causes, and stale `hash-dense-256` legacy
   index metadata rebuilt into BGE-M3 model-specific metadata. Remaining
   failures are diagnostic answer/citation quality issues
   (`answer_keyword_missing`, `citation_page_mismatch`,
   `downstream_answer_not_evaluated`), not execution-chain blockers; accepted
   final answer-quality benchmark status remains not_started
-> Phase 5I-B document-context inventory implemented locally:
   `scripts/inspect_phase5i_document_contexts.py` reads candidate SQLite
   `db_path` / `doc_id` pairs, checks persisted retrievable EvidenceBlocks,
   summarizes case keyword/page context readiness, and writes compact
   artifacts plus optional sync bundles without calling CLI, Qwen, BGE-M3,
   reranker, MinerU, VLM, or training; this is the next server-side selector
   before any model-backed answer-quality probe; server inventory
   `phase5ib_context_inventory_server_20260702` at commit `f50ce44` found
   57 ready candidate document contexts and selected
   `outputs/docagent.db` / `c1fc1c5e040ec894` as the strongest Phase 5I-B
   default-case context with 20/26 case-context readiness
-> Phase 5I-B final-answer-quality artifact inspector implemented locally:
   `scripts/inspect_phase5i_answer_quality_artifacts.py` validates manifest
   hashes, required output presence, safety flags, metrics/report consistency,
   and empty `training_candidates_raw.jsonl` without calling models or
   promoting validation rows to training data
-> AnswerPolicy training-pack preprocessing implemented locally:
   `scripts/build_answer_policy_training_pack.py` builds audited SFT and GRPO
   training-format artifacts from train-split `DocAgentSample` JSONL input,
   writes `sft_train.jsonl`, `grpo_train.jsonl`, audits, preview, summary, and
   manifest with hashes, and blocks non-train splits or validation-like input
   paths by default; it does not start SFT/GRPO, call Qwen, use validation
   subsets for training, or claim benchmark acceptance
-> AnswerPolicy v3 small training-data trial implemented locally:
   `ModelOutputV3` uses `answer`, `supporting_refs`, `support_status`, and
   `reasoning_summary`; `EvidenceRefMap` maps temporary `E#` refs to internal
   evidence/citation metadata without making block IDs a model target;
   `scripts/build_answer_policy_v3_training_data.py` builds high-confidence
   TAT-QA and MP-DocVQA train-only v3 SFT trial artifacts and blocks
   validation-like sources by default; local TAT-QA smoke
   `answer_policy_v3_tatqa_trial_20260704` produced 200 records; server
   MP-DocVQA train smoke
   `mpdocvqa_train_v3_pipeline_splitfix2_20260704` used MinerU API on 5 train
   documents, materialized 10/10 evidence-ready samples, and produced 7
   high-confidence v3 SFT records; both kept `used_training=false` and no
   SFT/GRPO execution
-> AnswerPolicy v3 insufficient-evidence data builder implemented locally:
   `scripts/build_answer_policy_v3_insufficient_data.py` builds train-only
   TAT-QA `insufficient_confirmed` records by pairing source questions with a
   different-document decoy evidence board that does not contain the gold
   answer string, producing v3 `support_status=insufficient` targets with empty
   `supporting_refs`; local smoke
   `answer_policy_v3_tatqa_insufficient_local_smoke_20260704` produced 32
   records; server smoke
   `answer_policy_v3_insufficient_server_smoke_20260704_verify` at commit
   `00a3fa2` produced 64 insufficient records from TAT-QA train data and a
   64-record mixed pack with 19 insufficient records selected after MP-DocVQA
   shortage backfill; both kept `used_training=false`, `used_qwen=false`,
   `validation_subset_used_for_training=false`, and
   `formal_benchmark_acceptance=false`; this fills the Stage 2 negative-sample
   data-prep gap but does not start or evaluate training
-> AnswerPolicy v3 schema warmup SFT smoke real-model verified:
   `scripts/run_answer_policy_v3_sft_warmup.py` merges v3 SFT records,
   validates the `ModelOutputV3` target, and runs a tiny PEFT LoRA schema
   smoke; server run `answer_policy_v3_sft_warmup_smoke_20260704`
   at commit `e9257fd` built 80 TAT-QA train v3 records, mixed them with
   the 7 MP-DocVQA train v3 records, trained Qwen3-1.7B for 1 step on 16
   selected records, wrote adapter artifacts, and preserved
   `formal_benchmark_acceptance=false` and
   `validation_subset_used_for_training=false`; this verifies the schema
   warmup training path only, not final answer-quality improvement or GRPO
-> AnswerPolicy v3 checkpoint diagnostic real-model verified:
   `scripts/eval_answer_policy_v3_sft_checkpoint.py` loads the base model plus
   a PEFT adapter and checks v3 JSON/schema/ref behavior without starting
   training; server run `answer_policy_v3_checkpoint_eval_smoke_20260704`
   evaluated 4 warmup records with json/schema/support-status/ref legality
   rates all 1.0, positive_ref_hit_rate 1.0, answer_exact_rate 0.5, and
   `used_training=false`; this accepts checkpoint-diagnostic plumbing only,
   not model-quality improvement
-> AnswerPolicy v3 expanded training backend preference recorded:
   keep the PEFT runner as the minimal schema-smoke path, but prefer
   `ms-swift` for later full/expanded SFT experiments after an environment
   preflight and explicit approval for any package installation; GRPO remains
   gated optional and not part of the current warmup
-> AnswerPolicy v3 ms-swift SFT smoke real-model verified:
   `scripts/run_answer_policy_v3_msswift_sft.py` converts validated v3 SFT
   records into Swift message JSONL, writes the exact `swift sft` command and
   compact artifacts, and only starts training with explicit `--execute`;
   server dry-run `answer_policy_v3_msswift_dry_run_20260704` confirmed
   `ms-swift=4.2.3` and train-only v3 input availability; server execute
   smoke `answer_policy_v3_msswift_execute_smoke2_20260704` trained Qwen3-1.7B
   for 1 step on 16 v3 records with LoRA and wrote a Swift PEFT checkpoint;
   follow-up diagnostic `answer_policy_v3_msswift_checkpoint_eval_20260704`
   evaluated 4 records with json/schema/support-status/ref legality rates all
   1.0, positive_ref_hit_rate 1.0, answer_exact_rate 0.5, and kept
   `formal_benchmark_acceptance=false`; this verifies the ms-swift training
   entrypoint and checkpoint contract only, not final model quality
-> AnswerPolicy v3 Stage 2 mixed-pack short SFT real-model verified:
   `scripts/build_answer_policy_v3_mixed_sft_pack.py` builds an audited
   train-only mixed SFT pack with target ratios, shortage/backfill accounting,
   validation-like path blocking, and compact sync artifacts; server run
   `answer_policy_v3_mixed_stage2_20260704` selected 64 records from train-only
   v3 sources, with MP-DocVQA limited to 7 available records and the remaining
   quota transparently backfilled from TAT-QA; server run
   `answer_policy_v3_msswift_stage2_short_20260704` trained Qwen3-1.7B for 3
   ms-swift LoRA steps on that mixed pack; diagnostic
   `answer_policy_v3_msswift_stage2_checkpoint_eval_20260704` evaluated 8
   records with json/schema/support-status/supporting-ref legality rates all
   1.0, positive_ref_hit_rate 0.875, answer_exact_rate 0.5, and kept
   `formal_benchmark_acceptance=false`; this verifies the mixed-pack and short
   SFT execution path only, not final model quality
-> AnswerPolicy v3 prompt-limit contract repair real-model verified:
   the v3 training prompt now explicitly requires `reasoning_summary` under
   300 characters, matching `ModelOutputV3` validation; after rebuilding
   train-only TAT-QA positive records, insufficient records, and a 64-record
   mixed pack with 19 insufficient records, server run
   `answer_policy_v3_promptlimit_stage2_short_20260704_verify` at commit
   `800c6ed` trained Qwen3-1.7B for 3 ms-swift LoRA steps and checkpoint
   diagnostic restored `json_valid_rate=1.0`, `schema_valid_rate=1.0`,
   `supporting_refs_subset_rate=1.0`, with `formal_benchmark_acceptance=false`
   and `validation_subset_used_for_training=false`; answer/status metrics
   remain small-smoke diagnostics only
-> AnswerPolicy v3 MP-DocVQA train expansion real-model verified:
   server run `mpdocvqa_train_v3_expand20_20260704_verify` used MinerU API/OCR
   on 20 MP-DocVQA train documents from `parquet_train`, materialized 65/65
   evidence-ready QA samples, produced 52 high-confidence MP-DocVQA v3 SFT
   records, and built a 96-record mixed pack with selected counts
   MP-DocVQA 48, TAT-QA 38, insufficient 10 and no shortage/backfill; follow-up
   server run `answer_policy_v3_msswift_stage2_expand20_short_20260704`
   trained Qwen3-1.7B for 3 ms-swift LoRA steps on that pack and checkpoint
   diagnostic over 12 records kept `json_valid_rate=1.0`,
   `schema_valid_rate=1.0`, and `supporting_refs_subset_rate=1.0`; this
   verifies expanded train-data and short training-chain stability only, not
   final model quality or benchmark acceptance
-> AnswerPolicy v3 reward calibration implemented locally:
   `docqa_v3_reward` now hard-gates invalid v3 schema outputs and explicitly
   scores insufficient-evidence refusals, while
   `scripts/calibrate_answer_policy_v3_rewards.py` reads train-only v3 SFT
   records and writes deterministic target/negative reward-component reports
   without calling models or starting training; local smoke
   `answer_policy_v3_reward_calibration_local_smoke_20260704` calibrated 32
   train-only records, and server run
   `answer_policy_v3_reward_calibration_expand20_20260704` calibrated the
   96-record expanded mixed train pack with target_reward_min 1.0,
   negative_reward_max 0.7, invalid_schema reward 0.0, and
   `reward_calibration_status=passed`; this prepares best-of-N/DPO/GRPO
   discussion only and does not approve GRPO
-> AnswerPolicy v3 rejection-sampling artifact builder implemented locally:
   `scripts/build_answer_policy_v3_rejection_sampling_artifacts.py` ranks
   train-only v3 candidate generations with the calibrated v3 reward, writes
   `ranked_candidates.jsonl`, `selected_candidates.jsonl`,
   `preference_pairs.jsonl`, `rejection_sft_candidates.jsonl`, preview,
   summary, and manifest artifacts, and blocks validation-like inputs by
   default; local calibration-variant smoke
   `answer_policy_v3_rejection_sampling_local_calibration_smoke_20260704`
   validated artifact shape on 32 train-only records without candidate model
   generations, with all selected/pair rows marked not training-ready because
   calibration variants are synthetic; server artifact smoke
   `answer_policy_v3_rejection_sampling_expand20_calibration_20260704` at
   commit `bd80fc7` validated the same contract on the 96-record expanded
   mixed train-only pack, producing 470 synthetic calibration candidates,
   96 selected rows, 96 preference pairs, and zero training-ready
   rejection-SFT rows
-> AnswerPolicy v3 real-model candidate generation implemented locally:
   `scripts/generate_answer_policy_v3_candidates.py` loads train-only v3 SFT
   prompts, optionally loads a PEFT adapter, generates multiple
   `model_generation` candidates per record, validates v3 JSON/schema locally,
   and writes `candidates.jsonl`, preview, summary, and manifest artifacts
   without starting training; local dry-run smoke
   `answer_policy_v3_candidate_generation_local_dryrun_20260704` validated
   synthetic artifact shape and confirmed synthetic candidates cannot become
   training-ready through the rejection builder; server Qwen smoke
   `answer_policy_v3_candidate_generation_qwen_smoke_20260704` at commit
   `e01ebf4` generated 8 real Qwen candidates from 4 train-only records with
   raw_json_ok_rate 1.0 and schema_ok_rate 1.0, and follow-up ranking
   `answer_policy_v3_rejection_sampling_qwen_smoke_20260704` consumed those
   `model_generation` candidates successfully; no selected/pair rows passed
   reward thresholds in this tiny base-model smoke, so no rejection-SFT rows
   were emitted and GRPO remains unapproved
-> AnswerPolicy v3 adapter-backed rejection distillation artifact path
   real-model verified:
   server run `answer_policy_v3_candidate_generation_expand20_adapter_smoke_20260704`
   at commit `f7120c7` loaded the short expanded ms-swift LoRA adapter
   `answer_policy_v3_msswift_stage2_expand20_short_20260704`, generated
   24 adapter-backed `model_generation` candidates from 8 train-only records
   with raw_json_ok_rate 1.0 and schema_ok_rate 1.0, and follow-up ranking
   `answer_policy_v3_rejection_sampling_expand20_adapter_smoke_20260704`
   selected 2 reward-qualified rows into `rejection_sft_candidates.jsonl`;
   dry-run `answer_policy_v3_rejection_sft_msswift_dryrun_20260704`
   validated those 2 records as ms-swift-compatible input without executing
   training, with source_counts mp_docvqa:1 and tatqa:1; preference pairs did
   not meet the reward-margin threshold; a bounded follow-up server run
   `answer_policy_v3_candidate_generation_expand20_adapter24x3_20260704` at
   commit `25dc367` generated 72 adapter-backed `model_generation` candidates
   from 24 train-only records with raw_json_ok_rate 1.0 and schema_ok_rate
   1.0, and ranking
   `answer_policy_v3_rejection_sampling_expand20_adapter24x3_20260704`
   again produced only 2 training-ready rejection-SFT rows, with 22 selected
   rows below the chosen-reward threshold and zero training-ready preference
   pairs; no additional training was started, and DPO/GRPO remain unapproved;
   `--offset` support was then added to the candidate-generation and
   rejection-ranking scripts so follow-up train-only slices do not repeatedly
   sample the same prefix; server run
   `answer_policy_v3_candidate_generation_expand20_adapter_offset24x3_20260704`
   at commit `e069da0` generated 72 candidates from train records 24-47
   with raw_json_ok_rate/schema_ok_rate 0.9028, and ranking
   `answer_policy_v3_rejection_sampling_expand20_adapter_offset24x3_20260704`
   selected 11 training-ready rejection-SFT rows and zero training-ready
   preference pairs; follow-up offset slices 48-71 and 72-95 completed under
   run `answer_policy_v3_rejection_adapter_remaining_slices_20260704` at
   commit `ddab988`, generating 144 more adapter-backed candidates from
   train-only records, selecting 6 and 7 additional training-ready
   rejection-SFT rows respectively, and producing 3 total training-ready
   preference pairs across the four 24-record slices; the preference-pair
   volume remains too small for DPO/GRPO approval
-> AnswerPolicy v3 rejection-SFT distillation smoke real-model verified:
   server run `answer_policy_v3_rejection_sft_msswift_execute_smoke_20260704`
   at commit `0ff5792` trained Qwen3-1.7B for 1 ms-swift LoRA step on the
   2 train-only `rejection_sft_candidates.jsonl` rows selected by the
   adapter-backed rejection sampler, with source_counts mp_docvqa:1 and
   tatqa:1, `used_training=true`, `formal_benchmark_acceptance=false`, and
   `validation_subset_used_for_training=false`; checkpoint diagnostic
   `answer_policy_v3_rejection_sft_checkpoint_eval_20260704` evaluated those
   2 records with json_valid_rate, schema_valid_rate,
   supporting_refs_subset_rate, support_status_match_rate,
   positive_ref_hit_rate, and answer_exact_rate all 1.0; this verifies the
   rejection-SFT distillation execution path only, not final answer-quality
   improvement; follow-up server run
   `answer_policy_v3_rejection_sft_adapter_offset24x3_short_20260704` at
   commit `e069da0` trained for 2 ms-swift LoRA steps on 8 of the 11
   train-only offset-slice rejection-SFT rows, and checkpoint diagnostic
   `answer_policy_v3_rejection_sft_adapter_offset24x3_checkpoint_eval_20260704`
   evaluated 8 rows with json/schema/support-status/supporting-ref/positive-ref
   and answer-exact rates all 1.0, while keeping
   `formal_benchmark_acceptance=false` and
   `validation_subset_used_for_training=false`; merged-slice follow-up
   `answer_policy_v3_rejection_sft_merged_slices_20260704` combined the four
   train-only slices into 26 rejection-SFT records with source_counts
   mp_docvqa:18 and tatqa:8, server run
   `answer_policy_v3_rejection_sft_merged_slices_short_20260704` trained
   Qwen3-1.7B for 3 ms-swift LoRA steps on 24 selected records, and checkpoint
   diagnostic `answer_policy_v3_rejection_sft_merged_slices_checkpoint_eval_20260704`
   evaluated 16 rows with json/schema/support-status/supporting-ref/positive-ref
   and answer-exact rates all 1.0, `thinking_rate=0.0`, and safety flags
   preserved false; this remains execution-chain evidence, not final
   answer-quality acceptance
-> AnswerPolicy v3 train-only heldout diagnostic split implemented locally:
   `scripts/split_answer_policy_v3_sft_records.py` deterministically splits
   validated v3 SFT records into non-overlapping `train_sft.jsonl` and
   `heldout_eval.jsonl`, writes excluded records plus summary/manifest
   artifacts, and blocks validation-like input paths by default; server run
   `answer_policy_v3_heldout_smoke_20260704` at commit `7a0d68a` split the
   96-record expanded train-only mixed pack into 64 train, 16 heldout, and
   16 excluded records with `overlap_count=0`, trained Qwen3-1.7B for
   3 ms-swift LoRA steps on the train split, and evaluated 16 heldout records
   with json/schema/supporting-ref legality rates all 1.0, support-status
   match 0.8125, positive-ref hit 0.5625, answer-exact 0.25, and
   `thinking_rate=0.0`; this verifies separated train/heldout execution
   plumbing only, not final model quality
-> AnswerPolicy v3 refs CLI/Qwen integration real-model verified:
   `docagent_answer_v3_supporting_refs` is now an optional CLI/Qwen
   AnswerPolicy contract via `--answer-output-contract v3_refs`; the model
   outputs `supporting_refs` and `support_status`, while the system maps refs
   back to internal citations through `EvidenceRefMap`; server smoke
   `answer_policy_v3_refs_cli_smoke_retry_20260704` at commit `56b7726`
   loaded a ms-swift SFT adapter through `scripts/docagent_cli.py`, produced
   schema-valid v3 JSON with `supporting_refs=["E1"]`, and mapped it to
   citation block `c1fc1c5e040ec894_p001_b0002`; this verifies the trained
   v3 adapter can enter the actual CLI/Qwen workflow, not final answer-quality
   acceptance
-> AnswerPolicy IO candidate schema and citation allowlist implemented locally
-> Qwen/AnswerPolicy shared prompt v2 candidate-citation contract implemented locally
-> final subset AnswerPolicy baseline runner implemented locally; first real
   Qwen server smoke completed as diagnostic_only, with citation contract
   repair required before SFT candidate generation
-> AnswerPolicy baseline review gate implemented locally for full artifacts or
   compact sync bundles; it emits diagnostic training-gate recommendations only
-> AnswerPolicy SFT candidate data builder implemented locally; it requires a
   real-Qwen-marked baseline and emits candidate records only, not training
-> AnswerPolicy training-gate orchestrator implemented locally; it runs
   baseline -> review -> optional SFT candidate artifact generation in one
   server-ready command, but still does not train
-> tool-result citation allowlist/priority repair implemented locally after
   the first real Qwen smoke; server rerun improved citation_block_hit_rate
   to 1.0, while invalid raw model citation ids remain diagnostic
-> AnswerPolicy review gate invalid-citation semantics adjustment implemented
   locally; server rerun accepted the diagnostic gate and recommends larger
   real Qwen baseline/manual review before training
-> larger 40-sample real Qwen diagnostic gate completed; citation remains
   stable, answer misses triggered SFT candidate data design artifacts, but no
   training has started
-> AnswerPolicy SFT candidate review script validated on server larger-gate
   real-Qwen artifacts; recommendation remains manual review before training
-> larger-gate manual review extraction found answer misses dominated by
   wrong tool outputs; enriched manual-review rows server validation succeeded,
   and explicit simple_calculation selection is now enforced locally to avoid
   table row-label words triggering unintended calculations
-> table row/header selection repair implemented locally for larger-gate
   tool failures: multi-row headers, direct row-label priority, repeated
   Granted/Vested activity rows, section-row context, high/low date columns,
   and $000-to-million display; local 12-row replay now has 12/12 tool
   answer hits; server deterministic audit on the same 12 rows succeeded with
   12/12 tool answer hits
-> larger 40-sample real Qwen diagnostic gate rerun after table-tool repair
   completed with answer_hit_rate 0.90, citation_block_hit_rate 1.0,
   pass_rate 0.90, answer_miss 4, and SFT gate deferred; next action is a
   larger real Qwen diagnostic, not training
-> full 80-sample real Qwen diagnostic gate after table-tool repair completed
   with answer_hit_rate 0.7625, citation_block_hit_rate 1.0, pass_rate
   0.7625, answer_miss 19; parse/schema inspection found one row-level
   schema failure that was already repaired into a canonical format-valid
   output; review-only server rerun confirmed the repaired-output semantics
   and now recommends continuing Qwen evaluation before training
-> full80 answer-miss artifact-only review completed on server as
   diagnostic_only: tracked reusable review script validated against the
   real-Qwen full80 tablefix baseline artifact, found 19 answer misses, and
   bucketed them into table/calculation tool review, model extractive
   precision review, metric/granularity review, and repaired-parse answer
   miss; it does not create training data
-> generic tool-output inspection before training implemented locally; it
   reads answer_miss rows from existing AnswerPolicy baseline artifacts,
   separates tool execution/contract issues, table-selection issues,
   calculation operand/operation issues, model tool-use misses, and metric
   granularity hints, without creating training data; server validation on
   the real-Qwen full80 tablefix artifact found 12 tool-expected answer
   misses, all with successful tool execution, dominated by generic
   calculation operand/operation and table selection review
-> generic deterministic table-tool repair implemented locally for the above
   patterns: total-across-years sum, percentage increase/decrease wording,
   same-row multi-year average with currency-parentheses negatives, requested
   period/quarter/as-reported column priority, and who/name table answers;
   server deterministic TAT-QA rerun improved answer_hit_rate to 0.7667 with
   46/60 answer hits and citation_block_hit_rate 1.0; remaining failures are
   still diagnostic and do not block moving back to real Qwen evaluation
-> full80 real-Qwen diagnostic gate after generic table-tool repair improved
   answer_hit_rate/pass_rate to 0.85 with citation_block_hit_rate 1.0;
   review recommends continuing Qwen evaluation before training and skips SFT
   candidates
-> final raw PDF smoke runner implemented locally as an API-only reproducible
   smoke around `docagent_cli.py --parser mineru_api --live-api`; it checks
   raw PDF ingestion, MinerU API result artifacts, EvidenceBlock persistence,
   CLI artifact files, citations, and evidence_used without rerunning
   training, VLM, or benchmark scoring
-> raw PDF existing-MinerU-output fallback smoke completed on server:
   run_id `final_raw_pdf_existing_mineru_audit_20260630` consumed a previously
   generated real MinerU output via `mineru_existing`, passed 4/4 CLI contract
   cases, and confirmed citations/evidence_used on evidence-bearing cases;
   this is regression evidence for consuming real MinerU output
-> MinerU API secret-file support accepted: the API client and
   existing ingestion runners now keep the old `MINERU_TOKEN` terminal export
   path while also supporting `.secrets/mineru.env` / `--mineru-env-file`;
   MinerU env files may use `MINERU_TOKEN=...` or `API_TOKEN=...`, matching
   the Router LLM secret-management pattern without committing secrets
-> MinerU API file-to-answer support accepted after live server smoke:
   `--parser mineru_api --live-api` writes API output into the document cache,
   then uses the existing EvidenceBlock/Router/tool/artifact path; server run
   `final_raw_pdf_mineru_api_cli_smoke_20260630` at commit `31cdd18` used
   `.secrets/mineru.env`, live MinerU API/OCR, passed 4/4 CLI contract cases,
   and confirmed citations/evidence_used on evidence-bearing cases; API-only
   cleanup rerun `final_raw_pdf_mineru_api_api_only_cleanup_20260630` at
   commit `060ad85` again passed 4/4 cases
-> MP-DocVQA evidence materialization runner implemented locally:
   `scripts/prepare_mpdocvqa_evidence.py` maps prepared MP-DocVQA PDFs through
   MinerU API/file-to-answer ingestion into SQLite EvidenceBlocks and
   `sample_evidence_manifest.jsonl`; AnswerPolicy baseline can optionally use
   that manifest plus DB to evaluate MP-DocVQA rows with page-level citation
   checks instead of skipping them; a 2-document live MinerU API server smoke
   `mpdocvqa_evidence_api_smoke_20260630` at commit `d325800` passed with
   document_passed_count 2/2 and sample_evidence_ready_count 4/4; after
   hardened MinerU API retry/resume handling, full selected-subset server run
   `mpdocvqa_evidence_api_retry_failed_hardened_20260630` at commit
   `13b1dc1` passed with document_passed_count 10/10 and
   sample_evidence_ready_count 55/55
-> final full-workflow retriever wiring real-model verified: `docagent_cli.py`
   lets local_fact_qa explicitly use bm25/dense/hybrid/hybrid_rerank
   retrieval, records dense/reranker metadata and workflow trace in CLI
   artifacts, and keeps bm25 as the default; server run
   `final_full_workflow_hybrid_rerank_smoke_rowalign_20260630` at commit
   `b0d274f` verified rule Router main path, LLM Router trigger probe,
   LLM Query Planner, real BGE-M3 dense retrieval, real bge-reranker-v2-m3
   cross-encoder reranking, Qwen AnswerPolicy, and workflow trace
   `retrieve_evidence -> build_evidence_context -> generate_answer ->
   check_format -> check_location -> answer_repair -> finalize`; this is
   execution-chain evidence, not final answer-quality benchmark evidence
-> post-scope-rule full-chain sanity rerun
   `final_delivery_chain_sanity_after_scope_rules_20260702` at commit
   `e3b5c43` used existing MP-DocVQA EvidenceBlocks plus real LLM Router,
   LLM Query Rewriter, Qwen base AnswerPolicy, BGE-M3 dense retrieval, and
   bge-reranker-v2-m3 on 4 rows with cli_success_rate 1.0 and all four rows
   exercising Qwen/dense/reranker/query-rewriter; this preserves the current
   delivery-chain baseline after evidence metadata and scope-rule updates,
   without claiming benchmark acceptance
-> raw PDF full-model workflow baseline real-model verified: fresh server run
   `final_raw_pdf_full_workflow_api_hybrid_qwen_fresh_20260630_172350` at
   commit `8a61600` started from `--file` raw PDF input with a fresh DB,
   ingested through live MinerU API without reusing an existing document,
   used LLM Router fallback, LLM Query Planner/Rewriter, real BGE-M3 dense
   retrieval, real bge-reranker-v2-m3 reranking, Qwen base AnswerPolicy,
   and produced non-empty answer/reasoning_summary/evidence_used/citations
   plus summary/result/trace/router_plan artifacts in one CLI workflow; this
   is now the execution-chain usability baseline, not final answer-quality
   or benchmark acceptance
-> MP-DocVQA retrieval inspection implemented locally:
   `scripts/inspect_mpdocvqa_retrieval.py` reads existing AnswerPolicy
   baseline or attribution artifacts plus the MP-DocVQA evidence SQLite DB,
   then writes diagnostic retrieval buckets, gold-page rank/recall signals,
   gold-page retrievable-block coverage, preview rows, manifest, and optional
   sync bundle; it does not call Qwen, start training, create training data,
   or tune against validation examples
-> MP-DocVQA full-workflow diagnostic runner implemented locally:
   `scripts/run_mpdocvqa_full_workflow_diagnostic.py` runs selected
   MP-DocVQA evidence-manifest rows through `scripts/docagent_cli.py --doc-id`
   with `--full-model-path` and configurable `hybrid_rerank` retrieval,
   then reports CLI success, retrieved/selected/cited gold-page hits,
   answer hit, buckets, trace evidence, and sync artifacts; this compares
   the accepted CLI full-model path against the old legacy-BM25 baseline
   without creating training data or claiming benchmark acceptance; server
   diagnostic `mpdocvqa_full_workflow_hybrid_qwen_limit8_20260630` at commit
   `0fe4859` passed with cli_success_rate 1.0, 8/8 Qwen/dense/reranker use,
   retrieved_gold_page_hit_rate 0.875, citation_page_hit_rate 0.875,
   answer_hit_rate 0.5, and bucket_counts passed:4,
   answer_generation_or_metric_miss:3, retrieval_gold_page_miss:1; second
   diagnostic `mpdocvqa_full_workflow_hybrid_qwen_offset8_limit16_20260630`
   at commit `afaf8a5` passed with cli_success_rate 1.0, 15/16
   Qwen/dense/reranker use, retrieved_gold_page_hit_rate 0.4375,
   citation_page_hit_rate 0.4375, answer_hit_rate 0.375, and bucket_counts
   retrieval_gold_page_miss:8, answer_generation_or_metric_miss:4, passed:3,
   task_type_not_local_fact_qa:1
-> MP-DocVQA full-workflow comparison implemented locally:
   `scripts/compare_mpdocvqa_full_workflow_runs.py` reads existing
   full-workflow diagnostic artifacts, aggregates per-run and cross-run
   CLI/component use, retrieval/citation/answer hit rates, failure buckets,
   preview rows, manifest, and optional sync bundle; server artifact-only
   validation `mpdocvqa_full_workflow_compare_24rows_20260701` at commit
   `ece6221` passed targeted tests and aggregated 24 rows with
   cli_success_rate 1.0, local_fact_qa_count 23, Qwen/dense/reranker use
   23/23, retrieved_gold_page_hit_rate 0.5833, citation_page_hit_rate
   0.5833, answer_hit_rate 0.4167, and bucket_counts
   retrieval_gold_page_miss:9, answer_generation_or_metric_miss:7, passed:7,
   task_type_not_local_fact_qa:1; it does not call Qwen, start training,
   create training data, or tune against validation examples
-> MP-DocVQA query/block granularity inspection implemented locally:
   `scripts/inspect_mpdocvqa_query_block_granularity.py` reads existing
   comparison/full-workflow rows plus the MP-DocVQA EvidenceBlock SQLite DB
   and separates retrieval misses into evidence mapping, gold-page OCR/text,
   query-answer bridge, and retriever/block scoring buckets without model
   calls or validation-derived training data; server artifact-only validation
   `mpdocvqa_query_block_granularity_24rows_20260701` at commit `bd64f64`
   passed targeted tests and found 9 retrieval misses, with 8
   gold_page_answer_text_not_found and 1 gold_page_without_retrievable_blocks,
   so the next diagnostic is OCR/page alignment before retrieval changes
-> MP-DocVQA OCR/page alignment inspection real-model verified:
   `scripts/inspect_mpdocvqa_ocr_page_alignment.py` reads the query/block
   inspection rows plus the MP-DocVQA EvidenceBlock SQLite DB and checks
   exact gold pages, gold page +/-1, retrieved pages, and all document pages
   for answer text; server artifact-only validation
   `mpdocvqa_ocr_page_alignment_24rows_20260701` at commit `634a7ef`
   inspected 9 retrieval misses and found 5 answers on gold_page-1, 1
   elsewhere in the document, 2 not found in document text, and 1 gold page
   without retrievable blocks; this points to page-index alignment before
   retrieval changes and does not call models, train, or tune against
   validation examples
-> MP-DocVQA page-index alignment inspection implemented locally:
   `scripts/inspect_mpdocvqa_page_index_alignment.py` cross-checks OCR/page
   alignment rows against prepared `qa.jsonl`, `sample_manifest.jsonl`, the
   evidence materialization manifest, document window manifests, and the
   EvidenceBlock DB; it treats MP-DocVQA citations as current input PDF pages
   1..N, preserves source page ids such as `fpbw0217_p17` only for traceability,
   and requires manifest/evidence page disagreement before recommending page
   mapping repair; adjacent-page answer-text hits now lead to manual/OCR review
   before retrieval or training changes; server validation
   `mpdocvqa_page_index_alignment_semantic_24rows_20260701` at commit
   `b377d1c` passed targeted tests, confirmed answer_page_idx/manifest/evidence
   page consistency rates of 1.0, and kept the next action at manual/OCR
   answer-text-hit review rather than page-index normalization
-> MP-DocVQA page-alignment manual review extraction implemented locally:
   `scripts/extract_mpdocvqa_page_alignment_review.py` reads the page-index
   alignment artifact, prepared document manifests, page image paths, and the
   EvidenceBlock DB to emit compact `manual_review.jsonl`/`manual_review.md`
   rows with current-window page numbers, source page ids, image paths, PDF
   paths, and OCR previews for human inspection; server artifact-only
   validation `mpdocvqa_page_alignment_manual_review_24rows_20260701` at
   commit `47f0997` passed targeted tests and produced 9 review rows:
   5 adjacent-page image comparisons, 2 OCR/answer-alias checks, 1
   annotation/duplicate-answer check, and 1 MinerU page-block materialization
   check; it does not call models, create training data, change gold pages,
   or tune retrieval
-> continue to stop before VLM, local_fact_qa answer-quality fixes,
   training, full GRPO E2E, MP-DocVQA/TAT-QA benchmark evaluation,
   and final Qwen answer-quality acceptance
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
Phase 5A architecture audit and contracts -> accepted
Phase 5B deterministic P0 document tools -> accepted
Phase 5C Router / Planner -> accepted
Phase 5D local_fact_qa wrapper -> accepted
Phase 5D-S local_fact_qa smoke runner -> accepted
Phase 5D-S server real-model smoke -> accepted
Phase 5F-1 Unified CLI MVP -> accepted
Phase 5F-1 server CLI smoke -> accepted
Phase 5F-2 file-to-answer ingestion integration -> accepted
Phase 5F-2 server file-to-answer smoke -> accepted
Phase 5F-3 MinerU-backed file-to-answer implementation -> accepted
Phase 5F-3 server smoke -> accepted
Phase 5G CLI regression baseline -> accepted
Phase 5G server regression -> accepted
Phase 5C-2 LLM-assisted Router fallback -> accepted
Phase 5C-3 Query Planning + Multi-Query Retrieval -> accepted
Phase 5H Full Workflow Validation Baseline -> accepted
Phase 5I old-semantics server benchmark -> benchmark_evaluated
Phase 5I-A Pre-LLM Evidence Readiness Benchmark runner -> accepted
Phase 5I-A corrected-semantics server benchmark -> accepted
Phase 5I-B Full Model-enhanced QA Path -> accepted
Phase 5I-B Final Answer Quality Benchmark artifact contract -> implemented
Phase 5I-B Final Answer Quality Benchmark execution -> not_started
Phase 5E Document Summary MVP -> implemented
Phase 5E-A Document Summary Acceptance Pack -> implemented
Phase 5 structured_extraction deterministic CLI -> implemented
Phase 5 final output contract cleanup -> implemented
Phase 5 table_lookup deterministic CLI -> implemented
Phase 5 simple_calculation deterministic CLI -> implemented
Phase 5 final evaluation subset preparation -> implemented
Phase 5 final evaluation local subset diagnostic runner -> implemented
Phase 5 final delivery CLI guide -> implemented
Phase 5 final delivery report -> implemented
Phase 5 final delivery readiness check -> implemented
Phase 5 final delivery benchmark gate -> accepted
Phase 5 AnswerPolicy IO candidate schema / citation allowlist -> implemented
Phase 5 AnswerPolicy prompt v2 candidate citation contract -> implemented
Phase 5 final AnswerPolicy baseline runner -> implemented
Phase 5 AnswerPolicy baseline review gate -> implemented
Phase 5 AnswerPolicy SFT candidate data builder -> implemented
Phase 5 AnswerPolicy training-gate orchestrator -> implemented
Phase 5 final AnswerPolicy Qwen smoke -> real_model_verified
Phase 5 tool-result citation allowlist repair -> implemented
Phase 5 AnswerPolicy review gate invalid-citation semantics -> real_model_verified
Phase 5 larger AnswerPolicy Qwen diagnostic gate -> real_model_verified
Phase 5 AnswerPolicy SFT candidate artifact generation -> implemented
Phase 5 AnswerPolicy SFT candidate review -> real_model_verified
Phase 5 table tool row/header selection repair -> accepted
Phase 5 larger AnswerPolicy Qwen tablefix diagnostic gate -> real_model_verified
Phase 5 full80 AnswerPolicy Qwen tablefix diagnostic gate -> real_model_verified
Phase 5 AnswerPolicy review gate repaired parse/schema semantics -> real_model_verified
Phase 5 AnswerPolicy answer-miss artifact review -> real_model_verified
Phase 5 AnswerPolicy generic tool-output pretraining inspection -> real_model_verified
Phase 5 generic table-tool operation/column repair -> accepted
Phase 5 full80 AnswerPolicy Qwen generic tablefix diagnostic gate -> real_model_verified
Phase 5 final raw PDF MinerU API smoke runner -> implemented
Phase 5 final raw PDF existing MinerU output fallback smoke -> real_model_verified
Phase 5 final raw PDF MinerU API server smoke -> accepted
Phase 5 MinerU API secret-file support -> accepted
Phase 5 MinerU API file-to-answer CLI support -> accepted
Phase 5 MP-DocVQA evidence materialization runner -> accepted
Phase 5 AnswerPolicy MP-DocVQA evidence-aware baseline path -> implemented
Phase 5 full-workflow real retriever CLI wiring -> real_model_verified
Phase 5 raw PDF full-model workflow baseline -> real_model_verified
Phase 5 MP-DocVQA retrieval inspection -> implemented
Phase 5 MP-DocVQA full-workflow diagnostic runner -> real_model_verified
Phase 5 MP-DocVQA full-workflow comparison -> real_model_verified
Phase 5 MP-DocVQA query/block granularity inspection -> real_model_verified
Phase 5 MP-DocVQA OCR/page alignment inspection -> real_model_verified
Phase 5 MP-DocVQA page-index alignment inspection -> real_model_verified
Phase 5 MP-DocVQA page-alignment manual review extraction -> real_model_verified
Phase 5F full CLI acceptance -> accepted
CDC -> not_started
MVP CLI / trace integration -> accepted
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
status = accepted
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

Phase 5D-S accepted server smoke:

```text
branch = codex/phase5d-local-fact-qa-smoke
runner_commit = 53b9d1000ce8389c9dd1a574072f61bdb6407eb7
db_path = outputs/docagent.db
doc_id = c1fc1c5e040ec894
dry_run_run_id = phase5d_local_fact_qa_20260624_155343_e1eac210
real_model_run_id = phase5d_local_fact_qa_20260624_155345_4076f226
real_model_summary = outputs/smoke/phase5d_local_fact_qa/phase5d_local_fact_qa_20260624_155345_4076f226/summary.json
real_model_results = outputs/smoke/phase5d_local_fact_qa/phase5d_local_fact_qa_20260624_155345_4076f226/results.jsonl
real_model_preview = outputs/smoke/phase5d_local_fact_qa/phase5d_local_fact_qa_20260624_155345_4076f226/preview.json
status = success
question_count = 3
completed_count = 3
failed_count = 0
used_dry_run = false
used_real_workflow = true
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
warning = evidence_packing_option_deferred_to_workflow
acceptance_boundary = execution stability, not benchmark-level answer quality
```

Phase 5F-1 accepted unified CLI MVP:

```text
branch = codex/phase5f1-unified-cli-mvp
commit = b7e92c89908ce57517f145e18cd6ca1b702a300e
entrypoint = scripts/docagent_cli.py
supports_doc_id_question = true
supports_list_documents = true
supports_file_question_contract = true
file_ingestion_status = partial_reuse_or_structured_unavailable
file_reuse = existing SQLite document can be reused by source file SHA
file_unavailable_error = file_ingestion_unavailable
router_used = true
deterministic_tools_used = true
local_fact_qa_used = true
document_summary_at_acceptance_time = not_started
table_lookup_at_acceptance_time = not_started
simple_calculation_at_acceptance_time = not_started
llm_router_fallback_at_acceptance_time = not_started
current_document_summary = implemented
current_table_lookup = implemented
current_simple_calculation = implemented
```

Phase 5F-1 accepted server CLI smoke:

```text
db_path = outputs/docagent.db
doc_id = c1fc1c5e040ec894
list_documents_run_id = docagent_cli_20260625_035337_52161dae
list_documents_status = success
list_documents_document_count = 2
document_statistics_run_id = docagent_cli_20260625_035423_8cea1735
document_statistics_status = success
document_statistics_task_type = document_statistics
document_statistics_tools_used = count_pages
document_statistics_answer = The document contains 5 pages.
page_lookup_run_id = docagent_cli_20260625_035527_52de8e1f
page_lookup_status = success
page_lookup_task_type = page_lookup
page_lookup_tools_used = get_page_text
page_lookup_citations_count = 1
local_fact_qa_dry_run_id = docagent_cli_20260625_035552_54cc8822
local_fact_qa_dry_run_status = success
local_fact_qa_dry_run_warning = dry_run_no_answer_generated
local_fact_qa_real_run_id = docagent_cli_20260625_035621_145b69a9
local_fact_qa_real_status = success
local_fact_qa_real_tool_run_id = 341437e6-7976-4a2f-a7b5-2dac762960d0
file_missing_run_id = docagent_cli_20260625_035702_766dcb4a
file_missing_status = error
file_missing_error = file_not_found
artifact_root = outputs/cli_smoke
acceptance_boundary = execution stability, not benchmark-level answer quality
```

Known Phase 5F-1 limitations:

```text
--file + --question is partial for non-text inputs: CLI contract and
existing-file SHA reuse exist, and Phase 5F-2 adds new .txt ingestion, but
new PDF/MinerU ingestion through docagent_cli remains not_started.
local_fact_qa real workflow executed successfully, but answer quality is
unstable. The server date question returned an irrelevant evidence text prefix
instead of a date.
Page metadata consistency needs audit: list-documents reports page_count = 5
for doc_id c1fc1c5e040ec894 while local_fact_qa citations include page 24.
This may reflect a documents.page_count vs evidence block page-number mismatch
or source/page-window metadata semantics.
```

Phase 5F-2 implemented file-to-answer ingestion integration:

```text
branch = codex/phase5f2-file-ingestion-cli
entrypoint = scripts/docagent_cli.py
parser_backend = docagent/parser/text_backend.py
supports_new_lightweight_file_ingestion = true
supported_new_file_type = .txt
ingestion_service_reused = DocumentIngestionService
document_registry_reused = DocumentRegistry
sqlite_repository_reused = DocumentRepository
supports_sha256_reuse = true
source_was_ingested_returned = true
source_reused_existing_returned = true
generated_or_reused_doc_id_returned = true
summary_records_ingestion_status = true
summary_records_reused_existing_document = true
pdf_without_cli_backend = parser_backend_unavailable
unsupported_extension_error = unsupported_file_type
file_not_found_error = file_not_found
page_metadata_inconsistent_warning = implemented
document_summary_at_acceptance_time = not_started
table_lookup_at_acceptance_time = not_started
simple_calculation_at_acceptance_time = not_started
llm_router_fallback_at_acceptance_time = not_started
current_document_summary = implemented
current_table_lookup = implemented
current_simple_calculation = implemented
```

Phase 5F-2 accepted server file-to-answer smoke:

```text
branch = codex/phase5f2-file-ingestion-cli
implementation_commit = 0c9d0842d7a9ac3d949f3fa990cb91dd0ab4c092
db_path = outputs/docagent_phase5f2_smoke.db
doc_id = b108d4d188313393
source_file = /tmp/docagent_phase5f2_smoke.txt
stats_log = outputs/logs/phase5f2_file_stats.json
stats_run_id = docagent_cli_20260625_071021_e8424977
stats_status = success
stats_task_type = document_statistics
stats_tools_used = count_pages
stats_answer = The document contains 1 pages.
stats_was_ingested = true
stats_reused_existing = false
stats_ingestion_status = parsed
stats_page_count = 1
stats_block_count = 1
stats_index_status = not_started
stats_structure_quality = passed
fact_dry_run_log = outputs/logs/phase5f2_file_fact_dry_run.json
fact_dry_run_id = docagent_cli_20260625_071021_4e422db6
fact_status = success
fact_task_type = local_fact_qa
fact_tools_used = local_fact_qa
fact_was_ingested = false
fact_reused_existing = true
fact_warning = dry_run_no_answer_generated
artifact_root = outputs/cli_smoke
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
acceptance_boundary = lightweight .txt execution stability, not benchmark answer quality
```

Known Phase 5F-2 limitations:

```text
Server smoke validates lightweight UTF-8 .txt file-to-answer execution
stability, not benchmark answer quality.
Current accepted file ingestion support covers UTF-8 .txt through
TextParserBackend.
At Phase 5F-2 acceptance time, PDF/MinerU-backed file-to-answer through
docagent_cli was not yet accepted; Phase 5F-3 later accepted existing MinerU
output-backed execution.
local_fact_qa answer quality remains a separate known limitation.
Dense index is not built in the lightweight smoke; index_status may remain
not_started.
At Phase 5F-2 acceptance time, Phase 5E document_summary remained not_started.
Phase 5E was implemented later; Phase 5C-2 LLM-assisted Router fallback and
Phase 5G server regression were also accepted later.
```

Phase 5F-3 accepted MinerU/parser-backed file-to-answer smoke:

```text
branch = codex/phase5f3-mineru-file-cli-smoke
implementation_commit = 3eaf488cd7870af2e64dcd74f0f807edd8a1cb01
entrypoint = scripts/docagent_cli.py
parser_backend = docagent/parser/mineru_backend.py
supported_parser_mode = mineru_existing / parse_existing
legacy_optional_parser_mode = local MinerU CLI removed from final delivery;
  use mineru_api or mineru_existing
existing_mineru_output_arg = --mineru-output-dir / --mineru-output
server_status = success
tested_file = data/real_documents/globocan_africa_2022/source/original.pdf
tested_mineru_output = data/real_documents/globocan_africa_2022/mineru_raw
doc_id = fe3465edd3da60d2
stats_artifact = outputs/logs/phase5f3_file_stats.json
stats_status = success
stats_question = How many pages are in this document?
stats_task_type = document_statistics
stats_answer = The document contains 2 pages.
stats_tools_used = count_pages
stats_was_ingested = true
stats_reused_existing = false
stats_ingestion_status = parsed
stats_parser = mineru_existing
stats_parser_mode = parse_existing
stats_page_count = 2
stats_block_count = 57
stats_block_type_counts = image:6, table:5, text:46
stats_structure_quality = passed_with_warnings
stats_metadata_consistency = ok
page_lookup_artifact = outputs/logs/phase5f3_file_page_lookup.json
page_lookup_status = success
page_lookup_question = Show the text from page 1.
page_lookup_task_type = page_lookup
page_lookup_tools_used = get_page_text
page_lookup_was_ingested = false
page_lookup_reused_existing = true
page_lookup_ingestion_status = reused_existing
page_lookup_metadata_consistency = ok
fact_dry_run_artifact = outputs/logs/phase5f3_file_fact_dry_run.json
fact_dry_run_status = success
fact_dry_run_question = What is this document about?
fact_dry_run_task_type = local_fact_qa
fact_dry_run_router_task_type = document_summary
fact_dry_run_tools_used = local_fact_qa
fact_dry_run_was_ingested = false
fact_dry_run_reused_existing = true
fact_dry_run_ingestion_status = reused_existing
fact_dry_run_metadata_consistency = ok
fact_dry_run_warnings = file_reused_existing_doc_id, tool_unavailable, fallback_to_local_fact_qa, router_plan_task_type_not_local_fact_qa, dry_run_no_answer_generated
artifact_root = outputs/cli_smoke
metadata_consistency_fields = documents.page_count, page_documents count, max evidence page, max citation page
metadata_consistency_warning = page_metadata_inconsistent
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
acceptance_boundary = existing MinerU output-backed execution smoke, not online MinerU OCR execution or benchmark answer quality
```

Known Phase 5F-3 limitations:

```text
Phase 5F-3 accepts existing MinerU output-backed file-to-answer execution.
At Phase 5F-3 acceptance time, online MinerU OCR/parser execution from raw PDF
was still a later task. It is now covered by the accepted MinerU API raw PDF
smoke in the current Phase 5 final-delivery track.
Router correctly classifies "What is this document about?" as document_summary,
but at Phase 5F-3 acceptance time Phase 5E document_summary was not
implemented, so CLI fell back to local_fact_qa dry-run. This did not block
that execution-smoke acceptance.
local_fact_qa answer quality is not benchmark-validated by this smoke.
The GLOBOCAN sample structure_quality is passed_with_warnings.
Phase 5E document_summary was implemented later. Phase 5C-2 LLM-assisted
Router fallback and Phase 5G server regression were also accepted later.
```

Phase 5H accepted full workflow validation baseline:

```text
branch = codex/phase5h-full-workflow-validation-baseline
entrypoint = scripts/run_phase5h_full_workflow_smoke.py
default_doc_id = c1fc1c5e040ec894
default_output_root = outputs/smoke/phase5h_full_workflow
default_mode = non_dry_run
case_count = 15
status = accepted
server_smoke = accepted
server_smoke_run_id = phase5h_full_workflow_20260627_102757_80a9b5bf
server_smoke_status = success
server_smoke_passed_count = 15
server_smoke_failed_count = 0
server_smoke_non_dry_run_cases = 15
server_smoke_json_valid_count = 15
server_smoke_artifact_write_count = 15
server_smoke_used_external_api = true
server_smoke_used_vlm = false
server_smoke_used_training = false
server_smoke_used_full_e2e = false
server_smoke_artifact_dir = /root/autodl-tmp/docagent/outputs/smoke/phase5h_full_workflow/phase5h_full_workflow_20260627_102757_80a9b5bf
```

Phase 5H validates the existing chain:

```text
user_request -> CLI --question -> Router -> Query Planner -> multi-query
retrieval -> local_fact_qa / deterministic tool / structured unsupported
boundary -> answer, citations, metadata, and artifacts
```

The CLI field is still named `question`, but Phase 5H treats it semantically
as `user_request`. It can be an interrogative question, imperative request,
declarative request, extraction task, calculation intent, summary request,
Chinese request, or ambiguous short request.

Calculation-intent cases are retrieval plus unsupported-boundary validation
only. They do not mean `table_lookup` or `simple_calculation` is implemented.

Phase 5H validates full workflow execution stability, not answer quality.
Phase 5I-A now defines the current benchmark as pre-LLM evidence readiness.
The old-semantics server benchmark has been reinterpreted, and the
corrected-semantics Phase 5I-A server benchmark is accepted with
`evidence_readiness_status=baseline_has_failures`. Final answer generation is
not evaluated in this stage. document_summary, table_lookup/simple_calculation,
online MinerU full parsing, VLM, training, final answer quality benchmarking,
and full GRPO E2E remain not_started or not executed as applicable.

Phase 5I-A accepted evidence-readiness benchmark:

```text
branch = codex/phase5i-answer-quality-golden-benchmark
accepted_commit = 0d45e389f098b3cfb72b289a2be8b3ce6aa4770c
runner = scripts/run_phase5i_answer_quality_benchmark.py
default_doc_id = c1fc1c5e040ec894
default_output_root = outputs/benchmark/phase5i_answer_quality/<run_id>/
default_mode = non_dry_run
evaluation_scope = pre_llm_evidence_readiness
final_answer_generation_enabled = false
final_answer_quality_evaluated = false
case_count = 26
old_semantics_server_benchmark = benchmark_evaluated
corrected_semantics_server_benchmark = accepted
server_execution_status = success
evidence_readiness_status = baseline_has_failures
run_id = phase5i_answer_quality_20260628_024037_e6ccd282
passed_count = 16
failed_count = 10
evidence_ready_count = 16
evidence_readiness_pass_count = 16
task_type_accuracy = 0.7692
failure_stage_distribution = evidence_readiness:4, router:6
failure_reason_distribution = evidence_keyword_missing:1,
  insufficient_evidence_signal_missing:3,
  task_type_mismatch:local_fact_qa!=document_statistics:1,
  task_type_mismatch:local_fact_qa!=document_summary:3,
  task_type_mismatch:local_fact_qa!=table_lookup_or_calculation:2,
  unsupported_boundary_missing:5
status = accepted
```

Phase 5I-A server preflight verified the expected commit, database, router LLM
secret file, benchmark script, and fixed document id. The benchmark summary and
manual review artifacts were readable at:

```text
outputs/benchmark/phase5i_answer_quality/phase5i_answer_quality_20260628_024037_e6ccd282/phase5i_summary.json
outputs/benchmark/phase5i_answer_quality/phase5i_answer_quality_20260628_024037_e6ccd282/manual_review.md
```

`manual_review.md` confirms `evaluation_scope=pre_llm_evidence_readiness`,
`final_answer_generation_enabled=false`,
`final_answer_quality_evaluated=false`, and that evidence-found cases with
missing answer keywords are downstream answer-generation review items, not
Phase 5I-A hard failures.

Phase 5I-A evaluates the accepted Phase 5H full workflow as a black box:

```text
user_request -> CLI --question -> Router -> Query Planner -> multi-query
retrieval -> local_fact_qa / deterministic tool / structured unsupported
boundary -> evidence package, citations, metadata, and artifacts
```

Phase 5I writes:

```text
phase5i_cases.jsonl
phase5i_results.jsonl
phase5i_summary.json
preview.json
manual_review.md
```

The lightweight rules check task_type, final_queries, evidence keywords,
citation pages, structured unsupported boundaries, insufficient-evidence
signals, CLI success, artifact writing, downstream-required flags, and
failure-stage attribution. `answer_keyword_hit` is informational by default and
does not cause hard failure unless `--evaluate-final-answer` is explicitly
enabled. Cases with evidence found but final answer generation not evaluated
are marked for manual review. Phase 5I-A does not implement document_summary,
table_lookup, simple_calculation, local_fact_qa answer fixes, Router task
classification changes, AnswerPolicy changes, VLM, training, final answer
quality benchmarking, or full GRPO E2E.

Phase 5I-B accepted full-model-path server validation:

```text
branch = phase5/phase5i-b-full-model-qa-path
accepted_commit = f83269f
resource_preflight = success
full_path_smoke_command = phase5i_b_step5_sync_and_rerun_cross_lingual_smoke
full_path_smoke_run_id = phase5i_b_full_path_smoke_5case_after_cross_lingual_retry
full_path_smoke_status = success
full_path_smoke_cases = 5
full_path_smoke_passed = 4
full_path_smoke_failed = 1
full_path_smoke_failure = ambiguous_short_date:evidence_keyword_missing
used_external_api = true
used_llm_query_rewriter = true
used_qwen_answer_policy = true
answer_policy_mode = base
trace_run_id_count = 4
same_language_probe_command = phase5i_b_step6_same_language_router_probe
same_language_probe_status = success
same_language_core_failed_count = 0
ambiguous_short_date_failed = true
router_probe_used_llm_router_count = 2
```

Phase 5I-B acceptance means the Phase 3/4/5 capabilities can enter one real
QA path with LLM planning enabled and local/server Qwen answer generation
available. The accepted boundary is path validation and artifact tracing, not
final answer quality. `ambiguous_short_date` remains a conservative diagnostic
evidence-readiness failure, not a per-sample repair target.

Phase 5 structured_extraction deterministic CLI support is implemented locally:

```text
module = docagent/tools/structured_extraction.py
cli = scripts/docagent_cli.py
supported_tools = extract_all_dates, extract_all_tables, extract_all_images,
  list_sections, document_outline, structured_extract
validation = tests/test_phase5f_cli.py and tests/test_phase5g_cli_regression.py
boundary = persisted-evidence structured scans only; table_lookup and
  simple_calculation are separate deterministic local tools; no VLM,
  answer-quality repair, or training
```

Phase 5F full CLI acceptance is accepted:

```text
runner = scripts/run_phase5f_full_cli_acceptance.py
local_run_id = phase5f_full_cli_20260629_054248_59c59b05
local_status = success
server_branch = phase5/phase5f-full-cli-acceptance
server_head = 42ee83d
server_run_id = phase5f_full_cli_20260629_055323_69679174
server_status = success
acceptance_status = accepted
case_count = 11
completed_count = 10
unsupported_count = 1
required_task_types = document_statistics, page_lookup, local_fact_qa,
  document_summary, structured_extraction, table_lookup_or_calculation
artifact_checked_count = 10
artifact_pass_count = 10
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
final_answer_quality_evaluated = false
server_artifacts = outputs/acceptance/phase5f_full_cli_server/phase5f_full_cli_20260629_055323_69679174/acceptance_result.json,
  acceptance_summary.md, artifact_checks.jsonl, regression_summary.json,
  regression_results.jsonl
boundary = full CLI entrypoint and artifact contract only; table_lookup and
  simple_calculation are implemented later as deterministic local tools, but
  no VLM, online MinerU OCR acceptance, training, full GRPO E2E, or final
  answer quality acceptance. MVP CLI / trace integration acceptance
  covers CLI trace artifact writing, not a new SQLite trace replay benchmark.
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

Phase 5E Document Summary MVP local validation:

```text
resource_boundary = local_only
document_summary_tool = implemented
cli_dispatch = implemented
acceptance_pack = implemented
artifact_outputs = result.json, summary.json, router_plan.json, trace.json
acceptance_report = outputs/phase5e_document_summary_acceptance/acceptance_report.json
used_external_api = false
used_llm_answer_generation = false
used_vlm = false
used_training = false
used_grpo = false
used_table_lookup = false
used_simple_calculation = false
used_online_mineru_ocr = false
final_answer_quality_evaluated = false
server_smoke = not_started
```

Validation commands:

```text
python scripts/run_phase5e_document_summary_acceptance.py --output-dir outputs/phase5e_document_summary_acceptance
python -m pytest tests/test_phase5e_document_summary_acceptance.py -q
python -m pytest tests/test_phase5e_document_summary_tool.py -q
python -m pytest tests/test_phase5e_document_summary_cli.py -q
python -m pytest tests/test_phase5f_cli.py tests/test_phase5_document_tools.py tests/test_phase5_router.py -q
python -m pytest tests/test_phase5g_cli_regression.py -q
python -m pytest tests/test_phase5f_full_cli_acceptance.py -q
python scripts/run_phase5f_full_cli_acceptance.py --db-path outputs/docagent.db --doc-id fe3465edd3da60d2 --output-dir outputs/acceptance/phase5f_full_cli_local --timeout-seconds 180
python -m pytest tests/test_phase5f_file_ingestion_cli.py tests/test_phase5f_mineru_file_cli.py -q
$files = Get-ChildItem -LiteralPath 'D:\Projects\docagent\tests' -Filter 'test_phase5*.py' | ForEach-Object { $_.FullName }; python -m pytest @files -q
python -m pytest tests/test_prepare_final_eval_subset.py -q
python scripts/prepare_final_eval_subset.py --dataset all --tatqa-limit 80 --mpdocvqa-target-qa-count 50 --mpdocvqa-min-qa-count 30 --mpdocvqa-max-qa-count 70 --overwrite
python -m pytest tests/test_run_final_eval_subset.py -q
python scripts/run_final_eval_subset.py --dataset all --max-samples 10 --run-id local_subset_probe_after_fix --output-dir outputs/final_eval/local_subset_diagnostic
```

Final-evaluation subset preparation local smoke:

```text
resource_boundary = local_only
script = scripts/prepare_final_eval_subset.py
tatqa_input = data/benchmark/tatqa/tatqa_dataset_dev.json
tatqa_output = outputs/final_eval/tatqa_dev_subset
tatqa_selected_sample_count = 80
tatqa_bucket_distribution = table_arithmetic:20, table_lookup:20,
  table_text:20, text:20
mpdocvqa_input = data/benchmark/mp_docvqa/val/val-00001-of-00029.parquet,
  data/benchmark/mp_docvqa/val/val-00002-of-00029.parquet
mpdocvqa_output = outputs/final_eval/mpdocvqa_val_subset
mpdocvqa_selected_window_count = 10
mpdocvqa_selected_sample_count = 55
mpdocvqa_conflicting_window_count = 0
status = implemented
benchmark_evaluation_status = not_started
used_external_api = false
used_vlm = false
used_training = false
used_online_mineru_ocr = false
used_qwen = false
```

Final-evaluation local subset diagnostic runner:

```text
resource_boundary = local_only
script = scripts/run_final_eval_subset.py
test = tests/test_run_final_eval_subset.py
local_probe_run_id = local_subset_full_diagnostic_report
local_probe_case_count = 135
local_probe_passed_count = 85
local_probe_failed_count = 50
local_probe_pass_rate = 0.6296
local_probe_tool_executed_count = 60
local_probe_tool_success_count = 37
local_probe_answer_hit_count = 10
local_probe_answer_hit_rate = 0.1667
local_probe_numeric_accuracy_count = 4
local_probe_numeric_accuracy_rate = 0.2
local_probe_citation_block_hit_count = 60
local_probe_citation_block_hit_rate = 1.0
local_probe_requires_model_answer_count = 75
local_probe_requires_mineru_or_retrieval_count = 55
local_probe_failure_stage_distribution = tool_execution:23, answer_quality:27
local_probe_failure_reason_distribution = table_lookup_unsupported:23,
  answer_miss:50
local_probe_summary_markdown_path = outputs/final_eval/local_subset_diagnostic/local_subset_full_diagnostic_report/summary.md
status = implemented
quality_status = diagnostic_only
benchmark_evaluation_status = not_started
used_external_api = false
used_vlm = false
used_training = false
used_online_mineru_ocr = false
used_qwen = false
```

Final-delivery CLI guide:

```text
resource_boundary = local_only
guide = docs/FINAL_DELIVERY_CLI.md
readme_entry = README.md
readiness_check = scripts/check_final_delivery_readiness.py
pm_handoff_docs = deprecated_not_updated
dataset_policy_update = docs/DATASETS.md
status = implemented
readiness_check_status = implemented
readiness_check_scope = required files, CLI options, output fields,
  citation/evidence location fields, documentation boundaries, deprecated PM
  handoff cleanup
benchmark_evaluation_status = not_started
used_external_api = false
used_vlm = false
used_training = false
used_online_mineru_ocr = false
used_qwen = false
```

AnswerPolicy IO candidate schema and citation allowlist:

```text
resource_boundary = local_only
module = docagent/workflow/answer_contract.py
prompt = docagent/workflow/prompts.py
parser = docagent/models/output_parser.py
adapter = docagent/workflow/output_adapter.py
workflow = docagent/workflow/graph.py
tool_surface = docagent/tools/local_fact_qa.py
training_data_builders = scripts/build_sft_dataset.py,
  scripts/build_grpo_dataset.py, scripts/build_grpo_from_sft_dataset.py
reward_eval_compatibility = docagent/rewards/combined.py,
  docagent/rewards/format_reward.py, scripts/eval_sft_checkpoint.py
supported_model_outputs = legacy answer/evidence_location/evidence/reason,
  candidate answer/reasoning_summary/citation_block_ids/evidence_used
local_behavior = filters model-selected citation block ids to the citation
  allowlist, records invalid ids in citation_validation, and now includes
  tool-result citation blocks as preferred sources when deterministic table or
  visual tools return citations; shared prompt version requests candidate
  citations directly from Qwen-style AnswerPolicy output
status = implemented
benchmark_evaluation_status = not_started
used_external_api = false
used_vlm = false
used_training = false
used_online_mineru_ocr = false
used_qwen = false
server_qwen_smoke = real_model_verified
server_qwen_smoke_run_id = answer_policy_training_gate_qwen_smoke_20260629
server_qwen_smoke_result = success, diagnostic_only, answer_hit_rate 0.75,
  citation_block_hit_rate 0.75, recommendation
  citation_contract_repair_before_training
server_rerun_after_citation_repair = success, diagnostic_only,
  run_id answer_policy_training_gate_qwen_tool_citation_fix_20260629,
  answer_hit_rate 0.75, citation_block_hit_rate 1.0, pass_rate 0.75,
  no citation_block_miss; review still recommended
  citation_contract_repair_before_training because invalid raw model citation
  ids were treated as a hard pre-training blocker
review_gate_invalid_citation_semantics = implemented locally; server rerun
  success, run_id answer_policy_review_gate_filtered_invalid_20260629,
  recommendation continue_qwen_eval_before_training, sft_gate defer,
  invalid_citation_id_count_in_rows 3, failure_reason answer_miss:3
```

Final AnswerPolicy baseline runner:

```text
resource_boundary = server_required_for_qwen_acceptance
script = scripts/run_final_answer_policy_baseline.py
test = tests/test_run_final_answer_policy_baseline.py
review_script = scripts/review_answer_policy_baseline.py
review_test = tests/test_review_answer_policy_baseline.py
sft_candidate_script = scripts/build_answer_policy_sft_candidates.py
sft_candidate_test = tests/test_build_answer_policy_sft_candidates.py
orchestrator_script = scripts/run_final_answer_policy_training_gate.py
orchestrator_test = tests/test_run_final_answer_policy_training_gate.py
input_scope = prepared final-eval subset artifacts under outputs/final_eval/
local_smoke = heuristic/fake-policy only; diagnostic_not_formal_benchmark
server_target = Qwen base prompt-v2 baseline over prepared TAT-QA
  local_fact_qa evidence cases plus table_lookup/simple_calculation tool
  result cases, with MP-DocVQA manifest cases explicitly skipped until raw
  PDF -> MinerU/retrieval evidence is available
artifact_outputs = result.json, results.jsonl, summary.json, summary.md,
  preview.json, failures_sample.jsonl, manifest.json, optional
  outputs/sync/<run_id>/ compact bundle
diagnostics = per-row compact final answer, citation validation, raw output
  preview, token/latency metadata, selected/dropped block ids, and evidence
  context hash for Qwen failure review without full prompt/log sync
review_gate = reads a full artifact directory or outputs/sync/<run_id>/ bundle
  and writes review.json/review.md with a diagnostic SFT/GRPO gate
  recommendation; it does not start training or mark benchmark acceptance
sft_candidate_builder = reads real-Qwen-marked baseline failures and prepared
  TAT-QA samples, reconstructs prompt-v2 SFT candidate records with evidence
  and compact tool results, and blocks non-Qwen baselines
training_gate_orchestrator = runs baseline, review, and optional SFT candidate
  generation in one command; local heuristic smoke skips candidate generation
sft_candidate_review = reviews larger real-Qwen answer misses, candidate
  alignment, target-field quality, attached tool context, and manual-review
  rows before any training
status = implemented
used_qwen_local = false
server_qwen_smoke = real_model_verified
server_qwen_smoke_run_id = answer_policy_training_gate_qwen_smoke_20260629
server_qwen_smoke_summary = case_count 24, evaluated_count 12,
  format_valid_rate 1.0, answer_hit_rate 0.75,
  citation_block_hit_rate 0.75, pass_rate 0.5833
server_rerun_after_citation_repair = case_count 24, evaluated_count 12,
  format_valid_rate 1.0, answer_hit_rate 0.75,
  citation_block_hit_rate 1.0, pass_rate 0.75, failure_reason answer_miss:3
server_training_gate_recommendation = citation_contract_repair_before_training
  before review-gate invalid-citation semantics adjustment
review_gate_invalid_citation_semantics = implemented locally; server rerun
  success, run_id answer_policy_review_gate_filtered_invalid_20260629,
  recommendation continue_qwen_eval_before_training, sft_gate defer,
  invalid_citation_id_count_in_rows 3, failure_reason answer_miss:3
larger_qwen_diagnostic = success, run_id
  answer_policy_training_gate_qwen_larger40_20260629, case_count 80,
  evaluated_count 40, pass_rate 0.65, format_valid_rate 1.0,
  answer_hit_rate 0.65, citation_block_hit_rate 1.0,
  failure_reason answer_miss:14, review recommendation
  sft_data_design_candidate, sft_candidate_record_count 13,
  used_training false, formal_benchmark_acceptance false
larger_qwen_tablefix_diagnostic = success, run_id
  answer_policy_training_gate_qwen_larger40_tablefix_20260629, case_count 80,
  evaluated_count 40, pass_rate 0.90, format_valid_rate 1.0,
  answer_hit_rate 0.90, citation_block_hit_rate 1.0,
  failure_reason answer_miss:4, review recommendation
  continue_qwen_eval_before_training, sft_gate defer, sft_candidates skipped,
  used_training false, formal_benchmark_acceptance false
full80_qwen_tablefix_diagnostic = success, run_id
  answer_policy_training_gate_qwen_full80_tablefix_20260629, case_count 135,
  evaluated_count 80, pass_rate 0.7625, format_valid_rate 1.0,
  answer_hit_rate 0.7625, citation_block_hit_rate 1.0,
  failure_reason answer_miss:19, review recommendation
  prompt_or_parser_repair_before_training, sft_gate not_ready,
  sft_candidates skipped, used_training false,
  formal_benchmark_acceptance false; next action
  fix_output_format_or_parser_before_sft means inspect raw JSON/schema rows
  before changing prompts, parser, or training data
full80_parse_failure_inspect = success, run_id
  answer_policy_full80_parse_failure_inspect_20260629, parse_fail_count 1,
  raw_json_fail_count 0, schema_fail_count 1,
  parse_fail_but_format_valid_count 1, parse_fail_and_answer_miss_count 1;
  this is a repaired candidate-schema miss rather than a final output format
  failure
review_gate_repaired_parse_schema_semantics = implemented locally; repaired
  raw JSON/schema failures now remain diagnostic when final format_valid is
  true, while unrepaired parse/schema failures still block SFT/GRPO decisions;
  server review-only rerun success, run_id
  answer_policy_full80_repaired_parse_review_20260629, git_commit 9f8a23d,
  recommendation continue_qwen_eval_before_training, sft_gate defer,
  parse_fail_count 1, repaired_parse_fail_count 1,
  unrepaired_parse_fail_count 0, invalid_citation_id_count 16,
  answer_miss_count 19, used_training false,
  formal_benchmark_acceptance false
answer_miss_artifact_review = server diagnostic success, run_id
  answer_policy_full80_answer_miss_review_20260630, git_commit cbd0db1,
  source_baseline answer_policy_training_gate_qwen_full80_tablefix_20260629,
  answer_miss_count 19, bucket_counts
  answer_granularity_or_metric_review:3,
  calculation_reasoning_or_operand_review:7,
  model_extractive_precision_review:4,
  repaired_parse_plus_answer_miss:1,
  table_selection_or_column_review:4, used_training false,
  formal_benchmark_acceptance false; tracked reusable script implemented
  locally as scripts/review_answer_policy_answer_misses.py and does not
  create training data
answer_miss_artifact_review_tracked = server diagnostic success, run_id
  answer_policy_full80_answer_miss_review_tracked_20260630,
  git_commit 2b2a431, source_run_id
  answer_policy_training_gate_qwen_full80_tablefix_20260629_baseline,
  answer_miss_count 19, bucket_counts
  answer_granularity_or_metric_review:2,
  calculation_reasoning_or_operand_review:7,
  model_extractive_precision_review:4,
  repaired_parse_plus_answer_miss:1,
  table_selection_or_column_review:5, used_qwen true,
  used_training false, formal_benchmark_acceptance false,
  validation_subset_used_for_training false, recommendation
  inspect_generic_tool_outputs_before_training
generic_tool_output_inspection = implemented locally in
  scripts/inspect_answer_policy_tool_outputs.py; reads existing
  AnswerPolicy baseline results, inspects answer_miss rows whose
  expected_tools include table_lookup or simple_calculation, writes
  result.json, summary.json, summary.md, tool_output_rows.jsonl,
  preview.json, and manifest.json, and does not rerun Qwen, train, or
  create validation-derived training data; server validation success, run_id
  answer_policy_tool_output_inspect_full80_tablefix_20260630,
  git_commit 61d5321, source_run_id
  answer_policy_training_gate_qwen_full80_tablefix_20260629_baseline,
  answer_miss_count 19, tool_expected_answer_miss_count 12,
  non_tool_answer_miss_count 7, bucket_counts
  generic_calculation_operand_or_operation_review:6,
  generic_table_selection_or_column_review:4,
  model_did_not_use_correct_tool_output:2, tool_status success:12,
  tool_operation_counts simple_calculation:7, table_lookup:5,
  used_training false, formal_benchmark_acceptance false,
  validation_subset_used_for_training false, recommendation
  inspect_generic_table_or_calculation_tool_outputs_before_training
generic_table_tool_operation_column_repair = implemented locally in
  docagent/tools/table_tools.py; adds generic operation/column handling for
  total-across-year sums, percentage increase/decrease wording,
  percentage-of-total expressions, same-row multi-year averages with
  currency-parentheses negative numbers, requested period/quarter/as-reported
  lookup columns, multi-column respective lookup values, and who/name table
  answers; local targeted regression passed, server deterministic validation
  success, run_id final_eval_tatqa_table_tool_repair_20260630,
  git_commit 7cac9fe, case_count 80, tool_executed_count 60,
  tool_success_count 57, pass_rate 0.825, answer_hit_count 46,
  answer_hit_rate 0.7667, numeric_accuracy_rate 0.7,
  citation_block_hit_rate 1.0, failure_reason_distribution
  answer_miss:14, table_lookup_unsupported:3, used_qwen false,
  used_training false, formal_benchmark_acceptance false
full80_qwen_generic_tablefix_diagnostic = success, run_id
  answer_policy_training_gate_qwen_full80_generic_tablefix_20260630,
  git_commit c0a7640, case_count 135, evaluated_count 80,
  pass_rate 0.85, format_valid_rate 1.0, answer_hit_rate 0.85,
  citation_block_hit_rate 1.0, failure_reason answer_miss:12,
  review recommendation continue_qwen_eval_before_training,
  sft_gate defer, sft_candidates skipped, used_qwen true,
  used_training false, formal_benchmark_acceptance false,
  next_action run_larger_real_qwen_baseline_or_manual_review
sft_candidate_review = server validation success, run_id
  answer_policy_sft_candidate_review_larger40_20260629_tracked,
  candidate_record_count 13, failed_without_candidate_count 1,
  candidate target quality flags clean, recommendation
  manual_review_sft_candidates_before_training, used_training false,
  formal_benchmark_acceptance false
manual_review_extract = success, run_id
  answer_policy_manual_review_extract_larger40_20260629, row_count 14,
  bucket_counts table_lookup_answer_miss_with_tool:6,
  calculation_answer_miss_with_tool:5, generation_answer_miss_review:2,
  tool_failure_without_candidate:1
enriched_manual_review = implemented locally in
  scripts/review_answer_policy_sft_candidates.py; adds full per-row
  review_bucket, prediction/tool/candidate gold-hit hints, target citations,
  raw output previews, and recommendation
  inspect_tool_and_metric_failures_before_sft when tool or metric issues are
  present; server validation success, run_id
  answer_policy_sft_candidate_review_larger40_enriched_20260629
table_tool_calculation_trigger = implemented locally; table lookup no longer
  infers calculation from question text when selected_tools lacks
  simple_calculation, preventing row-label terms such as "decrease" or
  "weighted-average" from forcing simple_calculation; server larger40 rerun
  pending
table_tool_row_header_selection = implemented locally; table parsing now
  preserves blank HTML cells, merges initial multi-row headers, prioritizes
  direct row-label tokens over generic year/end words, handles repeated
  Granted/Vested activity rows, uses section-row context for child rows such
  as Basic under Weighted-average common shares outstanding, computes high/low
  differences from the question date column, and appends traceable million
  display values for positive $000 lookup cells; local replay of the 12
  larger-gate table/tool miss rows has status success 12/12 and answer hits
  12/12, while the full local TAT-QA diagnostic is 80 cases, pass_rate 0.75,
  table-tool success 56/60, answer_hit 40/60, citation_block_hit 60/60;
  server deterministic audit success, run_id
  answer_policy_table_row_header_fix_audit_20260629, commit a2ae57e,
  loaded_row_count 12/12, status success 12/12, table_lookup 7,
  simple_calculation 5, tool_answer_hit_count 12, pass_count 12,
  failure_reason_distribution empty; this accepts the deterministic tool
  repair only, not final Qwen answer quality
benchmark_evaluation_status = not_started
```

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

1. Keep Phase 5C-3 Query Planning + Multi-Query Retrieval accepted as
   query-planning execution-stability evidence after the single-case and
   multi-question server smokes.
2. Keep Phase 5H accepted as full workflow execution-stability evidence, not
   answer-quality or golden-benchmark evidence.
3. Keep Phase 5I-A accepted as an evidence-readiness benchmark baseline; do
   not interpret it as final answer quality acceptance.
4. Keep Phase 5E document_summary as a locally implemented deterministic
   extractive summary tool; do not interpret it as final answer quality
   acceptance.
5. Keep Phase 5C-2 LLM-assisted Router fallback disabled by default unless
   explicitly configured and allowed.
6. Keep Phase 5F-3 server smoke accepted as execution-stability evidence, not
   online MinerU OCR or benchmark-level answer-quality evidence.
7. Keep Phase 5F-1 server smoke accepted as execution-stability evidence, not
   benchmark-level answer-quality evidence.
8. Keep Phase 4D-D deferred until MVP entrypoint, router, deterministic tools,
   and multi-task regression are accepted.
9. Keep Candidate-ID Reader postponed until reader-selection failures dominate
   after candidate coverage issues are resolved.
10. Keep optional full GRPO E2E postponed until candidate answer board quality
   improves.
11. Keep `page_children` as the default until more shard and document-type
   validation supports a global default change.
12. Keep CDC `not_started` until explicitly started.

## Stop Condition

```text
Phase 4D-B1.3 server sanity accepted
+ Phase 4D-C expanded unseen validation accepted
+ Phase 4D-D deferred
+ Phase 5A architecture audit and contract documents accepted
+ Phase 5B deterministic P0 document tools accepted
+ Phase 5C Router / Planner accepted
+ Phase 5D local_fact_qa wrapper accepted
+ Phase 5D-S server smoke accepted as execution stability evidence
+ Phase 5F-1 unified CLI MVP accepted
+ Phase 5F-1 server CLI smoke accepted as execution stability evidence
+ Phase 5F-2 file-to-answer ingestion integration accepted
+ Phase 5F-2 server file-to-answer smoke accepted as execution stability evidence
+ Phase 5F-3 MinerU-backed file-to-answer implementation accepted
+ Phase 5F-3 server smoke accepted as execution stability evidence
+ Phase 5C-2 LLM-assisted Router fallback accepted after real API smoke
+ Phase 5C-3 Query Planning + Multi-Query Retrieval accepted after targeted
  local tests plus single-case and multi-question server query-rewriter smokes
+ Phase 5H Full Workflow Validation Baseline accepted after 15-case
  non-dry-run server smoke
+ Phase 5I old-semantics server benchmark benchmark_evaluated and reinterpreted
+ Phase 5I-A Pre-LLM Evidence Readiness Benchmark runner accepted
+ Phase 5I-A corrected-semantics server benchmark accepted with
  evidence_readiness_status = baseline_has_failures
+ Phase 5I-B Full Model-enhanced QA Path accepted after server full-path smoke
  and Router LLM trigger probe
+ Phase 5I-B Final Answer Quality Benchmark artifact contract implemented:
  `scripts/run_phase5i_answer_quality_benchmark.py` writes
  `metrics.json`, `predictions.jsonl`, `case_reports.jsonl`,
  `failure_analysis.md`, `acceptance_report.json`,
  `training_candidates_raw.jsonl`, and `manifest.json`, with
  validation-subset training disabled and formal benchmark acceptance still
  false; `scripts/inspect_phase5i_answer_quality_artifacts.py` validates the
  artifact contract without rerunning models or creating training data
+ Phase 5I-B Final Answer Quality Benchmark execution not_started
+ Phase 5E Document Summary MVP implemented with local targeted and Phase 5
  regression tests passing
+ Phase 5F full CLI acceptance accepted after AutoDL server smoke with
  11 cases, 10 completed, 1 structured unsupported boundary, and 10/10
  artifact contracts passing
+ Final Delivery Contract local update implemented with top-level
  `reasoning_summary`, `evidence_used`, normalized citations,
  deterministic `table_lookup`, deterministic `simple_calculation`, and
  MinerU API raw PDF ingestion support
+ Final raw PDF MinerU API smoke accepted with run id
  `final_raw_pdf_mineru_api_cli_smoke_20260630`: live API/OCR used,
  4/4 CLI contract cases passed, citations/evidence_used present on
  evidence-bearing cases; this is execution/citation-contract evidence, not
  final answer-quality benchmark evidence
+ MP-DocVQA evidence materialization runner implemented locally with optional
  AnswerPolicy baseline consumption of `sample_evidence_manifest.jsonl` plus
  SQLite EvidenceBlocks; 2-document live MinerU API smoke
  `mpdocvqa_evidence_api_smoke_20260630` verified raw PDF -> MinerU API ->
  EvidenceBlock -> sample evidence manifest on 4 samples; full selected-subset
  retry/resume run `mpdocvqa_evidence_api_retry_failed_hardened_20260630`
  verified 10/10 MP-DocVQA documents and 55/55 samples as evidence-ready,
  enabling MP-DocVQA rows to enter the next real-Qwen diagnostic baseline
+ Full-workflow real retriever CLI wiring real-model verified with run id
  `final_full_workflow_hybrid_rerank_smoke_rowalign_20260630`: main QA path
  used LLM Query Planner, real BGE-M3 dense retrieval, real
  bge-reranker-v2-m3 cross-encoder reranking, Qwen AnswerPolicy, and persisted
  workflow trace including `retrieve_evidence`; separate Router probe used LLM
  fallback. This is full execution-chain smoke evidence, not final answer
  correctness or benchmark acceptance.
+ Raw PDF full-model workflow baseline real-model verified with run id
  `final_raw_pdf_full_workflow_api_hybrid_qwen_fresh_20260630_172350`: one
  fresh CLI workflow started from `--file` raw PDF input, ingested via live
  MinerU API into a new DB, used LLM Router fallback, LLM Query Planner,
  real BGE-M3 dense retrieval, real bge-reranker-v2-m3 reranking, Qwen base
  AnswerPolicy, and wrote answer/evidence/citation plus trace artifacts. This
  is the current whole-chain usability baseline, not answer-quality benchmark
  acceptance.
+ Final evaluation subset preparation implemented locally with TAT-QA dev and
  MP-DocVQA val shard 1-2 manifests, filter reports, source hashes, and
  previews under `outputs/final_eval/`
+ Final evaluation local subset diagnostic runner implemented locally with
  `results.jsonl`, `summary.json`, `summary.md`, `preview.json`, and
  `manual_review.md` outputs; status remains diagnostic-only, not
  benchmark-evaluated
+ Final delivery CLI guide implemented locally in `docs/FINAL_DELIVERY_CLI.md`
  and linked from `README.md`; status remains documentation/packaging only
+ Final delivery report implemented locally in
  `docs/FINAL_DELIVERY_REPORT.md`; it summarizes accepted,
  real_model_verified, implemented, and not_started delivery boundaries without
  promoting diagnostic subset results to benchmark acceptance
+ Final delivery readiness check implemented locally in
  `scripts/check_final_delivery_readiness.py`; it checks required files, CLI
  options, required output fields, citation/evidence location fields,
  documentation boundaries, and deprecated PM handoff cleanup without calling
  MinerU, Qwen, BGE-M3, reranker, datasets, or training
+ Final delivery benchmark gate implemented locally in
  `scripts/run_final_delivery_benchmark_gate.py`; it safely orchestrates
  readiness, final AnswerPolicy baseline, and MP-DocVQA full-workflow
  diagnostics with compact artifacts, but does not train or claim formal
  benchmark acceptance; server run
  `final_delivery_benchmark_gate_server_20260702_componentmetrics` plus
  review `final_delivery_gate_metric_review_componentcountfix_20260702`
  accepted the diagnostic gate/component-metric contract with safety flags
  preserved false
+ AnswerPolicy IO candidate schema, shared prompt v2 candidate-citation
  contract, SFT/GRPO record compatibility, and reward/eval schema
  compatibility implemented locally; final subset AnswerPolicy baseline runner
  review gate, SFT candidate-data builder, and training-gate orchestrator
  implemented locally with heuristic/fake-policy validation; real Qwen
  baseline, prompt-quality evidence, training execution, and final answer
  benchmark remain not_started
+ targeted and regression tests pass
+ status documents updated
+ branch pushed
+ stop before VLM, Reader prompt changes, external Answer API integration,
   real Qwen baseline acceptance, training execution, SFT/GRPO checkpoint
   changes, MP-DocVQA/TAT-QA benchmark runs, CDC, Demo, per-qid repairs,
   further 90-sample probe tuning, and any global `candidate_spans` default
   change
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

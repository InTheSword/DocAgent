# DocAgent Final Delivery Report

Updated: 2026-07-04

This report summarizes the current delivery status for the local, CLI-only
DocAgent MVP. It is a status and evidence index, not a new benchmark claim.
Detailed operating instructions remain in `docs/FINAL_DELIVERY_CLI.md`; active
implementation state remains in `docs/ACTIVE_PLAN.md` and `CURRENT_STATUS.md`.

## Delivery Scope

Current target:

```text
local PDF/text file or existing doc_id
-> question
-> MinerU API or persisted document evidence
-> Router and optional query planner
-> deterministic tools or local_fact_qa workflow
-> answer, reasoning_summary, evidence_used, citations, tools_used, trace_path
```

The baseline is single-document, English-first, local CLI usage. Multi-document
fields are schema-prepared through `doc_id` and `source_document`, but
multi-document QA is not a required delivery claim.

## Status Summary

| Area | Status | Evidence boundary |
|---|---:|---|
| Unified CLI contract | accepted | Phase 5F full CLI acceptance and server CLI smoke |
| Final output JSON contract | implemented | Local contract/readiness tests cover `answer`, `reasoning_summary`, `evidence_used`, `citations`, `tools_used`, `trace_path`, and citation/evidence location fields |
| Raw PDF parsing | accepted | MinerU API is the final raw PDF parser path; local MinerU CLI is not a delivery target |
| MinerU API secret-file support | accepted | `.secrets/mineru.env` supports `MINERU_TOKEN` or `API_TOKEN` without committing secrets |
| MinerU output preservation | implemented | Markdown/resource inventory metadata, content list fallback, table HTML, table/image resource paths, captions, and nearby OCR text are preserved into evidence metadata |
| Existing MinerU output ingestion | real_model_verified | Existing real MinerU artifacts are consumable through `mineru_existing` |
| Router and query planner | accepted | Rule-first Router and LLM-assisted fallback/query planning have server smokes |
| Full workflow with real retrieval and Qwen | real_model_verified | Server workflow smokes cover LLM Router/Rewriter, BGE-M3, reranker, Qwen AnswerPolicy, trace, and citations |
| Deterministic document tools | implemented | Document statistics, page lookup, document summary, structured extraction, table lookup, and simple calculation are locally tested |
| MP-DocVQA evidence materialization | accepted | 10/10 selected documents and 55/55 samples were materialized as evidence-ready after MinerU API retry hardening |
| TAT-QA / MP-DocVQA subset preparation | implemented | Reproducible validation-subset artifacts are prepared locally; they are not training data |
| Local diagnostics and readiness checks | implemented | Diagnostic subset runners and `scripts/check_final_delivery_readiness.py` write compact artifacts and check citation/evidence fields |
| Final delivery benchmark gate | accepted | Server run `final_delivery_benchmark_gate_server_20260702_componentmetrics` completed readiness, real-Qwen AnswerPolicy baseline, and MP-DocVQA full-workflow diagnostic steps successfully; `final_delivery_gate_metric_review_componentcountfix_20260702` verified manifest/safety flags and complete component-use metrics for 23 local_fact_qa workflow rows; `formal_benchmark_acceptance=false` |
| Final answer quality artifact contract | implemented | `scripts/run_phase5i_answer_quality_benchmark.py` writes `metrics.json`, `predictions.jsonl`, `case_reports.jsonl`, `failure_analysis.md`, `acceptance_report.json`, `training_candidates_raw.jsonl`, and `manifest.json`; it forwards retriever/dense/reranker settings into `docagent_cli.py` and blocks model-backed runs before CLI/Qwen execution when the requested `db_path` + `doc_id` has no retrievable persisted EvidenceBlocks; server guard run `phase5ib_answer_quality_context_block_20260702` verified that missing context returns blocked artifacts without Qwen; server inventory `phase5ib_context_inventory_server_20260702` found 57 ready candidate contexts and selected `outputs/docagent.db` / `c1fc1c5e040ec894`; follow-up probes added compact CLI/retriever/error/traceback diagnostics, then `phase5ib_answer_quality_selected_context_densefix_20260702` validated stale dense-index metadata rebuild with 8/8 CLI statuses successful; remaining small-scenario failures are answer/citation quality diagnostics, not execution-chain blockers |
| AnswerPolicy training-pack preprocessing | implemented | `scripts/build_answer_policy_training_pack.py` builds audited SFT/GRPO training-format artifacts from train-split `DocAgentSample` JSONL input, writes summary/preview/manifest hashes, and blocks non-train splits or validation-like paths such as `final_eval` by default; it does not start training or use validation subsets as training data |
| AnswerPolicy v3 training-data trial | implemented | `ModelOutputV3` targets `answer`, `supporting_refs`, `support_status`, and `reasoning_summary`; `scripts/build_answer_policy_v3_training_data.py` builds high-confidence TAT-QA and MP-DocVQA train-only v3 SFT trial artifacts with internal `EvidenceRefMap` metadata and validation-source blocking; local TAT-QA smoke `answer_policy_v3_tatqa_trial_20260704` produced 200 records, and server MP-DocVQA train smoke `mpdocvqa_train_v3_pipeline_splitfix2_20260704` materialized 10/10 evidence-ready samples and produced 7 v3 SFT records; no training was started |
| AnswerPolicy v3 insufficient-evidence data | implemented | `scripts/build_answer_policy_v3_insufficient_data.py` builds train-only TAT-QA `insufficient_confirmed` records by pairing source questions with different-document decoy evidence boards that do not contain the gold answer string; local smoke `answer_policy_v3_tatqa_insufficient_local_smoke_20260704` produced 32 v3 records, and server smoke `answer_policy_v3_insufficient_server_smoke_20260704_verify` at commit `00a3fa2` produced 64 insufficient records plus a 64-record mixed pack with 19 insufficient records selected; no training was started |
| AnswerPolicy v3 schema warmup SFT | real_model_verified | Server run `answer_policy_v3_sft_warmup_smoke_20260704` used Qwen3-1.7B plus PEFT LoRA on 16 selected v3 records for 1 step, wrote adapter artifacts, and preserved `formal_benchmark_acceptance=false` and `validation_subset_used_for_training=false`; this verifies the training path, not final answer-quality improvement |
| AnswerPolicy v3 checkpoint diagnostic | real_model_verified | Server run `answer_policy_v3_checkpoint_eval_smoke_20260704` loaded the Qwen3-1.7B base model plus the warmup PEFT adapter and evaluated 4 warmup records with `json_valid_rate=1.0`, `schema_valid_rate=1.0`, `support_status_match_rate=1.0`, `supporting_refs_subset_rate=1.0`, `positive_ref_hit_rate=1.0`, and `answer_exact_rate=0.5`; it kept `used_training=false`, `formal_benchmark_acceptance=false`, and `validation_subset_used_for_training=false`; this verifies diagnostic plumbing, not model-quality acceptance |
| AnswerPolicy v3 ms-swift SFT smoke | real_model_verified | `scripts/run_answer_policy_v3_msswift_sft.py` prepares Swift message JSONL and records the exact `swift sft` command, with training gated behind explicit `--execute`; server dry-run `answer_policy_v3_msswift_dry_run_20260704` confirmed `ms-swift=4.2.3` and train-only v3 inputs, server execute smoke `answer_policy_v3_msswift_execute_smoke2_20260704` trained Qwen3-1.7B for 1 step via LoRA and wrote a Swift PEFT checkpoint, and `answer_policy_v3_msswift_checkpoint_eval_20260704` verified v3 JSON/schema/ref metrics at 1.0 on 4 records with `answer_exact_rate=0.5`; this is backend-entrypoint evidence, not final quality acceptance |
| AnswerPolicy v3 mixed-pack short SFT | real_model_verified | `scripts/build_answer_policy_v3_mixed_sft_pack.py` builds train-only mixed packs with ratio, shortage, and backfill audit; prompt-limit repair run `answer_policy_v3_promptlimit_stage2_short_20260704_verify` restored v3 schema/ref stability after adding insufficient records; expanded MP-DocVQA train run `mpdocvqa_train_v3_expand20_20260704_verify` used MinerU API/OCR on 20 train documents, produced 52 MP-DocVQA v3 records, built a 96-record pack with MP-DocVQA 48, TAT-QA 38, insufficient 10 and no shortage, then `answer_policy_v3_msswift_stage2_expand20_short_20260704` trained 3 ms-swift LoRA steps and checkpoint diagnostic kept `json_valid_rate=1.0`, `schema_valid_rate=1.0`, and `supporting_refs_subset_rate=1.0`; this is short training-chain evidence, not final model-quality acceptance |
| AnswerPolicy v3 reward calibration | implemented | `docqa_v3_reward` now hard-gates invalid v3 schema outputs and scores insufficient-evidence refusals; `scripts/calibrate_answer_policy_v3_rewards.py` writes train-only target/negative reward-component reports without calling models or starting training; local smoke `answer_policy_v3_reward_calibration_local_smoke_20260704` passed on 32 records, and server run `answer_policy_v3_reward_calibration_expand20_20260704` passed on the 96-record expanded mixed train pack with `target_reward_min=1.0`, `negative_reward_max=0.7`, and invalid-schema reward 0.0; this prepares best-of-N/DPO/GRPO decisions but does not approve GRPO |
| AnswerPolicy v3 rejection-sampling artifacts | implemented | `scripts/build_answer_policy_v3_rejection_sampling_artifacts.py` ranks train-only v3 candidate generations with the calibrated v3 reward and writes ranked, selected, preference-pair, and filtered SFT candidate artifacts; local calibration-variant smoke validated artifact shape on 32 train-only records, and server smoke `answer_policy_v3_rejection_sampling_expand20_calibration_20260704` validated the contract on the 96-record expanded train-only pack with 470 synthetic calibration candidates, 96 selected rows, 96 preference pairs, and zero training-ready rows; real model candidate collection remains the next step before any best-of-N, DPO, or GRPO decision |
| AnswerPolicy v3 real-model candidate generation | real_model_verified | `scripts/generate_answer_policy_v3_candidates.py` generates multiple `model_generation` candidates from train-only v3 prompts, validates v3 JSON/schema, and writes candidate artifacts for the rejection builder without starting training; local dry-run confirmed synthetic candidates cannot become training-ready, and server Qwen smoke `answer_policy_v3_candidate_generation_qwen_smoke_20260704` generated 8 real Qwen candidates from 4 train-only records with JSON/schema rates 1.0; follow-up ranking `answer_policy_v3_rejection_sampling_qwen_smoke_20260704` consumed those candidates, but no rows passed reward thresholds in this tiny base-model smoke, so no rejection-SFT rows were emitted and GRPO remains unapproved |
| AnswerPolicy v3 adapter-backed rejection distillation artifacts | real_model_verified | Server run `answer_policy_v3_candidate_generation_expand20_adapter_smoke_20260704` loaded the short expanded ms-swift LoRA adapter, generated 24 adapter-backed candidates from 8 train-only records with JSON/schema rates 1.0, and `answer_policy_v3_rejection_sampling_expand20_adapter_smoke_20260704` selected 2 reward-qualified rows into `rejection_sft_candidates.jsonl`; dry-run `answer_policy_v3_rejection_sft_msswift_dryrun_20260704` verified those 2 rows are valid ms-swift SFT input without executing training; bounded follow-up `answer_policy_v3_candidate_generation_expand20_adapter24x3_20260704` generated 72 candidates from 24 train-only records with JSON/schema rates 1.0, but ranking `answer_policy_v3_rejection_sampling_expand20_adapter24x3_20260704` again produced only 2 training-ready rejection-SFT rows and zero training-ready preference pairs; DPO/GRPO remain unapproved |
| AnswerPolicy v3 rejection-SFT distillation smoke | real_model_verified | Server run `answer_policy_v3_rejection_sft_msswift_execute_smoke_20260704` trained Qwen3-1.7B for 1 ms-swift LoRA step on the 2 train-only rejection-SFT rows selected by the adapter-backed rejection sampler, then `answer_policy_v3_rejection_sft_checkpoint_eval_20260704` verified JSON/schema/supporting-ref/support-status/positive-ref metrics at 1.0 on those same rows; this verifies execution plumbing only, not final answer-quality improvement |
| Final answer quality benchmark | not_started | No accepted MP-DocVQA/TAT-QA final answer benchmark yet |
| Full SFT/GRPO training | not_started | The v3 PEFT warmup, ms-swift 1-step smoke, mixed-pack 3-step smoke, and checkpoint diagnostic smokes exist, but no expanded SFT run, GRPO run, or trained-checkpoint quality claim is accepted |
| Pixel-level VLM reasoning | not_started | Image support is OCR/caption/nearby-text/resource metadata only |
| UI / API service / cloud storage | not_started | Delivery remains CLI-only |

## Verification Evidence

Accepted or real-component evidence currently includes:

- `final_raw_pdf_mineru_api_cli_smoke_20260630`
- `final_raw_pdf_mineru_api_api_only_cleanup_20260630`
- `mpdocvqa_evidence_api_retry_failed_hardened_20260630`
- `final_full_workflow_hybrid_rerank_smoke_rowalign_20260630`
- `final_raw_pdf_full_workflow_api_hybrid_qwen_fresh_20260630_172350`
- `final_delivery_chain_sanity_after_scope_rules_20260702`
- `final_delivery_benchmark_gate_server_20260702_componentmetrics`
- `final_delivery_gate_metric_review_componentcountfix_20260702`
- `phase5ib_context_inventory_server_20260702`
- `phase5ib_answer_quality_selected_context_densefix_20260702`

These runs validate execution-chain continuity and artifact contracts. They do
not by themselves promote answer correctness to `benchmark_evaluated`.
The final delivery benchmark gate is accepted as a diagnostic orchestration
gate only; it is not a formal answer-quality benchmark claim.
Artifact-guard validation `phase5ib_answer_quality_context_block_20260702`
confirms that invalid Phase 5I-B document context is blocked before CLI/Qwen
execution; it is not answer-quality evidence.
Context inventory `phase5ib_context_inventory_server_20260702` identifies an
eligible Phase 5I-B probe context; it is not answer-quality evidence.
Selected-context probe `phase5ib_answer_quality_selected_context_20260702`
ran with Qwen but is diagnostic-only; it exposed metadata-level CLI/evidence
failures and prompted artifact-contract instrumentation, not benchmark
acceptance.
Follow-up probe `phase5ib_answer_quality_selected_context_artifactfix_20260702`
confirmed the real retriever stack initializes successfully and narrowed the
remaining failures to internal `workflow_failed` exceptions; the local contract
now preserves workflow exception class names for the next diagnostic rerun.
Cause-type probe `phase5ib_answer_quality_selected_context_causetype_20260702`
classified those internal failures as `AssertionError`. This remains an
execution-chain diagnostic blocker, not formal answer-quality benchmark
acceptance; Phase 5I-B artifacts now preserve compact traceback tails for
targeted follow-up.
Traceback probe `phase5ib_answer_quality_selected_context_traceback_20260702`
localized the blocker to a dense-index/query dimension mismatch inside FAISS.
The local repair prevents stale legacy dense-index metadata from being reused
with a different encoder and surfaces dimension mismatches before backend
search. Densefix probe
`phase5ib_answer_quality_selected_context_densefix_20260702` validated the
repair: all 8 cases reached successful CLI status, the stale `hash-dense-256`
legacy index was rebuilt for BGE-M3, and remaining failures are diagnostic
answer/citation quality misses rather than workflow execution failures.

## Known Boundaries

- validation subsets are used for diagnostics only; they are not used as training data
  and must not become sample-specific prompt/tool rules.
- Small MP-DocVQA/TAT-QA sample metrics are not optimized to 100 percent and
  are not a reason for sample-specific repairs.
- A model answer miss is not automatically a code defect; first classify
  whether it blocks the reusable delivery chain.
- Image/table evidence is available through OCR text, captions, table HTML,
  resource metadata, and page/block citations. Pixel-level VLM interpretation
  is deferred.
- Server-only validation remains required when a change touches live MinerU
  API, real BGE-M3, reranker, Qwen, large dataset workflow, SFT, GRPO, or VLM.

## Next Delivery Work

Near-term work should stay on reusable system behavior:

1. Preserve and test the MinerU output -> EvidenceBlock -> retrieval -> citation
   path after parser/evidence changes.
2. Keep the full workflow sanity path green after meaningful changes.
3. Review accepted final-delivery gate artifacts before promoting any result
   to formal final answer-quality benchmark work.
4. Use the Phase 5I-B artifact contract for the next small-scenario
   answer-quality server run only after confirming the selected `db_path` and
   `doc_id` contain retrievable EvidenceBlocks, while keeping
   `formal_benchmark_acceptance=false` until the run is reviewed.
5. Start SFT/GRPO only if future benchmark evidence shows reusable AnswerPolicy failures
   that prompt/tool/contract repair cannot address.

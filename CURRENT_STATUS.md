# Current Status

Updated: 2026-07-05

## Phase 4D-C Accepted / Phase 5 Active

AnswerPolicy v3 promptfix Stage 2 SFT is real-model verified as a train-only
objective improvement, not as final workflow deployment acceptance. The
repaired-prompt full4096 pack trained Qwen3-1.7B with ms-swift LoRA for 1024
update steps and improved the 256-row train-only heldout answer-exact rate
from 0.3750 to 0.5859 while improving schema validity and support/ref metrics.
The focused table/calculation fixed-evidence comparator
`answer_policy_v3_fixed_tablecalc_compare128_promptfix_20260705` further
recorded 36 candidate improvements and 2 regressions over 128 train-only
fixed-evidence rows, with answer-exact improving from 0.5234 to 0.7891. This
is evidence that the v3 AnswerPolicy objective improved; it does not promote
the adapter as the default full-workflow checkpoint.

AnswerPolicy v3 clean fixed-evidence comparison is real-model verified as a
diagnostic contract probe, not as formal benchmark acceptance. Server run
`phase5ib_v3refs_clean6_base_vs_adapter480_contract_compare_20260704` compared
the same 6 curated clean Phase 5I cases through real LLM query rewriting,
BGE-M3 retrieval, cross-encoder reranking, Qwen AnswerPolicy, and
`answer_output_contract=v3_refs`. Qwen3-1.7B base passed 6/6, while the
480-step LoRA adapter passed 3/6; both kept JSON/citation/location validity at
1.0. The current 480-step adapter remains useful as train-only heldout and
integration evidence, but it should not be promoted as the default full-workflow
AnswerPolicy from this signal.

This full-workflow clean6 result is a deployment/regression guard, not a
standalone training-effectiveness judgement. SFT/RL effectiveness must be
judged primarily with the intended AnswerPolicy v3 objectives on train-only
heldout or fixed-evidence probes: schema legality, `supporting_refs`,
`support_status`, positive evidence-ref hit, concise grounded reasoning, and
insufficient-evidence behavior. Real workflow diagnostics mainly verify that
the system follows the intended route through retrieval, evidence mapping,
citation, and answer generation; they cannot by themselves prove retrieval
improvement or new model knowledge.

Phase 5I answer-quality run comparison guard is implemented in
`scripts/compare_phase5i_answer_quality_runs.py`. It reads existing
`phase5i_summary.json`, `metrics.json`, and `case_reports.jsonl` artifacts,
writes case-level movement rows, and keeps training/benchmark safety flags
false. Local targeted tests passed, and server run
`phase5ib_v3refs_clean6_base_vs_adapter480_compare_script_20260704` reproduced
the clean6 base-vs-adapter result without calling Qwen or training. Follow-up
server run `phase5ib_v3refs_clean6_base_vs_adapter480_boundaryfix_20260704`
adds `promotion_gate.gate_scope=default_checkpoint_deployment_guard`,
`promotion_gate.training_effectiveness_judged=false`, and
`promotion_gate.decision=blocked` for default adapter deployment from this
artifact.

Phase 4D-C expanded unseen validation is accepted on MP-DocVQA validation
shards 5-8 using the accepted default `candidate_spans` pipeline. The strict
accepted set contains 77 document windows, 572 pages, and 218 QA. The main
bottleneck is candidate answer extraction and candidate span construction, not
Reader selection. Phase 4D-D candidate answer board generalized improvement is
deferred while Phase 5 starts the personal-use DocAgent MVP track.

Phase 5B P0 deterministic document tools are accepted in
`docagent/tools/document_tools.py`. The tools read from
`DocumentRepository`, `documents.page_count`, and persisted `EvidenceBlock`
payloads. They do not implement Router, `scripts/docagent_cli.py`, final CLI
trace artifact creation, or later Phase 5 CLI tools. `document_summary`,
`table_lookup`, and `simple_calculation` are implemented later in the Phase 5
CLI/tool layer.

Phase 5C rule-first Router / Planner is accepted in `docagent/router/`.
It returns schema-valid single-step planning decisions from question,
`available_tools`, and optional `document_profile`. It does not execute tools,
call external LLM/VLM APIs, wrap `local_fact_qa`, implement summary/table/
calculation tools, or write final CLI trace artifacts.

Phase 5D local_fact_qa tool wrapper is accepted in
`docagent/tools/local_fact_qa.py`. It reuses `DocumentRepository`,
`run_qa_workflow`, AnswerPolicy, retrieval/evidence context logic, and optional
`TraceRepository`. Local tests cover wrapper behavior, dry-run/fake workflow
boundaries, default heuristic workflow reuse, citation/supporting evidence
fields, SQLite trace persistence, and the accepted Phase 5D-S server smoke.

Phase 5D-S local fact QA smoke support is accepted in
`scripts/run_phase5d_local_fact_qa_smoke.py`. It runs the Phase 5D
`local_fact_qa` wrapper against an existing SQLite `doc_id`, supports dry-run
and non-dry workflow smoke, and writes `summary.json`, `summary.md`,
`results.jsonl`, and `preview.json` under
`outputs/smoke/phase5d_local_fact_qa/<run_id>/`. The accepted server smoke
validates execution stability, not benchmark-level answer quality.

Phase 5F-1 Unified CLI MVP is accepted in `scripts/docagent_cli.py`. The
CLI supports `--db-path`, `--doc-id`, `--file`, `--question`, `--output-dir`,
`--dry-run`, `--list-documents`, and `--limit`. It calls the Phase 5C Router
before dispatching supported tasks, uses Phase 5B deterministic tools for
`document_statistics`, uses page tools for `page_lookup`, and uses Phase 5D
`local_fact_qa` for fact QA. `--file + --question` is now a CLI contract, but
Phase 5F-1 only provided SHA reuse and structured unavailable behavior. The
accepted server CLI smoke validates execution stability only, not
benchmark-level answer quality.

Phase 5F-2 file-to-answer ingestion integration is accepted in
`scripts/docagent_cli.py` with `docagent/parser/text_backend.py`. The CLI can
ingest new UTF-8 `.txt` files through `DocumentIngestionService`, reuse
existing SHA-matched documents, return generated or reused `doc_id`, and
continue through Router dispatch to deterministic tools or `local_fact_qa`.
The accepted server file-to-answer smoke validates lightweight `.txt`
execution stability and SHA reuse, not benchmark-level answer quality.
PDF/image inputs without a configured CLI parser backend still return
structured `parser_backend_unavailable`; MinerU-backed PDF ingestion is split
across existing-output, API, and local CLI paths below.

Phase 5F-3 MinerU-backed file-to-answer support is accepted in
`scripts/docagent_cli.py` by reusing `MinerUParserBackend`,
`DocumentIngestionService`, `DocumentRegistry`, `DocumentRepository`, Router,
deterministic tools, and `local_fact_qa` dry-run. The implemented path consumes
existing MinerU output through `--parser mineru_existing` and
`--mineru-output-dir` / `--mineru-output`, then writes the same unified JSON
and CLI artifacts. The accepted server smoke validates existing MinerU
output-backed execution, not online MinerU OCR execution or benchmark answer
quality.

Phase 5G CLI regression baseline is accepted in
`scripts/run_phase5g_cli_regression.py`. The runner reads default or JSONL
regression cases, calls `scripts/docagent_cli.py`, validates stdout JSON,
task type, tools used, artifact writing, structured errors, skipped cases, and
known limitations, then writes `regression_cases.jsonl`,
`regression_results.jsonl`, `regression_summary.json`,
`regression_summary.md`, and `preview.json` under
`outputs/regression/phase5g_cli/<run_id>/`. This is an execution stability
baseline, not a benchmark answer-quality report. The accepted server
regression run `phase5g_cli_20260626_022925_9eca480b` completed 8 cases,
recorded 2 unsupported known-limitations cases, failed 0 cases, emitted valid
JSON for all 10 cases, and wrote 9 CLI artifacts without external API, VLM,
training, or full E2E execution.

Phase 5E Document Summary MVP is implemented in
`docagent/tools/document_summary.py` and wired through `scripts/docagent_cli.py`.
It is a deterministic extractive summary path: the tool loads persisted
EvidenceBlocks from `DocumentRepository`, groups evidence by page, selects a
bounded set of representative textual blocks, and returns `answer`, `summary`,
`key_points`, `page_summaries`, `citations`, `warnings`, and `trace`.
`document_summary` is now included in CLI `available_tools`, so obvious summary
requests route to the summary tool instead of the old generic unsupported path.
The implementation does not call external APIs, LLM answer generation, VLM,
AnswerPolicy, training, GRPO, or online MinerU OCR. Local Phase 5 tests pass;
no server smoke has been run for this
local-only deterministic milestone.

Phase 5E-A Document Summary Acceptance Pack is implemented in
`scripts/run_phase5e_document_summary_acceptance.py`. The runner executes a
real non-dry-run `.txt` ingestion plus summary through `scripts/docagent_cli.py`,
validates `document_summary` routing, parses `result.json`, `summary.json`,
`router_plan.json`, and `trace.json`, checks citations against persisted
EvidenceBlocks, and writes
`outputs/phase5e_document_summary_acceptance/acceptance_report.json`.
The local acceptance report is a packaging and grounding check only; it does
not evaluate final answer quality or use external LLM answer generation, VLM,
training, GRPO, table lookup, simple calculation, or online MinerU OCR.

Phase 5 Final Delivery local contract update is implemented in
`scripts/docagent_cli.py`, `docagent/tools/table_tools.py`,
`docagent/tools/local_fact_qa.py`, `docagent/tools/document_summary.py`,
`docagent/tools/structured_extraction.py`, and
`docagent/parser/mineru_backend.py`. The CLI now includes top-level
`reasoning_summary` and `evidence_used`, normalizes citation fields across
text/table/image/page evidence, dispatches `table_lookup_or_calculation` to a
deterministic table tool, supports traceable simple difference/sum/percentage
calculations from cited table values, and supports raw PDF ingestion through
the MinerU API path. Status is `implemented`: local tests verify the contract
and deterministic table paths, while MP-DocVQA/TAT-QA final evaluation and
real Qwen answer-quality acceptance remain pending.

Phase 5 final evaluation subset preparation is implemented in
`scripts/prepare_final_eval_subset.py` with local tests in
`tests/test_prepare_final_eval_subset.py`. The script prepares reproducible
validation-subset artifacts without downloading data or running models. The
2026-06-29 local smoke used
`data/benchmark/tatqa/tatqa_dataset_dev.json` to select 80 balanced TAT-QA dev
questions, and
`data/benchmark/mp_docvqa/val/val-00001-of-00029.parquet` plus
`val-00002-of-00029.parquet` to restore 10 MP-DocVQA page-window PDFs with 55
QA records. Artifacts are under `outputs/final_eval/tatqa_dev_subset` and
`outputs/final_eval/mpdocvqa_val_subset`. Status is `implemented`: this is
data preparation only, not MinerU OCR acceptance, final answer-quality
benchmarking, Qwen evaluation, SFT, or GRPO.

Phase 5 final evaluation local subset diagnostic runner is implemented in
`scripts/run_final_eval_subset.py` with tests in
`tests/test_run_final_eval_subset.py`. It reads the prepared TAT-QA and
MP-DocVQA manifests, runs deterministic table tools only when the sample
expects `table_lookup` or `simple_calculation`, and otherwise records
manifest/evidence readiness without fabricating model answers. The local probe
`local_subset_probe_after_fix` over 10 TAT-QA and 10 MP-DocVQA samples wrote
`results.jsonl`, `summary.json`, `preview.json`, and `manual_review.md` under
`outputs/final_eval/local_subset_diagnostic/`. The full local diagnostic
`local_subset_full_diagnostic_report` completed with 135 cases, 85 passed,
50 failed, 60 table-tool executions, 37 table-tool successes, 60/60 citation
block hits for evaluated tool cases, 10 answer hits, and 4 numeric-accuracy
hits, and wrote `results.jsonl`, `summary.json`, `summary.md`,
`preview.json`, and `manual_review.md`. The runner now reports diagnostic rates
and failure taxonomy:
`pass_rate=0.6296`, `answer_hit_rate=0.1667`,
`numeric_accuracy_rate=0.2`, `citation_block_hit_rate=1.0`,
`failure_stage_distribution=tool_execution:23, answer_quality:27`, and
`failure_reason_distribution=table_lookup_unsupported:23, answer_miss:50`.
Status is
`implemented` and `quality_status=diagnostic_only`: this exposes table-answer
quality gaps and does not count as `benchmark_evaluated`.

Phase 5 final delivery CLI guide is implemented in
`docs/FINAL_DELIVERY_CLI.md` and linked from `README.md`. It documents the
current local CLI contract, output fields, local storage paths, dataset subset
commands, diagnostic artifacts, image/table boundaries, and status rules. This
is documentation and packaging only: it does not change model behavior, run
online MinerU OCR, run Qwen, use VLM, start training, or promote local subset
diagnostics to `benchmark_evaluated`.

Phase 5 final delivery report is implemented in
`docs/FINAL_DELIVERY_REPORT.md` and linked from `README.md` and
`docs/FINAL_DELIVERY_CLI.md`. It summarizes the current accepted,
real_model_verified, implemented, and not_started delivery boundaries and keeps
validation subsets, final answer-quality benchmarking, and training status
separate. This is documentation and packaging only.

Phase 5 final delivery readiness check is implemented locally in
`scripts/check_final_delivery_readiness.py` with tests in
`tests/test_check_final_delivery_readiness.py`. The check verifies required
delivery files, user-facing CLI options, required output fields, documentation
boundary snippets, citation/evidence location fields for text/table/image
evidence, and removal of the deprecated PM handoff document. It writes
`result.json`, `summary.json`, and `manifest.json` under
`outputs/final_delivery_readiness/<run_id>/` when used directly. It is a local
packaging/contract guard only: it does not call MinerU, Qwen, BGE-M3, reranker,
datasets, VLM, or training, and it does not claim final answer-quality or
formal benchmark acceptance.

Phase 5 final delivery benchmark gate is implemented locally in
`scripts/run_final_delivery_benchmark_gate.py` with tests in
`tests/test_run_final_delivery_benchmark_gate.py`. The gate safely orchestrates
the final-delivery readiness check, the final AnswerPolicy baseline runner,
and the MP-DocVQA full-workflow diagnostic runner, then writes compact
`result.json`, `summary.json`, `summary.md`, `steps.jsonl`, `preview.json`, and
`manifest.json` artifacts with an optional sync bundle. It is a server-required
diagnostic gate only: it does not train, does not use validation subsets as
training data, and keeps `formal_benchmark_acceptance=false`. Commit `834d1f0`
stabilized the gate artifact contract so local manifests exclude self-hashes
and both local and sync manifests hash the final written artifact contents.
`scripts/inspect_final_delivery_benchmark_gate.py` is implemented locally as a
read-only artifact reviewer for that gate; it verifies manifest hashes, step
statuses, and benchmark/training safety flags without rerunning models.

Server diagnostic `final_delivery_benchmark_gate_server_20260702_componentmetrics`
accepted the final-delivery benchmark gate execution: readiness, AnswerPolicy
baseline, and MP-DocVQA full-workflow diagnostic steps all completed
successfully; `used_qwen=true`, `used_training=false`,
`formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false`. Follow-up review
`final_delivery_gate_metric_review_componentcountfix_20260702` at commit
`e289163` verified local/sync manifest hashes, safety flags, and complete
component-use metrics for the 23 `local_fact_qa` workflow rows. This is
diagnostic-gate acceptance only, not final answer-quality benchmark acceptance.

Phase 5I-B final-answer-quality artifact contract is implemented locally in
`scripts/run_phase5i_answer_quality_benchmark.py`. The runner now writes
`metrics.json`, `predictions.jsonl`, `case_reports.jsonl`,
`failure_analysis.md`, `acceptance_report.json`, and
`training_candidates_raw.jsonl`, plus `manifest.json` with artifact sizes and
hashes, in addition to the historical Phase 5I files. It also forwards
retriever/dense/reranker configuration into `docagent_cli.py`, allowing server
answer-quality probes to explicitly exercise `hybrid_rerank` with BGE-M3 and
the cross-encoder reranker instead of relying on the CLI default retriever.
For model-backed or final-answer-evaluated runs, the runner now preflights the
requested SQLite `db_path` and `doc_id`; if the document is missing or has no
retrievable persisted EvidenceBlocks, it writes blocked artifacts and does not
call `docagent_cli.py` or Qwen. This prevents empty-evidence server probes from
being misread as final answer-quality failures. Server guard validation
`phase5ib_answer_quality_context_block_20260702` at commit `d980841` confirmed
this behavior with `benchmark_status=blocked`, `blocker=db_path_not_found`,
`used_qwen_answer_policy=false`, targeted tests passing, and artifact review
success.
After context inventory, server probe
`phase5ib_answer_quality_selected_context_20260702` ran against
`outputs/docagent.db` / `c1fc1c5e040ec894` with Qwen enabled, but 7/8 cases
failed at metadata level with `cli_status_error` and
`retrieved_evidence_empty`. The uploaded compact artifacts did not include
enough CLI error or retriever initialization detail to classify the exact
server failure. The local artifact contract now writes compact CLI
status/error, retriever initialization metadata, retrieval/citation counts,
artifact directory, and stdout/stderr previews into `case_reports.jsonl` and
`failure_analysis.md`; `scripts/docagent_cli.py` also no longer marks Qwen as
used when retrieval setup fails before AnswerPolicy execution.
Server rerun `phase5ib_answer_quality_selected_context_artifactfix_20260702`
at commit `6e4085b` validated that the selected context still runs with Qwen
and the real retriever stack, but the seven local_fact_qa failures now classify
as `cli_execution` with `cli_error:workflow_failed`; retriever initialization
is `success` for all failed rows, so this is no longer a retriever setup or
missing-context failure. The remaining blocker is the internal workflow
exception cause. The local error contract now preserves workflow exception
class names through `error.cause_type` even when `str(exc)` is empty, so the
next server rerun can classify the exact workflow failure without broad log
inspection.
Server rerun `phase5ib_answer_quality_selected_context_causetype_20260702`
at commit `03928e3` completed successfully and classified the remaining seven
workflow failures as `AssertionError`; retriever initialization was still
`success`. This confirms the blocker is an execution-chain assertion inside
the QA workflow path, not a missing document context, missing retriever, or
training/benchmark issue. The local error artifact contract now includes a
compact `error.traceback_tail` in `local_fact_qa` and Phase 5I-B case reports
so the next server diagnostic can identify the exact assertion frame without
syncing full logs.
Server rerun `phase5ib_answer_quality_selected_context_traceback_20260702`
at commit `9bc8a16` localized that assertion to FAISS search
(`assert d == self.d`) through
`hybrid_retriever -> dense_index.search`, indicating a dense query/index
dimension mismatch. The local CLI now treats legacy dense-index metadata as
reusable only when its `model_id` matches the requested dense encoder; stale
legacy metadata is recorded and rebuilt when `--build-dense-index-if-missing`
is enabled. `DenseIndex.search` now also raises a clear dimension-mismatch
error before reaching FAISS. This is a generic artifact/index compatibility
repair. Server rerun
`phase5ib_answer_quality_selected_context_densefix_20260702` at commit
`f3d26fe` validated the repair with 8/8 CLI statuses successful, no workflow
errors or traceback causes, and stale `hash-dense-256` legacy metadata rebuilt
into BGE-M3 model-specific metadata. The selected-context Phase 5I-B execution
chain is now stable again; the remaining failures are diagnostic
answer/citation quality issues (`answer_keyword_missing`,
`citation_page_mismatch`, `downstream_answer_not_evaluated`), not blockers for
the reusable workflow chain.
`scripts/inspect_phase5i_document_contexts.py` is implemented locally as a
read-only selector for the next server probe. It inventories candidate
SQLite `db_path` / `doc_id` pairs, checks persisted retrievable EvidenceBlocks,
summarizes default or supplied Phase 5I-B case page/keyword context readiness,
and writes compact result, summary, row, preview, manifest, and optional sync
artifacts without calling `docagent_cli.py`, Qwen, BGE-M3, reranker, MinerU,
VLM, or training.
Server inventory `phase5ib_context_inventory_server_20260702` at commit
`f50ce44` succeeded with `ready_document_count=57` and
`candidate_document_count=57`; the strongest Phase 5I-B default-case context
was `outputs/docagent.db` / `c1fc1c5e040ec894`, with parsed MinerU evidence,
5 retrievable blocks, retrievable pages including 24, and 20/26 default cases
having basic page/keyword context readiness.
The artifact contract keeps `formal_benchmark_acceptance=false`,
`validation_subset_used_for_training=false`, and an empty raw training-candidate
export by default, so validation rows are not promoted to training data.
`scripts/inspect_phase5i_answer_quality_artifacts.py` is implemented locally as
a read-only artifact inspector for manifest hashes, required files, safety
flags, metrics/report consistency, and the empty training-candidate export.
Accepted final answer-quality benchmark status remains `not_started`; further
small-scenario answer/citation failures should not be chased unless they expose
a reusable workflow, evidence, citation, or artifact-contract defect.

AnswerPolicy training-pack preprocessing is implemented locally in
`scripts/build_answer_policy_training_pack.py` with tests in
`tests/test_build_answer_policy_training_pack.py`. The script takes train-split
`DocAgentSample` JSONL input and builds audited SFT and GRPO training-format
artifacts: `sft_train.jsonl`, `grpo_train.jsonl`, `sft_audit.json`,
`grpo_audit.json`, `preview.json`, `summary.json`, `summary.md`, and
`manifest.json` with artifact sizes and hashes. It blocks non-train sample
splits and validation-like input paths such as `final_eval` by default, while
preserving `used_training=false`, `training_started=false`,
`validation_subset_used_for_training=false`, and
`formal_benchmark_acceptance=false`. This is preprocessing only; it does not
start SFT/GRPO, call Qwen, load checkpoints, or promote diagnostic validation
subsets to training data.

AnswerPolicy v3 small training-data trial is implemented locally in
`scripts/build_answer_policy_v3_training_data.py` with tests in
`tests/test_answer_policy_v3_contract.py` and
`tests/test_build_answer_policy_v3_training_data.py`. The v3 model target is
`answer`, `supporting_refs`, `support_status`, and `reasoning_summary`; internal
`EvidenceRefMap` metadata maps temporary `E#` refs back to evidence/citation
records without making `block_id`, `doc_id`, or paths model-generation targets.
The local TAT-QA train smoke `answer_policy_v3_tatqa_trial_20260704` produced
200 high-confidence records and preserved `used_training=false`,
`training_started=false`, and `validation_subset_used_for_training=false`.
Server MP-DocVQA train smoke
`mpdocvqa_train_v3_pipeline_splitfix2_20260704` at commit `9433315` used
MinerU API on 5 train documents, materialized 10/10 evidence-ready samples
with answer-text gold-page hit rate 0.8, and produced 7
`evidence_extractive_supported` v3 SFT records while keeping
`used_training=false`, `formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false`.

AnswerPolicy v3 insufficient-evidence data preparation is implemented locally
in `scripts/build_answer_policy_v3_insufficient_data.py` with tests in
`tests/test_build_answer_policy_v3_insufficient_data.py`. The builder uses
train-split TAT-QA questions, samples a different-document decoy evidence board,
confirms the decoy candidate text does not contain the gold answer string, and
emits `insufficient_confirmed` v3 records whose target has
`support_status=insufficient` and empty `supporting_refs`. Local smoke
`answer_policy_v3_tatqa_insufficient_local_smoke_20260704` produced 32 records
with `used_training=false`, `formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false`. Server smoke
`answer_policy_v3_insufficient_server_smoke_20260704_verify` at commit
`00a3fa2` produced 64 insufficient records from
`/root/autodl-tmp/datasets/tatqa/tatqa_dataset_train.json`, then built a
64-record mixed pack that selected 19 insufficient records after MP-DocVQA
shortage backfill. The server run kept `used_training=false`,
`used_qwen=false`, `formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false`. This fills the current Stage 2
negative-sample data-prep gap; it does not start SFT/GRPO or claim answer
quality.

AnswerPolicy v3 schema warmup SFT is real-model verified through
`scripts/run_answer_policy_v3_sft_warmup.py` and server run
`answer_policy_v3_sft_warmup_smoke_20260704` at commit `e9257fd`. The run
rebuilt 80 TAT-QA train v3 records, mixed them with the 7 MP-DocVQA train v3
records, selected 16 records for a 1-step Qwen3-1.7B PEFT LoRA warmup, and
wrote adapter artifacts under
`outputs/training/answer_policy_v3_sft_warmup/answer_policy_v3_sft_warmup_smoke_20260704/adapter`.
It kept `formal_benchmark_acceptance=false` and
`validation_subset_used_for_training=false`; it is a schema/training-path smoke,
not final answer-quality acceptance or GRPO.

AnswerPolicy v3 checkpoint diagnostic is real-model verified through
`scripts/eval_answer_policy_v3_sft_checkpoint.py` and server run
`answer_policy_v3_checkpoint_eval_smoke_20260704`. The diagnostic loaded the
Qwen3-1.7B base model plus the warmup PEFT adapter, evaluated 4 warmup records,
and produced `json_valid_rate=1.0`, `schema_valid_rate=1.0`,
`support_status_match_rate=1.0`, `supporting_refs_subset_rate=1.0`,
`positive_ref_hit_rate=1.0`, and `answer_exact_rate=0.5` with
`used_training=false`, `formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false`. This verifies checkpoint
diagnostic plumbing and v3 output-contract stability on a tiny smoke only; it
does not claim answer-quality improvement.

For expanded AnswerPolicy v3 training, `ms-swift` is the preferred backend
because it supports LoRA, QLoRA, DoRA, GaLore, and related methods. The current
PEFT runner remains a minimal schema-smoke path. Before using `ms-swift` on the
server, run an environment/package preflight and get explicit approval before
installing or replacing packages in the stable `docagent` environment.

AnswerPolicy v3 ms-swift SFT smoke is real-model verified through
`scripts/run_answer_policy_v3_msswift_sft.py`. The server preflight found
`ms-swift=4.2.3`, CUDA available, Qwen3-1.7B present, and both TAT-QA/MP-DocVQA
train-only v3 SFT inputs present. Server dry-run
`answer_policy_v3_msswift_dry_run_20260704` converted 16 v3 records into
Swift message JSONL and wrote the exact `swift sft` command without starting
training. Server execute smoke
`answer_policy_v3_msswift_execute_smoke2_20260704` then trained Qwen3-1.7B for
1 step with LoRA via ms-swift, wrote a PEFT checkpoint under its
`swift_output/.../checkpoint-1` directory, and preserved
`formal_benchmark_acceptance=false` and
`validation_subset_used_for_training=false`. Follow-up checkpoint diagnostic
`answer_policy_v3_msswift_checkpoint_eval_20260704` evaluated 4 records with
`json_valid_rate=1.0`, `schema_valid_rate=1.0`,
`support_status_match_rate=1.0`, `supporting_refs_subset_rate=1.0`,
`positive_ref_hit_rate=1.0`, and `answer_exact_rate=0.5`. This verifies the
ms-swift training entrypoint and checkpoint contract only; full SFT and any
model-quality claim remain not_started.

AnswerPolicy v3 Stage 2 mixed-pack short SFT is real-model verified through
`scripts/build_answer_policy_v3_mixed_sft_pack.py` plus the ms-swift runner.
Server run `answer_policy_v3_mixed_stage2_20260704` built a 64-record
train-only mixed pack from the current v3 TAT-QA and MP-DocVQA train sources.
The target ratio was MP-DocVQA 50%, TAT-QA 40%, insufficient 10%, but the audit
correctly recorded only 7 available MP-DocVQA records and no insufficient
records, so the shortage was backfilled from TAT-QA. Server run
`answer_policy_v3_msswift_stage2_short_20260704` trained Qwen3-1.7B for 3
ms-swift LoRA steps on the mixed pack. Follow-up diagnostic
`answer_policy_v3_msswift_stage2_checkpoint_eval_20260704` evaluated 8 records
with `json_valid_rate=1.0`, `schema_valid_rate=1.0`,
`support_status_match_rate=1.0`, `supporting_refs_subset_rate=1.0`,
`positive_ref_hit_rate=0.875`, and `answer_exact_rate=0.5`, while preserving
`formal_benchmark_acceptance=false` and
`validation_subset_used_for_training=false`. This verifies mixed-pack
construction and short SFT execution only; expanded SFT, final answer-quality
benchmarking, and GRPO remain not_started.

AnswerPolicy v3 prompt-limit contract repair is real-model verified through
`scripts/build_answer_policy_v3_training_data.py` and server run
`answer_policy_v3_promptlimit_stage2_short_20260704_verify` at commit
`800c6ed`. The v3 training prompt now explicitly requires
`reasoning_summary` under 300 characters, matching `ModelOutputV3` validation.
The server rebuilt 80 TAT-QA train records, 64 insufficient records, and a
64-record mixed pack with 19 insufficient records selected after MP-DocVQA
shortage backfill, then trained Qwen3-1.7B for 3 ms-swift LoRA steps.
Checkpoint diagnostic evaluated 8 records with `json_valid_rate=1.0`,
`schema_valid_rate=1.0`, `supporting_refs_subset_rate=1.0`,
`positive_ref_hit_rate=0.625`, and `answer_exact_rate=0.375`, while preserving
`formal_benchmark_acceptance=false` and
`validation_subset_used_for_training=false`. This verifies the prompt/schema
contract after adding insufficient records; answer/status rates remain
small-smoke diagnostics only.

AnswerPolicy v3 MP-DocVQA train expansion is real-model verified through
server run `mpdocvqa_train_v3_expand20_20260704_verify` at commit `cd31d12`.
The run used MinerU API/OCR on 20 MP-DocVQA train documents, materialized
65/65 evidence-ready QA samples with `answer_text_gold_page_hit_rate=0.8615`,
and built 52 high-confidence MP-DocVQA v3 SFT records. The mixed pack
`answer_policy_v3_mixed_expand20_20260704` selected 96 records with category
counts MP-DocVQA 48, TAT-QA 38, and insufficient 10, with no MP-DocVQA
shortage/backfill. Follow-up server run
`answer_policy_v3_msswift_stage2_expand20_short_20260704` trained Qwen3-1.7B
for 3 ms-swift LoRA steps on the expanded pack, and checkpoint diagnostic
`answer_policy_v3_msswift_stage2_expand20_checkpoint_eval_20260704` evaluated
12 records with `json_valid_rate=1.0`, `schema_valid_rate=1.0`,
`supporting_refs_subset_rate=1.0`, `positive_ref_hit_rate=0.5`, and
`answer_exact_rate=0.25`, while preserving `formal_benchmark_acceptance=false`
and `validation_subset_used_for_training=false`. This verifies the expanded
train-data and short training-chain stability only; it does not claim final
model quality or benchmark acceptance.

AnswerPolicy v3 expanded Stage 2 mixed SFT is real-model verified on the
larger train-only data pack. Server run
`mpdocvqa_train_evidence_api_848_resume400_20260705` materialized 848/848
MP-DocVQA train document windows with live MinerU API/OCR; 3036/3039 QA rows
were evidence-ready. The run status is `failed` only because three QA rows
were not evidence-ready; document materialization completed with
`document_failed_count=0`. From this source,
`answer_policy_v3_mpdocvqa_supported_848docs_20260705` produced 2156
high-confidence supported MP-DocVQA v3 SFT records, and
`answer_policy_v3_mpdocvqa_insufficient_848docs_20260705` produced 2000
MP-DocVQA insufficient records. Together with TAT-QA train expansion
(`answer_policy_v3_tatqa_train_full_20260705`, 5000 supported records, and
`answer_policy_v3_tatqa_insufficient_full_20260705`, 2000 insufficient
records), the mixed pack
`answer_policy_v3_mixed_stage2_full4096_20260705` selected 4096 train-only
records with no shortage/backfill: 2048 MP-DocVQA supported, 1638 TAT-QA
supported, and 410 insufficient records.

Server run `answer_policy_v3_msswift_stage2_full4096_1024steps_20260705`
trained Qwen3-1.7B with ms-swift LoRA for 1024 steps on that 4096-record mixed
pack. Training completed successfully in about 940 seconds and wrote adapter
checkpoint `swift_output/v0-20260705-033450/checkpoint-1024`. On the same
64-record v3 contract diagnostic subset, adapter run
`answer_policy_v3_full4096_adapter1024_checkpoint_eval64_20260705` reached
`json_valid_rate=1.0`, `schema_valid_rate=1.0`,
`supporting_refs_subset_rate=1.0`, `support_status_match_rate=0.984375`,
`positive_ref_hit_rate=0.97619`, `insufficient_ref_empty_rate=1.0`, and
`answer_exact_rate=0.796875`. The base-only comparison
`answer_policy_v3_full4096_base_checkpoint_eval64_20260705` reached
`json_valid_rate=0.96875`, `schema_valid_rate=0.96875`,
`support_status_match_rate=0.640625`, `positive_ref_hit_rate=0.707317`,
`insufficient_ref_empty_rate=0.0`, and `answer_exact_rate=0.234375`. This is
strong evidence that the v3 AnswerPolicy output contract and evidence-ref use
improved on the intended train-only diagnostic objective; it is not final
workflow answer-quality benchmark acceptance.

AnswerPolicy v3 reward calibration is implemented locally in
`scripts/calibrate_answer_policy_v3_rewards.py`, with reusable reward
components exposed through `docqa_v3_reward_breakdown`. The v3 reward now
requires a valid `ModelOutputV3` schema before granting answer/status/ref
credit and explicitly scores insufficient-evidence outputs for a refusal-style
answer, preventing malformed or fabricated-insufficient outputs from receiving
full reward. Local smoke
`answer_policy_v3_reward_calibration_local_smoke_20260704` calibrated 32
train-only v3 records. Server run
`answer_policy_v3_reward_calibration_expand20_20260704` then calibrated the
96-record expanded mixed train pack, producing `target_reward_min=1.0`,
`negative_reward_max=0.7`, `invalid_schema_missing_refs.max=0.0`, and
`reward_calibration_status=passed`, while preserving `used_training=false`,
`used_qwen=false`, `formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false`. This is a reward/readiness report
for later best-of-N, DPO, or gated GRPO decisions; it does not start GRPO or
claim model-quality acceptance.

Server run `answer_policy_v3_reward_calibration_full4096_20260705` calibrated
the 4096-record expanded mixed pack. It kept `target_reward_min=1.0`,
`negative_reward_max=0.7`, and `reward_calibration_status=passed`, with
410 insufficient and 3686 supported targets. This keeps best-of-N/DPO design
open and still does not approve GRPO.

AnswerPolicy v3 rejection-sampling artifacts are implemented locally in
`scripts/build_answer_policy_v3_rejection_sampling_artifacts.py`. The builder
reads train-only v3 SFT records plus optional candidate-generation JSONL,
ranks candidates with the calibrated v3 reward, and writes
`ranked_candidates.jsonl`, `selected_candidates.jsonl`,
`preference_pairs.jsonl`, `rejection_sft_candidates.jsonl`, `preview.json`,
`summary.json`, `summary.md`, and `manifest.json`. It blocks validation-like
paths by default and marks synthetic calibration variants as not training-ready
so artifact-shape smokes cannot be mistaken for real rejection-sampling data.
Local smoke `answer_policy_v3_rejection_sampling_local_calibration_smoke_20260704`
ran on 32 train-only records with synthetic calibration variants,
`training_ready_selected_count=0`, `training_ready_preference_pair_count=0`,
`used_training=false`, `used_qwen=false`, and
`validation_subset_used_for_training=false`. Server artifact smoke
`answer_policy_v3_rejection_sampling_expand20_calibration_20260704` at commit
`bd80fc7` ran on the 96-record expanded mixed train-only pack, produced 470
synthetic calibration candidates, 96 selected rows, 96 preference pairs, and
zero training-ready rejection-SFT rows, with `used_training=false`,
`used_qwen=false`, `formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false`.

AnswerPolicy v3 real-model candidate generation is implemented locally in
`scripts/generate_answer_policy_v3_candidates.py`. The script reads train-only
v3 SFT records, blocks validation-like paths, optionally loads a PEFT adapter,
generates multiple `model_generation` candidates per prompt, validates v3
JSON/schema locally, and writes `candidates.jsonl`, preview, summary, and
manifest artifacts without starting training. Local dry-run
`answer_policy_v3_candidate_generation_local_dryrun_20260704` produced 16
synthetic candidates from 8 records and confirmed, via
`answer_policy_v3_rejection_sampling_local_dryrun_candidates_20260704`, that
synthetic candidates remain non-training-ready in the rejection builder.
Server Qwen smoke `answer_policy_v3_candidate_generation_qwen_smoke_20260704`
at commit `e01ebf4` generated 8 real Qwen candidates from 4 train-only records
with `raw_json_ok_rate=1.0`, `schema_ok_rate=1.0`, `used_qwen=true`,
`used_training=false`, and `validation_subset_used_for_training=false`.
Follow-up ranking `answer_policy_v3_rejection_sampling_qwen_smoke_20260704`
consumed the `model_generation` candidates successfully; no selected/pair rows
passed the reward thresholds in this tiny base-model smoke, so no
rejection-SFT rows were emitted and GRPO remains unapproved.

AnswerPolicy v3 adapter-backed rejection distillation artifacts are
real-model verified at the artifact-contract level. Server run
`answer_policy_v3_candidate_generation_expand20_adapter_smoke_20260704` at
commit `f7120c7` loaded the short expanded ms-swift LoRA adapter from
`answer_policy_v3_msswift_stage2_expand20_short_20260704`, generated 24
adapter-backed `model_generation` candidates from 8 train-only records, and
kept `raw_json_ok_rate=1.0`, `schema_ok_rate=1.0`, `used_qwen=true`,
`used_training=false`, and `validation_subset_used_for_training=false`.
Follow-up ranking
`answer_policy_v3_rejection_sampling_expand20_adapter_smoke_20260704`
selected 2 reward-qualified rows into `rejection_sft_candidates.jsonl`;
preference pairs stayed below the reward-margin threshold. Dry-run
`answer_policy_v3_rejection_sft_msswift_dryrun_20260704` accepted those
2 records as ms-swift-compatible SFT input without executing training, with
source counts `mp_docvqa=1` and `tatqa=1`. This verifies the candidate
generation -> reward selection -> rejection-SFT artifact -> ms-swift input
path only; it does not claim answer-quality improvement or approve DPO/GRPO.
Bounded follow-up server run
`answer_policy_v3_candidate_generation_expand20_adapter24x3_20260704` at
commit `25dc367` generated 72 adapter-backed `model_generation` candidates
from 24 train-only records with `raw_json_ok_rate=1.0`,
`schema_ok_rate=1.0`, `used_qwen=true`, `used_training=false`, and
`validation_subset_used_for_training=false`. Ranking run
`answer_policy_v3_rejection_sampling_expand20_adapter24x3_20260704`
selected the best candidate for all 24 records but only 2 rows met the
training-ready rejection-SFT threshold; 22 selected rows were below the chosen
reward threshold and all 24 preference pairs stayed below the reward-margin
threshold. No additional training was started from this run.
To avoid repeatedly sampling the same prefix, `--offset` support was added to
`scripts/generate_answer_policy_v3_candidates.py` and
`scripts/build_answer_policy_v3_rejection_sampling_artifacts.py`, with local
targeted tests covering offset slicing. Server run
`answer_policy_v3_candidate_generation_expand20_adapter_offset24x3_20260704`
at commit `e069da0` used offset 24 / limit 24 over the train-only expanded
mixed pack, generated 72 adapter-backed candidates, and produced
`raw_json_ok_rate=0.9028`, `schema_ok_rate=0.9028`, with 7 `no_json`
candidates. Ranking run
`answer_policy_v3_rejection_sampling_expand20_adapter_offset24x3_20260704`
selected 11 training-ready rejection-SFT rows, with 13 selected rows below the
chosen reward threshold, 2 chosen schema invalid rows, and zero training-ready
preference pairs.
Follow-up server run `answer_policy_v3_rejection_adapter_remaining_slices_20260704`
at commit `ddab988` completed the remaining train-only offset slices 48-71 and
72-95. Offset 48 generated 72 candidates with `raw_json_ok_rate=0.8194`,
`schema_ok_rate=0.8194`, selected 6 training-ready rejection-SFT rows, and
produced 2 training-ready preference pairs. Offset 72 generated 72 candidates
with `raw_json_ok_rate=1.0`, `schema_ok_rate=1.0`, selected 7 training-ready
rejection-SFT rows, and produced 1 training-ready preference pair. Across the
four 24-record slices, the artifact path now has 26 training-ready
rejection-SFT rows and 3 training-ready preference pairs. This is enough for a
small rejection-SFT smoke, but still too small to approve DPO/GRPO.

Full-pack adapter-backed candidate generation is real-model verified at the
post-training artifact level. Server run
`answer_policy_v3_candidates_full4096_adapter1024_256x4_20260705` loaded the
1024-step full4096 ms-swift LoRA adapter, generated 1024 real
`model_generation` candidates from 256 train-only v3 records, and kept
`raw_json_ok_rate=1.0`, `schema_ok_rate=1.0`, `used_qwen=true`,
`used_training=false`, `formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false`. Follow-up ranking
`answer_policy_v3_rejection_full4096_adapter1024_256x4_20260705` selected
222 training-ready rejection-SFT rows and 25 training-ready preference pairs.
This is enough evidence to expand or run a bounded rejection-SFT distillation
experiment; the preference-pair volume remains too small to approve DPO/GRPO.

AnswerPolicy v3 rejection-SFT distillation smoke is real-model verified at the
execution-contract level. Server run
`answer_policy_v3_rejection_sft_msswift_execute_smoke_20260704` at commit
`0ff5792` trained Qwen3-1.7B for 1 ms-swift LoRA step on the 2 train-only
`rejection_sft_candidates.jsonl` rows selected by the adapter-backed rejection
sampler. The run completed with `used_training=true`,
`formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false`. Checkpoint diagnostic
`answer_policy_v3_rejection_sft_checkpoint_eval_20260704` evaluated those same
2 records with `json_valid_rate=1.0`, `schema_valid_rate=1.0`,
`supporting_refs_subset_rate=1.0`, `support_status_match_rate=1.0`,
`positive_ref_hit_rate=1.0`, and `answer_exact_rate=1.0`. This verifies the
rejection-SFT distillation execution path only; it does not establish final
answer-quality improvement.
Follow-up server run
`answer_policy_v3_rejection_sft_adapter_offset24x3_short_20260704` at commit
`e069da0` trained Qwen3-1.7B for 2 ms-swift LoRA steps on 8 of the 11
train-only offset-slice rejection-SFT rows selected above, with source counts
`mp_docvqa=7` and `tatqa=4` in the input audit. Checkpoint diagnostic
`answer_policy_v3_rejection_sft_adapter_offset24x3_checkpoint_eval_20260704`
evaluated 8 rows with `json_valid_rate=1.0`, `schema_valid_rate=1.0`,
`answer_exact_rate=1.0`, `support_status_match_rate=1.0`,
`supporting_refs_subset_rate=1.0`, `positive_ref_hit_rate=1.0`, and
`thinking_rate=0.0`, while keeping `used_training=false`,
`formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false` for the evaluation. This remains a
train-only execution-chain smoke, not a final answer-quality claim.
Merged-slice server run `answer_policy_v3_rejection_sft_merged_slices_20260704`
combined four train-only slices into 26 rejection-SFT records with source
counts `mp_docvqa=18` and `tatqa=8`. Follow-up training run
`answer_policy_v3_rejection_sft_merged_slices_short_20260704` trained
Qwen3-1.7B for 3 ms-swift LoRA steps on 24 selected records, and checkpoint
diagnostic `answer_policy_v3_rejection_sft_merged_slices_checkpoint_eval_20260704`
evaluated 16 records with `json_valid_rate=1.0`, `schema_valid_rate=1.0`,
`answer_exact_rate=1.0`, `support_status_match_rate=1.0`,
`supporting_refs_subset_rate=1.0`, `positive_ref_hit_rate=1.0`, and
`thinking_rate=0.0`. The run used training only in the training step, kept
`formal_benchmark_acceptance=false`, and kept
`validation_subset_used_for_training=false`; it verifies the merged
rejection-SFT execution chain, not final answer-quality improvement.
The ms-swift v3 runner now supports an optional `--adapter-path`, passed to
ms-swift as `--adapters`, so bounded rejection-SFT can continue from an
existing LoRA adapter instead of starting a new adapter from the base model.
Server dry-run `answer_policy_v3_rejection_sft_full4096_adapter_dryrun_20260705`
confirmed the generated command loads the 1024-step full4096 adapter. Server
run `answer_policy_v3_rejection_sft_full4096_adapter_56steps_20260705` then
continued from that adapter on 222 train-only rejection-SFT records for
56 ms-swift update steps, completed in 83.858 seconds, and wrote checkpoint
`swift_output/v0-20260705-044828/checkpoint-56`; train loss was reported as
`0.01333`, with `used_training=true`, `formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false`. Same-input 64-record diagnostics
showed the full4096 adapter at answer-exact 0.875, support-status match
0.984375, positive-ref hit 0.975, and the continued rejection-SFT adapter at
answer-exact 0.921875, support-status match 1.0, positive-ref hit 1.0, with
json/schema/supporting-ref legality and insufficient empty-ref rates all 1.0
for both. This verifies the intended v3 train-only distillation objective and
adapter-continuation execution path; it still does not approve DPO/GRPO or
claim final workflow answer-quality acceptance.
Follow-up full train-only heldout diagnostic
`answer_policy_v3_full4096_mixed_heldout256_compare_20260705` evaluated the
complete 256-record heldout split from the 4096-record mixed pack. Compared
with the 1024-step full4096 adapter, the continued rejection-SFT adapter
improved aggregate json/schema validity 0.9921875 -> 0.99609375,
answer-exact 0.6484375 -> 0.66796875, support-status match 0.984375 ->
0.98828125, supporting-ref subset legality 0.9921875 -> 0.99609375, and
positive-ref hit 0.953586 -> 0.962185, while preserving insufficient
empty-ref at 0.941176 and thinking leakage at 0.0. Source breakdown showed
MP-DocVQA supported answer-exact 0.43609 -> 0.481203 and positive-ref hit
0.924812 -> 0.93985, while TAT-QA supported answer-exact changed 0.867925 ->
0.858491 and positive-ref hit stayed about 0.9904. This indicates no broad v3
contract regression and a modest MP-DocVQA-supported gain, but the TAT-QA
answer-exact dip means the continued adapter remains a candidate checkpoint,
not a default deployment choice or DPO/GRPO approval.

Clean fixed-evidence workflow probes then tested both later checkpoints through
the same 6 curated Phase 5I cases used by the earlier clean6 guard. Server runs
`phase5ib_v3refs_clean6_full4096_adapter1024_20260705` and
`phase5ib_v3refs_clean6_rejection_continue56_20260705` both used real LLM
query rewriting, BGE-M3 retrieval, cross-encoder reranking, Qwen AnswerPolicy,
and `answer_output_contract=v3_refs`; both passed 3/6, with
format/citation/location rates all 1.0. Artifact-only comparisons
`phase5ib_v3refs_clean6_base_vs_full4096_adapter1024_20260705` and
`phase5ib_v3refs_clean6_base_vs_rejection_continue56_20260705` kept the
default deployment gate `blocked`: the prior base clean6 run passed 6/6 and
each adapter regressed 3 cases. Comparison
`phase5ib_v3refs_clean6_full4096_vs_rejection_continue56_20260705` showed the
rejection continuation matched the 1024-step adapter at 3/6; it did not improve
the clean workflow pass signal.

Read-only attribution
`phase5ib_v3refs_clean6_checkpoint_failure_attribution_20260705` compared the
same clean6 case reports and predictions without calling models or training.
It found 3 `both_adapters_regress_from_base` cases and 3 `all_pass` cases. The
adapter-regressed rows preserved citation-page hits and successful
`hybrid_rerank` retrieval, so the failure is not a broken routing, retrieval,
or citation-mapping chain. The generic pattern is AnswerPolicy value selection
from a correct-page table/evidence board, with one answer-selection gap, one
table evidence/metric plus answer-selection gap, and one evidence-keyword
metric gap with a correct answer possible. This blocks default adapter
deployment and does not justify DPO/GRPO; it points to broader fixed-evidence
AnswerPolicy table/value selection work rather than case-specific clean6
repairs.

AnswerPolicy v3 training-prompt contract repair is implemented locally and
server-smoked on train-only data. `scripts/build_answer_policy_v3_training_data.py`
now builds SFT prompts with runtime-style v3 evidence headers
`[E#] kind=... page=...`, includes the shared table/list/key-value extraction
rules used by the workflow prompt, emits the `ModelOutputV3` schema line, and
keeps `calculation_result` observation text intact. Local targeted tests for
v3 data construction, v3 contract validation, mixed-pack building, ms-swift
command generation, checkpoint evaluation, and split plumbing passed. Server
smoke `answer_policy_v3_prompt_contract_tatqa_smoke_20260705` at commit
`a4ef88c` rebuilt 32 TAT-QA train records with
`used_training=false`, `validation_subset_used_for_training=false`,
`formal_benchmark_acceptance=false`, `has_kind_page_candidate=true`, and
`has_legacy_table_prefix=false`. Existing full4096 and rejection-continuation
checkpoints are retained as historical diagnostics; the next SFT experiment
should rebuild train-only data with this repaired prompt contract before
training.

AnswerPolicy v3 promptfix full4096 SFT diagnostic is real-model verified on
train-only data. Server rebuilds
`answer_policy_v3_tatqa_train_full_promptfix_20260705`,
`answer_policy_v3_tatqa_insufficient_full_promptfix_20260705`,
`answer_policy_v3_mpdocvqa_supported_848docs_promptfix_20260705`, and
`answer_policy_v3_mpdocvqa_insufficient_848docs_promptfix_20260705` fed the
mixed pack `answer_policy_v3_mixed_stage2_full4096_promptfix_20260705`.
The pack contains 4096 train-only records with 2048 TAT-QA records,
2048 MP-DocVQA records, and 410 insufficient examples. Split
`answer_policy_v3_full4096_promptfix_split256_20260705` produced 3840 train
rows and 256 heldout rows with `overlap_count=0`.

Server run `answer_policy_v3_msswift_stage2_promptfix3840_1024steps_20260705`
trained Qwen3-1.7B with ms-swift LoRA for 1024 update steps on the promptfix
train split and wrote checkpoint
`swift_output/v0-20260705-060610/checkpoint-1024`. Heldout comparison
`answer_policy_v3_promptfix_heldout256_compare_20260705` showed the adapter
improving the base model on the intended v3 objective: `answer_exact_rate`
0.375 -> 0.5859375, schema validity 0.890625 -> 0.99609375,
`support_status_match_rate` 0.90625 -> 0.97265625, positive-ref hit
0.885106 -> 0.940678, and insufficient empty-ref behavior 0.055556 ->
0.947368. This is training-method and output-contract evidence, not formal
benchmark acceptance.

The same promptfix checkpoint was also run through the clean6 full workflow as
`phase5ib_v3refs_clean6_promptfix_adapter1024_20260705`, using real LLM query
rewriting, BGE-M3 retrieval, cross-encoder reranking, Qwen AnswerPolicy, and
`answer_output_contract=v3_refs`. It passed 4/6 with format, citation, and
location rates all 1.0. Artifact-only comparison
`phase5ib_v3refs_clean6_base_vs_promptfix_adapter1024_20260705` kept the
default deployment gate `blocked` because the base clean6 run passed 6/6 and
candidate regressions remain. This confirms system-chain operability but does
not promote the adapter as the default full-workflow AnswerPolicy.

AnswerPolicy v3 fixed-evidence table/calculation subset selection is
implemented locally in
`scripts/select_answer_policy_v3_fixed_evidence_subset.py`. The selector reads
train-only v3 SFT records, parses runtime-style `[E#] kind=...` evidence
headers, filters by the target `supporting_refs` evidence kind, and writes an
`eval_records.jsonl` subset plus row audit, preview, summary, and manifest. It
blocks validation-like inputs and does not call Qwen, start training, or claim
benchmark acceptance. Local targeted tests passed, and server test validation
passed in the `docagent` environment.

Server run `answer_policy_v3_fixed_evidence_table_calc_promptfix_20260705` at
commit `a9f0117` selected 512 supported table/calculation records from the
repaired-prompt full4096 train-only pack. The selected subset contains 202
`calculation_supported` rows and 310 `table_value_supported` rows, with source
counts MP-DocVQA 218 and TAT-QA 294. Follow-up real-Qwen diagnostic
`answer_policy_v3_fixed_tablecalc_eval128_promptfix_20260705` evaluated 128
selected rows with base Qwen3-1.7B and the promptfix 1024-step adapter. The
adapter improved `answer_exact_rate` 0.5234375 -> 0.7890625 and schema
validity 0.7734375 -> 1.0, while preserving `positive_ref_hit_rate=0.96875`
and `thinking_rate=0.0`. Category breakdown: calculation answer exact improved
0.7692 -> 0.9808, and table-value answer exact improved 0.3553 -> 0.6579.
This is stronger reusable evidence for the fixed-evidence table/calculation
training target than the tiny clean6 workflow guard, but it still does not
promote the adapter as the default full-workflow AnswerPolicy.

AnswerPolicy v3 train-only heldout diagnostic splitting is implemented locally
in `scripts/split_answer_policy_v3_sft_records.py`. The splitter validates v3
SFT records, blocks validation-like input paths by default, writes
non-overlapping `train_sft.jsonl` and `heldout_eval.jsonl`, records excluded
rows, and emits summary/manifest artifacts without calling models or starting
training. Server smoke `answer_policy_v3_heldout_smoke_20260704` at commit
`7a0d68a` used the 96-record expanded train-only mixed pack, produced
64 train records, 16 heldout records, 16 excluded records, and
`overlap_count=0`. Follow-up training
`answer_policy_v3_msswift_heldout_short_20260704` trained Qwen3-1.7B for
3 ms-swift LoRA steps on the train split, and heldout checkpoint diagnostic
`answer_policy_v3_msswift_heldout_checkpoint_eval_20260704` evaluated
16 heldout rows with `json_valid_rate=1.0`, `schema_valid_rate=1.0`,
`supporting_refs_subset_rate=1.0`, `support_status_match_rate=0.8125`,
`positive_ref_hit_rate=0.5625`, `answer_exact_rate=0.25`, and
`thinking_rate=0.0`. This verifies separated train/heldout execution plumbing
on train-only data; it is not final answer-quality acceptance.

AnswerPolicy v3 400-document mixed SFT diagnostic is real-model verified on
the server. MP-DocVQA train materialization
`mpdocvqa_train_evidence_api_400_reuse233_20260704` reused 233 completed
document windows, parsed 167 additional windows with MinerU API/OCR, and
reached 400/400 passed documents with 1467/1469 evidence-ready QA samples.
Converter run `answer_policy_v3_mpdocvqa_train_400docs_20260704` produced
1037 high-confidence MP-DocVQA v3 SFT records. Mixed pack
`answer_policy_v3_mixed_stage2_2048_mp400_20260704` selected 2048 train-only
records with MP-DocVQA 1024, TAT-QA supported 819, and insufficient 205; split
`answer_policy_v3_mixed_stage2_2048_mp400_split128_20260704` produced
1920 train records and 128 heldout records with `overlap_count=0`. Server run
`answer_policy_v3_msswift_stage2_1920_steps480_20260704` trained Qwen3-1.7B
LoRA through ms-swift for `max_steps=480` optimizer update steps, not epochs,
and wrote `checkpoint-480`. Heldout comparison between
`answer_policy_v3_base_only_heldout128_mp400_eval_20260704` and
`answer_policy_v3_msswift_stage2_1920_steps480_heldout128_eval_20260704`
improved `answer_exact_rate` 0.3516 -> 0.5938,
`support_status_match_rate` 0.8828 -> 0.9844, `positive_ref_hit_rate`
0.6814 -> 0.9138, and insufficient empty-ref behavior 0.0 -> 0.9167 while
raising JSON/schema validity to 1.0/1.0. This is train-only heldout diagnostic
evidence that the v3 SFT method can improve the intended contract; it is not
formal benchmark acceptance, validation-subset training, or GRPO approval.

AnswerPolicy v3 480-step checkpoint CLI integration smoke is real-model
verified. `scripts/run_phase5i_answer_quality_benchmark.py` now accepts and
passes `--answer-output-contract` through to `scripts/docagent_cli.py`; local
targeted tests verified the generated CLI command carries `v3_refs`. Server
smoke `phase5ib_v3refs_400doc_checkpoint_cli_smoke_20260704` at commit
`1bc3b2e` ran 2 Phase 5I full-model cases with real LLM query rewriting,
BGE-M3 retrieval, cross-encoder reranking, Qwen3-1.7B plus the 480-step
ms-swift LoRA checkpoint, and `--answer-output-contract v3_refs`. Both cases
used Qwen AnswerPolicy and the LLM query rewriter, retrieved 5 evidence items,
and emitted citations; the recorded commands contain
`--answer-output-contract v3_refs` and `--adapter-path .../checkpoint-480`.
Both rows still failed diagnostic answer/citation checks
(`answer_keyword_missing`, with one `citation_page_mismatch`), so this is
system integration evidence for the trained v3 checkpoint, not final
answer-quality benchmark acceptance.

AnswerPolicy v3 480-step checkpoint system-level comparison is complete as a
diagnostic, not as answer-quality acceptance. Server comparison
`answer_policy_v3_system_compare_base_vs_adapter480_8cases_20260704_pathfix`
read the real workflow artifacts from base run
`phase5ib_v3refs_base_compare8_20260704` and adapter run
`phase5ib_v3refs_adapter480_compare8_20260704`. Both runs used the same 8
Phase 5I selected-context cases with real LLM query rewriting, BGE-M3
retrieval, cross-encoder reranking, Qwen AnswerPolicy, and
`answer_output_contract=v3_refs`. Base passed 2/8 with
`answer_correct_rate=0.125`; the adapter passed 2/8 with
`answer_correct_rate=0.0`. Both kept `format_valid_rate=1.0`,
`citation_valid_rate=1.0`, and `location_valid_rate=0.75`. Case movement was
0 improved, 0 regressed, 2 unchanged passed, and 6 unchanged failed. This
confirms real workflow integration but not system-level answer-quality
improvement, so the next step is failure attribution before more training or
post-training.

Read-only failure inspection
`answer_policy_v3_system_failure_inspect_base_vs_adapter480_8cases_20260704`
then bucketed the 8 rows into 2 already-passed rows, 4
answer-generation-or-keyword-metric rows, and 2
citation-or-expected-page-alignment rows. This reinforces that the next lever
is cleaner system-level evaluation and targeted reusable failure attribution,
not blindly increasing SFT steps or starting GRPO from the current checkpoint.

Phase 5I answer-quality case-quality audit is implemented in
`scripts/audit_phase5i_case_quality.py`. It audits built-in or JSONL Phase 5I
cases and optional existing run artifacts for weak answer keywords, missing
automatic answer-quality gold, and repeated non-expected citation pages without
rerunning models, changing scoring, or creating training data. It writes
`accepted_cases.jsonl`, `accepted_answer_quality_cases.jsonl`, and
`review_cases.jsonl`. Local targeted tests passed, and server read-only audit
`phase5i_case_quality_v3refs_compare8_answerpack_20260704` over the v3_refs
base-vs-adapter artifacts found 12/26 default cases needing review: 8 cases
whose answer keywords are type markers, 5 observed rows where all runs failed
weak answer-keyword checks, and 2 observed rows where all runs cited a
non-expected page. The broader accepted pack contains 14 cases, but
`accepted_answer_quality_case_count=0`; therefore the current default Phase 5I
cases should not be used as the automatic system-level AnswerPolicy
answer-quality target for more training decisions. This is a case-quality
guard, not a benchmark acceptance result.

AnswerPolicy v3 first training report is implemented in
`docs/ANSWER_POLICY_V3_FIRST_TRAINING_REPORT.md`. It summarizes MP-DocVQA
400-window materialization, mixed-pack composition, 1920/128 train-heldout
split, 480-step ms-swift LoRA training configuration, base-vs-adapter heldout
deltas, CLI v3_refs smoke, the 8-case real workflow comparison, limitations,
and the next decision. It records train-only heldout improvement evidence while keeping
`formal_benchmark_acceptance=false`, `validation_subset_used_for_training=false`,
and GRPO unapproved.

AnswerPolicy v3 refs CLI/Qwen integration is real-model verified at commit
`56b7726`. `scripts/docagent_cli.py` now accepts
`--answer-output-contract v3_refs`; Qwen AnswerPolicy can compile the
`docagent_answer_v3_supporting_refs` prompt, parse `ModelOutputV3`, and let the
workflow map temporary `supporting_refs` back to internal citations through
`EvidenceRefMap`. Server smoke
`answer_policy_v3_refs_cli_smoke_retry_20260704` loaded the short expanded
ms-swift SFT adapter through the real CLI path, produced schema-valid v3 JSON
with `support_status=supported` and `supporting_refs=["E1"]`, and mapped the
ref to citation block `c1fc1c5e040ec894_p001_b0002`. This verifies system
integration for the v3 adapter contract; it is not final answer-quality
acceptance.

Phase 5 final raw PDF smoke runner is implemented locally in
`scripts/run_final_raw_pdf_smoke.py` with tests in
`tests/test_run_final_raw_pdf_smoke.py`. The runner executes
`scripts/docagent_cli.py` over one raw PDF with
`--parser mineru_api --live-api` and checks the final delivery execution
contract: first-run file ingestion, MinerU API result artifacts,
EvidenceBlock-backed document metadata, required CLI artifacts, citations,
`evidence_used`, and trace path. It writes
`cases.jsonl`, `results.jsonl`, `summary.json`, `summary.md`, `preview.json`,
and `manifest.json` under `outputs/smoke/final_raw_pdf/<run_id>/`. Real
MinerU API execution is server-verified below. Final answer quality, VLM,
training, and formal benchmark acceptance remain out of this smoke.

A read-only fallback audit found previously generated real MinerU output and
completed
`final_raw_pdf_existing_mineru_audit_20260630` successfully: 4/4 CLI contract
cases passed, 3 cases had citations, and 3 cases had `evidence_used`. This is
`real_model_verified` regression evidence for consuming existing real MinerU
output through `mineru_existing`.

MinerU API raw-PDF file-to-answer execution is accepted as an execution smoke
after server run `final_raw_pdf_mineru_api_cli_smoke_20260630` at commit
`31cdd18`. The run used `/root/autodl-tmp/docagent/.secrets/mineru.env`,
confirmed the MinerU token was configured without printing it, selected a real
PDF under `data/real_documents/globocan_africa_2022/`, executed
`scripts/run_final_raw_pdf_smoke.py --parser mineru_api --live-api`, and
reported `used_mineru_api=true`, `used_online_mineru_ocr=true`, 4/4 passed
cases, 0 failures, 3 citation-bearing cases, and 3 `evidence_used` cases.
Artifacts were written under
`outputs/smoke/final_raw_pdf_api/final_raw_pdf_mineru_api_cli_smoke_20260630/`
with a compact sync bundle under
`outputs/sync/final_raw_pdf_mineru_api_cli_smoke_20260630/`. This accepts the
raw PDF -> MinerU API -> EvidenceBlock -> CLI artifact/citation contract path;
it does not evaluate final answer correctness. Local MinerU CLI execution is
no longer a final-delivery target unless explicitly reopened later.
After removing the final-delivery local CLI path, server rerun
`final_raw_pdf_mineru_api_api_only_cleanup_20260630` at commit `060ad85`
confirmed the API-only smoke remains accepted: parser `mineru_api`,
`used_mineru_api=true`, `used_online_mineru_ocr=true`, 4/4 cases passed, and
no failure reasons.

MinerU API secret-file support is implemented and server-verified in
`docagent/integrations/mineru_api.py`, `scripts/ingest_document.py`, and
`scripts/run_phase4b_mpdocvqa_ingestion.py`. `MinerUApiClient` still accepts
the historical `MINERU_TOKEN` environment variable and now also accepts an
explicit env file containing either `MINERU_TOKEN=...` or `API_TOKEN=...`;
the existing ingestion scripts default to `.secrets/mineru.env` when the file
exists and expose `--mineru-env-file` for manual override. The server
`final_raw_pdf_mineru_api_cli_smoke_20260630` run verified this secret-file
path without committing or printing the token.

MinerU API file-to-answer support is implemented locally in
`scripts/docagent_cli.py`. The final CLI now accepts
`--parser mineru_api --live-api` with optional `--mineru-env-file`, runs
`MinerUApiClient` into the document cache, then reuses the same
`MinerUParserBackend(mode=parse_existing)`, EvidenceBlock persistence, Router,
tools, citations, and artifact-writing path as existing MinerU output. Local
tests cover missing `--live-api`, fake API ingestion, artifact flags, and
secret-file argument plumbing. The live server API smoke
`final_raw_pdf_mineru_api_cli_smoke_20260630` accepted this path as execution
stability evidence, not final answer-quality evidence.

Phase 5 MP-DocVQA evidence materialization is implemented locally in
`scripts/prepare_mpdocvqa_evidence.py` with tests in
`tests/test_prepare_mpdocvqa_evidence.py`. The runner reads the prepared
`outputs/final_eval/mpdocvqa_val_subset` documents and sample manifest, calls
`scripts/docagent_cli.py --parser mineru_api --live-api` per selected PDF,
persists MinerU-backed EvidenceBlocks to a local SQLite database, and writes
`documents.jsonl`, `sample_evidence_manifest.jsonl`, `summary.json`,
`summary.md`, `preview.json`, and `manifest.json`. It records the mapping from
MP-DocVQA window ids to actual ingested DocAgent ids and page-level evidence
readiness. Status is `accepted`: server run
`mpdocvqa_evidence_api_smoke_20260630` at commit `d325800` used live MinerU
API/OCR for 2 selected MP-DocVQA PDFs, passed 2/2 document materializations,
and produced evidence-ready rows for 4/4 samples. The full selected-subset
run initially exposed a transient MinerU result download `IncompleteRead`; the
generic API retry/resume hardening at commit `13b1dc1` then passed server run
`mpdocvqa_evidence_api_retry_failed_hardened_20260630` with 10/10 documents
materialized and 55/55 samples evidence-ready. This is evidence-readiness and
artifact-contract acceptance, not final answer-quality benchmark acceptance.

Phase 5 full-workflow real retriever CLI wiring is real-model verified in
`scripts/docagent_cli.py`. The CLI can now run `local_fact_qa` with explicit
`bm25`, `dense`, `hybrid`, or `hybrid_rerank` retrieval modes and records
retriever metadata plus workflow trace artifacts. Server run
`final_full_workflow_hybrid_rerank_smoke_rowalign_20260630` at commit
`b0d274f` verified the final delivery execution chain on a materialized
MP-DocVQA PDF: rule Router main path, LLM Router trigger probe, LLM Query
Planner, real BGE-M3 dense retrieval, real bge-reranker-v2-m3 cross-encoder
reranking, Qwen AnswerPolicy, persisted `summary.json`/`trace.json`, and
workflow trace steps
`retrieve_evidence -> build_evidence_context -> generate_answer ->
check_format -> check_location -> answer_repair -> finalize`. The run used
84 evidence blocks, built a BGE index, returned 5 retrieval candidates and 1
citation, and passed all execution-chain checks. This is `real_model_verified`
execution evidence only; it does not evaluate final answer correctness or mark
MP-DocVQA/TAT-QA benchmark acceptance.

Post-scope-rule full-chain sanity rerun
`final_delivery_chain_sanity_after_scope_rules_20260702` at commit `e3b5c43`
confirmed the same delivery path still works after the MinerU evidence metadata
and delivery-focused scope-rule updates. It used the existing MP-DocVQA
EvidenceBlock DB, real LLM Router fallback, LLM Query Rewriter, Qwen base
AnswerPolicy, BGE-M3 dense retrieval, and bge-reranker-v2-m3 on 4 rows:
`cli_success_rate=1.0`, Qwen/dense/reranker/query-rewriter use `4/4`,
`retrieved_gold_page_hit_rate=1.0`, `citation_page_hit_rate=1.0`, and
`answer_hit_rate=0.75`. This is a compact execution-chain regression only, not
formal benchmark or answer-quality acceptance.

Phase 5 raw PDF full-model workflow baseline is real-model verified after
fresh server run
`final_raw_pdf_full_workflow_api_hybrid_qwen_fresh_20260630_172350` at commit
`8a61600`. The run started from one `--file` raw PDF input, used a fresh DB,
ingested the document through live MinerU API without reusing an existing
record, then completed one CLI workflow through LLM Router fallback, LLM Query
Planner/Rewriter, `hybrid_rerank` retrieval, real BGE-M3 dense embeddings on
`cuda:0`, real bge-reranker-v2-m3 cross-encoder reranking on CPU, and Qwen
base AnswerPolicy. It produced non-empty `answer`, `reasoning_summary`,
`evidence_used`, and `citations`, wrote `summary.json`, `result.json`,
`trace.json`, and `router_plan.json`, and recorded workflow steps
`retrieve_evidence -> build_evidence_context -> generate_answer ->
check_format -> check_location -> finalize`. This is the current whole-chain
usability baseline for future changes; it is not final answer-quality or
formal benchmark acceptance.

Phase 5 MP-DocVQA retrieval inspection is implemented locally in
`scripts/inspect_mpdocvqa_retrieval.py` with tests in
`tests/test_inspect_mpdocvqa_retrieval.py`. The script reads existing
AnswerPolicy baseline or attribution artifacts plus the MP-DocVQA evidence
SQLite DB, then separates generic retrieval-stage signals: whether the gold
page has retrievable MinerU/EvidenceBlock text, whether retrieved/selected/
cited blocks hit the gold page, first gold-page retrieval rank, recall@1/3/5,
and buckets such as `retrieval_gold_page_miss`,
`gold_page_without_retrievable_blocks`, `selected_context_gold_page_miss`, and
`answer_generation_or_metric_miss`. It writes `result.json`, `summary.json`,
`summary.md`, `mpdocvqa_retrieval_rows.jsonl`, `preview.json`, `manifest.json`,
and an optional compact sync bundle. This is artifact-only diagnostic tooling:
it does not call Qwen, start SFT/GRPO, create training records, tune against
validation rows, or claim benchmark acceptance.

Phase 5 MP-DocVQA full-workflow diagnostic runner is implemented locally in
`scripts/run_mpdocvqa_full_workflow_diagnostic.py` with tests in
`tests/test_run_mpdocvqa_full_workflow_diagnostic.py`. The runner reads
selected rows from the MP-DocVQA evidence manifest, calls
`scripts/docagent_cli.py --doc-id <ingested_doc_id> --question <question>`
with `--full-model-path`, configurable Router/Rewriter, BGE-M3,
`hybrid_rerank`, reranker, and Qwen AnswerPolicy options, then evaluates the
resulting CLI artifacts for execution success, retrieved/selected/cited
gold-page hits, answer hit, trace steps, and failure buckets. This is the
bridge from the old direct `run_qa_workflow` legacy-BM25 baseline to the
accepted CLI full-model path. Status is `implemented`: local tests use a fake
CLI runner and validate the artifact contract. Server evidence below upgrades
the runner to `real_model_verified` for diagnostic execution only, not formal
benchmark acceptance.

Server diagnostic `mpdocvqa_full_workflow_hybrid_qwen_limit8_20260630` at
commit `0fe4859` real-model verified the runner on 8 MP-DocVQA evidence-ready
rows. The run completed with `cli_success_rate=1.0`, `used_qwen_answer_policy`
8/8, dense retrieval 8/8, reranker 8/8, `retrieved_gold_page_hit_rate=0.875`,
`selected_gold_page_hit_rate=0.875`, `citation_page_hit_rate=0.875`,
`answer_hit_rate=0.5`, and bucket counts `passed=4`,
`answer_generation_or_metric_miss=3`, `retrieval_gold_page_miss=1`. This
confirms the accepted CLI full-model/hybrid_rerank path behaves materially
better than the old direct legacy-BM25 MP-DocVQA baseline on this small
diagnostic slice. It remains diagnostic-only and is not formal MP-DocVQA
benchmark acceptance.

Server diagnostic `mpdocvqa_full_workflow_hybrid_qwen_offset8_limit16_20260630`
at commit `afaf8a5` extended the same path to the next 16 MP-DocVQA
evidence-ready rows. The run completed with `cli_success_rate=1.0`, Qwen,
dense retrieval, and reranker use on 15/16 rows, `retrieved_gold_page_hit_rate`
`0.4375`, `selected_gold_page_hit_rate=0.4375`, `citation_page_hit_rate=0.4375`,
`answer_hit_rate=0.375`, and bucket counts `retrieval_gold_page_miss=8`,
`answer_generation_or_metric_miss=4`, `passed=3`, and
`task_type_not_local_fact_qa=1`. This keeps the execution chain
real-model verified but shows that MP-DocVQA quality bottlenecks vary by
chunk and should be inspected at the retrieval/query/block-granularity level
before any training decision.

Phase 5 MP-DocVQA full-workflow comparison is implemented locally in
`scripts/compare_mpdocvqa_full_workflow_runs.py` with tests in
`tests/test_compare_mpdocvqa_full_workflow_runs.py`. The script reads existing
full-workflow diagnostic artifacts, aggregates per-run and cross-run
CLI/component use, retrieved/selected/cited gold-page hits, answer hits,
failure buckets, preview rows, manifest, and an optional sync bundle. It does
not call Qwen, start SFT/GRPO, create training records, tune against validation
rows, or claim benchmark acceptance.

Server artifact-only diagnostic `mpdocvqa_full_workflow_compare_24rows_20260701`
at commit `ece6221` real-model verified the comparison tool against the two
existing MP-DocVQA full-workflow chunks. It aggregated 24 rows with
`cli_success_rate=1.0`, `local_fact_qa_count=23`, Qwen, dense retrieval, and
reranker use on 23/23 local_fact_qa rows, `retrieved_gold_page_hit_rate=0.5833`,
`citation_page_hit_rate=0.5833`, `answer_hit_rate=0.4167`, and bucket counts
`retrieval_gold_page_miss=9`, `answer_generation_or_metric_miss=7`,
`passed=7`, `task_type_not_local_fact_qa=1`. The recommendation remains
`inspect_retrieval_query_or_block_granularity_before_training`; this is still
diagnostic-only and not formal benchmark acceptance.

Phase 5 MP-DocVQA query/block granularity inspection is implemented locally in
`scripts/inspect_mpdocvqa_query_block_granularity.py` with tests in
`tests/test_inspect_mpdocvqa_query_block_granularity.py`. The script reads
existing comparison or full-workflow rows plus the MP-DocVQA EvidenceBlock
SQLite DB, then separates retrieval misses into evidence DB/mapping, gold-page
OCR or answer-text availability, query-answer bridge weakness, and
retriever/block scoring buckets. It does not call Qwen, start SFT/GRPO, create
training records, tune against validation rows, or claim benchmark acceptance.

Server artifact-only diagnostic `mpdocvqa_query_block_granularity_24rows_20260701`
at commit `bd64f64` real-model verified the query/block granularity tool
against the 24-row comparison artifact and MP-DocVQA EvidenceBlock DB. It
inspected 9 retrieval misses and found `gold_page_answer_text_not_found=8` and
`gold_page_without_retrievable_blocks=1`, with `gold_page_answer_text_hit_rate`
`0.0` and `gold_page_question_overlap_rate=0.0`. This means the next useful
diagnostic is OCR/page alignment or gold-page text availability before changing
retrieval scoring, query rewriting, or training.

Phase 5 MP-DocVQA OCR/page alignment inspection is implemented locally in
`scripts/inspect_mpdocvqa_ocr_page_alignment.py` with tests in
`tests/test_inspect_mpdocvqa_ocr_page_alignment.py`. The script reads the
query/block inspection rows plus the MP-DocVQA EvidenceBlock SQLite DB, then
checks exact gold pages, gold page -1, gold page +1, retrieved pages, and all
document pages for answer text. It separates likely page-index offset,
gold-page mapping mismatch, missing retrievable page blocks, and answer text
not found in OCR. It does not call Qwen, start SFT/GRPO, create training
records, tune against validation rows, or claim benchmark acceptance.

Server artifact-only diagnostic `mpdocvqa_ocr_page_alignment_24rows_20260701`
at commit `634a7ef` real-model verified the OCR/page alignment tool against
the 24-row workflow comparison lineage and MP-DocVQA EvidenceBlock DB. It
inspected 9 retrieval misses and found `answer_on_gold_minus_one_page=5`,
`answer_elsewhere_in_document=1`, `answer_not_found_in_document_text=2`, and
`gold_page_without_retrievable_blocks=1`. The answer was found somewhere in
the document for 6/9 inspected rows and on an adjacent page for 5/9 rows. The
next diagnostic is page-index alignment before retrieval scoring, query
rewriting, model prompting, or training changes.

Phase 5 MP-DocVQA page-index alignment inspection is implemented locally in
`scripts/inspect_mpdocvqa_page_index_alignment.py` with tests in
`tests/test_inspect_mpdocvqa_page_index_alignment.py`. The script cross-checks
OCR/page alignment rows against prepared `qa.jsonl`, final
`sample_manifest.jsonl`, document window manifests, the materialized
`sample_evidence_manifest.jsonl`, and the EvidenceBlock SQLite DB. It treats
the current MP-DocVQA window PDF as the document whose pages are `1..N`; source
page ids such as `fpbw0217_p17` are retained for traceability, while printed
page numbers inside the image/OCR text are not used as citation page ids. The
script only recommends page-mapping repair when `answer_page_idx`,
`gold_page_ordinal`, final manifest pages, or evidence-manifest pages disagree.
If answer text appears on an adjacent page while those page fields remain
consistent, the next step is manual/OCR/text-match review rather than gold-page
normalization. It is diagnostic-only: it does not change gold pages, call Qwen,
start training, create training data, tune per validation row, or claim
benchmark acceptance.

Server artifact-only diagnostic
`mpdocvqa_page_index_alignment_semantic_24rows_20260701` at commit `b377d1c`
validated the page-index audit on the 24-row full-workflow lineage. It
inspected 9 rows, found dominant answer-page shift `-1` at rate `0.8333`, but
also confirmed `answer_page_idx`, prepared manifests, and materialized
EvidenceBlock gold pages are mutually consistent at rate `1.0`. Therefore this
does not justify shifting MP-DocVQA gold pages or changing citation page
semantics. The next action is manual/OCR answer-text-hit review before retrieval
or training changes.

Phase 5 MP-DocVQA page-alignment manual review extraction is implemented
locally in `scripts/extract_mpdocvqa_page_alignment_review.py` with tests in
`tests/test_extract_mpdocvqa_page_alignment_review.py`. The script reads a
page-index audit artifact, prepared document manifests, page image paths, and
the EvidenceBlock DB, then emits compact `manual_review.jsonl` and
`manual_review.md` rows with current-window page numbers, source page ids, PDF
and image paths, OCR previews, and review buckets. It does not call models,
change page mappings, create training data, tune retrieval, or claim benchmark
acceptance. Server artifact-only validation
`mpdocvqa_page_alignment_manual_review_24rows_20260701` at commit `47f0997`
passed targeted tests and produced 9 manual-review rows from the server-side
page-index artifact and MP-DocVQA EvidenceBlock DB. Bucket counts were
`manual_compare_gold_and_adjacent_page_images=5`,
`manual_check_ocr_text_or_answer_alias=2`,
`manual_check_gold_annotation_or_duplicate_answer=1`, and
`manual_check_mineru_page_block_materialization=1`. The source page-index
mapping rates stayed at `1.0`, so the next step remains manual/OCR inspection
before retrieval or training changes.

Phase 5 AnswerPolicy IO candidate schema and citation allowlist are
implemented locally in `docagent/workflow/answer_contract.py`,
`docagent/models/output_parser.py`, `docagent/workflow/output_adapter.py`,
`docagent/workflow/graph.py`, and `docagent/tools/local_fact_qa.py`. The model
output parser now accepts both the legacy
`answer/evidence_location/evidence/reason` schema and the candidate
`answer/reasoning_summary/citation_block_ids/evidence_used` schema. The
workflow canonicalization layer filters model-selected citation block ids to
the citation allowlist, records invalid ids in `citation_validation`, and
exposes canonical `reasoning_summary`, `evidence_used`, and `citations`
through `local_fact_qa`. After the first real Qwen smoke, the citation
allowlist also includes deterministic tool-result citation blocks as preferred
sources, so table/calculation tool evidence is not dropped merely because the
retrieval top-k omitted the table block or the model cited a weaker retrieved
block. Status is `implemented`: local tests verify the contract and backwards
compatibility. The shared prompt compiler now uses
`docagent_answer_v2_candidate_citations` and asks Qwen-style AnswerPolicy
outputs for `answer`, `reasoning_summary`, `citation_block_ids`, and
`evidence_used`; SFT/GRPO record builders and reward/eval helpers can read the
candidate citation location as well as the legacy `evidence_location`. This is
not a Qwen server baseline, prompt-quality acceptance, training execution,
checkpoint update, or final answer benchmark.

Phase 5 final subset AnswerPolicy baseline runner is implemented locally in
`scripts/run_final_answer_policy_baseline.py` with tests in
`tests/test_run_final_answer_policy_baseline.py`. It runs an AnswerPolicy over
prepared TAT-QA `local_fact_qa` evidence cases and
`table_lookup`/`simple_calculation` tool-result cases, writes compact
diagnostic artifacts (`result.json`, `results.jsonl`, `summary.json`,
`summary.md`, `preview.json`, `failures_sample.jsonl`, `manifest.json`) and
can create an optional compact `outputs/sync/<run_id>/` bundle for server
result return. Per-row diagnostics include compact final answers, citation
validation, raw output previews, token/latency metadata, selected/dropped
block ids, compact tool results for table/calculation prompts, and evidence
context hashes, without syncing full prompts or logs. It explicitly skips
MP-DocVQA manifest rows unless `--mpdocvqa-evidence-manifest` and
`--mpdocvqa-db-path` point to materialized MinerU EvidenceBlocks from
`scripts/prepare_mpdocvqa_evidence.py`; when those artifacts are present it
evaluates MP-DocVQA rows with page-level citation checks.
Local smoke uses heuristic/fake policies only. The first server-side Qwen base
diagnostic smoke ran with run id
`answer_policy_training_gate_qwen_smoke_20260629`: `used_qwen=true`,
`used_training=false`, `formal_benchmark_acceptance=false`, `case_count=24`,
`evaluated_count=12`, `format_valid_rate=1.0`, `answer_hit_rate=0.75`,
`citation_block_hit_rate=0.75`, and `pass_rate=0.5833`. The review gate
recommended `citation_contract_repair_before_training`, so Qwen execution is
`real_model_verified` for smoke only. After tool-result citation allowlist
repair, the server rerun
`answer_policy_training_gate_qwen_tool_citation_fix_20260629` reached
`citation_block_hit_rate=1.0`, `pass_rate=0.75`, and no
`citation_block_miss`; the remaining review blocker was
`invalid_model_selected_citation_ids_present`, meaning invalid raw model
citation ids had been filtered from the canonical final output but were still
treated as a hard pre-training blocker. Prompt-quality acceptance, training,
and formal benchmark status remain `not_started`.

Phase 5 AnswerPolicy baseline review gate is implemented locally in
`scripts/review_answer_policy_baseline.py` with tests in
`tests/test_review_answer_policy_baseline.py`. It reads either a full
AnswerPolicy baseline artifact directory or a compact `outputs/sync/<run_id>/`
bundle, then writes `review.json` and `review.md` with failure distributions,
compact failed samples, and a diagnostic training-gate recommendation. Missing
baseline artifacts return a structured failed review. The gate now treats
filtered invalid raw model citation ids as diagnostic when final canonical
citations hit the gold block and there is no `citation_block_miss`; invalid
ids remain a hard citation-contract blocker only when final citations are
empty or miss.
Server review rerun `answer_policy_review_gate_filtered_invalid_20260629`
accepted the diagnostic gate with `recommendation=continue_qwen_eval_before_training`,
`sft_gate=defer`, `invalid_citation_id_count_in_rows=3`, and
`failure_reason_distribution=answer_miss:3`. This gate does not start SFT,
start GRPO, accept Qwen prompt quality, or promote local diagnostics to a
formal benchmark result.

The review gate now also distinguishes unrepaired parse/schema failures from
candidate outputs that failed the narrow model-output schema but were
canonicalized into a final `format_valid=true` answer. Repaired parse/schema
failures remain diagnostic and do not preempt answer-quality or SFT-candidate
recommendations; unrepaired failures still return
`prompt_or_parser_repair_before_training`. This semantic repair is
implemented locally and was validated by the review-only server rerun
`answer_policy_full80_repaired_parse_review_20260629` at commit `9f8a23d`.
The rerun used the existing full80 tablefix baseline artifacts, did not rerun
Qwen, did not train, and returned
`recommendation=continue_qwen_eval_before_training`, `sft_gate=defer`,
`parse_fail_count_in_rows=1`, `repaired_parse_fail_count_in_rows=1`,
`unrepaired_parse_fail_count_in_rows=0`,
`invalid_citation_id_count_in_rows=16`, and
`answer_miss_count_in_rows=19`.

Phase 5 AnswerPolicy answer-miss artifact review is implemented locally in
`scripts/review_answer_policy_answer_misses.py` with tests in
`tests/test_review_answer_policy_answer_misses.py`. It reads an existing
AnswerPolicy baseline artifact directory, selects rows with `answer_miss`,
assigns broad diagnostic buckets, and writes `result.json`, `summary.json`,
`summary.md`, `answer_miss_rows.jsonl`, `preview.json`, and `manifest.json`.
The review is artifact-only: it does not rerun Qwen, create training records,
start SFT/GRPO, or tune against individual validation examples. The initial
server one-off diagnostic `answer_policy_full80_answer_miss_review_20260630`
over the full80 tablefix baseline found 19 answer misses with bucket counts
`answer_granularity_or_metric_review=3`,
`calculation_reasoning_or_operand_review=7`,
`model_extractive_precision_review=4`,
`repaired_parse_plus_answer_miss=1`, and
`table_selection_or_column_review=4`.

The tracked server validation
`answer_policy_full80_answer_miss_review_tracked_20260630` succeeded at commit
`2b2a431` against the real-Qwen full80 tablefix baseline artifact. It found
the same 19 answer misses and reported bucket counts
`answer_granularity_or_metric_review=2`,
`calculation_reasoning_or_operand_review=7`,
`model_extractive_precision_review=4`,
`repaired_parse_plus_answer_miss=1`, and
`table_selection_or_column_review=5`, with `used_training=false`,
`formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false`. The one-bucket shift from the
one-off diagnostic comes from the tracked script's generic bucket assignment,
not from sample-specific tuning. This is diagnostic evidence for generic tool,
prompt, or metric review before training decisions; it is not final answer
quality acceptance or benchmark evaluation.

Phase 5 AnswerPolicy generic tool-output pretraining inspection is implemented
locally in `scripts/inspect_answer_policy_tool_outputs.py` with tests in
`tests/test_inspect_answer_policy_tool_outputs.py`. It reads an existing
AnswerPolicy baseline artifact directory, filters answer-miss rows that
expected `table_lookup` or `simple_calculation`, and writes `result.json`,
`summary.json`, `summary.md`, `tool_output_rows.jsonl`, `preview.json`, and
`manifest.json`. The inspection separates tool execution or contract issues,
generic table-selection issues, generic calculation operand or operation
issues, model failures to use a gold-overlapping tool answer, and answer
granularity or metric-normalization hints. It is artifact-only: it does not
rerun Qwen, create training records, start SFT/GRPO, or tune against
individual validation examples. Server validation on the full80 tablefix
baseline artifact succeeded with run id
`answer_policy_tool_output_inspect_full80_tablefix_20260630` at commit
`61d5321`. It used the existing real-Qwen full80 tablefix baseline artifact,
did not rerun Qwen, did not train, and returned
`answer_miss_count=19`, `tool_expected_answer_miss_count=12`,
`non_tool_answer_miss_count=7`, `tool_status_counts=success:12`,
`tool_operation_counts=simple_calculation:7, table_lookup:5`, and bucket
counts `generic_calculation_operand_or_operation_review=6`,
`generic_table_selection_or_column_review=4`, and
`model_did_not_use_correct_tool_output=2`. The recommendation is
`inspect_generic_table_or_calculation_tool_outputs_before_training`, with
`used_training=false`, `formal_benchmark_acceptance=false`, and
`validation_subset_used_for_training=false`.

The first generic table-tool repair after that inspection is implemented
locally in `docagent/tools/table_tools.py` with tests in
`tests/test_phase5_table_tools.py`. It improves deterministic table lookup
and simple calculation for total-across-year sums, percentage
increase/decrease wording, percentage-of-total expressions, same-row
multi-year averages with currency-parentheses negative numbers, requested
period/quarter/as-reported lookup columns, multi-column respective lookup
values, and who/name table answers. The repair is general table-tool behavior,
not per-sample logic, does not change AnswerPolicy prompts, does not rerun
Qwen locally, and does not start SFT/GRPO. Server rerun on the full80 tablefix
baseline succeeded with run id `final_eval_tatqa_table_tool_repair_20260630`
at commit `7cac9fe`. The deterministic TAT-QA subset diagnostic returned
`case_count=80`, `pass_rate=0.825`, `tool_executed_count=60`,
`tool_success_count=57`, `answer_hit_count=46`, `answer_hit_rate=0.7667`,
`numeric_accuracy_rate=0.7`, and `citation_block_hit_rate=1.0`; remaining
failures were `answer_miss=14` and `table_lookup_unsupported=3`. This accepts
the deterministic table-tool repair only. It used no Qwen, no training, no
VLM, and is not final answer-quality acceptance or formal benchmark
acceptance.

The full 80-sample real-Qwen diagnostic gate was rerun after the generic
table-tool repair with run id
`answer_policy_training_gate_qwen_full80_generic_tablefix_20260630` at commit
`c0a7640`. It evaluated the same 80 TAT-QA AnswerPolicy cases, skipped the
55 MP-DocVQA manifest rows that still require raw PDF/MinerU/retrieval
evidence, used Qwen base, did not train, and did not claim formal benchmark
acceptance. The baseline improved to `pass_rate=0.85`,
`answer_hit_rate=0.85`, `citation_block_hit_rate=1.0`,
`format_valid_rate=1.0`, and `failure_reason_distribution=answer_miss:12`.
The review recommendation is `continue_qwen_eval_before_training`, with
`sft_gate=defer`, `grpo_gate=defer_until_sft_result`, and SFT candidates
skipped. This is real-Qwen diagnostic evidence that the generic table-tool
repair improves the model-enhanced path; it is not final answer-quality
acceptance or benchmark evaluation.

Phase 5 AnswerPolicy SFT candidate data builder is implemented locally in
`scripts/build_answer_policy_sft_candidates.py` with tests in
`tests/test_build_answer_policy_sft_candidates.py`. It reads a real-Qwen-marked
AnswerPolicy baseline artifact directory or sync bundle, selects failed TAT-QA
AnswerPolicy rows, reconstructs prompt-v2 SFT candidate records from the
prepared TAT-QA samples plus compact tool results, and writes
`sft_candidates.jsonl`, `summary.json`, `summary.md`, `preview.json`,
`result.json`, and `manifest.json`. It blocks heuristic/fake non-Qwen baselines
to avoid treating local smoke output as training evidence. This is candidate
data design only; it does not start SFT/GRPO or claim final model quality.

Phase 5 AnswerPolicy SFT candidate review is implemented locally in
`scripts/review_answer_policy_sft_candidates.py` with tests in
`tests/test_review_answer_policy_sft_candidates.py`. It reviews a larger
real-Qwen baseline directory and the generated SFT candidate directory,
summarizes answer misses, candidate alignment, malformed target fields,
missing tool-result context, preview artifacts, and `manual_review.jsonl`.
The server one-off inspection of
`answer_policy_training_gate_qwen_larger40_20260629` found 14 TAT-QA answer
misses, 13 generated SFT candidate records, one failed sample without a
candidate because tool execution failed, and the recommendation
`manual_review_sft_candidates_before_training`. Server validation of the
tracked script succeeded with run id
`answer_policy_sft_candidate_review_larger40_20260629_tracked`: candidate
target quality flags were clean, `failed_without_candidate_count=1`,
`used_training=false`, and `formal_benchmark_acceptance=false`. It does not
start SFT, start GRPO, accept model quality, or promote the diagnostic run to
a formal benchmark.

The follow-up manual review extraction
`answer_policy_manual_review_extract_larger40_20260629` found 14 answer-miss
rows with bucket counts `table_lookup_answer_miss_with_tool=6`,
`calculation_answer_miss_with_tool=5`, `generation_answer_miss_review=2`,
and `tool_failure_without_candidate=1`. Most candidate targets hit the gold
answer, while many successful tool outputs did not, so immediate SFT would mix
gold targets with misleading tool context. The local review script now writes
enriched full `manual_review.jsonl` rows with review bucket, prediction/tool/
candidate gold-hit hints, target citations, and raw output previews, and it
recommends `inspect_tool_and_metric_failures_before_sft` when tool or metric
issues are present. Server validation of the enriched review succeeded with
run id `answer_policy_sft_candidate_review_larger40_enriched_20260629`.
The next required action is tool/metric repair before any SFT data or training
decision.

The first local tool repair is implemented in `docagent/tools/table_tools.py`
with tests in `tests/test_phase5_table_tools.py`: `table_lookup_or_calculation`
now performs `simple_calculation` only when `selected_tools` explicitly
contains `simple_calculation`. It no longer upgrades table lookup to
calculation merely because the question text contains row-label terms such as
`decrease` or `weighted-average`. Local tests pass; the larger40 server rerun
is pending and this repair is not yet a final answer-quality acceptance.

The next local table-tool repair is implemented in
`docagent/tools/table_tools.py` with expanded tests in
`tests/test_phase5_table_tools.py`. It preserves blank HTML cells, merges
multi-row headers, prioritizes direct row-label matches over generic
`year/end/amount/number` terms, handles repeated `Granted`/`Vested` activity
rows, uses section-row context for child rows such as `Basic`, computes
`High`/`Low` differences from the question date column, and appends a
traceable million display for positive `$000` lookup cells. Local diagnostic
replay of the 12 larger-gate table/tool miss rows now has 12/12 successful
tool executions and 12/12 answer hits. The full local TAT-QA subset diagnostic
`local_table_tool_row_context_scale_probe_20260629` has 80 cases,
`pass_rate=0.75`, 56/60 table-tool successes, 40/60 answer hits, and 60/60
citation block hits. Server deterministic audit
`answer_policy_table_row_header_fix_audit_20260629` succeeded at commit
`a2ae57e`: 12/12 target rows loaded, 12/12 tool executions succeeded, 7
`table_lookup` and 5 `simple_calculation` operations ran, 12/12 tool answers
hit gold, and the failure distribution was empty. This accepts the
deterministic table-tool repair only; it is not final Qwen answer-quality
acceptance.

The larger real-Qwen diagnostic gate was rerun after the table-tool repair
with run id `answer_policy_training_gate_qwen_larger40_tablefix_20260629`.
It evaluated 40 TAT-QA AnswerPolicy cases plus 40 skipped MP-DocVQA manifest
rows, used Qwen base, did not train, and did not claim formal benchmark
acceptance. The result improved to `pass_rate=0.90`, `answer_hit_rate=0.90`,
`citation_block_hit_rate=1.0`, `format_valid_rate=1.0`, and
`failure_reason_distribution=answer_miss:4`. The review recommendation is
`continue_qwen_eval_before_training`, with `sft_gate=defer` and SFT candidates
skipped. This confirms that the earlier larger40 answer misses were mostly
tool-context defects and that the next step is a larger real-Qwen diagnostic,
not SFT/GRPO training.

The full 80-sample real-Qwen diagnostic gate after the table-tool repair ran
with run id `answer_policy_training_gate_qwen_full80_tablefix_20260629`. It
processed the prepared final-eval artifacts, evaluated 80 TAT-QA AnswerPolicy
cases, skipped 55 MP-DocVQA manifest rows that still require raw
PDF/MinerU/retrieval evidence, used Qwen base, did not train, and did not
claim formal benchmark acceptance. The baseline result was
`pass_rate=0.7625`, `answer_hit_rate=0.7625`,
`citation_block_hit_rate=1.0`, `format_valid_rate=1.0`, and
`failure_reason_distribution=answer_miss:19`. The review gate returned
`prompt_or_parser_repair_before_training`, `sft_gate=not_ready`, because raw
JSON or schema failures were present in row-level parse diagnostics despite
the canonical format-valid rate being 1.0. Follow-up inspection
`answer_policy_full80_parse_failure_inspect_20260629` found one row-level
schema failure, zero raw JSON failures, and one
`parse_fail_but_format_valid` row; the row was already canonicalized into the
final output contract and also failed answer quality. The local review-gate
semantics now treat this as a repaired-output diagnostic rather than a hard
parser blocker. Review-only server rerun
`answer_policy_full80_repaired_parse_review_20260629` confirmed the gate now
recommends continuing Qwen evaluation before training. This is
`real_model_verified` diagnostic evidence for review-gate behavior only, not
final answer-quality acceptance or benchmark evaluation.

Phase 5 AnswerPolicy training-gate orchestrator is implemented locally in
`scripts/run_final_answer_policy_training_gate.py` with tests in
`tests/test_run_final_answer_policy_training_gate.py`. It runs the final
AnswerPolicy baseline, reviews the baseline artifacts, and only when the
review recommends `sft_data_design_candidate` builds SFT candidate records.
It writes orchestration `result.json`, `summary.json`, `summary.md`,
`preview.json`, and `manifest.json`, and can create a compact sync bundle with
the top-level gate summary plus nested baseline/review/candidate summaries.
Local heuristic smoke is diagnostic and correctly skips SFT candidate
generation with `needs_real_qwen_baseline`. The first real Qwen server smoke
completed successfully but skipped SFT candidates because
`citation_block_hit_rate=0.75` was below the review gate threshold. The
post-repair server rerun improved final canonical citation hit to 1.0 and
left only answer misses. The follow-up review-only server rerun recommended
`continue_qwen_eval_before_training`, so the next step is a larger real Qwen
diagnostic baseline or manual review rather than immediate SFT/GRPO. The
larger diagnostic gate `answer_policy_training_gate_qwen_larger40_20260629`
then ran 40 evaluated TAT-QA AnswerPolicy cases plus 40 skipped MP-DocVQA
manifest rows: `format_valid_rate=1.0`, `citation_block_hit_rate=1.0`,
`answer_hit_rate=0.65`, `pass_rate=0.65`, and
`failure_reason_distribution=answer_miss:14`. The review recommendation became
`sft_data_design_candidate` with `sft_gate=candidate`, and the orchestrator
generated 13 SFT candidate records under
`outputs/final_eval/answer_policy_sft_candidates/answer_policy_training_gate_qwen_larger40_20260629_sft_candidates/`.
This is still diagnostic data design only; no SFT/GRPO training started, and
the next step is to inspect answer failures and SFT candidates before training.
This is a server-ready execution wrapper with real-model smoke evidence only;
real Qwen baseline acceptance, training execution, and benchmark acceptance
remain `not_started`.

Phase 5F full CLI acceptance is accepted in
`scripts/run_phase5f_full_cli_acceptance.py`. The runner reuses the Phase 5G
CLI regression execution and adds full-entrypoint acceptance checks for
required task coverage, structured unsupported table/calculation boundary,
`result.json` / `summary.json` / `router_plan.json` / `trace.json` artifact
presence, and summary flags proving no external API, VLM, training, or full
E2E path was used. Local execution
`phase5f_full_cli_20260629_054248_59c59b05` passed 11 cases with 10 completed
and 1 structured unsupported boundary. AutoDL server smoke on
`phase5/phase5f-full-cli-acceptance` at `42ee83d` also passed with run id
`phase5f_full_cli_20260629_055323_69679174`, 11 cases, 10 completed, 1
structured unsupported boundary, and 10/10 artifact contracts passing. This
acceptance covers the CLI entrypoint and trace artifact contract, not final
answer quality, visual pixel QA, online MinerU OCR, training, full GRPO E2E,
or a new SQLite trace replay benchmark. Table lookup and simple calculation
are implemented later as local deterministic tools and require separate
product/dataset evaluation before any benchmark claim.

Phase 5C-2 LLM-assisted Router fallback is accepted in
`docagent/router/llm_client.py`, `docagent/router/llm_router.py`, and
`scripts/docagent_cli.py`. The accepted rule router remains the deterministic
baseline; LLM fallback is disabled by default and requires explicit
`--allow-llm-router` plus environment or `--router-llm-env-file` configuration.
The Router LLM only receives the question, available tools, initial rule plan,
and lightweight document profile. It does not receive full document text,
retrieved evidence, OCR full text, image pixels, user file contents, or
`local_fact_qa` outputs. The LLM-facing output schema is intentionally narrow:
`task_type`, optional `query_rewrite`, optional `selected_tools`, and optional
diagnostics such as confidence / intent labels. `llm_router.py` canonicalizes
that minimal decision into the full internal RouterPlan. Missing or
non-standard confidence is normalized or warned about, but does not by itself
fail validation. Invalid JSON, illegal task type, unavailable tool selection
with no safe fallback, visual-understanding requests, missing config, and API
errors fall back to the rule plan.

Phase 5C-3 Query Planning + Multi-Query Retrieval is accepted in
`docagent/retrieval/query_planner.py`,
`docagent/retrieval/query_generator_rule.py`,
`docagent/retrieval/query_generator_llm.py`, and
`docagent/retrieval/query_fusion.py`, with retrieval integration in
`docagent/retrieval/hybrid_retriever.py`,
`docagent/retrieval/index_manager.py`, and optional CLI exposure in
`scripts/docagent_cli.py`. The rule extractor always produces deterministic
structural anchor queries from the question, optional router task type,
page/table/image/statistics signals, and keywords. The LLM Query Rewriter is
decoupled from Router context: it reuses the Phase 5C-2 OpenAI-compatible
Router LLM configuration and client, but receives only `question` and must
output retrieval query strings. It does not receive task_type,
document_profile, rule_queries, RouterPlan, full document text, retrieved
evidence, OCR full text, image pixels, or tool state. Query fusion deduplicates
rule and LLM queries, caps the final list at 8, preserves rule-query priority,
and records `query_sources`. If LLM config is missing, the API fails, output is
invalid/empty, or the LLM echoes the input payload, retrieval falls back to rule
queries. This phase does not change Router task classification,
`local_fact_qa` answer logic, AnswerPolicy, ingestion, VLM logic, training, or
full GRPO E2E.

Phase 5C-3 single-case LLM semantic query expansion server smoke and
multi-question Query Rewriter smoke passed on AutoDL. Phase 5C-3 Query
Rewriter / Query Planner is accepted for query-planning execution stability.
The acceptance boundary does not include full business workflow validation,
non-dry-run Router + Query Planning + Retrieval + local_fact_qa validation, or
answer quality benchmarking.

```text
command = phase5c3_query_retry_smoke
status = success
doc_id = c1fc1c5e040ec894
question = What date or financial year is mentioned in the shareholder notice about unclaimed dividend?
task_type = local_fact_qa
query_planner_mode = hybrid
llm_status = used
llm_retry_count = 0
llm_added_unique_query_count = 5
llm_queries = unclaimed dividend financial year; shareholder notice unclaimed dividend; unpaid dividend transfer date; financial year dividend notice; dividend unclaimed notice date
warnings = query_planning_enabled; dry_run_no_answer_generated; page_metadata_inconsistent
artifact = outputs/logs/phase5c3_query_retry_cli.json
cli_artifact_dir = /root/autodl-tmp/docagent/outputs/cli_smoke/docagent_cli_20260627_065700_775efc88
judgment = Phase 5C-3 single-case LLM semantic query expansion smoke passed
```

Multi-question Query Rewriter server smoke evidence:

```text
command = phase5c3_query_rewriter_multi_smoke
status = success
run_id = phase5c3_query_rewriter_20260627_080409_7bc51dc6
artifact_dir = outputs/smoke/phase5c3_query_rewriter/phase5c3_query_rewriter_20260627_080409_7bc51dc6
case_count = 10
passed_count = 10
failed_count = 0
semantic_case_count = 7
semantic_passed_count = 7
failure_reasons = {}
task_type_distribution = local_fact_qa:8, page_lookup:1, document_statistics:1
router_task_type_distribution = local_fact_qa:8, page_lookup:1, document_statistics:1
artifacts = query_rewriter_cases.jsonl; query_rewriter_results.jsonl; query_rewriter_summary.json; preview.json
judgment = Phase 5C-3 multi-question Query Rewriter smoke passed
```

Current Query Rewriter contract:

```text
recommended LLM output schema = {"queries": ["...", "..."]}
first attempt user payload = {"question": "..."}
retry user payload = {"question": "...", "avoid_exact_queries": [...]}
not sent = document_profile, task_type, RouterPlan, available_tools,
           retrieved evidence, OCR full text, document full text
hybrid mode = rule_queries + llm_queries -> fusion -> final_queries
query_sources.rule / query_sources.llm record final-query source
multi-query retrieval executes the final_queries list and fuses retrieval results with RRF
multi-question smoke runner = scripts/run_phase5c3_query_rewriter_smoke.py
multi-question smoke status = passed
full business workflow validation baseline = accepted in Phase 5H
non-dry-run Router + Query Planning + Retrieval + local_fact_qa validation baseline = accepted in Phase 5H
answer quality validation = not completed
full E2E / GRPO / VLM / training = not executed
```

Phase 5H Full Workflow Validation Baseline is accepted in
`scripts/run_phase5h_full_workflow_smoke.py`. This runner does not add core
document-answering capability; it calls the existing `scripts/docagent_cli.py`
for each case and validates the full execution chain:

```text
user_request -> Router -> Query Planner -> multi-query retrieval ->
local_fact_qa / deterministic tool / structured unsupported boundary ->
answer, citations, metadata, and CLI artifacts
```

The current CLI parameter remains `--question`, but Phase 5H treats that field
semantically as `user_request`. It may contain an interrogative question,
imperative request, declarative request, extraction task, calculation intent,
summary request, Chinese request, or ambiguous short request.

Phase 5H default cases cover:

```text
interrogative fact QA
ordinary date request without the invoice example
amount / number / percentage request
page_lookup
document_statistics
summary boundary
Chinese summary and extraction requests
declarative request
imperative extraction request
calculation intent
table_lookup boundary
duplicate-prone short request
```

Calculation-intent cases are validation boundaries only. They check that the
system routes, plans queries, attempts retrieval when applicable, or returns a
structured unsupported limitation without crashing. They do not mean
`simple_calculation` or `table_lookup` has been implemented.

Phase 5H artifacts are written under
`outputs/smoke/phase5h_full_workflow/<run_id>/`:

```text
phase5h_cases.jsonl
phase5h_results.jsonl
phase5h_summary.json
preview.json
```

Phase 5H non-dry-run server full workflow smoke passed and is accepted:

```text
preflight_command = phase5h_preflight
preflight_head = 1bc8515c3a37cdc870a01bc4c5ccde7da940276f
preflight_head_matches_expected = true
preflight_db_exists = true
preflight_secret_exists = true
preflight_script_exists = true
preflight_fixed_doc_id = c1fc1c5e040ec894
preflight_fixed_doc_exists = true

command = phase5h_full_workflow_smoke
status = success
run_id = phase5h_full_workflow_20260627_102757_80a9b5bf
case_count = 15
passed_count = 15
failed_count = 0
dry_run_cases = 0
non_dry_run_cases = 15
semantic_query_expected_count = 10
calculation_intent_count = 2
unsupported_boundary_count = 5
json_valid_count = 15
artifact_write_count = 15
request_form_distribution = ambiguous:1, calculation:2, declarative:1, extraction:2, imperative:2, interrogative:5, summary:2
task_type_distribution = document_statistics:1, local_fact_qa:12, page_lookup:1, table_lookup_or_calculation:1
router_task_type_distribution = document_statistics:1, local_fact_qa:12, page_lookup:1, table_lookup_or_calculation:1
tools_used_distribution = count_pages:1, get_page_text:1, local_fact_qa:12
failure_stage_distribution = {}
failure_reason_distribution = {}
used_external_api = true
used_vlm = false
used_training = false
used_full_e2e = false
artifact_dir = /root/autodl-tmp/docagent/outputs/smoke/phase5h_full_workflow/phase5h_full_workflow_20260627_102757_80a9b5bf
artifacts = phase5h_cases.jsonl; phase5h_results.jsonl; phase5h_summary.json; preview.json
```

Phase 5H acceptance validates structured execution across Router, Query
Planner, retrieval, local_fact_qa, deterministic tools, unsupported-boundary
handling, and artifact writing. Final answer quality validation,
document_summary, table_lookup/simple_calculation, online MinerU full parsing,
VLM, training, and full GRPO E2E remain not completed or not_started as
applicable. Calculation-intent cases remain retrieval plus unsupported-boundary
validation only and do not mean `simple_calculation` has been implemented.

Phase 5I-A Pre-LLM Evidence Readiness Benchmark is accepted in
`scripts/run_phase5i_answer_quality_benchmark.py`. The script name is retained
for compatibility, but the default evaluation scope is
`pre_llm_evidence_readiness`, with `final_answer_generation_enabled=false` and
`final_answer_quality_evaluated=false`. It calls the accepted
`scripts/docagent_cli.py` full workflow against fixed
`doc_id = c1fc1c5e040ec894` and 26 manually defined cases, then evaluates
Router task type, Query Planner final queries, retrieval/evidence keyword
hits, citation metadata, structured unsupported boundaries,
insufficient-evidence signals, CLI success, artifact writing, and downstream
requirement flags. `answer_keyword_hit` is retained as an
informational/manual-review field and is not a default hard failure unless
`--evaluate-final-answer` is explicitly enabled.

Phase 5I-A accepted server execution:

```text
preflight_command = phase5i_evidence_readiness_preflight
preflight_head = 0d45e389f098b3cfb72b289a2be8b3ce6aa4770c
head_matches_expected = true
db_exists = true
secret_exists = true
script_exists = true
fixed_doc_id = c1fc1c5e040ec894
fixed_doc_exists = true

benchmark_command = phase5i_answer_quality_benchmark
status = success
evaluation_scope = pre_llm_evidence_readiness
final_answer_generation_enabled = false
final_answer_quality_evaluated = false
evidence_readiness_status = baseline_has_failures
quality_status_semantics = pre_llm_evidence_readiness_not_final_answer_quality
run_id = phase5i_answer_quality_20260628_024037_e6ccd282
case_count = 26
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
summary_path = outputs/benchmark/phase5i_answer_quality/phase5i_answer_quality_20260628_024037_e6ccd282/phase5i_summary.json
manual_review_exists = true
preview_exists = true
manual_review_confirms_final_answer_generation_not_evaluated = true
used_external_api = true
used_vlm = false
used_training = false
used_full_e2e = false
```

The `baseline_has_failures` result is an evidence-readiness baseline, not a
final QA quality failure report. Phase 5I-A does not add core answer
capability and does not modify Router classification, `local_fact_qa` answer
logic, AnswerPolicy, document_summary, table lookup, simple calculation, VLM,
training, or full GRPO E2E. Phase 5I-B final answer quality benchmarking
remains not_started until a downstream answer module is connected.

Phase 5I-B Full Model-enhanced QA Path is implemented locally in
`scripts/docagent_cli.py` and `scripts/run_phase5i_answer_quality_benchmark.py`.
The CLI now exposes `--full-model-path`, which enables LLM Router fallback,
hybrid LLM Query Rewriter planning, and real `local_fact_qa` dispatch in one
path. It also exposes local Qwen AnswerPolicy selection through
`--answer-policy {heuristic,base,sft,grpo}` plus model/adapter/device/token
parameters. The default AnswerPolicy remains `heuristic` for local tests and
backward compatibility; server full-path smoke should use at least
`--answer-policy base`.

Phase 5I-B server full-path validation is accepted on branch
`phase5/phase5i-b-full-model-qa-path` at commit `f83269f`. The AutoDL
resource preflight found `outputs/docagent.db`, `.secrets/router_llm.env`,
Qwen3-1.7B, BGE-M3, and reranker resources available with CUDA on one RTX
4090D. The full-path smoke used real Router/Rewriter API configuration and
Qwen base AnswerPolicy. It completed 5 cases with 4 passed and 1 conservative
diagnostic failure (`ambiguous_short_date:evidence_keyword_missing`), recorded
`used_external_api=true`, `used_llm_query_rewriter=true`,
`used_qwen_answer_policy=true`, `answer_policy_mode=base`, and 4 trace run
ids. The follow-up same-language probe passed all non-ambiguous core cases and
confirmed that low-confidence English requests triggered the Router LLM in 2
probe cases.

Phase 5I-B artifacts now record whether each case used or skipped the Router
LLM, whether LLM query rewriting affected final retrieval queries,
`answer_policy_mode`, `used_qwen_answer_policy`,
`used_external_answer_api=false`, retrieval/citation counts, and trace run id.
The Phase 5I command-line runner defaults to full-model-path validation and
returns `blocked` if Router/Rewriter LLM configuration is missing. Library
entry points remain compatible with Phase 5I-A tests. Final answer correctness,
answer keyword hit, and location hit are diagnostic-only in this phase; they
are not accepted as Qwen quality claims until the Qwen input/output contract
and future training data design are revisited. No external Answer API, VLM,
table lookup, simple calculation, SFT/GRPO retraining, or full GRPO E2E was
added.

Phase 5 structured_extraction deterministic CLI support is implemented in
`docagent/tools/structured_extraction.py` and wired through
`scripts/docagent_cli.py`. The Router can now dispatch supported
`structured_extraction` requests to deterministic persisted-evidence scans for
dates, table blocks, image/figure blocks, section metadata, and generic
structured evidence. The output includes `structured_result`, citations, and
trace artifacts through the existing CLI finalization path. This is not
`table_lookup`, row/column QA, simple calculation, VLM, or answer-quality
repair.

Phase 5C-2 accepted server real API smoke evidence:

```text
command = phase5c2_router_llm_schema_smoke
status = success
artifact = outputs/logs/phase5c2_router_llm_schema_smoke.json
cli_artifact_dir = /root/autodl-tmp/docagent/outputs/cli_smoke/docagent_cli_20260626_093156_bbb1c380
cli_status = success
task_type = local_fact_qa
router_source = llm_fallback
llm_router_status = used
llm_router_error_type = null
validation_errors = []
normalization_warnings = []
warnings = llm_router_used, dry_run_no_answer_generated, page_metadata_inconsistent
acceptance_boundary = router fallback execution stability, not answer quality
```

Phase 5G accepted server regression evidence:

```text
run_id = phase5g_cli_20260626_022925_9eca480b
status = success
case_count = 10
completed_count = 8
failed_count = 0
skipped_count = 0
unsupported_count = 2
json_valid_count = 10
artifact_write_count = 9
task_type_distribution = document_statistics:3, document_summary:1, local_fact_qa:2, page_lookup:1, table_lookup_or_calculation:1
tools_used_distribution = count_pages:3, get_page_text:1, local_fact_qa:2
failure_taxonomy = {}
unsupported_taxonomy = document_summary_not_implemented:1, table_lookup_not_implemented:1
skipped_taxonomy = {}
known_limitation_counts = document_summary_not_implemented:1, dry_run_no_answer_generated:2, fallback_to_local_fact_qa:3, table_lookup_not_implemented:1, visual_understanding_unsupported:1
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
artifact_dir = /root/autodl-tmp/docagent/outputs/regression/phase5g_cli/phase5g_cli_20260626_022925_9eca480b
cases_path = /root/autodl-tmp/docagent/outputs/regression/phase5g_cli/phase5g_cli_20260626_022925_9eca480b/regression_cases.jsonl
results_path = /root/autodl-tmp/docagent/outputs/regression/phase5g_cli/phase5g_cli_20260626_022925_9eca480b/regression_results.jsonl
summary_path = /root/autodl-tmp/docagent/outputs/regression/phase5g_cli/phase5g_cli_20260626_022925_9eca480b/regression_summary.json
summary_md_path = /root/autodl-tmp/docagent/outputs/regression/phase5g_cli/phase5g_cli_20260626_022925_9eca480b/regression_summary.md
preview_path = /root/autodl-tmp/docagent/outputs/regression/phase5g_cli/phase5g_cli_20260626_022925_9eca480b/preview.json
```

Status:

```text
Phase 4B -> accepted
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
Phase 5F full CLI acceptance -> accepted
Phase 5 final delivery report -> implemented
Phase 5 final delivery readiness check -> implemented
Phase 5 final delivery benchmark gate -> accepted
CDC -> not_started
MVP CLI / trace integration -> accepted
Demo/closure -> not_started
```

Phase 4D-B1.3 accepted server sanity:

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

Phase 5D-S accepted server smoke evidence:

```text
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
```

The warning does not block smoke acceptance. It records that the
`evidence_packing` option is deferred to the existing workflow path.

Real-model smoke result preview:

```text
Q1: What is this document about?
A1: The Cigarette Industry in India
citations_count = 3
supporting_evidence_ids_count = 3

Q2: What date is mentioned in this document?
A2: 2000-01
citations_count = 5
supporting_evidence_ids_count = 5

Q3: What amount or total is mentioned in this document?
A3: 10
citations_count = 5
supporting_evidence_ids_count = 5
```

Phase 5F-1 accepted server CLI smoke evidence:

```text
branch = codex/phase5f1-unified-cli-mvp
commit = b7e92c89908ce57517f145e18cd6ca1b702a300e
db_path = outputs/docagent.db
doc_id = c1fc1c5e040ec894
list_documents_run_id = docagent_cli_20260625_035337_52161dae
list_documents_status = success
list_documents_document_count = 2
list_documents_key_doc_page_count = 5
list_documents_key_doc_parse_status = parsed
list_documents_key_doc_index_status = ready
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
local_fact_qa_dry_run_citations_count = 5
local_fact_qa_dry_run_supporting_evidence_ids_count = 5
local_fact_qa_dry_run_warning = dry_run_no_answer_generated
local_fact_qa_real_run_id = docagent_cli_20260625_035621_145b69a9
local_fact_qa_real_status = success
local_fact_qa_real_tool_run_id = 341437e6-7976-4a2f-a7b5-2dac762960d0
local_fact_qa_real_citations_count = 5
local_fact_qa_real_supporting_evidence_ids_count = 5
file_missing_run_id = docagent_cli_20260625_035702_766dcb4a
file_missing_status = error
file_missing_error = file_not_found
artifact_root = outputs/cli_smoke
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
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

Phase 5F-2 implemented local file-to-answer ingestion:

```text
branch = codex/phase5f2-file-ingestion-cli
entrypoint = scripts/docagent_cli.py
parser_backend = docagent/parser/text_backend.py
new_lightweight_file_ingestion = .txt
ingestion_service_reused = DocumentIngestionService
document_registry_reused = DocumentRegistry
sqlite_repository_reused = DocumentRepository
sha256_reuse_supported = true
generated_or_reused_doc_id_returned = true
source_was_ingested_returned = true
source_reused_existing_returned = true
summary_used_file_ingestion = true
summary_reused_existing_document = true
summary_ingestion_status = true
summary_ingestion_error = true
structured_errors = file_not_found, parser_backend_unavailable, unsupported_file_type, file_ingestion_failed
page_metadata_inconsistent_warning = implemented
used_external_api = false
used_vlm = false
used_training = false
used_full_e2e = false
```

Phase 5F-2 accepted server file-to-answer smoke evidence:

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
```

Phase 5F-3 accepted MinerU-backed file-to-answer smoke:

```text
branch = codex/phase5f3-mineru-file-cli-smoke
implementation_commit = 3eaf488cd7870af2e64dcd74f0f807edd8a1cb01
entrypoint = scripts/docagent_cli.py
parser_backend = docagent/parser/mineru_backend.py
supported_parser_mode = mineru_existing / parse_existing
current_raw_pdf_parser = mineru_api
existing_mineru_output_arg = --mineru-output-dir / --mineru-output
server_status = success
tested_file_type = pdf
tested_sample_path = data/real_documents/globocan_africa_2022/source/original.pdf
tested_mineru_output = data/real_documents/globocan_africa_2022/mineru_raw
doc_id = fe3465edd3da60d2
stats_artifact = outputs/logs/phase5f3_file_stats.json
stats_status = success
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
page_lookup_task_type = page_lookup
page_lookup_tools_used = get_page_text
page_lookup_was_ingested = false
page_lookup_reused_existing = true
page_lookup_ingestion_status = reused_existing
page_lookup_metadata_consistency = ok
fact_dry_run_artifact = outputs/logs/phase5f3_file_fact_dry_run.json
fact_dry_run_status = success
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
At Phase 5F-3 acceptance time, document_summary was not implemented and
summary-like questions could fall back to local_fact_qa dry-run with warnings.
Phase 5E document_summary was implemented later as a deterministic local tool.
local_fact_qa answer quality is not benchmark-validated by this smoke.
The GLOBOCAN sample structure_quality is passed_with_warnings.
```

Current conclusion:

- Phase 4C `candidate_spans` is accepted.
- Phase 4D-A diagnostics and failure attribution tooling are accepted as
  diagnostic infrastructure.
- Phase 4D-B1.1 candidate evidence completeness fix is accepted and retained.
- Phase 4D-B1 table/index enhancement is not accepted as default; it remains
  experimental behind `--enable-table-index-packing`.
- Phase 4D-B1.3 default pipeline sanity is accepted.
- Phase 4D-C expanded unseen validation is accepted.
- Candidate-ID Reader remains postponed.
- Phase 4D-D candidate answer board generalized improvement is deferred.
- Phase 5 Personal-use DocAgent MVP is active.
- Phase 5A architecture audit and contracts are accepted.
- Phase 5B P0 deterministic tools are accepted from SQLite document
  metadata and EvidenceBlock payloads.
- Phase 5C rule-first Router / Planner is accepted without external LLM API
  calls or tool execution.
- Phase 5D `local_fact_qa` wrapper is accepted as a callable tool interface.
- Phase 5D-S smoke runner and server real-model smoke are accepted as execution
  stability evidence, not as a benchmark-level answer-quality result.
- Phase 5F-1 unified CLI MVP is accepted with Router dispatch,
  deterministic tools, page lookup, local_fact_qa, list-documents, and a
  structured `--file` contract.
- Phase 5F-1 server CLI smoke is accepted as execution-stability evidence, not
  as benchmark-level answer-quality evidence.
- Phase 5F-2 file-to-answer ingestion integration and server smoke are
  accepted for UTF-8 `.txt` files and SHA reuse, with structured failures for
  unsupported parser paths.
- Phase 5F-3 MinerU-backed file-to-answer implementation and server smoke are
  accepted for existing MinerU output-backed execution.
- Phase 5G CLI regression baseline and server regression are accepted as
  execution-stability evidence, not benchmark answer-quality evidence.
- Phase 5C-2 LLM-assisted Router fallback is accepted after real API smoke.
- Phase 5C-3 Query Planning + Multi-Query Retrieval is accepted with
  Router-decoupled LLM Query Rewriter, rule structural anchors, query-source
  tracking, multi-query BM25 / dense retrieval fusion, and CLI opt-in via
  `--enable-query-planning`. Single-case real API query-expansion smoke and
  multi-question Query Rewriter smoke both passed.
- Phase 5H Full Workflow Validation Baseline is accepted as a non-dry-run
  smoke runner that exercises the existing CLI path from user request through
  Router, Query Planner, retrieval, local_fact_qa/deterministic tools, answer,
  citations, and artifacts. The accepted server run passed 15/15 non-dry-run
  cases with valid JSON and artifact output for every case.
- Phase 5E document_summary is implemented locally as a deterministic
  extractive summary tool. Deterministic table lookup and simple calculation
  are implemented locally. Online MinerU OCR execution acceptance and
  local_fact_qa answer quality improvement remain not_started.

Phase 4D-C accepted server result:

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

Step C accepted retrieval-only / candidate_spans:

```text
candidate_evidence_count = 218 / 218
qid_set_match = true
table_index_enhancement_enabled = false
no_gold_leakage = true
gold_page_has_candidate_span_rate = 0.9128
candidate Recall@1/3/5 = 0.7248 / 0.8945 / 0.9128
candidate MRR = 0.8099
```

Step D accepted candidate answer diagnostics:

```text
candidate_span_answer_coverage = 0.7523
candidate_answer_coverage_all = 0.4266
candidate_answer_coverage_top20 = 0.3991
candidate_answer_no_gold_leakage = true
bucket_A = 19
bucket_C = 43
bucket_D = 72
bucket_G = 84
```

Step E accepted failure attribution:

```text
extraction_rule_gap = 72
candidate_span_or_normalization_gap = 38
reader_selection_gap = 5
table_or_index_span_gap = 14
candidate_span_selection_gap = 10
candidate_span_partial_context_gap = 9
page_number_or_content_lookup_gap = 5
```

Phase 4D-C interpretation:

- The accepted default `candidate_spans` path remains stable on the strict
  unseen set.
- Candidate answer coverage is lower than the 90-sample probe
  (`all: 0.5222 -> 0.4266`, `top20: 0.4556 -> 0.3991`), so candidate board
  quality is a real expanded-set bottleneck.
- Candidate-ID Reader remains postponed because reader/reranking attribution
  is only 5 cases versus 72 extraction cases and 38 span cases.
- Optional full GRPO E2E remains postponed until candidate answer board quality
  improves.

Phase 4D-C scaffold / command preparation:

- Branch started from `origin/main`:
  `codex/phase4d-c-expanded-unseen-validation`.
- Goal is expanded unseen validation on MP-DocVQA validation shards 5-8, not
  further 90-sample probe tuning.
- Existing scripts are sufficient for Step A-E command preparation:
  `build_phase4b_expanded_sample.py`, `run_phase4b_mpdocvqa_ingestion.py`,
  `run_phase4b_mpdocvqa_e2e.py`,
  `analyze_phase4d_candidate_answer_coverage.py`, and
  `export_phase4d_failure_inspection.py`.
- No code changes were required for this scaffold round.
- Default pipeline remains accepted `candidate_spans` with
  `rank_aware_context = false`, table/index enhancement disabled, no
  Candidate-ID Reader, no prompt tuning, and no training.
- Candidate-ID Reader remains postponed until expanded unseen diagnostics show
  reader-selection failures dominate after candidate coverage issues are
  resolved.

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

Interpretation:

- Do not enter Candidate-ID Grounded Reader directly from this result.
- Improve candidate answer extraction, normalization, ranking, and top-k
  coverage metrics first.
- `D=25` is the main extraction-improvement opportunity.
- `C=22` still requires candidate span improvement.
- `E=13` remains later Reader or candidate-selection work.

Phase 4D-A.1 implemented boundary:

- heading/title, city/state/location, quarter short-form, key-value,
  organization/company/board, and source/footer extraction improvements;
- rank, top-k flags, duplicate penalty, generic numeric penalty, and long-text
  penalty on candidate answers;
- all/top1/top3/top5/top10/top20 coverage metrics;
- limited top-k board artifacts for future Candidate-ID Reader design;
- `bucket_transition_estimate.json` for D-bucket extraction-improvement
  potential.

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
bucket_A = 4
bucket_B = 0
bucket_C = 22
bucket_D = 21
bucket_E = 14
bucket_F = 29
bucket_G = 0
candidate_answer_no_gold_leakage = true
```

Phase 4D-A.2 implemented boundary:

- preserve all candidates for `candidate_answer_coverage_all`;
- add top-k eligibility, filter reasons, and stronger penalties for generic
  numeric, type mismatch, duplicate, near-duplicate, long text, and noisy text;
- select `candidate_answers_topk.jsonl` through type-aware top-k selection;
- add top-k filtering metrics and `refinement_comparison.json`.

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

Phase 4D-A.3 implemented boundary:

- export `failure_inspection_cases.jsonl`, preview, summary, and C/D/E
  bucket-specific JSONL files;
- include gold answers only in the inspection debug artifact;
- keep `candidate_answers.jsonl` and `candidate_answers_topk.jsonl` gold-field
  free;
- add automatic diagnosis hints for candidate span, extraction, and
  Reader/candidate-selection gaps.

Phase 4D-A.3 accepted server inspection:

```text
artifacts = failure_inspection_cases.jsonl,
            bucket_C_cases.jsonl,
            bucket_D_cases.jsonl,
            bucket_E_cases.jsonl,
            failure_inspection_summary.json,
            failure_inspection_summary.md
```

Phase 4D-A.3.1 implemented boundary:

- add `bucket_answer_hit_breakdown` and
  `bucket_candidate_coverage_breakdown` to `failure_inspection_summary.json`;
- add `true_failure_action_counts`;
- add `failure_inspection_refined_cases.jsonl`,
  `failure_inspection_refined_summary.json`, and
  `failure_inspection_refined_summary.md`;
- keep refined artifacts audit-only and out of Reader input.

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

- export only statistics, subtype labels, preview, summary, and decision
  guidance for `candidate_span_or_normalization_gap` cases;
- write `candidate_span_gap_cases.jsonl`,
  `candidate_span_gap_preview.json`, `candidate_span_gap_summary.json`, and
  `candidate_span_gap_summary.md`;
- split cases into the allowed subtypes:
  `normalization_or_metric_gap`, `candidate_span_selection_gap`,
  `candidate_span_partial_context_gap`, `table_or_index_span_gap`,
  `page_number_or_content_lookup_gap`, `ocr_or_parsing_gap`, and
  `unclear_mixed_gap`;
- mark all cases `should_not_patch_specific_qid = true`.

Phase 4D-A.4 decision boundary:

- No per-qid or per-document repairs are allowed.
- If one subtype dominates and has a generic repair path, implement one narrow
  generic fix.
- If subtypes are dispersed, stop tuning this 90-sample probe and expand
  validation coverage.
- Candidate-ID Reader remains postponed.

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

- add generic table/index question hint detection;
- add table/index span scoring bonuses for field-label overlap, percentage
  values, parenthesized index values, field-value rows, table/list-like rows,
  and same-line label/value/parenthesized-index evidence;
- retain table/index neighbor context, including adjacent rows and table
  header-like blocks;
- add aggregate diagnostics for table/index candidate span counts, answer
  coverage, top-span field-value presence, neighbor context, and
  parenthesized-index span counts.

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

Root cause:

- The server validation command did not pass an explicit Gate 4 doc-id
  manifest.
- The runner fell back to `DEFAULT_DOC_IDS`, the three historical Gate 3
  documents, instead of inferring all document windows from the active
  expanded `sample_root/qa.jsonl`.

Phase 4D-B1.1 accepted boundary:

- infer doc scope from `sample_root/qa.jsonl` when no explicit doc scope is
  provided;
- preserve original candidate_spans fallback for non-table/index questions;
- add `candidate_evidence_completeness` to summary and candidate packing
  metrics;
- fail before writing candidate evidence if candidate records do not exactly
  match the loaded QA qid set.

Phase 4D-B1.1 server validation:

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

Phase 4D-B1.2 closeout:

- B1 table/index enhancement failed acceptance on the 90-sample probe: it
  reduced `table_or_index_span_gap` only from 10 to 8, did not improve overall
  candidate coverage, and shifted `page_number_or_content_lookup_gap` from 1
  to 4.
- The B1.1 completeness fix is retained.
- Table/index scoring and neighbor-context enhancement are disabled by default
  and kept experimental behind `--enable-table-index-packing`.
- A.4 remains the final diagnostic split for the 90-sample probe. No further
  per-case tuning on this probe is allowed.
- Next step: larger unseen validation using the accepted pipeline and existing
  diagnostics.
- Candidate-ID Reader remains postponed.

Unchanged boundary:

- Reader prompts, AnswerPolicy, retrieval models, MinerU, checkpoints, reward,
  training data, CDC, Demo, and global `candidate_spans` default remain
  unchanged.
- Phase 4D-B1.1 server validation is accepted.

## Phase 4D-A Local Implementation

Phase 4D-A adds an audit layer after the accepted Phase 4C
`candidate_spans` evidence packing path. It extracts typed candidate answers
from candidate spans and measures whether gold answers are covered by spans,
extracted answers, ranks, and error buckets.

Status:

```text
Phase 4B -> accepted
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
CDC -> not_started
Router/tools -> not_started
Demo/closure -> not_started
```

Implemented boundary:

- deterministic rule-based extraction for date, percentage, index, source,
  heading, numeric, and short text candidates;
- candidate answer board artifacts and preview;
- coverage metrics for candidate spans, candidate answers, rank distribution,
  and distractor counts;
- error buckets A-G separating retrieval miss, span coverage miss, extraction
  miss, Reader wrong, Reader correct, and unclear cases;
- automatic no-gold-leakage checks for candidate answer artifacts.

Unchanged boundary:

- default `--evidence-packing page_children` remains unchanged;
- Phase 4C `candidate_spans` remains an accepted experimental and recommended
  mode, not a global default;
- Reader prompts, AnswerPolicy, retrieval models, MinerU, checkpoints, reward,
  training data, CDC, and Demo remain unchanged;
- Phase 4D-A diagnostics and failure attribution tooling through Phase
  4D-A.4 are accepted as diagnostic infrastructure.

## Phase 4C Accepted

Phase 4C adds an experimental multi-granularity evidence packing path on top
of the accepted Phase 4B Gate 4 page-level retrieval chain.

Status:

```text
Phase 4B -> accepted
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
CDC -> not_started
Router/tools -> not_started
Demo/closure -> not_started
```

Accepted boundary:

- default `--evidence-packing page_children` keeps the accepted Phase 4B fixed
  evidence behavior;
- `--evidence-packing candidate_spans` is an accepted experimental and
  recommended evidence packing mode for the Gate 4 style raw-input E2E path;
- candidate artifacts and metrics are written separately from answer/gold
  metrics;
- server retrieval-only / packing-only reached `no_gold_leakage=true`;
- retrieval models, AnswerPolicy prompt defaults, checkpoints, and training
  data are unchanged;
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

Compact A/B result:

| Metric | page_children | candidate_spans | Delta |
|---|---:|---:|---:|
| normalized_exact_match | 0.3333 | 0.4111 | +0.0778 |
| answer_hit | 0.3444 | 0.4556 | +0.1111 |
| token_f1 | 0.3689 | 0.4628 | +0.0939 |
| character_f1 | 0.5235 | 0.6341 | +0.1106 |
| gold_page_location_hit | 0.4889 | 0.6778 | +0.1889 |
| block_location_hit | 0.9667 | 1.0000 | +0.0333 |
| answer_miss | 59 | 49 | -10 |
| gold_page_location_miss | 46 | 29 | -17 |
| retrieval_gold_miss_top5 | 4 | 4 | 0 |

Interpretation:

Phase 4C shows that query-aware / structure-aware candidate evidence packing
improves Reader grounding and answer extraction under the same retrieval and
AnswerPolicy setting. Hybrid retrieval metrics stayed unchanged, so the gain
comes from reorganizing Reader input evidence rather than retrieval-model
changes, prompt changes, or retraining.

Detailed report:

```text
docs/PHASE4C_CANDIDATE_SPANS_REPORT.md
```

## Phase 4B Accepted

Phase 4A remains accepted. Phase 4B expanded raw-input regression is accepted
on `main` after the single feature branch `codex/phase4b-mpdocvqa-e2e` was
fast-forwarded.

Canonical status labels in this file use the repository vocabulary:
`not_started`, `implemented`, `ready`, `mock_verified`,
`server_dependency_ready`, `real_model_verified`, `benchmark_evaluated`,
`accepted`, `frozen`, `blocked`, and `blocked_by_missing_mineru_output`.
Historical metric descriptions below are evidence summaries, not current
canonical status labels.

Current Phase 4 status:

```text
Phase 4A -> accepted
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
CDC -> not_started
Router/tools -> not_started
Demo/closure -> not_started
```

Gate 1 local implementation adds a reusable MP-DocVQA page-window ingestion
runner for:

```text
Phase 4A sample assets
-> existing MinerU API client
-> existing DocumentIngestionService
-> EvidenceBlock
-> page_documents
-> structure quality
-> QA page mapping
-> compact acceptance report
```

Gate 1 single-page live MinerU ingestion is accepted. Gate 2 accepted the
representative 1/4/20-page windows after existing-artifact revalidation fixed
the SQLite JSON path-scan false positive. Gate 3 real E2E completed on AutoDL
for 3 windows / 25 pages / 8 QA with valid JSON and trace persistence, but
Reader quality remains under review because the model often selects a non-gold
page or similar field from the retrieved top-k pages. Gate 3A local
instrumentation was accepted after artifact checks. The rank-aware prompt and
context default changed reader behavior and is now opt-in only via
`--rank-aware-context`; default full E2E returns to the Gate 3 prompt/context
shape. Gate 4 expanded raw-input E2E regression is now accepted. Gate 4 is not
a formal benchmark and should be read as stability, retrieval, answer, trace,
and failure distribution evidence over the expanded sample.

Gate 4 accepted sample:

```text
sample_root = outputs/phase4/mpdocvqa_raw_gate4_expanded
ingestion_root = outputs/phase4/mpdocvqa_ingestion
source_shards = MP-DocVQA val shards 1-4
document_count = 26
page_count = 197
qa_count = 90
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
page_location_hit = 0.4889
block_location_hit = 0.9667
final_location_in_evidence_rate = 1.0
trace_counts.qa_runs = 90
trace_counts.tool_traces = 613
failure_taxonomy = answer_miss:59, gold_page_location_miss:46, retrieval_gold_miss_top5:4
```

Interpretation:

- Gate 4 is an expanded raw-input regression, not a strict independent
  benchmark.
- Flow stability is accepted: ingestion, page mapping, page retrieval, fixed
  evidence, GRPO AnswerPolicy JSON/format validation, and SQLite trace all ran
  through.
- Hybrid retrieval is usable on the expanded sample, with Top-5 page recall
  0.9556.
- Answer quality remains limited by `answer_miss` and
  `gold_page_location_miss`.
- `--rank-aware-context` remains diagnostic only and defaults to false.
- Gate 4 artifacts are server-side acceptance outputs. Missing local mirrors
  under `outputs/phase4/mpdocvqa_raw_gate4_expanded`,
  `outputs/phase4/mpdocvqa_ingestion`, or
  `outputs/evaluation/phase4b_mpdocvqa_gate4/` are an artifact sync boundary,
  not a missing main-branch code path.

## Phase 4A Accepted

Phase 3 is accepted and frozen. Its evaluation implementation, metrics, and
conclusions remain historical and unchanged.

Phase 4A server acceptance is complete at commit
`f3d6237b9f7f53cd9f2a8e21d4441e7f911a7979` on branch
`codex/phase4-mpdocvqa-raw-foundation`.

Accepted server input:

- shard:
  `/root/autodl-tmp/datasets/mp_docvqa/parquet/val-00001-of-00029.parquet`
- `size_bytes=255412525`
- `sha256=493d31bb7b99da676876e4350b27f15ca3e4273518493a09fc799f31d5a3609b`
- long-lived untracked server paths `data/`, `tmp.py`, `.ipynb_checkpoints/`,
  and `scripts/.ipynb_checkpoints/` were explicitly treated as non-blocking
  because they are not tracked modifications

Accepted server results:

- `builder --help`, `py_compile`, real-shard `validate-only`, 5-window sample
  build, and sample artifact self-check all passed
- `phase4_mpdocvqa_raw_server_smoke_shell_exit_code=0`
- real shard audit:
  `row_count=179`, `unique_source_doc_count=44`, `unique_window_count=61`,
  `different_window_same_source_doc_count=23`,
  `conflicting_window_count=0`
- sample build:
  `document_window_count=5`, `qa_count=12`, `absolute_path_hit_count=0`

Accepted document/window boundary:

- The restored artifact is an MP-DocVQA `page_window` document, not
  necessarily a complete original source document.
- Stable document-window identity is defined by:
  `source_doc_id + ordered_page_ids`.
- Different ordered page windows under the same `source_doc_id` are valid
  independent inputs, not conflicts.

Accepted sample windows:

- `rzbj0037__e09400dd12a9c549`: `source_doc_id=rzbj0037`, `page_count=4`,
  `qa_count=6`
- `hqvw0217__bc714cf4181a5632`: `source_doc_id=hqvw0217`, `page_count=1`,
  `qa_count=1`
- `jrcy0227__558596710c584b02`: `source_doc_id=jrcy0227`, `page_count=20`,
  `qa_count=1`
- `mxxj0037__3e113e49e156e47c`: `source_doc_id=mxxj0037`, `page_count=2`,
  `qa_count=2`
- `hljn0226__2583bb36ed16bec4`: `source_doc_id=hljn0226`, `page_count=2`,
  `qa_count=2`

All accepted sample windows satisfy:

- `input_scope=page_window`
- `document.pdf` exists
- `document_manifest.json` exists
- `source_shards` are recorded correctly
- persistent paths remain relative

Overlap audit:

- Historical SFT/GRPO source artifacts were not present in the checked local
  repo paths, so overlap status remains `not_available`.
- The MP-DocVQA raw document path is intended for integration, page retrieval,
  and system E2E, not as strict independent generalization evidence.

Status:

```text
Phase 3 -> accepted
Phase 3 evaluation implementation -> frozen
Phase 4A implementation -> accepted
MP-DocVQA raw Parquet schema audit -> accepted
page-window identity model -> accepted
multi-page image restoration -> accepted
deterministic document asset builder -> accepted
Linux PDF generation -> accepted
cross-shard identity design -> implemented
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
CDC -> not_started
Router/tools -> not_started
Demo/closure -> not_started
```

## Phase 1 Complete

The current implementation stage connects a configurable answer policy to the traceable QA workflow.

Completed in this phase:

- Added shared AnswerPolicy abstractions under `docagent/models/`.
- Added Qwen answer policy wrapper for `base`, `sft`, and `grpo` modes.
- Added shared workflow prompt builder and structured output parser.
- Updated `run_qa_workflow` to require an explicit answer policy instead of silently using `heuristic_answer`.
- Added bounded repair routing after format/location checks.
- Added run-level SQLite trace persistence through `TraceRepository`.
- Added CLI smoke/eval/trace inspection scripts for workflow-level testing.
- Aligned workflow Qwen generation default with the standalone checkpoint eval `MAX_NEW_TOKENS=1024` setting to avoid truncating valid JSON outputs.
- Verified Base/SFT/GRPO policy switching through the same workflow CLI.

Validation on AutoDL:

| Mode | Samples | Workflow Success | Raw JSON | Schema | Answer EM | Answer F1 | Location | Trace Persist |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| base | 10 | 1.0 | 1.0 | 1.0 | 0.50 | 0.5562 | 0.90 | 1.0 |
| sft | 50 | 1.0 | 1.0 | 1.0 | 0.58 | 0.6715 | 0.92 | 1.0 |
| grpo | 50 | 1.0 | 1.0 | 1.0 | 0.56 | 0.6769 | 0.94 | 1.0 |

The GRPO workflow run also passed SQLite trace inspection. A persisted run can be replayed through `scripts/inspect_workflow_trace.py`, with ordered nodes for `retrieve_evidence`, `generate_answer`, `check_format`, `check_location`, and `finalize`.

Current boundary:

- No new SFT/GRPO training.
- No reward changes.
- No data split changes.
- No Dense Retriever, Reranker, MinerU, TAT-QA, InfographicVQA, VLM, API, or Demo expansion in this phase.

Known limitation:

- Remaining low-answer examples are mostly reader extraction errors inside the correct OCR block, such as neighboring entities, abbreviation expansion ambiguity, or numeric row selection. This matches the earlier SFT/GRPO reader error analysis and is not a workflow integration failure.

## Phase 2A Accepted

Phase 2A real hybrid retrieval and workflow integration is accepted.

Server validation:

- BGE-M3 model API smoke passed with dense embeddings on `cuda:1`.
- bge-reranker-v2-m3 smoke passed through the Transformers sequence-classification backend on `cuda:1`.
- Real hybrid retrieval smoke passed:
  `BGE-M3 -> FAISS save/reload -> BM25 + Dense + RRF -> Transformers reranker`.
- Real Qwen3 GRPO workflow smoke passed:
  `hybrid_rerank -> top-k EvidenceBlock -> GRPO AnswerPolicy -> JSON parse -> format/location validation -> SQLite trace`.
- The accepted workflow smoke used `doc_id=smoke_invoice`, retrieved `smoke_invoice_p1_b1`, generated answer `March 12, 2020`, and persisted run
  `1d88ec99-1f62-4746-9ae2-c0616fa924e7`.

Status:

```text
BGE-M3 -> real_model_verified
FAISS index save/reload -> real_model_verified
BM25 + Dense + RRF -> real_model_verified
Transformers Reranker -> real_model_verified
real hybrid retrieval -> accepted
real Qwen3 workflow integration -> accepted
Phase 2A -> accepted
```

Boundary:

```text
Phase 2A implementation/integration -> accepted
formal retrieval and QA benchmark -> not_started
```

The single successful smoke is integration evidence, not a performance metric.

## Phase 2B First Milestone Accepted

The current implementation stage has accepted the first real structured PDF
parsing milestone. It preserves Phase 1 AnswerPolicy and trace behavior while
adding a real MinerU output conversion path.

Completed before Phase 2B:

- Added document registration with SHA256-based `doc_id`, source caching, and
  supported PDF/PNG/JPG input checks.
- Added MinerU `parse_existing` backend and converter for text/table/image
  content-list records into stable `EvidenceBlock` IDs.
- Added page-level aggregate blocks for future page-first retrieval while
  keeping block-level retrieval as the default.
- Extended SQLite with document, evidence block, and document index metadata
  persistence without removing Phase 1 `qa_runs` or `tool_traces`.
- Added unified retrieval candidates with BM25, Dense, RRF, and reranker score
  fields.
- Added BGE-M3 dense encoder wrapper, DenseIndex save/load, RRF fusion, and a
  real bge-reranker-v2-m3 wrapper with explicit errors when models are missing.
- Switched the default real reranker path to Transformers
  `AutoModelForSequenceClassification` for Transformers 5.x compatibility.
- Added `IndexedDocumentRetriever` and injected it into `run_qa_workflow`
  without changing the default Phase 1 path.
- Added CLI entry points:
  `scripts/ingest_document.py`, `scripts/inspect_document.py`,
  `scripts/query_document.py`, `scripts/eval_retrieval_phase2.py`, and
  `scripts/eval_workflow_phase2.py`.
- Added `scripts/build_phase2_parse_existing_fixture.py` to create
  MinerU-like `content_list.json` fixtures from existing DocAgent JSONL
  records, so Phase 2 can be smoke-tested without installing MinerU.
- Added explicit no-download smoke backends for Phase 2 retrieval:
  `HashDenseEncoder` and `KeywordOverlapReranker`. These are for wiring tests
  only and must not be reported as BGE-M3 or bge-reranker-v2-m3 results.
- `scripts/eval_retrieval_phase2.py` and `scripts/eval_workflow_phase2.py`
  now support the same `hash` dense and `keyword` reranker smoke backends for
  no-download batch validation.

Local no-card validation:

- `python -m pytest -q`: 41 passed.
- Temporary parse-existing smoke completed:
  register dummy PDF -> parse mock MinerU content list -> save blocks ->
  inspect document -> query with BM25 + heuristic answer policy.

Phase 2B first milestone:

- one real public PDF: `903-africa-fact-sheet.pdf`;
- data directory: `data/real_documents/globocan_africa_2022/`;
- `doc_id=fe3465edd3da60d2`;
- source SHA256:
  `fe3465edd3da60d26b2020ab751d75bfba26a465a9d66c43eff5dce12f4db37a`;
- MinerU API batch:
  `56a4776f-aa1c-47d0-8901-99038de6a851`;
- real MinerU `parse_existing` converted 57 raw content-list records into
  57 `EvidenceBlock` records;
- structure-quality status: `passed_with_warnings`;
- only warning: MinerU `_origin.pdf` SHA256 differs from the submitted source
  PDF, so the submitted PDF remains the document identity source.

Validation:

- `python -m pytest -q`: 72 passed before merge-prep hardening.
- Real GLOBOCAN `mineru_existing` smoke persisted SQLite document/block records.
- Existing-batch MinerU API read-only smoke returned `state=done`, downloaded a
  ZIP under `outputs/mineru_api/live_smoke/`, and safely extracted an ordinary
  `*_content_list.json`.

Merge-prep hardening:

- Persisted MinerU artifact paths are document-directory-relative POSIX paths
  in EvidenceBlocks, page documents, ingestion report, structure-quality report,
  source manifest, and SQLite `payload_json`.
- `image_path` is the EvidenceBlock resource reference; duplicate
  `metadata.normalized_resource_path` and `metadata.source_content_list` are no
  longer written.
- Structure quality now reports `missing_retrieval_content_count`,
  `empty_boilerplate_count`, and `empty_boilerplate_block_ids` separately, so
  retained empty boilerplate does not fail quality status.
- Added fixed verifier `scripts/verify_phase2b_real_pdf.py`.
- Local validation after hardening:
  `python -m pytest -q`: 74 passed.
- Real GLOBOCAN verifier:
  `outputs/verification/phase2b_globocan/verification_report.json`;
  `raw_block_count=57`, `converted_block_count=57`, `page_document_count=2`,
  `table_count=5`, `chart_count=6`, `empty_boilerplate_count=2`,
  `missing_retrieval_content_count=0`, `persisted_absolute_path_count=0`,
  `overall_status=passed_with_warnings`.

Status:

```text
Real MinerU output -> accepted
Phase 2B first milestone -> accepted
```

## Phase 2B-2 Accepted

Phase 2B-2 real-document scenario acceptance is complete. This is a
real-document scenario acceptance result, not a formal benchmark.

Accepted integration:

- Real GLOBOCAN PDF and existing MinerU output were ingested through
  `mineru_existing`.
- 57 raw records converted to 57 EvidenceBlocks; 22 boilerplate blocks were
  excluded, leaving 35 retrieval blocks.
- Real BGE-M3, FAISS, BM25, RRF, Transformers sequence-classification reranker,
  and Qwen3 GRPO AnswerPolicy ran end to end.
- JSON, format, and location validation completed through the existing workflow.
- SQLite trace persisted 8 `qa_runs` and 49 `tool_traces`.
- `no_gold_leakage=true`, `no_mock_fallback=true`, and
  `persisted_absolute_path_count=0`.

Scenario metrics:

- Scenario samples: 8/8 completed.
- Retrieval: `Recall@1=0.875`, `Recall@3=0.875`, `Recall@5=0.875`,
  `MRR=0.875`, `gold_page_hit_rate=1.0`.
- Answer: `normalized_exact_match=0.625`, `token_f1=0.675`,
  `character_f1=0.7842548076923077`, `answer_hit=0.625`,
  `valid_json_rate=1.0`, `format_valid_rate=1.0`.
- Location: `block_location_hit=0.875`, `page_location_hit=1.0`,
  `final_location_in_retrieved_top_k=1.0`, `location_valid_rate=1.0`.

Failure taxonomy:

- 2 reader table-column selection errors: q001 and q002 selected the Males
  column instead of Both sexes while retrieval and location were correct.
- 1 retrieval / partial-answer / location error: q008 missed the large table
  gold block, returned a partial liver cases answer, and cited the wrong block.

Status:

```text
Phase 2B-2 -> accepted
implementation/integration -> accepted
scenario quality evidence -> accepted
formal benchmark -> not_started
quality optimization -> not_started
```

## Phase 3A Implemented

Phase 3A local focused-evaluation framework is implemented. Real focused
evaluation on AutoDL has not started.

Implemented locally:

- benchmark validity contract for corpus-backed records with
  `metadata.gold_block_ids`;
- deterministic qid-hash subset sampling;
- BM25 vs Hybrid retrieval runner using shared retrieval code;
- fixed Hybrid evidence artifact generation for shared SFT/GRPO reader input;
- SFT vs GRPO AnswerPolicy runner over identical evidence order;
- comparison JSON and Markdown summary outputs;
- fixture tests using explicit mock backends only.

Status:

```text
Phase 3A -> implemented
real focused evaluation -> not_started
retrieval evaluation -> blocked
answer policy evaluation -> implemented
formal benchmark -> not_started
```

Boundary:

- Local validation does not load real BGE-M3, reranker, SFT, or GRPO models.
- Mock fixture output must not be reported as real focused-evaluation results.
- The current `mp_docvqa_imdb_ocr_5000_split/dev.jsonl` artifact is not an
  accepted retrieval corpus because its evidence is stored per QA record and no
  independent canonical per-doc corpus artifact has been verified.
- `scripts/build_phase3_mpdocvqa_retrieval_benchmark.py` can build the required
  QA/corpus/manifest artifacts from real RRC IMDb / official OCR data, but the
  server has not yet produced and validated those artifacts.
- SFT vs GRPO can still run through `--answer-only` when a reader evidence
  artifact passes the reader contract, but that path must not report retrieval
  Recall/MRR.
- Do not modify retrieval algorithms, query normalization, prompts,
  AnswerPolicy, reward code, checkpoints, or training data in Phase 3A.

## Phase 3 Local Closure Implemented

The local Phase 3 closure now separates model-facing protocol, real-document
contracts, and server acceptance orchestration. No real model evaluation has
been run for this update.

Implemented locally:

- Added a shared evidence-context builder and checkpoint-compatible answer
  prompt compiler used by SFT dataset construction, GRPO dataset construction,
  heuristic policy, Qwen AnswerPolicy, and the workflow model node.
- Added a canonical output adapter so workflow traces can store raw model
  output, canonical output, validation status, and repair status consistently.
- Extended workflow traces with `prompt_version`, `task_type`, selected and
  dropped block ids, `evidence_context_hash`, prompt token count, truncation,
  raw output, canonical output, validation, and repair metadata.
- Added real-document QA/corpus/document-manifest/benchmark-manifest contract
  construction for the existing GLOBOCAN scenario corpus.
- Added one fixed server acceptance entry point:
  `scripts/run_phase3_server_acceptance.py`.
- Added `--retrieval-only` to the Phase 3 focused runner so retrieval contract
  checks and real-document retrieval regression can run without loading SFT or
  GRPO adapters.

Status:

```text
training-inference contract -> implemented
real-document evaluation framework -> implemented
server real evaluation -> accepted
GLOBOCAN regression -> accepted
fixed-evidence safety hotfix -> accepted
MP-DocVQA retrieval evaluation -> blocked
MP-DocVQA AnswerPolicy evaluation -> accepted
CDC -> not_started
```

Boundary:

- Local tests use fixtures or help startup only; they do not load BGE-M3,
  reranker, Qwen, SFT adapter, or GRPO adapter.
- CDC is the next priority and still requires server-side MinerU output or
  MinerU API ingestion before it can become a second accepted real-document
  scenario.
- GLOBOCAN regression is accepted as a real-document scenario contract, not a
  formal benchmark result.

## Phase 3 GLOBOCAN Server Regression Accepted

The GLOBOCAN real-document scenario regression passed on AutoDL at commit
`3390bcde1c703c7bd95c567e6da3bdb04591c0d8`.

Server environment for that historical GLOBOCAN run:

```text
Python -> /root/miniconda3/envs/docagent/bin/python
Conda environment -> docagent
GPU -> 2 x NVIDIA GeForce RTX 4090 D
PyTorch -> 2.12.0+cu130
Transformers -> 5.8.1
PEFT -> 0.19.1
FlagEmbedding -> import passed
```

Run scope:

```text
evaluation_scope = scenario_regression
formal_benchmark = false
verified_qa_count = 8
query_independent_block_count = 35
document_count = 1
```

Retrieval scenario comparison:

| Metric | BM25 | Hybrid | Absolute Delta | Relative Delta |
|---|---:|---:|---:|---:|
| Recall@1 | 0.375 | 0.875 | +0.500 | +1.3333 |
| Recall@3 | 0.875 | 0.875 | 0.000 | 0.0000 |
| Recall@5 | 0.875 | 0.875 | 0.000 | 0.0000 |
| MRR | 0.6041666667 | 0.875 | +0.2708333333 | +0.4482758621 |
| Gold page hit rate | 1.0 | 1.0 | 0.000 | 0.0000 |

```text
在 GLOBOCAN 8 条真实文档场景回归中，Hybrid + Reranker
主要改善正确证据的首位排序：
Recall@1 从 0.375 提升至 0.875，MRR 从 0.604 提升至 0.875。
Recall@3/5 未提升，说明当前收益主要来自重排，而不是扩大候选覆盖。
```

AnswerPolicy scenario comparison:

```text
fixed_evidence_sha256 = 04536f8fdbd3ea2e6c4a8ef93befd6aa270eb5c5ae700f1edcdacf2eed35adee
normalized EM = 0.625
answer hit = 0.625
token F1 = 0.675
character F1 = 0.7842548077
valid JSON rate = 1.0
format valid rate = 1.0
block location hit = 0.875
page location hit = 0.875
final location in evidence rate = 1.0
repair attempted rate = 0.0
repair success rate = 0.0
```

SFT and GRPO used the same fixed evidence and produced identical metrics.

```text
真实文档回归验证了 SFT 与 GRPO adapter 均可通过统一
Training–Inference Contract、Canonical Output 和验证链路运行。

8 条 GLOBOCAN 场景中未观察到 GRPO 相对 SFT 的回答指标提升。
该结果只证明兼容性和无明显回归，不能用于宣称 GRPO 优于 SFT。
```

Status:

```text
training-inference contract -> accepted
real-document evaluation framework -> accepted
fixed-evidence safety hotfix -> accepted
GLOBOCAN regression contract -> accepted
GLOBOCAN server real regression -> accepted
Hybrid retrieval scenario evidence -> accepted
AnswerPolicy scenario compatibility -> accepted
MP-DocVQA AnswerPolicy evaluation -> accepted
MP-DocVQA AnswerPolicy sample_count -> 150
SFT/GRPO fixed-evidence parity -> accepted
GRPO grounding evidence -> accepted
GRPO answer accuracy evidence -> accepted
formal benchmark -> not_started
MP-DocVQA retrieval evaluation -> blocked
CDC -> not_started
```

Boundary:

- This is a real-document scenario regression result, not a formal benchmark.
- GRPO effectiveness remains unproven beyond compatibility on this scenario.
- GRPO vs SFT has now been evaluated on a larger MP-DocVQA fixed-evidence
  reader artifact; CDC should next be added as a second real document scenario.

## Phase 3 MP-DocVQA AnswerPolicy Evaluation Measured

MP-DocVQA fixed-evidence reader evaluation completed on AutoDL at commit
`1ef68838210d56e8624b7ef0c0633b705e8ccfe5`. This is not a formal benchmark
and does not report retrieval Recall/MRR.

Run scope:

```text
server_gpu = 1 x NVIDIA GeForce RTX 4090D 24GB
dataset = data/benchmark/mp_docvqa_imdb_ocr_5000_split/dev.jsonl
evaluation_scope = mpdocvqa_fixed_evidence_reader
formal_benchmark = false
sample_limit = 150
seed = 42
top_k = 20
fixed_evidence_sha256 = 8c4d60a189675a4ba52fa61d47db68c070f2f13218b5e73b1a18ded6fceeb940
output_dir = outputs/evaluation/phase3_focused_eval/mpdocvqa_answer_policy_150_top20_20260616_131117/
```

The `top_k=20` setting is only the fixed-evidence reader-evaluation evidence
budget over the existing reader artifact. It is not an online Retrieval top-k
setting and must not be used to compute Retrieval Recall/MRR. The earlier
`top_k=5` smoke failure was not a code defect because qid `64253` had its gold
block at source-evidence rank 8.

Metrics:

| Metric | SFT | GRPO | Delta |
|---|---:|---:|---:|
| Completed | 150/150 | 150/150 | 0 |
| Failed | 0 | 0 | 0 |
| Normalized EM | 0.380000 | 0.386667 | +0.006667 |
| Answer hit | 0.406667 | 0.406667 | 0.000000 |
| Token F1 | 0.483865 | 0.484643 | +0.000778 |
| Character F1 | 0.615299 | 0.625152 | +0.009853 |
| Valid JSON | 1.000000 | 1.000000 | 0.000000 |
| Format valid | 1.000000 | 1.000000 | 0.000000 |
| Block location hit | 0.866667 | 0.893333 | +0.026667 |
| Page location hit | 0.880000 | 0.900000 | +0.020000 |
| Final location in evidence | 1.000000 | 1.000000 | 0.000000 |
| Repair attempted/success | 0.086667 | 0.086667 | 0.000000 |
| Mean latency | 4289.27 ms | 4237.41 ms | -51.86 ms |

Conclusion:

```text
在 150 条相同 fixed evidence 的 MP-DocVQA reader 样本上，
GRPO 相比 SFT 在 block/page 证据定位和 character F1 上有轻微提升，
Normalized EM 仅提高约 0.67 个百分点，Answer Hit 不变。

结果说明 GRPO 没有破坏结构化输出，并表现出有限的 grounding 改善；
不能据此宣称 GRPO 在答案正确率上存在显著优势。
```

Current status:

```text
fixed-evidence safety hotfix -> accepted
MP-DocVQA AnswerPolicy evaluation -> accepted
MP-DocVQA AnswerPolicy sample_count -> 150
SFT/GRPO fixed-evidence parity -> accepted
GRPO grounding evidence -> accepted
GRPO answer accuracy evidence -> accepted
formal benchmark -> not_started
MP-DocVQA retrieval evaluation -> blocked
GLOBOCAN regression -> accepted
CDC -> not_started
```

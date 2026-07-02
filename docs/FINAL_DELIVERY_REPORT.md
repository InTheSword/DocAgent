# DocAgent Final Delivery Report

Updated: 2026-07-02

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
| Final answer quality benchmark | not_started | No accepted MP-DocVQA/TAT-QA final answer benchmark yet |
| New SFT/GRPO training | not_started | Candidate builders/gates exist, but no current final training run is claimed |
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

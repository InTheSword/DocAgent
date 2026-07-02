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

These runs validate execution-chain continuity and artifact contracts. They do
not by themselves promote answer correctness to `benchmark_evaluated`.

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
3. Prepare a formal final answer-quality benchmark only after the execution
   chain is stable and the benchmark scope is explicitly selected.
4. Start SFT/GRPO only if the benchmark shows reusable AnswerPolicy failures
   that prompt/tool/contract repair cannot address.

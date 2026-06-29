# DocAgent Project Handoff for Product Manager

Updated: 2026-06-29

## 1. One-page Conclusion

DocAgent is currently a personal-use complex document QA MVP track, not a
finished commercial product and not a final answer-quality benchmark system.

The implemented system already has a working technical chain:

```text
document registration / ingestion
-> MinerU or text parser output to EvidenceBlock
-> SQLite persistence
-> deterministic Router
-> optional LLM router fallback
-> optional query planning / multi-query retrieval
-> deterministic document tools or local_fact_qa
-> citations, JSON output, CLI artifacts, and traces
```

The strongest accepted evidence is still execution stability:

- Phase 5G CLI regression: accepted historically; current local regression now includes deterministic table lookup / simple calculation paths.
- Phase 5H full workflow smoke: accepted, 15 non-dry-run cases, 15 passed, 0 failed.
- Phase 5I-A evidence-readiness benchmark: accepted as a pre-LLM evidence-readiness baseline, 16 passed and 10 failed out of 26. This is not final answer quality.
- Final delivery local contract update: implemented top-level
  `answer`, `reasoning_summary`, `evidence_used`, normalized `citations`,
  deterministic `table_lookup`, deterministic `simple_calculation`, and MinerU
  `local_cli` failure artifacts.
- Final evaluation subset preparation: implemented locally for TAT-QA dev and
  MP-DocVQA val shard 1-2, with manifests, source hashes, filter reports, and
  previews under `outputs/final_eval/`.
- Final evaluation local subset diagnostic runner: implemented locally; the
  current 135-case local diagnostic is diagnostic-only and shows table
  answer-quality gaps.

The most important product gap is clear:

```text
DocAgent can route, retrieve, cite, and produce structured artifacts, but it
has not yet proven final answer quality, MP-DocVQA/TAT-QA subset benchmark
quality, online MinerU OCR execution, VLM reasoning, training gains, or
UI/demo closure.
```

## 2. Source of Truth

Use this priority order when taking over:

1. current PM or owner instruction;
2. `AGENTS.md`;
3. `docs/ACTIVE_PLAN.md`;
4. verified current code, tests, and accepted server artifacts;
5. `CURRENT_STATUS.md` and `DECISIONS.md`;
6. phase-specific plans and design documents;
7. original blueprint PDF.

Do not treat planned capability as implemented capability. Mock or fixture
validation must not be reported as real-model completion.

## 3. Current Project Goal

The active track is Phase 5: personal-use DocAgent MVP.

Minimum intended product behavior:

```text
PDF file or already ingested document
-> user request
-> task routing
-> deterministic document tool or local_fact_qa workflow
-> structured answer
-> citations
-> trace path and artifacts
```

This target is intended for personal testing, job-search demonstration, and
project portfolio demonstration. It is not yet positioned as a production
multi-user SaaS, formal leaderboard benchmark, or visual document intelligence
system.

## 4. Implementation Level Against Original Plan

Original DocAgent 3.0 target came from `docs/DocAgent 技术文档 3.0.pdf`.
The blueprint described seven broad stages: data processing, document parsing
and Evidence Index, Query Rewrite plus hybrid retrieval, traceable QA
workflow, LoRA-SFT, GRPO, and demo/materials.

| Target area | Current implementation level | Status | PM interpretation |
|---|---|---|---|
| Unified schema and evidence model | `EvidenceBlock`, `DocAgentSample`, `QAState`, `EvidenceLocation` exist in `docagent/schemas.py`. | accepted | Stable foundation. |
| MP-DocVQA data construction | Historical Phase 1/4 builders and accepted raw page-window assets exist. | accepted | Usable for experiments, not the current product focus. |
| Final eval subset preparation | `scripts/prepare_final_eval_subset.py` builds TAT-QA and MP-DocVQA validation subset manifests and reports from local files. | implemented | Data is prepared; benchmark evaluation is still future work. |
| Final eval local diagnostic runner | `scripts/run_final_eval_subset.py` writes local results, summary, preview, and manual review files for prepared subsets. | implemented | Diagnostic-only; current probe exposes answer-quality gaps and is not benchmark acceptance. |
| TAT-QA | Dev JSON local subset preparation is implemented; table/numeric product tools have a deterministic local baseline. | implemented | Structured table/numeric source, not raw PDF or MinerU evidence. |
| InfographicVQA | Dataset builder exists, but visual reasoning is not implemented. | not_started | Future VLM branch. |
| MinerU to EvidenceBlock | Existing MinerU output conversion, quality report, page blocks, and SQLite persistence exist. | accepted | Existing MinerU output path works. |
| Online MinerU OCR from raw PDF | CLI has `--parser mineru --parser-mode local_cli` wiring and structured failure artifacts. | implemented | Real local/API MinerU execution still needs approved environment smoke. |
| BM25 retrieval | Implemented and tested. | accepted | Baseline retrieval available. |
| Dense retrieval and reranker | BGE-M3, FAISS, RRF, reranker integration exist with server smoke history. | accepted | Server/model-dependent, not always local. |
| Query planning / multi-query retrieval | Rule query generation and optional LLM query rewriting are accepted. | accepted | Helps retrieval, not answer generation. |
| Traceable QA workflow | `run_qa_workflow` with retrieval, prompt context, AnswerPolicy, validation, repair, and SQLite trace exists. | accepted | Execution chain exists. |
| Qwen3 AnswerPolicy | Base/SFT/GRPO policy integration exists historically. | accepted | Quality remains scenario-dependent. |
| LoRA-SFT | Training/eval scripts and accepted historical checkpoints are recorded. | accepted | Frozen unless explicitly restarted. |
| GRPO | Reward code, training scripts, and historical GRPO E2E runs exist. | accepted | Do not restart during Phase 5 without approval. |
| Deterministic document tools | Page/block/table/image counts, page text, list pages are implemented. | accepted | MVP-ready deterministic utilities. |
| Router | Rule-first router plus optional LLM fallback are accepted. | accepted | Default is deterministic rule router. |
| Unified CLI | `scripts/docagent_cli.py` is accepted for Phase 5F execution. | accepted | Main user entrypoint today. |
| Full product CLI acceptance | The CLI has regression/smoke evidence and the final local output contract is implemented. | implemented | Final closure still needs product/dataset acceptance. |
| Document summary | Deterministic extractive summary tool is implemented and wired through CLI. | implemented | Not an LLM summary-quality benchmark. |
| Table lookup and simple calculation | Deterministic table lookup and simple calculation over parsed table EvidenceBlocks are implemented. | implemented | Complex TAT-QA reasoning and benchmark quality remain future work. |
| Visual reasoning / VLM | Explicitly out of Phase 5. | not_started | Do not promise image understanding. |
| Final answer quality benchmark | Phase 5I-A is only evidence readiness. Phase 5I-B is not started. | not_started | Do not claim final QA quality. |
| UI / Demo closure | No FastAPI/Gradio product UI is accepted. | not_started | CLI-only handoff. |

## 5. Accepted Phase 5 Capabilities

### 5.1 Deterministic Document Tools

Implemented in `docagent/tools/document_tools.py`.

Accepted tools:

- `count_pages`
- `count_blocks`
- `count_tables`
- `count_images`
- `get_page_text`
- `list_pages`

These read from `DocumentRepository`, `documents.page_count`, and persisted
`EvidenceBlock` payloads. They do not call an LLM, VLM, Router, retriever, or
training code.

Product meaning: deterministic metadata and page lookup are reliable enough
for MVP execution stability.

### 5.2 Router and Planner

Implemented in `docagent/router/`.

Supported task types:

- `local_fact_qa`
- `table_lookup_or_calculation`
- `document_statistics`
- `page_lookup`
- `structured_extraction`
- `document_summary`

Important boundary:

Routing to a task type does not by itself prove answer quality. Today,
`document_summary`, `structured_extraction`, and
`table_lookup_or_calculation` have deterministic local tool paths, while
complex reasoning and final answer quality still need evaluation.

### 5.3 Optional LLM Router Fallback

Implemented in `docagent/router/llm_client.py`,
`docagent/router/llm_router.py`, and `scripts/docagent_cli.py`.

Default behavior is rule-only. LLM fallback requires explicit enablement with
`--allow-llm-router` and env/config.

LLM router sees only:

- question;
- available tools;
- initial rule plan;
- lightweight document profile.

It must not receive:

- full document text;
- retrieved evidence;
- OCR full text;
- image pixels;
- user file contents;
- local_fact_qa outputs.

### 5.4 Query Planning and Multi-query Retrieval

Implemented in:

- `docagent/retrieval/query_planner.py`
- `docagent/retrieval/query_generator_rule.py`
- `docagent/retrieval/query_generator_llm.py`
- `docagent/retrieval/query_fusion.py`
- `docagent/retrieval/hybrid_retriever.py`
- `docagent/retrieval/index_manager.py`

Accepted behavior:

- deterministic rule query extraction;
- optional LLM semantic query rewriting;
- deduped query fusion capped at 8 queries;
- multi-query BM25 and hybrid retrieval integration;
- rule query priority and source tracking.

Product meaning: query planning is a retrieval preprocessing layer, not a
summary engine, answer engine, or Router replacement.

### 5.5 local_fact_qa

Implemented in `docagent/tools/local_fact_qa.py`.

It reuses:

- `DocumentRepository`;
- `run_qa_workflow`;
- AnswerPolicy;
- retrieval and evidence context logic;
- optional `TraceRepository`.

It supports dry-run, fake workflow injection for tests, real workflow reuse,
citations, supporting evidence ids, warnings, and structured errors.

Known limitation: answer quality is unstable and not benchmark-validated by
Phase 5D/5H.

### 5.6 Unified CLI

Implemented in `scripts/docagent_cli.py`.

Supported options include:

- `--db-path`
- `--doc-id`
- `--file`
- `--question`
- `--output-dir`
- `--document-root`
- `--parser`
- `--parser-mode`
- `--mineru-output-dir` / `--mineru-output`
- `--dry-run`
- `--list-documents`
- `--limit`
- `--allow-llm-router`
- `--router-llm-threshold`
- `--router-llm-model`
- `--router-llm-env-file`
- `--enable-query-planning`
- `--query-planner-mode`

Supported file paths:

- new UTF-8 `.txt` file ingestion through `TextParserBackend`;
- existing MinerU output-backed PDF/image/document ingestion with
  `--parser mineru_existing` and `--mineru-output-dir`;
- SHA-based reuse for already ingested files.

Unsupported or incomplete paths:

- raw PDF to online MinerU OCR without existing output;
- document summary;
- table lookup;
- simple calculation;
- VLM reasoning.

## 6. Current Benchmarks and Evidence

### 6.1 Phase 4C Candidate Spans

Phase 4C showed that query-aware / structure-aware evidence packing improved
Reader grounding under the same retrieval model and AnswerPolicy.

Key accepted comparison on 90 QA:

| Metric | page_children | candidate_spans |
|---|---:|---:|
| normalized_exact_match | 0.3333 | 0.4111 |
| answer_hit | 0.3444 | 0.4556 |
| token_f1 | 0.3689 | 0.4628 |
| character_f1 | 0.5235 | 0.6341 |
| gold_page_location_hit | 0.4889 | 0.6778 |

Boundary: this was an expanded raw-input integration regression, not a formal
MP-DocVQA benchmark.

### 6.2 Phase 4D-C Expanded Unseen Validation

Accepted strict set:

```text
77 document windows
572 pages
218 QA samples
candidate_evidence_count = 218 / 218
qid_set_match = true
no_gold_leakage = true
candidate Recall@1/3/5 = 0.7248 / 0.8945 / 0.9128
candidate MRR = 0.8099
candidate_span_answer_coverage = 0.7523
candidate_answer_coverage_all = 0.4266
candidate_answer_coverage_top20 = 0.3991
```

Interpretation: dominant bottlenecks are candidate answer extraction and
candidate span construction, not Reader selection.

### 6.3 Phase 5G CLI Regression

Accepted server regression:

```text
case_count = 10
completed_count = 8
failed_count = 0
unsupported_count = 2
json_valid_count = 10
artifact_write_count = 9
```

This validates CLI execution stability, not answer quality.

### 6.4 Phase 5H Full Workflow Smoke

Accepted server smoke:

```text
case_count = 15
passed_count = 15
failed_count = 0
non_dry_run_cases = 15
json_valid_count = 15
artifact_write_count = 15
used_external_api = true
used_vlm = false
used_training = false
used_full_e2e = false
```

This validates full workflow execution stability over Router, Query Planner,
retrieval, local_fact_qa, deterministic tools, unsupported boundaries, and
artifacts.

### 6.5 Phase 5I-A Evidence Readiness

Accepted corrected-semantics run:

```text
evaluation_scope = pre_llm_evidence_readiness
final_answer_generation_enabled = false
final_answer_quality_evaluated = false
case_count = 26
passed_count = 16
failed_count = 10
task_type_accuracy = 0.7692
evidence_readiness_status = baseline_has_failures
failure_stage_distribution = evidence_readiness:4, router:6
```

Product interpretation: the benchmark runner and semantics are accepted, but
the evidence-readiness baseline still has failures. This is not a final answer
quality score.

## 7. Not Implemented or Not Accepted

These must not be marketed as completed:

| Capability | Current status | Practical effect |
|---|---|---|
| Phase 5I-B Final Answer Quality Benchmark | not_started | No accepted final QA quality metric. |
| Phase 5E Document Summary MVP | not_started | Summary requests are routed but unsupported or fallback. |
| Phase 5F full CLI acceptance | not_started | CLI has accepted smokes, but final product acceptance remains open. |
| `table_lookup` | not_started | Table intents are classified but no row/column engine exists. |
| `simple_calculation` | not_started | Calculation intents are not computed by a traceable numeric tool. |
| Structured extraction tools | not_started | Router supports the type, but extraction tools are not implemented. |
| Online MinerU OCR/parser execution from raw PDF | not_started | Existing MinerU output path is accepted; raw OCR pipeline is not. |
| VLM / visual_pixel_qa | not_started | Image/chart answers rely on OCR/caption/metadata only. |
| Candidate-ID Reader | not_started | Postponed until candidate coverage improves. |
| Full GRPO E2E by default in Phase 5 | not_started | Historical GRPO exists; not a current MVP default. |
| CDC real-document scenario | not_started | Still a future scenario. |
| UI demo / FastAPI / Gradio closure | not_started | Current user surface is CLI. |
| Cloud vector DB / multi-user service | not_started | Out of Phase 5 scope. |

## 8. PM Decision Points

Recommended next PM decision:

```text
Pick exactly one next milestone.
```

Best next milestone candidates:

1. Phase 5E Document Summary MVP.
   - Reason: summary is already part of the Router taxonomy and current smoke
     limitations. It is visible to users and can be implemented without new
     training.
2. Router/evidence-readiness cleanup for Phase 5I-A failures.
   - Reason: Phase 5I-A has 10 failures, including router task mismatches and
     missing unsupported boundaries. This improves trust in the existing MVP.
3. Table lookup + simple calculation P0.
   - Reason: product value for financial and report documents is high, but it
     requires a clear row/column and citation contract.
4. Online MinerU OCR path.
   - Reason: product convenience improves if users can pass a raw PDF, but
     environment risk is higher.
5. Final answer quality benchmark Phase 5I-B.
   - Reason: only after a downstream answer module or answer-quality strategy
     is connected.
6. CLI demo packaging / UI.
   - Reason: needed for portfolio delivery, but should wait until summary or
     evidence-readiness gaps are handled.

Do not start VLM, training, full GRPO E2E, CDC, or Candidate-ID Reader unless
the PM explicitly changes the roadmap.

## 9. Architecture Map

### 9.1 Current CLI Flow

```text
scripts/docagent_cli.py
-> optional file resolution / ingestion
-> DocumentRepository
-> document profile
-> Router
-> optional LLM router fallback
-> optional Query Planner
-> task dispatch
   -> document_statistics: deterministic tools
   -> page_lookup: get_page_text / list_pages
   -> local_fact_qa: run_qa_workflow
   -> unsupported tasks: structured error or fallback warning
-> result.json / summary.json / router_plan.json / trace.json
```

### 9.2 Ingestion Flow

```text
DocumentRegistry
-> parser backend
   -> TextParserBackend for UTF-8 .txt
   -> MinerUParserBackend for existing MinerU output or local CLI mode
-> mineru_converter.content_list_to_blocks
-> build_page_blocks
-> DocumentRepository / SQLite
-> ingestion_report.json / structure_quality.json
```

### 9.3 local_fact_qa Flow

```text
DocumentRepository.load_evidence_blocks
-> optional query planning
-> retriever
-> build_evidence_context
-> AnswerPolicy.generate
-> format check
-> location check
-> bounded repair
-> final answer and SQLite trace
```

## 10. Code Inventory

This section is based on Git-tracked files. Local `__pycache__`, `outputs/`,
and `data/real_documents/` are generated or ignored artifacts, not code
ownership boundaries.

### 10.1 Core Package

Root:

- `docagent/__init__.py`: package marker.
- `docagent/schemas.py`: core dataclasses for evidence, samples, result, and QA state.

Evaluation:

- `docagent/eval/__init__.py`: eval package marker.
- `docagent/eval/answer_metrics.py`: text, token, character, and numeric answer metrics.
- `docagent/eval/retrieval_metrics.py`: Recall@k and MRR@k helpers.
- `docagent/eval/phase3_focused.py`: large focused-evaluation contract, retrieval, fixed-evidence, answer-policy, and report logic.

Ingestion:

- `docagent/ingestion/__init__.py`: ingestion package marker.
- `docagent/ingestion/document_registry.py`: SHA-based document registration and cache records.
- `docagent/ingestion/hashing.py`: file SHA and doc_id helpers.
- `docagent/ingestion/quality.py`: structure-quality checks and parsing artifact diagnostics.
- `docagent/ingestion/service.py`: document ingestion orchestration, parser invocation, page blocks, index metadata, SQLite persistence.

Integrations:

- `docagent/integrations/__init__.py`: integration package marker.
- `docagent/integrations/mineru_api.py`: MinerU API client, signed upload handling, safe result extraction.

Models:

- `docagent/models/__init__.py`: model exports.
- `docagent/models/base.py`: AnswerPolicy protocol, generation result, heuristic policy.
- `docagent/models/output_parser.py`: robust JSON output parsing and schema validation.
- `docagent/models/qwen_answer_policy.py`: Qwen AnswerPolicy wrapper.
- `docagent/models/registry.py`: AnswerPolicy factory.

Parser:

- `docagent/parser/__init__.py`: parser package marker.
- `docagent/parser/base.py`: parser backend protocol.
- `docagent/parser/build_evidence_blocks.py`: evidence block collection helper.
- `docagent/parser/mineru_backend.py`: existing MinerU output and local CLI parser backend.
- `docagent/parser/mineru_converter.py`: MinerU content list to EvidenceBlock conversion.
- `docagent/parser/parse_infographicvqa.py`: InfographicVQA record conversion.
- `docagent/parser/parse_mpdocvqa.py`: MP-DocVQA record conversion.
- `docagent/parser/parse_tatqa.py`: TAT-QA table/question conversion.
- `docagent/parser/parser_registry.py`: parser backend factory.
- `docagent/parser/run_mineru_parse.py`: MinerU parse helper.
- `docagent/parser/text_backend.py`: UTF-8 text file parser backend.

Retrieval:

- `docagent/retrieval/__init__.py`: retrieval package marker.
- `docagent/retrieval/base.py`: retriever interfaces and candidate/result types.
- `docagent/retrieval/bm25_index.py`: BM25 indexing and search.
- `docagent/retrieval/candidate_answer_extraction.py`: candidate answer extraction, ranking, coverage, bucket diagnostics.
- `docagent/retrieval/dense_encoder.py`: FlagEmbedding dense encoder and hash mock encoder.
- `docagent/retrieval/dense_index.py`: FAISS/numpy dense index.
- `docagent/retrieval/evidence_packing.py`: candidate span packing, question hints, diagnostics.
- `docagent/retrieval/fusion.py`: reciprocal-rank fusion.
- `docagent/retrieval/hybrid_retriever.py`: BM25/dense/hybrid/rerank retrieval and multi-query integration.
- `docagent/retrieval/index_manager.py`: indexed document retriever wrapper.
- `docagent/retrieval/query_fusion.py`: query normalization and deduped fusion.
- `docagent/retrieval/query_generator_llm.py`: optional LLM query generation and parsing.
- `docagent/retrieval/query_generator_rule.py`: deterministic query generation.
- `docagent/retrieval/query_planner.py`: query planner output, rule/LLM/hybrid planning, retry diagnostics.
- `docagent/retrieval/query_rewrite.py`: legacy deterministic query rewrite.
- `docagent/retrieval/reranker.py`: cross-encoder reranker and keyword mock reranker.

Rewards:

- `docagent/rewards/__init__.py`: reward package marker.
- `docagent/rewards/answer_reward.py`: answer reward.
- `docagent/rewards/combined.py`: combined doc QA reward.
- `docagent/rewards/format_reward.py`: JSON/format reward.
- `docagent/rewards/location_reward.py`: evidence location reward.

Router:

- `docagent/router/__init__.py`: router exports.
- `docagent/router/schemas.py`: router input/options/decision schemas and validation.
- `docagent/router/rule_router.py`: deterministic rule-first planner.
- `docagent/router/llm_client.py`: OpenAI-compatible client config and env loading.
- `docagent/router/llm_router.py`: optional LLM fallback, canonicalization, and safety fallback.

Storage:

- `docagent/storage/__init__.py`: storage package marker.
- `docagent/storage/db.py`: SQLite connection, schema migration, legacy save helpers.
- `docagent/storage/repositories.py`: DocumentRepository and TraceRepository.
- `docagent/storage/schema.sql`: SQLite schema for documents, evidence, indexes, QA runs, tool traces, eval results.

Tools:

- `docagent/tools/__init__.py`: tool exports.
- `docagent/tools/answer_repair.py`: bounded answer repair.
- `docagent/tools/calculator.py`: small safe arithmetic helper, not accepted as table calculation product tool.
- `docagent/tools/document_tools.py`: deterministic Phase 5 document tools.
- `docagent/tools/format_check.py`: answer format check.
- `docagent/tools/local_fact_qa.py`: local_fact_qa wrapper.
- `docagent/tools/location_check.py`: evidence location check.
- `docagent/tools/table_tools.py`: deterministic table lookup and simple calculation over parsed table EvidenceBlocks.
- `docagent/tools/visual_review.py`: metadata/text-only visual review helper, not VLM.

Utilities:

- `docagent/utils/__init__.py`: utils package marker.
- `docagent/utils/jsonl.py`: JSONL read/write helpers.

Workflow:

- `docagent/workflow/__init__.py`: workflow package marker.
- `docagent/workflow/answer_policy.py`: heuristic answer logic.
- `docagent/workflow/graph.py`: traceable QA workflow.
- `docagent/workflow/output_adapter.py`: canonical answer output adapter.
- `docagent/workflow/prompts.py`: prompt assembly and evidence context construction.

### 10.2 Script Entrypoints

Current product/MVP scripts:

- `scripts/docagent_cli.py`: main Phase 5 CLI.
- `scripts/run_phase5c3_query_rewriter_smoke.py`: Query Rewriter smoke.
- `scripts/run_phase5d_local_fact_qa_smoke.py`: local_fact_qa smoke.
- `scripts/run_phase5g_cli_regression.py`: CLI regression runner.
- `scripts/run_phase5h_full_workflow_smoke.py`: full workflow smoke.
- `scripts/run_phase5i_answer_quality_benchmark.py`: evidence-readiness benchmark runner.
- `scripts/prepare_final_eval_subset.py`: local TAT-QA / MP-DocVQA final-evaluation subset preparation.
- `scripts/run_final_eval_subset.py`: local diagnostic runner for prepared final-evaluation subsets.

Document ingestion and inspection:

- `scripts/ingest_document.py`
- `scripts/query_document.py`
- `scripts/inspect_document.py`
- `scripts/preflight_phase2.py`
- `scripts/verify_phase2b_real_pdf.py`
- `scripts/verify_phase2b_real_e2e.py`

Phase 4 MP-DocVQA raw/E2E:

- `scripts/build_mpdocvqa_raw_documents.py`
- `scripts/build_phase4b_expanded_sample.py`
- `scripts/run_phase4b_mpdocvqa_ingestion.py`
- `scripts/run_phase4b_mpdocvqa_e2e.py`
- `scripts/analyze_phase4d_candidate_answer_coverage.py`
- `scripts/export_phase4d_failure_inspection.py`

Phase 3 and benchmark construction:

- `scripts/build_phase3_mpdocvqa_retrieval_benchmark.py`
- `scripts/run_phase3_focused_eval.py`
- `scripts/run_phase3_server_acceptance.py`
- `scripts/build_real_document_benchmark.py`

Training and dataset scripts:

- `scripts/build_sft_dataset.py`
- `scripts/build_grpo_dataset.py`
- `scripts/build_grpo_from_sft_dataset.py`
- `scripts/build_retrieved_reader_dataset.py`
- `scripts/build_answer_hard_grpo_subset.py`
- `scripts/build_mpdocvqa_imdb_subset.py`
- `scripts/build_hf_vqa_subset.py`
- `scripts/build_vqa_subset.py`
- `scripts/build_tatqa_subset.py`
- `scripts/build_mixed_dataset.py`
- `scripts/build_smoke_benchmark.py`
- `scripts/split_dataset_by_doc.py`
- `scripts/filter_training_data.py`
- `scripts/audit_training_data.py`
- `scripts/profile_sft_lengths.py`

Evaluation and analysis scripts:

- `scripts/eval_retrieval.py`
- `scripts/eval_retrieval_phase2.py`
- `scripts/eval_workflow_phase2.py`
- `scripts/eval_workflow_e2e.py`
- `scripts/eval_sft_checkpoint.py`
- `scripts/compare_eval_predictions.py`
- `scripts/analyze_reader_errors.py`
- `scripts/analyze_sft_eval.py`
- `scripts/recompute_sft_eval_metrics.py`
- `scripts/merge_eval_shards.py`
- `scripts/llm_audit_samples.py`
- `scripts/write_project_report.py`

Smoke and runtime inspection:

- `scripts/smoke_test.py`
- `scripts/smoke_phase2_real_models.py`
- `scripts/smoke_phase2_real_retrieval.py`
- `scripts/smoke_phase2_real_workflow.py`
- `scripts/run_workflow_smoke.py`
- `scripts/run_paddleocr_samples.py`
- `scripts/check_runtime.py`
- `scripts/check_local_model.py`
- `scripts/check_no_vllm_swift_grpo_import.py`
- `scripts/inspect_env.py`
- `scripts/inspect_hf_dataset.py`
- `scripts/inspect_hf_rows.py`
- `scripts/inspect_hf_viewer.py`
- `scripts/inspect_jsonl.py`
- `scripts/inspect_rl_stack.py`
- `scripts/inspect_swift_cli.py`
- `scripts/inspect_trl_grpo_api.py`
- `scripts/inspect_workflow_trace.py`
- `scripts/list_hf_dataset_files.py`
- `scripts/extract_log_errors.py`

Training/runtime shell helpers:

- `scripts/bootstrap_autodl.sh`
- `scripts/eval_checkpoint_parallel.sh`
- `scripts/run_grpo_background.sh`
- `scripts/repair_autodl_env.sh`
- `scripts/server_smoke.sh`
- `scripts/train_grpo.sh`
- `scripts/train_sft.sh`
- `scripts/train_sft_smoke.sh`
- `scripts/train_trl_grpo.py`
- `scripts/train_trl_grpo_dual.sh`
- `scripts/train_custom_grpo.py`
- `scripts/grpo_reward_plugin.py`
- `scripts/no_vllm_stub.py`
- `scripts/no_vllm_swift_entrypoint.py`
- `scripts/no_vllm_sitecustomize/sitecustomize.py`
- `scripts/lib/gpu_env.sh`
- `scripts/sync_to_autodl.ps1`
- `scripts/summarize_grpo_run.py`
- `scripts/workflow_record_utils.py`
- `scripts/__init__.py`

### 10.3 Tests

The test suite is broad and mostly unit/fixture based. Important groups:

Phase 5:

- `tests/test_phase5_router.py`
- `tests/test_phase5c2_llm_router.py`
- `tests/test_phase5c3_query_planner.py`
- `tests/test_phase5_document_tools.py`
- `tests/test_phase5_local_fact_qa_tool.py`
- `tests/test_phase5d_local_fact_qa_smoke.py`
- `tests/test_phase5f_cli.py`
- `tests/test_phase5f_file_ingestion_cli.py`
- `tests/test_phase5f_mineru_file_cli.py`
- `tests/test_phase5g_cli_regression.py`
- `tests/test_phase5i_answer_quality_benchmark.py`

Ingestion, parsing, storage:

- `tests/test_document_registry.py`
- `tests/test_document_ingestion.py`
- `tests/test_ingestion_quality_report.py`
- `tests/test_mineru_converter.py`
- `tests/test_mineru_api_client.py`
- `tests/test_sqlite_trace.py`
- `tests/fixtures/mineru_real_schema/*`

Retrieval, packing, candidate diagnostics:

- `tests/test_dense_index.py`
- `tests/test_flagembedding_wrappers.py`
- `tests/test_reranker.py`
- `tests/test_rrf_fusion.py`
- `tests/test_query_document_smoke_backends.py`
- `tests/test_evidence_packing.py`
- `tests/test_candidate_answer_extraction.py`

Workflow, model, output, rewards:

- `tests/test_answer_policy.py`
- `tests/test_output_parser.py`
- `tests/test_workflow_model_node.py`
- `tests/test_workflow_repair_route.py`
- `tests/test_protocol_parity.py`
- `tests/test_reader_prompts.py`
- `tests/test_rewards.py`
- `tests/test_grpo_pipeline.py`
- `tests/test_smoke.py`

Historical Phase 2/3/4:

- `tests/test_phase2_e2e_mock.py`
- `tests/test_phase2_eval_smoke_backends.py`
- `tests/test_phase2_parse_existing_fixture.py`
- `tests/test_phase2_real_retrieval_smoke.py`
- `tests/test_phase2_real_workflow_smoke.py`
- `tests/test_phase2b_portability.py`
- `tests/test_phase2b_real_e2e_verifier.py`
- `tests/test_phase2b_verifier.py`
- `tests/test_phase3_focused_eval.py`
- `tests/test_phase3_mpdocvqa_retrieval_builder.py`
- `tests/test_phase3_server_acceptance.py`
- `tests/test_phase4b_expanded_sample.py`
- `tests/test_phase4b_mpdocvqa_e2e.py`
- `tests/test_phase4b_mpdocvqa_ingestion.py`
- `tests/test_mpdocvqa_raw_documents_builder.py`
- `tests/test_real_document_benchmark_contract.py`
- `tests/test_preflight_phase2.py`

Reports and helpers:

- `tests/test_analyze_reader_errors.py`
- `tests/test_build_answer_hard_grpo_subset.py`
- `tests/test_write_project_report.py`

### 10.4 Configs

- `configs/answer_policy.yaml`
- `configs/document_workflow.yaml`
- `configs/eval.yaml`
- `configs/grpo_qwen3.yaml`
- `configs/parser.yaml`
- `configs/parser_mineru.yaml`
- `configs/retrieval_hybrid.yaml`
- `configs/retriever.yaml`
- `configs/sft_qwen3_lora.yaml`
- `configs/workflow_mpdocvqa.yaml`

## 11. Documentation Inventory

Root documents:

- `README.md`: early project overview and local/server examples.
- `AGENTS.md`: repository rules, source-of-truth priority, status vocabulary, server command policy.
- `CURRENT_STATUS.md`: canonical current capability/status narrative.
- `DECISIONS.md`: chronological decision log.
- `pyproject.toml`: package metadata and optional dependencies.

Main planning documents:

- `docs/ACTIVE_PLAN.md`: current canonical milestone, status, blockers, stop condition.
- `docs/IMPLEMENTATION_PLAN.md`: high-level roadmap.
- `docs/PHASE5_ACTIVE_PLAN.md`: detailed current Phase 5 plan and accepted evidence.
- `docs/PHASE5_MVP_ACCEPTANCE.md`: MVP acceptance criteria.
- `docs/PHASE5_ROUTER_CONTRACT.md`: router and query planner contract.
- `docs/PHASE5_TOOL_INVENTORY.md`: reusable tools and gaps.

Historical phase documents:

- `docs/PHASE2_ACTIVE_PLAN.md`: accepted Phase 2 ingestion/retrieval history.
- `docs/PHASE3_ACTIVE_PLAN.md`: accepted/frozen Phase 3 evaluation record.
- `docs/PHASE4_ACTIVE_PLAN.md`: accepted Phase 4B/4C/4D record.
- `docs/PHASE4C_CANDIDATE_SPANS_REPORT.md`: candidate_spans A/B report.
- `docs/PHASE4D-A_Candidate_Answer_Coverage_Audit.md`: candidate answer coverage audit design.

Environment and data:

- `docs/SERVER_SETUP.md`: AutoDL paths, environment rules, command protocol, security.
- `docs/DATASETS.md`: dataset policy and download constraints.

Detailed design:

- `docs/design/phase2/PHASE2_REAL_DOCUMENT_HYBRID_RETRIEVAL_MVP.zh-CN.md`: detailed ingestion/retrieval design.
- `docs/design/phase2/PHASE2_STRUCTURED_PDF_PARSING_SUPPLEMENT.zh-CN.md`: structured parsing and context preservation design.
- `docs/DocAgent 技术文档 3.0.pdf`: original architecture blueprint.

This handoff:

- `docs/PROJECT_HANDOFF_PM.md`: PM-oriented consolidated handoff.

## 12. Data and Artifacts

Tracked source code does not include raw datasets, large model weights, or
most outputs. `.gitignore` excludes:

- `data/raw/`
- `data/processed/`
- `data/benchmark/*.jsonl`
- `data/real_documents/`
- `outputs/`
- model directories
- SQLite/db/log/zip files
- secrets and env files

Local workspace currently contains useful ignored artifacts, including:

- GLOBOCAN real-document sample under `data/real_documents/globocan_africa_2022/`;
- local `outputs/docagent.db`;
- Phase 2/4/5 smoke and benchmark output folders;
- MinerU live-smoke outputs.

PM rule: local ignored artifacts are helpful evidence for inspection, but
canonical accepted status should be read from `docs/ACTIVE_PLAN.md`,
`CURRENT_STATUS.md`, and accepted server artifact paths recorded there.

## 13. Environment Boundary

Local Windows workspace:

- edit code;
- run unit tests and lightweight local smoke;
- inspect docs and artifacts.

AutoDL server:

- GPU/model-dependent retrieval, Qwen, reranker, and full workflow smoke;
- expected repo path: `/root/autodl-tmp/docagent`;
- expected model root: `/root/autodl-tmp/models`;
- stable Conda env: `docagent`.

Do not silently install or replace Torch/CUDA, MinerU, models, or datasets.
Large downloads and environment mutation need explicit approval.

Secrets:

- Router LLM config can use `.secrets/router_llm.env`.
- `.secrets/` is ignored and must not be committed.

## 14. Risk Register

| Risk | Impact | Current mitigation |
|---|---|---|
| Final answer quality is not accepted | Users may see plausible but wrong answers | Phase 5I-A labels this as evidence readiness only; Phase 5I-B is future. |
| Summary/table/calculation are routed but not implemented | Product demo may expose unsupported paths | CLI returns structured unsupported errors or warnings. |
| local_fact_qa answer quality is unstable | Fact QA may fail even when execution succeeds | Keep execution-stability and quality claims separate. |
| Online MinerU OCR not accepted | Raw PDF UX depends on existing MinerU output | Existing-output path is accepted; online OCR is future work. |
| Page metadata inconsistency warning | Citation page may exceed `documents.page_count` in some scenarios | Warning exists; needs audit before product polish. |
| External LLM fallback may leak data if misused | Privacy and compliance risk | LLM Router/Rewriter receive only narrow planning/query payloads by contract. |
| Ignored local artifacts are not portable | New owner may not have the same data/output state | Use documented server artifact paths and regenerate when needed. |
| Large historical codebase | PM may confuse historical experiments with current product | Use `ACTIVE_PLAN.md` and this handoff as entry points. |

## 15. Recommended Next Milestone

Recommended next milestone:

```text
Phase 5E Document Summary MVP
```

Rationale:

- It is already in the Router taxonomy.
- It is visible in accepted regression limitations.
- It can improve user-facing MVP value without retraining.
- It should be bounded: use page text/page metadata, generate cited summary,
  avoid arbitrary top-k retrieval as the only context.

Minimal acceptance idea:

```text
one already ingested document
-> document_summary request
-> bounded page summary or extractive page preview strategy
-> final summary with page citations
-> JSON output and CLI artifacts
-> targeted tests and one server smoke
```

Out of scope for that milestone:

- table lookup;
- simple calculation;
- VLM;
- training;
- AnswerPolicy prompt changes;
- Candidate-ID Reader;
- full final answer-quality benchmark.

## 16. PM Takeover Checklist

First reading order:

1. `docs/PROJECT_HANDOFF_PM.md`
2. `docs/ACTIVE_PLAN.md`
3. `CURRENT_STATUS.md`
4. `docs/PHASE5_ACTIVE_PLAN.md`
5. `docs/PHASE5_MVP_ACCEPTANCE.md`
6. `docs/PHASE5_ROUTER_CONTRACT.md`
7. `docs/PHASE5_TOOL_INVENTORY.md`
8. `DECISIONS.md` recent entries only
9. `docs/SERVER_SETUP.md` before any server command

First product questions to answer:

- Should the next milestone be document summary, evidence-readiness cleanup,
  table/calculation, online MinerU, final answer quality, or UI/demo?
- Is the MVP expected to be CLI-only or should UI start after the next
  accepted backend milestone?
- Is external LLM allowed for summary generation, or only for routing/query
  planning?
- What documents define the demo scenario?
- What answer-quality bar is sufficient for portfolio presentation?

What not to do first:

- Do not restart training.
- Do not tune one failed sample.
- Do not build a VLM path.
- Do not call raw PDF OCR stable without an accepted MinerU environment.
- Do not claim Phase 5I-A is final answer quality.

## 17. Glossary

- EvidenceBlock: unified text/table/image/page evidence unit.
- candidate_spans: query-aware, structure-aware evidence packing mode.
- local_fact_qa: current fact QA wrapper around retrieval and AnswerPolicy.
- Router: task classifier and planner, not an answering model.
- Query Planner: retrieval query expansion and fusion layer.
- Evidence readiness: whether the pipeline can route, retrieve, cite, and
  package evidence before final answer evaluation.
- Final answer quality: answer correctness, not yet accepted for Phase 5.

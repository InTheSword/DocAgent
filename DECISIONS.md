# Decisions

## 2026-06-08: Phase 1 Workflow Integration Scope

Decision: integrate the trained Qwen Answer Policy into the workflow before expanding retrieval or multimodal branches.

Rationale:

- The project already has MP-DocVQA retrieved-reader SFT and grounded GRPO checkpoints.
- The main workflow still used a heuristic answer generator, so checkpoint quality was not represented in the traceable QA chain.
- Prompt construction, JSON parsing, validation, repair, and trace persistence need to be shared by eval and workflow paths before larger retrieval changes.

Constraints:

- `heuristic_answer` remains available only as an explicit local/mock backend.
- Workflow callers must pass an `AnswerPolicy`.
- Repair is bounded to one deterministic pass and cannot access gold answers or gold locations.
- Qwen model paths are configurable through CLI/config/environment usage and are not hard-coded into Python source.
- SQLite stores run summaries and node traces, but full prompts and chain-of-thought are not persisted.

## 2026-06-08: Phase 1 Acceptance

Decision: treat Phase 1 Qwen Answer Policy workflow integration as accepted and move next implementation effort to retrieval enhancement preparation.

Evidence:

- Base, SFT, and GRPO modes run through the same workflow CLI.
- SFT 50-sample workflow eval reached workflow success 1.0, raw JSON 1.0, schema 1.0, Answer F1 0.6715, location accuracy 0.92, and trace persist 1.0.
- GRPO 50-sample workflow eval reached workflow success 1.0, raw JSON 1.0, schema 1.0, Answer F1 0.6769, location accuracy 0.94, and trace persist 1.0.
- SQLite trace inspection successfully recovered the run and ordered node traces.

Follow-up:

- Do not tune prompts around individual low-answer examples in this phase.
- Track remaining answer mistakes as reader extraction errors for later answer-specific supervision or reward refinement.
- The next system-level implementation branch should start retrieval enhancement ablations, beginning with BGE-M3 dense retrieval and fusion design.

## 2026-06-11: Phase 2 MVP Boundary

Decision: start Phase 2 with real-document ingestion, MinerU conversion, and
hybrid retrieval infrastructure before running additional model training.

Rationale:

- Phase 1 already validated that Base/SFT/GRPO answer policies can run through
  the traceable workflow.
- The main project gap is now system shape: accepting real documents, caching
  parsed blocks, building retrievable indexes, and passing top-k evidence into
  the existing answer workflow.
- Dense and reranker model wrappers must fail loudly when model paths or
  packages are missing. A run must not be labeled `hybrid_rerank` unless the
  reranker executed.

Constraints:

- No new SFT/GRPO training in this stage.
- No reward changes or MP-DocVQA split changes.
- BM25 remains available as a baseline.
- The default Phase 1 workflow path remains compatible; the new retriever is
  opt-in through `run_qa_workflow(..., retriever=...)`.
- Local tests use mock/parse-existing fixtures. Real MinerU, BGE-M3, and
  reranker validation must run on AutoDL.

## 2026-06-13: Phase 2A Reranker Backend

Decision: in the current Transformers 5.x server environment, the real
`bge-reranker-v2-m3` path uses `AutoTokenizer` plus
`AutoModelForSequenceClassification` and raw logits for ranking. It does not
default to `FlagReranker.compute_score()`.

Rationale:

- `FlagEmbedding==1.4.0` reranker scoring calls tokenizer APIs that are not
  compatible with the installed `Transformers==5.8.1` tokenizer behavior.
- The sequence-classification path loads the local reranker model with
  `local_files_only=True`, supports explicit devices such as `cuda:1`, and
  records backend, model path, device, dtype, and max length in trace metadata.
- The server real model API smoke and real workflow smoke passed with backend
  `transformers_sequence_classification`.

Constraints:

- Do not silently fall back to keyword reranking for real-model runs.
- Do not downgrade Transformers or patch site-packages to make
  `FlagReranker.compute_score()` work.
- `FlagReranker` may only be revisited as an explicit optional backend after
  compatibility is proven.

## 2026-06-15: Phase 2B-2 Real Document E2E Acceptance

Decision: accept Phase 2B-2 as a real-document scenario integration milestone,
with scenario quality measured and formal benchmark evaluation still deferred.

Evidence:

- The fixed verifier `scripts/verify_phase2b_real_e2e.py` completed on the
  GLOBOCAN Africa 2022 PDF with real MinerU output, BGE-M3, FAISS, BM25, RRF,
  Transformers sequence-classification reranker, Qwen3 GRPO AnswerPolicy, JSON
  validation, location validation, and SQLite trace.
- `sample_count=8`, `completed_count=8`, `no_gold_leakage=true`,
  `no_mock_fallback=true`, `qa_runs=8`, and `tool_traces=49`.
- Retrieval metrics were `Recall@1=0.875`, `Recall@3=0.875`,
  `Recall@5=0.875`, and `MRR=0.875`.
- Answer metrics were `normalized_exact_match=0.625`, `token_f1=0.675`,
  `character_f1=0.7842548076923077`, and `answer_hit=0.625`.
- Location metrics were `block_location_hit=0.875`, `page_location_hit=1.0`,
  `final_location_in_retrieved_top_k=1.0`, and `location_valid_rate=1.0`.

Boundary:

- This is a real-document scenario acceptance result, not a formal DocVQA,
  MP-DocVQA, or general PDF-QA benchmark.
- Do not describe the current metrics as benchmark performance or model-quality
  sufficiency.
- Defer quality optimization. Current known failures are two reader table-column
  selection errors and one large-table retrieval / partial-answer / location
  error.

## 2026-06-15: Phase 3A Focused Evaluation Boundary

Decision: implement a focused fixed-subset evaluation layer instead of
expanding product features or creating a broad ablation matrix.

Rationale:

- Phase 2B-2 accepted the real-document integration path but did not produce a
  formal benchmark.
- The next evidence needed for project presentation is narrow: BM25 vs Hybrid
  retrieval, and SFT vs GRPO over identical fixed evidence.
- Existing retrieval, workflow, AnswerPolicy, metrics, and validators are
  sufficient; Phase 3A should orchestrate them rather than alter algorithms or
  prompts.

Constraints:

- The retrieval comparison must use the same qids, corpus, gold evidence,
  document scope, top-k, query input, and metric code.
- SFT and GRPO must consume the same fixed Hybrid evidence artifact; they must
  not retrieve independently.
- `deterministic_keyword_v1` is recorded only as deterministic query
  normalization, not as a full query-rewrite strategy.
- Local tests may use explicit mock backends, but real focused evaluation
  remains `not_started` until AutoDL runs real BGE-M3, reranker, SFT, and GRPO.
- The result is a fixed-subset evaluation unless an official complete split and
  official scoring protocol are used.

## 2026-06-15: Phase 3A Retrieval Corpus Contract

Decision: do not treat per-QA MP-DocVQA evidence arrays as a legal retrieval
benchmark corpus.

Rationale:

- `scripts/build_mpdocvqa_imdb_subset.py` builds each QA record from IMDb
  `image_name` and `ocr_tokens`, then stores those pages as that record's
  `evidence`.
- `metadata.imdb_doc_pages` and `metadata.total_doc_pages` are retained as
  metadata; the script does not emit a separate canonical per-document OCR
  corpus.
- Server audit found repeated `doc_id` values with multiple evidence
  signatures and partial page coverage, so simply unioning per-QA evidence
  would not be a proven query-independent corpus.

Constraints:

- BM25 vs Hybrid Recall/MRR requires an explicit `--corpus-input` containing
  stable query-independent `EvidenceBlock` records.
- Without that corpus, retrieval evaluation is `blocked` and must fail
  validation with a non-zero exit code.
- Valid reader artifacts may still be used for SFT vs GRPO through
  `--answer-only`, but that path is an AnswerPolicy comparison only and must
  not report retrieval metrics.

## 2026-06-15: Phase 3A MP-DocVQA Corpus Construction

Decision: construct the Phase 3A MP-DocVQA retrieval benchmark as separate
QA, corpus, and manifest artifacts.

Rationale:

- The QA artifact should carry qid, doc_id, question, answer, answer_type, and
  existing `metadata.gold_block_ids`, but no embedded candidate evidence.
- The corpus artifact should carry one stable official-OCR page block per
  canonical document page, using the existing `{page_id}_official_ocr` block ID
  rule.
- Gold mapping must be reused from the source QA artifact when available, or
  from explicit IMDb answer-page metadata; it must not be inferred by searching
  the answer string.

Constraints:

- Server-specific IMDb/OCR paths must be CLI inputs, not tracked constants.
- The generated corpus must pass the Phase 3 runner validator with
  `corpus_is_query_independent=true`, one corpus per doc, no duplicate block
  IDs, non-empty retrieval text, and complete gold block coverage before
  retrieval evaluation can move from `blocked` to `ready`.
- The builder does not run BGE-M3, the reranker, Qwen, or AnswerPolicy smoke.

## 2026-06-16: Unified Training-Inference Answer Protocol

Decision: route SFT dataset construction, GRPO dataset construction,
heuristic AnswerPolicy, Qwen AnswerPolicy, and workflow answer generation
through one evidence-context builder and one checkpoint-compatible prompt
compiler.

Rationale:

- Phase 3 comparisons require the training and inference paths to share prompt
  semantics, evidence ordering, block serialization, and truncation metadata.
- The workflow must persist enough trace data to audit whether a real retrieved
  block reached the model prompt and whether validation or repair changed the
  final answer.

Constraints:

- Do not change retrieval algorithms, top-k, query normalization, reward code,
  checkpoints, or training splits as part of this unification.
- Keep the core answer prompt semantics compatible with the existing SFT/GRPO
  checkpoints.
- Do not persist full prompts, credentials, signed URLs, or private artifacts in
  Git.

## 2026-06-16: Real-Document Acceptance Entry Point

Decision: add a single server acceptance entry point that performs compact
preflight, real-document contract construction, retrieval-only regression, and
optional focused-eval orchestration without loading answer models unless that
stage is explicitly selected.

Rationale:

- The server worktree may contain large untracked data and temporary notebook
  artifacts, so acceptance should reject tracked dirty changes but ignore
  untracked `data/`, `.ipynb_checkpoints`, and scratch files.
- GLOBOCAN is a real-document regression/scenario corpus and should be emitted
  as explicit QA, corpus, document manifest, and benchmark manifest artifacts.
- CDC should be handled as a real-document parsing dependency: ready when
  parsed MinerU output exists, otherwise blocked until server-side MinerU API
  ingestion is run with a runtime token.

Constraints:

- The server command must not install packages, download models, or commit
  generated artifacts.
- It must write long logs under `outputs/`, emit compact JSON, and avoid
  printing or persisting API tokens.
- Real metrics remain `not_started` until AutoDL runs the selected real-model
  stages.

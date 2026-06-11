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

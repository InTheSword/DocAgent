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

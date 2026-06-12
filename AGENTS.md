# DocAgent Codex Instructions

> Repository-level rules for Codex.  
> Keep this file concise. Project architecture and implementation details belong in `docs/`.

## 1. Mandatory reading

Before every task, read only:

1. `AGENTS.md`
2. `docs/PHASE2_ACTIVE_PLAN.md`
3. source code and tests directly related to the task

Do not scan every document by default.

## 2. Conditional document routing

Read additional documents only when the task requires them.

| Document | Read when |
|---|---|
| `docs/IMPLEMENTATION_PLAN.md` | deciding project scope, changing milestones, or updating the roadmap |
| `docs/SERVER_SETUP.md` | proposing server commands, checking environments, installing packages, downloading models, or running real models/tools |
| `docs/DATASETS.md` | downloading, converting, splitting, rebuilding, or evaluating datasets |
| `docs/design/phase2/PHASE2_REAL_DOCUMENT_HYBRID_RETRIEVAL_MVP.zh-CN.md` | implementing document registration, EvidenceBlock persistence, BGE-M3, FAISS, RRF, reranker, retrieval integration, SQLite document/index storage, or Phase 2 CLI/evaluation |
| `docs/design/phase2/PHASE2_STRUCTURED_PDF_PARSING_SUPPLEMENT.zh-CN.md` | implementing MinerU conversion, heading hierarchy, section paths, boilerplate filtering, table/image structure, context expansion, cross-page relations, or parsing-quality checks |
| `docs/DocAgent 技术文档 3.0.pdf` | architecture intent is unclear, a new phase is being designed, or implementation may diverge from the original blueprint |
| `CURRENT_STATUS.md` | checking verified current capabilities or updating accepted status |
| `DECISIONS.md` | revisiting a durable architecture, dependency, or scope decision |

The detailed design files explain **how** a Phase 2 module should work.  
`docs/PHASE2_ACTIVE_PLAN.md` defines **what must be done now**.

## 3. Source-of-truth priority

When information conflicts, use:

```text
1. explicit current user instruction
2. AGENTS.md
3. docs/PHASE2_ACTIVE_PLAN.md
4. verified current code, tests, and server artifacts
5. relevant detailed design document
6. CURRENT_STATUS.md / DECISIONS.md
7. docs/IMPLEMENTATION_PLAN.md
8. docs/DocAgent 技术文档 3.0.pdf
9. historical reports or old conversation notes
```

A planned capability is not an implemented capability.

## 4. Status vocabulary

Use only:

```text
not_started
implemented
mock_verified
server_dependency_ready
real_model_verified
benchmark_evaluated
accepted
frozen
blocked
```

Examples:

```text
hash dense backend → mock_verified
keyword reranker → mock_verified
synthetic MinerU fixture → mock_verified
real BGE-M3 server smoke → real_model_verified
formal real-model ablation → benchmark_evaluated
```

Mock verification must never be reported as real-component completion.

## 5. Single-milestone rule

Only implement the milestone in:

```text
docs/PHASE2_ACTIVE_PLAN.md
```

Before a non-trivial change, briefly state:

1. current gap;
2. relevant existing code;
3. files to modify;
4. dependencies;
5. acceptance test;
6. out-of-scope work;
7. stop condition.

Do not enter another milestone without explicit user approval.

## 6. Scope-control rules

Required:

- reuse existing abstractions before adding new ones;
- prefer the smallest change that enables real-component verification;
- stop when the active plan says to stop;
- wait for server output when the next action depends on server state.

Do not:

- optimize hash dense or keyword reranker after wiring smoke passes;
- add another fallback backend without explicit approval;
- run formal Recall/MRR or answer metrics with mock backends;
- treat synthetic MinerU output as real PDF parsing;
- modify SFT/GRPO checkpoints, reward, training split, or Phase 1 AnswerPolicy unless explicitly requested;
- start TAT-QA, VLM, Demo, or a new training phase while the active milestone is incomplete;
- mix unrelated refactors or style changes into the milestone commit.

## 7. Testing policy

Use the minimum sufficient validation:

```text
targeted unit tests
+ existing regression tests
+ one mock/fixture smoke if needed
+ one real server smoke
+ formal evaluation only after real smoke
```

Do not increase test count as a goal by itself.

When a failure occurs, classify it first:

```text
code defect
missing dependency
missing model/artifact
server configuration
incorrect command
unsupported case
non-blocking quality issue
```

Fix only issues that block the active milestone.

## 8. Server boundary

Codex works locally and cannot assume AutoDL resources exist.

Before proposing server commands, read:

```text
docs/SERVER_SETUP.md
```

Do not silently:

- install or replace Torch/CUDA;
- install MinerU;
- download large models or datasets;
- modify the stable `docagent` environment.

Large installation or download requires explicit user approval.

AutoDL no-card mode may produce:

```text
torch.cuda.is_available() == False
```

This is not, by itself, an environment error.

## 9. Server command and result protocol

Provide at most one executable server command group per round.

Commands must:

- use the correct project directory and Conda environment;
- contain no unresolved placeholders;
- check required paths and packages first;
- write long output to files;
- request only the minimum result needed.

Success response:

```json
{
  "command": "...",
  "status": "success",
  "artifact_paths": [],
  "metrics": {}
}
```

Failure response:

```json
{
  "command": "...",
  "status": "failed",
  "exit_code": 1,
  "exception": "...",
  "log_tail": "last 60 lines"
}
```

Do not routinely request full terminal logs, prompts, EvidenceBlocks, traces, or generations.

## 10. Completion rule

A real component may be marked `accepted` only after:

```text
implementation
+ targeted tests
+ regression tests
+ server dependency available
+ real component smoke
+ required artifact saved
+ status updated
```

If only mocks pass, use `mock_verified`.  
If code exists but the real dependency is unavailable, use `implemented`.  
If an external dependency prevents progress, use `blocked`.

## 11. Documentation updates

Update only when relevant:

- `PHASE2_ACTIVE_PLAN.md`: active milestone state or next action changes;
- `CURRENT_STATUS.md`: a real component is verified or a milestone is accepted;
- `DECISIONS.md`: a durable architecture or dependency decision changes;
- `IMPLEMENTATION_PLAN.md`: roadmap or phase status changes;
- `SERVER_SETUP.md`: stable server facts change;
- `DATASETS.md`: dataset source, split, or role changes;
- `AGENTS.md`: repository-wide rules change.

Do not store temporary logs in planning documents.

## 12. Communication style

Report:

1. conclusion;
2. milestone status;
3. changed files;
4. tests performed;
5. one next action;
6. stop condition.

Avoid repeating the full project history or suggesting unrelated expansion.

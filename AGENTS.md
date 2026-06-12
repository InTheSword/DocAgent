# DocAgent Codex Working Agreement

> Repository-level instructions for Codex.  
> This file defines how Codex should reason, plan, modify code, request server validation, and report progress.  
> It does not replace the project blueprint or the active milestone plan.

---

## 1. Project objective

DocAgent is being developed as a complete and verifiable complex-document question-answering assistant:

```text
real document input
→ structure-aware parsing
→ EvidenceBlock construction
→ BM25 + Dense Retrieval + RRF + Reranker
→ Qwen3 Answer Policy
→ format/location validation
→ bounded repair
→ SQLite trace
```

The current priority is to complete the real-component system loop.

Prefer:

```text
real component integration
→ one reproducible smoke test
→ milestone acceptance
```

over:

```text
more mock backends
→ more non-blocking tests
→ repeated local patching
```

Model quality, large-scale parameter tuning, and broader feature expansion are secondary until the current active milestone is accepted.

---

## 2. Required document reading order

Before planning, reasoning about, or modifying the repository, read the following files in order:

1. `AGENTS.md`
2. `docs/PHASE2_ACTIVE_PLAN.md`
3. `docs/IMPLEMENTATION_PLAN.md`
4. `docs/SERVER_SETUP.md`
5. `docs/DATASETS.md`
6. `docs/DocAgent 技术文档 3.0.pdf` when architecture, module scope, data flow, training design, evaluation design, or long-term project intent is relevant
7. `CURRENT_STATUS.md` if it exists
8. `DECISIONS.md` if it exists
9. Relevant source code, tests, generated reports, and recent Git history

The active task is always the milestone defined in:

```text
docs/PHASE2_ACTIVE_PLAN.md
```

Do not choose another milestone unless the user explicitly changes or accepts the current milestone.

---

## 3. Document roles and when to read them

### `AGENTS.md`

Role:

- repository-wide execution rules;
- Codex behavior constraints;
- task planning and server handoff protocol;
- mock/real status definitions;
- scope-control and stop conditions.

Read:

```text
before every task
before every implementation plan
before every server command proposal
```

Update only when repository-wide governance rules change.

---

### `docs/PHASE2_ACTIVE_PLAN.md`

Role:

- current unique milestone;
- current status;
- in-scope and out-of-scope work;
- required deliverables;
- server acceptance conditions;
- stop condition.

Read:

```text
before every Phase 2 task
before selecting files to modify
before claiming a milestone is complete
```

This is the most frequently updated planning document.

Update only when:

- the active milestone status changes;
- preflight or real-component verification changes the next action;
- the user explicitly accepts, replaces, or narrows the milestone.

Do not rewrite it during unrelated bug fixes.

---

### `docs/IMPLEMENTATION_PLAN.md`

Role:

- high-level project roadmap;
- completed, frozen, active, and deferred phases;
- long-term architecture and evaluation direction.

Read when:

- checking whether a proposed feature belongs to the project;
- determining the next phase after the active milestone;
- avoiding duplicate or conflicting implementations;
- updating overall project status.

Do not use it to override the narrower active plan.

Update only after:

- a milestone is accepted;
- a roadmap-level architectural decision changes;
- the user explicitly changes project priorities.

---

### `docs/SERVER_SETUP.md`

Role:

- local/server execution boundary;
- stable AutoDL paths;
- Conda environment policy;
- no-card/GPU-mode interpretation;
- model and dataset path conventions;
- installation and download restrictions;
- server result-return protocol.

Read before:

- proposing any server command;
- diagnosing CUDA/GPU behavior;
- installing packages;
- downloading models or datasets;
- invoking MinerU;
- running real BGE-M3, Reranker, Qwen3, or training jobs.

Important:

```text
torch.cuda.is_available() == False
```

is expected in AutoDL no-card mode and is not sufficient evidence of an environment failure.

Update only when stable server facts change.

Do not store transient logs, API keys, access tokens, passwords, or signed URLs.

---

### `docs/DATASETS.md`

Role:

- authoritative dataset sources;
- current data roles;
- frozen Phase 1 artifacts;
- split/leakage policy;
- deferred data work;
- download restrictions.

Read before:

- downloading or converting datasets;
- rebuilding SFT/GRPO data;
- changing train/dev/test splits;
- adding TAT-QA, InfographicVQA, or another source;
- making claims about MinerU, official OCR, or image data.

Update only when:

- a dataset source or role changes;
- a new dataset is formally accepted;
- frozen artifacts or split policies change;
- a new real-document ScenarioSet is accepted.

---

### `docs/DocAgent 技术文档 3.0.pdf`

Role:

- original project blueprint;
- target architecture;
- intended data construction, parsing, retrieval, workflow, SFT, GRPO, reward, and evaluation design.

Read when:

- architecture intent is unclear;
- a new module is being designed;
- implementation decisions may diverge from the blueprint;
- reviewing whether the project remains suitable for the intended resume positioning.

Do not treat planned modules in this document as already implemented.

Do not repeatedly reread the whole PDF for small local fixes when the active plan and current code are sufficient.

---

### `CURRENT_STATUS.md`

Role:

- concise current implementation status and verified artifacts.

Read when:

- checking what is already implemented;
- avoiding duplicate work;
- preparing a milestone report.

Update after real acceptance or a meaningful status change, not after every minor test.

---

### `DECISIONS.md`

Role:

- durable architecture and implementation decisions;
- rejected alternatives and reasons;
- scope changes caused by real implementation constraints.

Read before revisiting a previously decided issue.

Update only for decisions with future implementation impact.

Do not use it as a running terminal log.

---

## 4. Source-of-truth priority

When documents conflict, use this priority:

```text
1. explicit current user instruction
2. AGENTS.md
3. docs/PHASE2_ACTIVE_PLAN.md
4. verified current code and tests
5. CURRENT_STATUS.md / DECISIONS.md
6. docs/IMPLEMENTATION_PLAN.md
7. docs/DocAgent 技术文档 3.0.pdf
8. historical reports and old conversation notes
```

The blueprint defines intended direction. Verified code and accepted milestones define current reality.

Never report a planned capability as implemented solely because it appears in the blueprint.

---

## 5. Status vocabulary

Every major module or milestone must use one of the following states:

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

Definitions:

- `not_started`: implementation has not begun.
- `implemented`: code exists but has not completed required validation.
- `mock_verified`: mock/fixture wiring works; no real model/tool claim is allowed.
- `server_dependency_ready`: required packages, models, and artifacts exist on the server.
- `real_model_verified`: the real model, parser, or external tool passed a server smoke test.
- `benchmark_evaluated`: a reproducible benchmark report exists.
- `accepted`: all milestone acceptance criteria are satisfied.
- `frozen`: do not modify unless explicitly requested.
- `blocked`: an external dependency or explicit decision prevents progress.

Mock verification must never be presented as real-component completion.

Examples:

```text
hash dense backend → mock_verified
keyword reranker → mock_verified
synthetic MinerU content_list → mock_verified
BGE-M3 server smoke → real_model_verified
real MinerU output conversion → real_model_verified
formal retrieval ablation → benchmark_evaluated
```

---

## 6. Current execution principle

Only one active milestone may be implemented at a time.

Before modifying code for a non-trivial task, provide a concise implementation plan containing:

1. current gap;
2. relevant files already present;
3. files to modify or add;
4. dependencies and server resources;
5. exact deliverables;
6. local test commands;
7. server acceptance command;
8. explicit out-of-scope items;
9. stop condition.

Do not begin broad implementation before the task boundary is clear.

For a small, isolated fix, a shorter plan is acceptable, but it must still remain within the active milestone.

---

## 7. Scope-control rules

### Required behavior

- implement only the current active milestone;
- reuse existing abstractions before adding new ones;
- prefer the smallest change that enables real-component verification;
- stop after the milestone's stated stop condition;
- wait for server results when the next action depends on server state;
- clearly distinguish implementation from verification and acceptance.

### Prohibited behavior

Do not:

1. start TAT-QA, InfographicVQA, VLM, Demo, or new training during the current real-retrieval milestone;
2. modify SFT/GRPO checkpoints, reward, training split, or Phase 1 AnswerPolicy unless explicitly requested;
3. add another fallback backend after the current mock wiring has passed;
4. optimize hash dense or keyword reranker quality;
5. run formal Recall/MRR or answer metrics using mock backends;
6. treat synthetic MinerU fixtures as real PDF parsing;
7. silently broaden the task because a future module appears useful;
8. fix unrelated style, formatting, or refactoring issues in the same commit;
9. repeatedly patch non-blocking edge cases before real-component smoke;
10. continue into the next milestone without explicit user approval.

---

## 8. Mock backend policy

Mock backends exist only for:

```text
unit tests
CI
interface wiring
one local smoke test
```

After mock wiring passes:

```text
freeze the mock backend
move to the real component
```

Mock backends must not be used to support resume claims, formal reports, or benchmark conclusions.

The following substitutions are prohibited:

```text
hash encoder ≠ BGE-M3
keyword overlap ≠ cross-encoder reranker
synthetic content_list ≠ real MinerU output
heuristic answer ≠ Qwen3 AnswerPolicy
```

If a real component is unavailable, mark the milestone `blocked` or `implemented`, not `accepted`.

---

## 9. Testing policy

Each milestone should use the minimum sufficient validation stack:

1. targeted unit tests;
2. existing regression tests;
3. one local mock/fixture smoke if needed;
4. one server real-component smoke;
5. formal benchmark only after real-component smoke;
6. milestone acceptance.

Do not increase test count as a goal by itself.

Do not create repeated tests that validate the same behavior without addressing a known risk.

Do not continue improving mock output after it has proven interface connectivity.

When a failure occurs, first classify it as:

```text
code defect
missing dependency
missing model/artifact
server configuration
incorrect command
expected unsupported case
non-blocking quality issue
```

Fix only defects that block the active milestone.

---

## 10. Server execution boundary

Codex works in the local repository and cannot directly operate AutoDL.

Never assume the server has:

- the latest Git commit;
- the expected Conda environment;
- GPU mode enabled;
- BGE-M3;
- Reranker;
- MinerU;
- benchmark artifacts;
- built FAISS indexes;
- example documents.

Use the preflight script before real-component execution.

No code or command may silently:

- download a large model;
- download a large dataset;
- install CUDA/Torch;
- install MinerU;
- mutate the stable `docagent` environment.

Any large download or environment mutation requires explicit user approval.

---

## 11. Server command requirements

Every server command group must begin with:

```bash
cd /root/autodl-tmp/docagent
conda activate docagent
```

Unless the task explicitly targets an isolated environment such as MinerU.

Requirements:

1. provide at most one command group per round;
2. include all required path checks;
3. include all required package/model prechecks;
4. do not use unresolved placeholders such as:
   - `<sample>`
   - `<doc_id>`
   - `<model_path>`
5. do not ask the user to manually infer missing command arguments;
6. write long output to a log or JSON artifact;
7. request only the minimum result needed for the next decision.

If an identifier must be produced by an earlier command, capture it programmatically in the same command group or stop after the first command.

---

## 12. Server result-return protocol

For success, request only a compact summary such as:

```json
{
  "command": "phase2_real_retrieval_smoke",
  "status": "success",
  "backend": {
    "dense": "bge_m3",
    "reranker": "bge_reranker_v2_m3"
  },
  "artifact_paths": [],
  "metrics": {}
}
```

For failure, request only:

```json
{
  "command": "phase2_real_retrieval_smoke",
  "status": "failed",
  "exit_code": 1,
  "exception": "ExceptionType: message",
  "log_tail": "last 60 lines"
}
```

Do not routinely request:

- full terminal output;
- complete EvidenceBlock objects;
- full prompts;
- full traces;
- complete model generations;
- every environment package;
- large JSON files.

Request a specific field only when it is required to diagnose a named issue.

---

## 13. Preflight rule

Before any real BGE-M3, Reranker, MinerU, Qwen, or benchmark task, use the appropriate consolidated preflight.

The current Phase 2 preflight must:

- inspect only;
- not install;
- not download;
- not load full model weights;
- emit compact JSON;
- record optional missing resources without a long traceback.

After implementing the preflight script:

```text
stop
wait for the user's server preflight JSON
```

Do not proceed directly to installation or real-model smoke.

---

## 14. MinerU-specific rules

MinerU must not be installed into the stable `docagent` environment.

Current accepted roles:

```text
parse_existing fixture → mock verification only
real MinerU output → required for real parser verification
local MinerU CLI → optional deployment mechanism
```

MinerU installation is not part of the current real-retrieval milestone.

Do not let MinerU installation block BGE-M3/Reranker verification.

When MinerU becomes active:

- use a separate environment;
- prefer real structured output over Markdown-only chunking;
- preserve page, bbox, reading order, block type, table structure, image/caption relations, and hierarchy;
- do not call Markdown fixed-length chunking "layout-aware parsing".

---

## 15. Data and training constraints

During the current Phase 2 milestone:

- reuse accepted EvidenceBlock and benchmark artifacts;
- do not rebuild SFT/GRPO datasets;
- do not change document-level split;
- do not mine new hard subsets;
- do not restart GRPO sweeps;
- do not add a new dataset.

Inference and repair must never receive:

- gold answer;
- gold location;
- assistant target.

Any future dataset work must follow `docs/DATASETS.md`.

---

## 16. Git policy

- use one focused branch or commit series per milestone;
- one commit should have one clear purpose;
- do not mix unrelated refactors with milestone implementation;
- preserve stable checkpoints and generated benchmark artifacts;
- do not mark an implementation complete before real server smoke;
- include local test commands in the commit summary or task report;
- do not automatically enter the next milestone after pushing.

Before requesting server validation, report:

```text
commit hash
changed files
tests passed
expected server artifact
single server command group
```

---

## 17. Documentation update policy

Do not update every document after every minor edit.

### Update `docs/PHASE2_ACTIVE_PLAN.md` when:

- milestone state changes;
- preflight changes the next action;
- real smoke succeeds or fails in a way that changes the plan;
- the user changes scope.

### Update `CURRENT_STATUS.md` when:

- a real component is verified;
- a benchmark is completed;
- a milestone is accepted;
- a previously reported capability is invalidated.

### Update `DECISIONS.md` when:

- an architectural decision has future impact;
- a dependency/backend is selected or rejected;
- scope is intentionally changed.

### Update `docs/IMPLEMENTATION_PLAN.md` when:

- a milestone is accepted;
- the roadmap changes.

### Update `docs/SERVER_SETUP.md` when:

- stable environment facts or path policies change.

### Update `docs/DATASETS.md` when:

- dataset source, role, split, or accepted artifact changes.

### Update `AGENTS.md` only when:

- repository-wide execution rules change.

Do not place terminal logs or temporary debugging details in these documents.

---

## 18. Completion rule

A real component or milestone may be marked `accepted` only when all required conditions are satisfied:

```text
code implemented
+ targeted tests passed
+ regression tests passed
+ server dependency available
+ real component smoke passed
+ required artifacts saved
+ status document updated
```

If only local mocks pass:

```text
status = mock_verified
```

If code exists but the model/tool is unavailable:

```text
status = implemented
```

If an external dependency prevents progress:

```text
status = blocked
```

Do not use phrases such as "Phase 2 complete" or "real hybrid retrieval completed" before these conditions are met.

---

## 19. Communication style

Responses should prioritize:

1. current conclusion;
2. current milestone status;
3. files changed;
4. tests performed;
5. one next action;
6. exact stop condition.

Avoid:

- repeating the whole project history;
- producing long speculative roadmaps during a narrow task;
- asking for large, unfiltered logs;
- suggesting unrelated feature expansion;
- describing mock output as a project result;
- requesting multiple server test rounds at once.

---

## 20. Current mandatory stop behavior

For the current Phase 2 active plan:

1. read `docs/PHASE2_ACTIVE_PLAN.md`;
2. implement only the preflight task if it is still pending;
3. run local targeted and regression tests;
4. commit and push;
5. provide one compact server command group;
6. stop and wait for the server preflight JSON.

Do not install models, run real retrieval, start MinerU, or enter another phase before the preflight result is reviewed.

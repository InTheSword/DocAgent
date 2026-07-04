# DocAgent Codex Instructions

> Repository-level rules for Codex.  
> Keep this file concise. Project architecture and implementation details belong in `docs/`.

## 1. Mandatory reading

Before every task, read only:

1. `AGENTS.md`
2. `docs/ACTIVE_PLAN.md`
3. source code and tests directly related to the task

Do not scan every document by default.

## 2. Conditional document routing

Read additional documents only when the task requires them.

| Document | Read when |
|---|---|
| `docs/IMPLEMENTATION_PLAN.md` | deciding project scope, changing milestones, or updating the roadmap |
| `docs/SERVER_SETUP.md` | proposing server commands, checking environments, installing packages, downloading models, or running real models/tools |
| `docs/GPU_SERVER_BOUNDARY.md` | classifying whether implementation, tests, evaluation, or artifacts require GPU/server resources |
| `docs/DATASETS.md` | downloading, converting, splitting, rebuilding, or evaluating datasets |
| `docs/PHASE3_ACTIVE_PLAN.md` | checking detailed Phase 3 implementation notes or updating the Phase 3 working record |
| `docs/PHASE2_ACTIVE_PLAN.md` | checking archived Phase 2 status or legacy Phase 2 stop conditions |
| `docs/design/phase2/PHASE2_REAL_DOCUMENT_HYBRID_RETRIEVAL_MVP.zh-CN.md` | implementing document registration, EvidenceBlock persistence, BGE-M3, FAISS, RRF, reranker, retrieval integration, SQLite document/index storage, or Phase 2 CLI/evaluation |
| `docs/design/phase2/PHASE2_STRUCTURED_PDF_PARSING_SUPPLEMENT.zh-CN.md` | implementing MinerU conversion, heading hierarchy, section paths, boilerplate filtering, table/image structure, context expansion, cross-page relations, or parsing-quality checks |
| `docs/DocAgent 技术文档 3.0.pdf` | architecture intent is unclear, a new phase is being designed, or implementation may diverge from the original blueprint |
| `CURRENT_STATUS.md` | checking verified current capabilities or updating accepted status |
| `DECISIONS.md` | revisiting a durable architecture, dependency, or scope decision |

The detailed design files explain **how** a Phase 2 module should work.  
`docs/ACTIVE_PLAN.md` defines **what must be done now**.

PM-oriented handoff documents, including `docs/PROJECT_HANDOFF_PM.md`, are
deprecated and are not active planning sources. Do not read or update them
unless the user explicitly asks.

## 3. Source-of-truth priority

When information conflicts, use:

```text
1. explicit current user instruction
2. AGENTS.md
3. docs/ACTIVE_PLAN.md
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
ready
mock_verified
server_dependency_ready
real_model_verified
benchmark_evaluated
accepted
frozen
blocked
blocked_by_missing_mineru_output
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
docs/ACTIVE_PLAN.md
```

Before a non-trivial change, briefly state:

1. current gap;
2. relevant existing code;
3. files to modify;
4. dependencies;
5. acceptance test;
6. out-of-scope work;
7. GPU/server validation boundary;
8. stop condition.

Do not enter another milestone without explicit user approval.

## 6. Scope-control rules

Required:

- reuse existing abstractions before adding new ones;
- prefer the smallest change that enables real-component verification;
- stop when the active plan says to stop;
- wait for server output when the next action depends on server state.
- keep work anchored to the current delivery and functional goal, not to
  open-ended diagnostics, score chasing, or curiosity-driven local analysis.
- when an audit or evaluation finds an issue, first decide whether it blocks
  the deliverable execution chain. If it does not, record the limitation and
  move back to the next delivery task.

Do not:

- optimize hash dense or keyword reranker after wiring smoke passes;
- add another fallback backend without explicit approval;
- run formal Recall/MRR or answer metrics with mock backends;
- treat synthetic MinerU output as real PDF parsing;
- modify SFT/GRPO checkpoints, reward, training split, or Phase 1 AnswerPolicy unless explicitly requested;
- start TAT-QA, VLM, Demo, or a new training phase while the active milestone is incomplete;
- mix unrelated refactors or style changes into the milestone commit.
- keep repeating diagnosis on the same small sample set after the functional
  cause and delivery impact are understood;
- make case-specific repairs for one validation row, PDF page, table value,
  answer string, or question wording just to improve a local metric;
- use validation subsets as training data or as a source for sample-specific
  prompt/tool rules.

Generic fixes are allowed only when they improve reusable behavior such as:

- parser output preservation and conversion;
- EvidenceBlock, retrieval, evidence collection, citation, or artifact
  contracts;
- table/calculation behavior expressed as general rules;
- full workflow continuity from input document to final answer output.

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

Before implementing or validating a feature, classify the work as local-only,
server-optional, or server-required using `docs/GPU_SERVER_BOUNDARY.md`.
Product requests may omit this boundary; Codex owns the classification during
implementation and validation.

If the feature touches real BGE-M3, reranker, Qwen, SFT, GRPO, VLM, online
MinerU, or large real-model evaluation, add or reuse a real server validation
path and compact artifact contract. Local mocks, fixtures, hash dense,
keyword reranker, heuristic AnswerPolicy, and dry-run tests are not sufficient
for real-component acceptance.

If the feature is deterministic, API-only, CLI glue, SQLite/JSON contract work,
or another non-GPU function, implement and verify locally with targeted and
regression tests unless the active plan explicitly requires server smoke.

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

Codex may operate both the local workspace and the configured AutoDL server.
When the server connection is available and direct server work is authorized,
run the required server-side checks over SSH instead of asking the user to
manually paste commands or shuttle result files. Direct SSH access does not
remove the need for path, package, model, dataset, and GPU preflights.

Before running or proposing server commands, read:

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

Use direct SSH as the default server execution path when available. Provide a
user-pasted command group only when SSH is unavailable, the user explicitly
requests a pasted command, or the task requires user-side interactive handling.
In either mode, keep the server action focused and report compact structured
results.

Commands must:

- use the correct project directory and Conda environment;
- contain no unresolved placeholders;
- check required paths and packages first;
- write long output to files;
- request only the minimum result needed.
- define a two-layer evidence contract when terminal JSON may be insufficient:
  compact terminal JSON for status routing, plus named result/sync files for
  optional follow-up triage.
- preserve the user's interactive terminal session. User-pasted server command
  groups must not deliberately terminate the shell or parent terminal when a
  step fails.

When Codex runs the command over SSH, inspect the generated server artifacts
directly and summarize the result. Do not require manual upload/return of files
that can be read through the active server connection.

For Phase 4B Gate 3 server evaluation, provide Git sync, environment preflight,
and real evaluation as three short foreground Bash command blocks only if the
user must paste the commands. Do not use
`nohup`, `setsid`, background `&`, `tmux`, `kill`, `pkill`, or `exec` in
user-pasted commands.

Also do not use `set -e`, shell `exit`, `trap ... EXIT`, or inline Python
`raise SystemExit` / `sys.exit(...)` as outer-wrapper failure propagation in
commands the user pastes into an interactive server terminal. Capture
subprocess return codes and exceptions into compact JSON instead. If a called
script may return non-zero, wrap it so the supervising command still prints a
structured failure result and leaves the terminal open.

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

For new server tasks, prefer a curated sync bundle under
`outputs/sync/<run_id>/` with compact `result.json`, `manifest.json`,
`summary.json`, `summary.md`, previews, failure samples, and log tails. Do not
sync raw datasets, full output trees, model weights, databases, complete logs,
or secrets.

Treat terminal JSON as the first triage layer, not the whole evidence record.
Do not ask for extra files by default. If Codex has SSH access and compact JSON
is insufficient to classify a failure, inspect the named sync/result files or
run a small read-only server inspection command before doing a deep local code
audit. If SSH is unavailable, request only the specific named files or compact
inspection output needed to classify the failure.

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

- `PHASE3_ACTIVE_PLAN.md`: active milestone state or next action changes;
- `CURRENT_STATUS.md`: a real component is verified or a milestone is accepted;
- `DECISIONS.md`: a durable architecture or dependency decision changes;
- `IMPLEMENTATION_PLAN.md`: roadmap or phase status changes;
- `SERVER_SETUP.md`: stable server facts change;
- `GPU_SERVER_BOUNDARY.md`: GPU/server validation boundary or sync-artifact policy changes;
- `DATASETS.md`: dataset source, split, or role changes;
- `AGENTS.md`: repository-wide rules change.

Do not update PM-oriented handoff documents unless explicitly requested.
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

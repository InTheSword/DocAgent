# AutoDL Server Setup

> Stable environment facts and local/server execution rules only.  
> Task scope is defined in `docs/ACTIVE_PLAN.md`.

## 1. Execution model

```text
local Windows workspace:
  Codex edits code, runs local tests, commits, and pushes

AutoDL server:
  Codex may run SSH commands directly when the configured server connection is
  available and the user has authorized direct server work; otherwise the user
  can still paste the provided command group and return compact JSON/artifacts
```

Direct server operation does not relax the environment-safety rules in this
document. Server commands still need preflights, compact artifacts, no silent
large downloads, no unapproved package installation, and no destructive Git or
filesystem operations.

## 2. Server paths

```text
/root/autodl-tmp/docagent/   # repository, logs, outputs
/root/autodl-tmp/models/     # model weights
/root/autodl-tmp/datasets/   # raw datasets
```

Do not commit credentials, access tokens, signed URLs, or private SSH details.

## 3. Main DocAgent environment

```bash
cd /root/autodl-tmp/docagent
source /root/miniconda3/etc/profile.d/conda.sh
conda activate docagent
```

Non-interactive shells must load the Conda hook before `conda activate`.
Do not assume the hook is already available in Bash.

Observed environment:

```text
Python: 3.10.20
PyTorch: 2.12.0+cu130
Transformers: 5.8.1
ms-swift: 4.2.3
TorchVision: not installed
GPU: 1 x NVIDIA GeForce RTX 4090D 24GB
```

AutoDL no-card mode may produce:

```text
torch.cuda.is_available() == False
```

This is expected and must not be treated as a broken installation.

Do not reinstall PyTorch solely because no-card mode reports no CUDA device.

The current `docagent` environment is stable for the accepted Qwen3 workflow.

Current Phase 3 evaluation policy:

```text
default device scope: single GPU
current server GPU: 1 x NVIDIA GeForce RTX 4090D 24GB
```

The completed Qwen3-1.7B fixed-evidence runs used `cuda:0`. Two GPUs do not
automatically speed up the current inference, retrieval, or document-evaluation
paths because generation is single-sample autoregressive and SFT/GRPO runs are
serial. Use two GPUs only for heavier training, or after implementing explicit
SFT/GRPO dual-process parallelism with separate GPU assignment.

## 4. Expected model paths

```text
Qwen3:
/root/autodl-tmp/models/Qwen3-1.7B

BGE-M3:
/root/autodl-tmp/models/bge-m3

Reranker:
/root/autodl-tmp/models/bge-reranker-v2-m3
```

These are expected locations, not proof that the models exist.

Scripts must not silently download missing models.

AnswerPolicy v3 schema-smoke training may use the lightweight in-repo PEFT
LoRA runner to verify data and output contracts. For expanded or production
training experiments, prefer `ms-swift` as the training backend because it
supports LoRA, QLoRA, DoRA, GaLore, and related methods. Before using it on the
server, run a package/environment preflight first; do not install or replace
packages in the stable `docagent` environment without explicit approval.

## 5. MinerU environment policy

MinerU must use a separate environment.

Current status:

```text
parse_existing fixture: mock_verified
existing real MinerU output consumption: real_model_verified
real MinerU CLI: not_started; no longer a final-delivery target
MinerU API raw PDF smoke: accepted on 2026-06-30, run_id
  final_raw_pdf_mineru_api_cli_smoke_20260630, commit 31cdd18, 4/4 CLI
  contract cases passed with used_mineru_api=true and used_online_mineru_ocr=true
MinerU API client: accepted for secret-file execution; reads MINERU_TOKEN from
  environment, or MINERU_TOKEN/API_TOKEN from .secrets/mineru.env when present
```

Allowed options:

1. consume one real MinerU output produced externally;
2. use MinerU API with `MINERU_TOKEN` supplied through environment variables
   or `MINERU_TOKEN`/`API_TOKEN` in `.secrets/mineru.env`;
3. create an isolated MinerU CLI environment only if a future task explicitly
   reopens local CLI execution.

Recommended local secret file:

```bash
# .secrets/mineru.env
MINERU_TOKEN=...
# API_TOKEN=... is also accepted in this file for compatibility with
# historical MinerU examples.
```

The file is ignored by Git. Server runs may also keep using a manually
exported `MINERU_TOKEN` for one terminal session.

Do not install MinerU CLI packages into the stable `docagent` environment.

MinerU installation must not block the current Phase 2A retrieval milestone.

## 6. Environment and download rules

Before any environment mutation:

1. run the relevant preflight;
2. list missing packages/models;
3. propose one minimal action;
4. wait for user approval.

Do not silently:

- install CUDA/Torch;
- downgrade Transformers;
- install MinerU;
- download BGE-M3, Reranker, Qwen, or datasets.

## 7. Preflight

Current command is defined by the active milestone.

The preflight must:

- inspect only;
- not install;
- not download;
- not load full model weights;
- output compact JSON;
- report missing optional resources without a long traceback.

## 8. Server command requirements

Every command group must:

- begin in `/root/autodl-tmp/docagent`;
- activate the intended environment;
- contain no unresolved placeholders;
- check required files/packages first;
- write long output under `outputs/logs/`;
- provide at most one command group per interaction;
- define the expected evidence contract: compact terminal JSON for status
  routing, and only when useful, exact result files, sync-bundle files,
  previews, or log-tail files for optional follow-up triage;
- preserve the interactive terminal. A pasted command group must not
  deliberately close, replace, or terminate the user's shell or terminal session
  when any inner command fails.

For Phase 4B Gate 3, use three short foreground Bash blocks: Git sync,
environment/data/model preflight, and the actual evaluation. Do not use
`nohup`, `setsid`, background `&`, `tmux`, `kill`, `pkill`, or `exec` in
commands the user directly pastes into the server terminal. The evaluation block
should write full stdout/stderr to logs while printing stage messages and a
compact final JSON in the foreground.

Do not use `set -e`, shell `exit`, `trap ... EXIT`, or inline Python
`raise SystemExit` / `sys.exit(...)` as outer-wrapper failure propagation in
commands pasted into an interactive server terminal. Capture return codes and
exceptions into the compact JSON result instead. If a called script may fail
with a non-zero status, the wrapper must continue far enough to print the
failure JSON and leave the terminal open.

If a task targets MinerU, explicitly activate the isolated MinerU environment instead of `docagent`.

## 9. Result-return protocol

Success:

```json
{
  "command": "...",
  "status": "success",
  "artifact_paths": [],
  "metrics": {}
}
```

Failure:

```json
{
  "command": "...",
  "status": "failed",
  "exit_code": 1,
  "exception": "...",
  "log_tail": "last 60 lines"
}
```

Do not request full logs, prompts, EvidenceBlocks, traces, or generations unless debugging a named field.

Compact terminal JSON is a routing signal, not always a complete debugging
record. Do not require extra files for every successful command. If the
returned JSON does not contain enough evidence to classify a failure, first
request the named artifacts already produced by the run, or provide a small
read-only follow-up command that prints only the missing summary fields. Do not
begin broad local code changes from under-specified server failures.

## 10. Git synchronization

Use:

```bash
cd /root/autodl-tmp/docagent
source /etc/network_turbo 2>/dev/null || true
git status --short
git fetch origin --prune
```

AutoDL provides `/etc/network_turbo` to improve outbound network reliability.
Source it before server-side Git commands such as `fetch`, `pull`, or `push`.
If the file is unavailable, continue with normal Git diagnostics and report the
network failure compactly.

Do not run destructive reset commands without explicit user approval.

Large generated artifacts, model weights, raw datasets, and indexes should remain outside Git or be ignored.

## 11. Security

Do not commit:

- SSH passwords or tokens;
- API keys;
- private repository credentials;
- signed dataset URLs;
- personal filesystem secrets.

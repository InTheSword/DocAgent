# AutoDL Server Setup

> Stable environment facts and local/server execution rules only.  
> Task scope is defined in `docs/ACTIVE_PLAN.md`.

## 1. Execution model

```text
local Windows workspace:
  Codex edits code, runs local tests, commits, and pushes

AutoDL server:
  Codex runs server work directly over SSH by default, inspects compact
  artifacts over SSH, and summarizes results without manual file handoff.
  User-pasted command groups are exceptional fallback only.
```

Direct server operation does not relax the environment-safety rules in this
document. Server actions still need preflights, compact artifacts, no silent
large downloads, no unapproved package installation, and no destructive Git or
filesystem operations. Manual command/file transfer is reserved for SSH outage,
explicit user request, or genuinely interactive user-side handling.

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

Current operating default:

```text
AutoDL starts in no-card mode unless the user explicitly switches to GPU mode.
```

Codex may continue CPU/API-only server work in no-card mode. Any task that
loads or trains Qwen, BGE-M3, the cross-encoder reranker, VLMs, or other
GPU-required model paths must pause first and ask the user to switch the server
to GPU mode.

Use this lightweight check to classify the current server mode without loading
project models:

```bash
python scripts/check_runtime.py --compact
```

Interpret `resource_mode=gpu_visible` as GPU-visible for PyTorch. Treat
`no_card_or_cpu`, `gpu_driver_visible_torch_cpu`, `cuda_inconsistent`, or
`torch_unavailable` as not ready for GPU-required model work until the user
switches the server mode or the environment issue is resolved.

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

## 8. Server action requirements

Every server action must:

- begin in `/root/autodl-tmp/docagent`;
- activate the intended environment;
- contain no unresolved placeholders;
- check required files/packages first;
- write long output under `outputs/logs/`;
- define the expected evidence contract: compact terminal JSON for status
  routing, and only when useful, exact result files, sync-bundle files,
  previews, or log-tail files for optional follow-up triage;
- inspect the generated server artifacts directly over SSH before deciding the
  next local code or documentation change.

If a user-pasted fallback command is unavoidable, provide at most one short
foreground command group per interaction. It must preserve the interactive terminal
and must not deliberately close, replace, or terminate the user's shell when any
inner command fails. Do not use `nohup`, `setsid`, background `&`, `tmux`,
`kill`, `pkill`, or `exec` in commands the user directly pastes into the server
terminal.

Do not use `set -e`, shell `exit`, `trap ... EXIT`, or inline Python
`raise SystemExit` / `sys.exit(...)` as outer-wrapper failure propagation in
fallback commands pasted into an interactive server terminal. Capture return
codes and exceptions into compact JSON instead.

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
record. Do not require extra files for every successful command. If the returned
JSON or summary does not contain enough evidence to classify a failure, inspect
the named artifacts already produced by the run over SSH or run a small
read-only follow-up inspection that prints only the missing summary fields. If
SSH is unavailable, request only those named artifacts or the compact inspection
output. Do not begin broad local code changes from under-specified server
failures.

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

If Git network access still fails after sourcing `/etc/network_turbo`, clear
proxy variables and retry after a short pause before re-enabling the accelerator:

```bash
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY
sleep 30
source /etc/network_turbo 2>/dev/null || true
git fetch origin --prune
```

If this still fails, use compact diagnostics or an SSH-transferred Git bundle
for small code/doc syncs rather than blocking on repeated GitHub retries.

Do not run destructive reset commands without explicit user approval.

Large generated artifacts, model weights, raw datasets, and indexes should remain outside Git or be ignored.

## 11. Security

Do not commit:

- SSH passwords or tokens;
- API keys;
- private repository credentials;
- signed dataset URLs;
- personal filesystem secrets.

# AutoDL Server Setup

> Stable environment facts and local/server execution rules only.  
> Task scope is defined in `docs/PHASE2_ACTIVE_PLAN.md`.

## 1. Execution model

```text
local Windows workspace:
  Codex edits code, runs local tests, commits, and pushes

AutoDL server:
  user pulls code and runs GPU/model/data-dependent commands
```

Codex cannot directly inspect or operate AutoDL.

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

## 5. MinerU environment policy

MinerU must use a separate environment.

Current status:

```text
parse_existing fixture: mock_verified
existing real MinerU output consumption: real_model_verified
real MinerU CLI local_cli: blocked, no isolated MinerU Conda env observed on 2026-06-30
```

Allowed options:

1. consume one real MinerU output produced externally;
2. use an isolated CPU `mineru[pipeline]` environment for a small document set;
3. create an isolated GPU MinerU environment only if throughput requires it.

Do not install `mineru[core]` or `mineru[all]` into the stable `docagent` environment.

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
- provide at most one command group per interaction.

For Phase 4B Gate 3, use three short foreground Bash blocks: Git sync,
environment/data/model preflight, and the actual evaluation. Do not use
`nohup`, `setsid`, background `&`, `tmux`, `kill`, `pkill`, or `exec` in
commands the user directly pastes into the server terminal. The evaluation block
should write full stdout/stderr to logs while printing stage messages and a
compact final JSON in the foreground.

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

## 10. Git synchronization

Use:

```bash
cd /root/autodl-tmp/docagent
git status --short
git fetch origin --prune
```

Do not run destructive reset commands without explicit user approval.

Large generated artifacts, model weights, raw datasets, and indexes should remain outside Git or be ignored.

## 11. Security

Do not commit:

- SSH passwords or tokens;
- API keys;
- private repository credentials;
- signed dataset URLs;
- personal filesystem secrets.

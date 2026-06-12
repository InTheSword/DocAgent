# AutoDL Server Setup and Execution Boundary

> This document records stable server facts and the local/server collaboration protocol.  
> Do not store SSH passwords, API keys, private repository tokens, or other secrets in this file.

---

## 1. Execution model

DocAgent uses:

```text
local Windows workspace:
  Codex edits code, runs local tests, commits and pushes

AutoDL server:
  user pulls code and runs GPU/model/data-dependent commands
```

Codex cannot directly inspect or operate the AutoDL server and must not assume server resources exist.

---

## 2. Remote layout

```text
/root/autodl-tmp/docagent/   # code, logs, small processed artifacts
/root/autodl-tmp/models/     # model weights
/root/autodl-tmp/datasets/   # raw datasets
```

Large models and datasets are downloaded manually after explicit user confirmation.

Do not commit real SSH endpoints or credentials to the repository. Keep them in a local, untracked note if needed.

---

## 3. Main DocAgent environment

Environment name:

```bash
conda activate docagent
```

Current observed environment:

```text
Python: 3.10.20
PyTorch: 2.12.0+cu130
Transformers: 5.8.1
TorchVision: not installed
```

In AutoDL no-card mode:

```text
torch.cuda.is_available() == False
```

is expected and must not be treated as an installation failure.

Do not reinstall PyTorch solely because CUDA is unavailable in no-card mode.

The `docagent` environment is considered stable for the current Qwen3 workflow and must not be modified to install MinerU.

---

## 4. MinerU environment policy

MinerU must use a separate environment because its dependency constraints may conflict with the current DocAgent environment.

Current status:

```text
MinerU local environment: not accepted
real MinerU CLI smoke: not completed
parse_existing fixture: mock_verified only
```

Allowed deployment options, in priority order:

1. use one real MinerU output from an external/online/independent environment;
2. use an isolated CPU `mineru[pipeline]` environment for a small number of PDFs;
3. create a separate GPU MinerU environment only if throughput becomes necessary.

Do not install `mineru[all]` or `mineru[core]` in the `docagent` environment.

Do not let MinerU installation block the active real BGE-M3/Reranker milestone.

---

## 5. Model paths

Expected paths:

```text
Qwen3:
/root/autodl-tmp/models/Qwen3-1.7B

BGE-M3:
/root/autodl-tmp/models/bge-m3

Reranker:
/root/autodl-tmp/models/bge-reranker-v2-m3
```

These are expected locations, not proof that the models exist.

The Phase 2 preflight script must check:

- path existence;
- basic config/tokenizer files;
- required Python packages;
- no large model loading.

No script may silently download a missing model.

---

## 6. Dataset paths

```text
/root/autodl-tmp/datasets/mp_docvqa/
/root/autodl-tmp/datasets/tatqa/
```

Raw data remains outside the repository.

Processed benchmark JSONL files and small reports may live under:

```text
/root/autodl-tmp/docagent/data/benchmark/
/root/autodl-tmp/docagent/outputs/
```

---

## 7. Server preflight

Before any real-component milestone, run one consolidated preflight instead of many ad hoc commands.

Target script:

```bash
cd /root/autodl-tmp/docagent
conda activate docagent

python scripts/preflight_phase2.py   --qwen-model-path /root/autodl-tmp/models/Qwen3-1.7B   --bge-model-path /root/autodl-tmp/models/bge-m3   --reranker-model-path /root/autodl-tmp/models/bge-reranker-v2-m3   --output outputs/preflight/phase2.json
```

The script must:

- inspect only;
- not install;
- not download;
- not load full model weights;
- output compact JSON;
- exit successfully even when optional resources are missing.

---

## 8. Server command rules

Every command group provided by Codex must begin with:

```bash
cd /root/autodl-tmp/docagent
conda activate docagent
```

Requirements:

1. no unresolved placeholders such as `<doc_id>` or `<model_path>`;
2. at most one command group per interaction;
3. check paths and packages before execution;
4. no automatic large dependency/model download;
5. any environment mutation requires explicit approval;
6. long jobs must write logs to `outputs/logs/`.

---

## 9. Result return protocol

Successful run:

```json
{
  "command": "phase2_preflight",
  "status": "success",
  "backend": null,
  "artifact_paths": [
    "outputs/preflight/phase2.json"
  ],
  "metrics": {}
}
```

Failed run:

```json
{
  "command": "phase2_preflight",
  "status": "failed",
  "exit_code": 1,
  "exception": "ExceptionType: message",
  "log_tail": "last 60 lines"
}
```

Unless a specific field is being debugged, do not request:

- full terminal output;
- full EvidenceBlock objects;
- full prompts;
- full traces;
- full model generations.

---

## 10. Runtime checks

Use the project runtime/preflight scripts rather than interpreting `nvidia-smi` alone.

No-card mode and GPU mode must be distinguished explicitly.

Do not infer a broken CUDA installation from:

```text
torch.cuda.is_available() == False
```

when the server is intentionally in no-card mode.

---

## 11. Git and server synchronization

Standard flow:

```bash
cd /root/autodl-tmp/docagent
git status --short
git pull --ff-only
```

Do not run destructive reset commands unless the user explicitly requests them.

Server-generated large artifacts, model weights, indexes, and raw datasets must remain outside Git or be ignored.

---

## 12. Security

Do not commit:

- SSH host/user details if the repository is public;
- access tokens;
- API keys;
- private model URLs;
- signed dataset URLs;
- personal filesystem secrets.

Use environment variables or untracked local notes.

# GPU and Server Validation Boundary

> Resource boundary for DocAgent implementation, validation, and server
> artifact handling. This document is operational policy, not a milestone plan.

## Purpose

Product requirements may not mention whether a feature is local-only or
server/GPU-dependent. Implementation still must classify the resource boundary
before choosing tests, evaluation, and acceptance evidence.

A planned capability is not an implemented capability. A local mock, fixture,
or CPU-only test is not evidence that a real GPU/model component is complete.

## Resource Classes

Use these classes when planning implementation and validation.

| Class | Meaning | Validation rule |
|---|---|---|
| `local_only` | Deterministic code or lightweight API logic with no local model, GPU, or large dataset requirement. | Local targeted tests plus relevant regression tests are sufficient. |
| `server_optional` | Can run locally in a limited way, but realistic throughput or real dependencies may require a server. | Local tests are required; server smoke is required only when the accepted milestone depends on the real dependency. |
| `server_required` | Requires real GPU/model/server resources for acceptance. | Add or reuse a real server smoke/evaluation path. Local tests alone can only support `implemented` or `mock_verified`. |

## Server-Required Components

These components must be verified on server GPU resources when they are part of
the acceptance claim.

| Component | Typical code/scripts | Required server dependency | Notes |
|---|---|---|---|
| BGE-M3 dense encoder | `docagent/retrieval/dense_encoder.py`, `scripts/smoke_phase2_real_models.py`, `scripts/smoke_phase2_real_retrieval.py` | `/root/autodl-tmp/models/bge-m3`, CUDA-capable PyTorch | Hash dense tests are mock-only. |
| bge-reranker-v2-m3 CrossEncoder | `docagent/retrieval/reranker.py`, `scripts/smoke_phase2_real_models.py`, `scripts/smoke_phase2_real_retrieval.py` | `/root/autodl-tmp/models/bge-reranker-v2-m3`, CUDA-capable PyTorch | Keyword reranker tests are mock-only. |
| Real hybrid retrieval benchmark/smoke | `scripts/smoke_phase2_real_retrieval.py`, `scripts/run_phase4b_mpdocvqa_e2e.py` | BGE-M3, reranker, FAISS, accepted corpus artifacts | BM25/RRF unit tests do not prove real dense retrieval. |
| Qwen3 AnswerPolicy inference | `docagent/models/qwen_answer_policy.py`, `scripts/run_workflow_smoke.py`, `scripts/eval_workflow_e2e.py` | `/root/autodl-tmp/models/Qwen3-1.7B`, optional SFT/GRPO adapter, CUDA | Heuristic AnswerPolicy is local-only and not a model substitute. |
| Full GRPO workflow E2E | `scripts/smoke_phase2_real_workflow.py`, `scripts/verify_phase2b_real_e2e.py`, `scripts/run_phase4b_mpdocvqa_e2e.py` | BGE-M3, reranker, Qwen3, GRPO adapter, CUDA | Retrieval models should be released before loading Qwen when memory is tight. |
| SFT training | `scripts/train_sft.sh`, `scripts/train_sft_smoke.sh` | Qwen3 base model, training dataset, CUDA | New training is out of scope unless explicitly approved. |
| GRPO/RL training | `scripts/train_grpo.sh`, `scripts/train_trl_grpo.py`, `scripts/train_custom_grpo.py` | Qwen3 base model, adapter, reward code, dataset, CUDA | GRPO CPU runs are too slow for project validation. |
| VLM visual review | `docagent/integrations/vlm_api.py`, `docagent/tools/visual_summary.py`, `docagent/tools/visual_review.py`, `scripts/docagent_cli.py` | VLM model/API or GPU VLM runtime | Current status is `real_model_verified` for API summary/review, CLI pre-index persistence, and one real PDF file-input visual chain via `visual_vlm_api_real_smoke_clean_20260707`, `visual_vlm_cli_prepare_index_smoke_20260707`, and `existing_pdf_visual_vlm_full_chain_artifact_review_20260707`; formal visual-answer benchmarking is not accepted. |
| Large real-model benchmark | Phase 3/4/5 server benchmark scripts | Accepted dataset artifacts plus required models | Local fixture tests are not benchmark evidence. |

## Server-Optional Components

| Component | Boundary |
|---|---|
| MinerU parsing from raw PDF | Existing MinerU output can be consumed locally or on server. Online MinerU CLI/API execution must use an isolated environment; GPU MinerU is required only if throughput requires it. |
| External LLM Router or Query Planner fallback | Does not require local GPU, but requires API credentials and a real API smoke when acceptance depends on the fallback. |
| FAISS index save/load | Can be tested locally with small embeddings. Real dense embeddings still require BGE-M3 server validation. |
| SQLite trace, CLI JSON contracts, deterministic tools | Local tests are normally sufficient unless the test path also invokes real models. |

## Per-Task Validation Checklist

For every non-trivial implementation task, classify the requested feature before
choosing validation.

1. Does the implementation call or evaluate BGE-M3, reranker, Qwen, SFT, GRPO,
   VLM, online MinerU, or a large accepted dataset?
2. Does the expected acceptance claim include `real_model_verified`,
   `benchmark_evaluated`, or `accepted` for a real component?
3. Is a local test using a mock, fixture, hash dense backend, keyword reranker,
   heuristic AnswerPolicy, or dry-run path?
4. If the answer to 1 or 2 is yes, add or reuse a server validation path and a
   compact artifact contract.
5. If the answer to 1 and 2 is no, keep implementation and verification local.

When a feature is `server_required`, local work should still include targeted
unit tests and regression tests, but the final status must remain
`implemented` or `mock_verified` until real server evidence exists.

## Server Validation Requirements

Server validation commands and scripts must:

- check model, dataset, database, and package paths before running;
- for GPU-required work, classify the current server mode first with
  `python scripts/check_runtime.py --compact`; only `resource_mode=gpu_visible`
  is GPU-ready for PyTorch model loading/training;
- avoid silent downloads and environment replacement;
- print a compact final JSON result;
- write long stdout/stderr to files;
- save summaries, metrics, previews, and failure samples as structured files;
- avoid storing secrets, signed URLs, full prompts, full generations, or raw
  large data in sync artifacts;
- report whether GPU, external API, VLM, training, and full E2E paths were used.

## Syncable Server Artifacts

Raw `outputs/`, datasets, databases, logs, checkpoints, and models stay ignored.
Do not unignore or commit them wholesale.

For new server tasks, create a small curated sync bundle when remote inspection
is useful:

```text
outputs/sync/<run_id>/
  result.json
  manifest.json
  summary.json
  summary.md
  preview.json
  failures_sample.jsonl
  log_tail.txt
  stderr_tail.txt
```

Required files:

- `result.json`: final command status, exit code, metrics, and key artifact paths.
- `manifest.json`: run id, command name, git commit, server path, file list,
  file sizes, and hashes for synced files.
- `summary.json` and `summary.md`: compact machine-readable and human-readable
  result summaries.
- `log_tail.txt` and `stderr_tail.txt`: only the last relevant lines, normally
  60-200 lines.

Optional files:

- `preview.json`: capped preview of representative records.
- `failures_sample.jsonl`: capped and sanitized failure examples.
- `metrics.json`: metrics-only payload when `summary.json` is broader.

Sync bundle rules:

- target size should stay under 2 MB;
- if a bundle would exceed 10 MB, summarize it instead and keep the raw files
  server-side;
- never include model weights, datasets, full SQLite databases, complete raw
  logs, `.env` files, API keys, signed URLs, or private tokens;
- prefer derived summaries over raw generations or full EvidenceBlocks;
- include enough artifact paths and hashes to let a later server rerun locate
  the original full outputs.
- command instructions should name specific sync/result files only when those
  files are expected to be useful for follow-up triage; do not make broad file
  upload a default requirement for every successful command.

When a server command completes, Codex should inspect sync artifacts directly
from the server over SSH in this order:

1. `outputs/sync/<run_id>/result.json`
2. `outputs/sync/<run_id>/manifest.json`
3. `outputs/sync/<run_id>/summary.md`
4. `outputs/sync/<run_id>/summary.json`
5. targeted preview or failure sample files only if needed

Do not request files from the user unless SSH is unavailable and a fallback
command was run outside Codex. Do not request full terminal logs unless the sync
bundle is missing or insufficient for triage.

If the terminal JSON is inconclusive, do not infer the root cause from local
code alone. Inspect the named sync/result files directly over SSH or run a
narrow read-only inspection command that reports only the missing fields needed
to classify the failure. Without SSH access, ask only for the named sync/result
files or compact inspection output required to classify the failure.

## Acceptance Mapping

| Evidence available | Allowed status |
|---|---|
| Local implementation only | `implemented` |
| Local mock/fixture/hash/keyword tests pass | `mock_verified` |
| Server dependency exists but real component smoke has not run | `server_dependency_ready` |
| Real model smoke passes and artifact is saved | `real_model_verified` |
| Formal real-model evaluation passes on accepted scope | `benchmark_evaluated` |
| Required implementation, tests, server smoke, artifacts, and status updates are complete | `accepted` |

If a GPU/server dependency is unavailable, use `blocked` rather than reporting a
real component as complete from local-only evidence.

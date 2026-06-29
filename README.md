# DocAgent

DocAgent is a local, CLI-first complex-document QA project. The current active
track is the Phase 5 personal-use MVP: ingest or select a document, ask a
question, and return an answer with a short reasoning summary, evidence used,
citations, tools used, and local trace artifacts.

The current delivery is not a UI product, cloud service, VLM visual-reasoning
system, or accepted final answer-quality benchmark.

## Current Entry Points

Main CLI:

```powershell
python scripts\docagent_cli.py --file <path> --question "<question>"
python scripts\docagent_cli.py --doc-id <doc_id> --question "<question>"
```

List local documents:

```powershell
python scripts\docagent_cli.py --list-documents --db-path outputs\docagent.db
```

Prepare local final-evaluation subsets:

```powershell
python scripts\prepare_final_eval_subset.py `
  --dataset all `
  --tatqa-limit 80 `
  --mpdocvqa-target-qa-count 50 `
  --mpdocvqa-min-qa-count 30 `
  --mpdocvqa-max-qa-count 70 `
  --overwrite
```

Run local subset diagnostics:

```powershell
python scripts\run_final_eval_subset.py `
  --dataset all `
  --run-id local_subset_full_diagnostic_report `
  --output-dir outputs\final_eval\local_subset_diagnostic
```

See [docs/FINAL_DELIVERY_CLI.md](docs/FINAL_DELIVERY_CLI.md) for the complete
current CLI contract, storage paths, dataset commands, output fields, and
limitations.

## Current Output Contract

Normal QA-style CLI output includes:

```json
{
  "answer": "...",
  "reasoning_summary": "...",
  "evidence_used": [],
  "citations": [],
  "tools_used": [],
  "trace_path": "outputs/cli/<run_id>/trace.json"
}
```

Citation records carry document and location fields such as `doc_id`, `page`,
`block_id`, `block_type`, and preview text/table/image metadata when available.

## Local Storage

Default paths:

```text
outputs/docagent.db
outputs/cli/<run_id>/
data/documents/
outputs/final_eval/
```

These are local artifacts. Raw datasets, generated outputs, SQLite databases,
document caches, secrets, model weights, and logs are not intended for Git
commits.

## Implemented Locally

- unified CLI and artifact contract;
- text file ingestion;
- existing MinerU output ingestion;
- raw PDF MinerU local CLI wrapper with structured failure artifacts;
- deterministic document statistics and page lookup;
- deterministic extractive document summary;
- deterministic structured extraction over persisted evidence;
- deterministic table lookup and simple traceable calculations;
- `local_fact_qa` workflow wrapper;
- AnswerPolicy candidate output schema and citation allowlist filtering;
- local TAT-QA / MP-DocVQA validation-subset preparation;
- local diagnostic reporting with `summary.json` and `summary.md`.

## Not Accepted Yet

- formal MP-DocVQA/TAT-QA final answer benchmark;
- final Qwen answer-quality acceptance;
- accepted online MinerU OCR run from raw PDF;
- pixel-level image/chart VLM reasoning;
- new SFT/GRPO training;
- UI, FastAPI, Gradio, cloud storage, or multi-user service.

## Documentation Map

- [docs/ACTIVE_PLAN.md](docs/ACTIVE_PLAN.md): current milestone and stop
  condition.
- [CURRENT_STATUS.md](CURRENT_STATUS.md): current verified capability status.
- [docs/FINAL_DELIVERY_CLI.md](docs/FINAL_DELIVERY_CLI.md): current CLI
  delivery guide.
- [docs/DATASETS.md](docs/DATASETS.md): dataset roles, split policy, and
  download constraints.
- [AGENTS.md](AGENTS.md): repository rules for implementation and validation.

PM-oriented handoff documents are deprecated and are not current planning
sources.

Historical Phase 1-4 implementation details remain in the phase-specific docs
under `docs/`.

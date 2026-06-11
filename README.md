# DocAgent

DocAgent is a complex document QA and post-training project based on the
DocAgent 3.0 plan. The first implementation milestone is intentionally small:
it validates the data schema, evidence retrieval, traceable QA workflow,
reward functions, and evaluation code before GPU training.

## First milestone

```text
DocAgentSample
-> EvidenceBlock
-> Query rewrite
-> BM25 retrieval
-> QA workflow trace
-> format / answer / location rewards
-> smoke evaluation
```

MinerU, Qwen3 LoRA-SFT, GRPO, and VLM review are represented as explicit
integration points. They are not required for the local smoke test.

## Local smoke test

```bash
cd docagent
python scripts/smoke_test.py
```

## Phase 1 workflow smoke

The traceable workflow now accepts an explicit answer policy. Local tests use
the heuristic backend only as a mock policy; server validation should use the
Qwen base/SFT/GRPO backends.

No-card local smoke:

```bash
python scripts/smoke_test.py
```

GPU workflow smoke on AutoDL:

```bash
python scripts/run_workflow_smoke.py \
  --input data/benchmark/mp_docvqa_dev_sft_retrieved_clean.jsonl \
  --index 0 \
  --policy-mode grpo \
  --base-model-path /root/autodl-tmp/models/Qwen3-1.7B \
  --adapter-path outputs/checkpoints/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-grounded-100step-20260606_105535 \
  --max-new-tokens 1024 \
  --sqlite-path outputs/traces/workflow_grpo_smoke.sqlite \
  --output outputs/traces/workflow_grpo_smoke_000.json
```

The workflow smoke/eval scripts preserve retrieved-reader evidence order by
default. Pass `--rerank-input-evidence` only when the input contains an
unranked evidence pool.

Small workflow eval:

```bash
python scripts/eval_workflow_e2e.py \
  --input data/benchmark/mp_docvqa_dev_sft_retrieved_clean.jsonl \
  --output outputs/eval/workflow_phase1_grpo.jsonl \
  --summary-output outputs/eval/workflow_phase1_grpo_summary.json \
  --limit 20 \
  --policy-mode grpo \
  --base-model-path /root/autodl-tmp/models/Qwen3-1.7B \
  --adapter-path outputs/checkpoints/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-grounded-100step-20260606_105535 \
  --max-new-tokens 1024
```

## Phase 2 real-document MVP

Phase 2 starts the real-document ingestion and hybrid retrieval chain. The
local no-card path can validate registration, parse-existing MinerU output,
SQLite persistence, BM25 retrieval, and heuristic answer policy. Real MinerU,
BGE-M3, bge-reranker-v2-m3, and Qwen policy evaluation should run on AutoDL.

No-card parse-existing smoke:

```bash
python scripts/build_phase2_parse_existing_fixture.py \
  --input data/benchmark/mp_docvqa_dev_sft_retrieved_clean.jsonl \
  --output-dir outputs/phase2_parse_existing_fixture \
  --index 0

python scripts/ingest_document.py \
  --file outputs/phase2_parse_existing_fixture/source/<source_file> \
  --mineru-output-dir outputs/phase2_parse_existing_fixture/mineru \
  --document-root data/documents \
  --sqlite-path outputs/docagent.db

python scripts/inspect_document.py \
  --doc-id <doc_id> \
  --show-blocks \
  --show-index \
  --sqlite-path outputs/docagent.db

python scripts/query_document.py \
  --doc-id <doc_id> \
  --question "What is the invoice date?" \
  --retriever bm25 \
  --policy-mode heuristic \
  --sqlite-path outputs/docagent.db
```

GPU hybrid retrieval query:

```bash
python scripts/query_document.py \
  --doc-id <doc_id> \
  --question "..." \
  --retriever hybrid_rerank \
  --policy-mode grpo \
  --dense-model-path /root/autodl-tmp/models/bge-m3 \
  --dense-device cuda:1 \
  --dense-fp16 \
  --build-index-if-missing \
  --reranker-model-path /root/autodl-tmp/models/bge-reranker-v2-m3 \
  --reranker-device cuda:1 \
  --reranker-fp16 \
  --base-model-path /root/autodl-tmp/models/Qwen3-1.7B \
  --adapter-path outputs/checkpoints/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-grounded-100step-20260606_105535 \
  --max-new-tokens 1024 \
  --sqlite-path outputs/docagent.db
```

No-download hybrid smoke:

Use this only to verify Phase 2 wiring when BGE-M3 or bge-reranker-v2-m3 are
not present on the server. The output must be reported as `hash` dense and
`keyword` reranker, not as a BGE/reranker result.

```bash
python scripts/query_document.py \
  --doc-id <doc_id> \
  --question "..." \
  --retriever hybrid_rerank \
  --policy-mode heuristic \
  --dense-backend hash \
  --build-index-if-missing \
  --reranker-backend keyword \
  --sqlite-path outputs/docagent.db
```

## Planned server workflow

Use local development with git/ssh, then run GPU jobs on the 2x RTX 3090
server.

```bash
ssh user@gpu-server "cd /path/to/docagent && git pull"
ssh user@gpu-server "cd /path/to/docagent && bash scripts/train_sft.sh"
ssh user@gpu-server "cd /path/to/docagent && bash scripts/train_grpo.sh"
```

## Implementation phases

1. Data schema and evidence index.
2. Query rewrite, BM25, dense retrieval, and reranker.
3. Traceable QA workflow with tools and SQLite traces.
4. MinerU parsing for ScenarioSet and real uploaded files.
5. Qwen3 LoRA-SFT with ms-swift.
6. GRPO reward training and ablation.
7. OCR-only vs OCR+VLM review on InfographicVQA.

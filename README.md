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


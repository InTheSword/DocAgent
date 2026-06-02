# Dataset Notes

Large datasets should be downloaded on AutoDL, not on the local Windows
machine.

## Primary datasets

### TAT-QA

Preferred source:

- Hugging Face: `next-tat/TAT-QA`

Role:

- Table-text QA
- Numerical reasoning
- Calculator and numeric reward

### InfographicVQA

Preferred source:

- Official DocVQA / RRC portal download.
- Community alternatives may exist on Hugging Face, but field schemas can vary.

Role:

- OCR-only vs OCR + VLM visual review
- Image/figure evidence block construction

### MP-DocVQA

Preferred source:

- Official DocVQA / RRC portal download when available.
- If official access is slow, use a public retrieval subset first for the
  retrieval MVP, then replace it with the official dataset.

Role:

- Multi-page evidence retrieval
- Page-level location accuracy
- Evidence-grounded answer policy training

## First remote subset target

Do not download or process the full datasets first.

Initial target:

- 50-100 MP-DocVQA-style samples.
- 50-100 TAT-QA samples.
- 50-100 InfographicVQA samples.

Expected generated files:

```text
data/benchmark/train_sft.jsonl
data/benchmark/dev_sft.jsonl
data/benchmark/test_eval.jsonl
data/benchmark/grpo_train.jsonl
```

The first dataset milestone is schema correctness, not volume.


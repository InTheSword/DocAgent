# Dataset Notes

Large datasets should be downloaded manually on AutoDL, not on the local
Windows machine. Scripts should read from local dataset paths by default.

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

## MP-DocVQA / InfographicVQA local subset conversion

Download only annotation files and small image/OCR subsets first. Keep raw files
outside the repository, for example:

```text
/root/autodl-tmp/datasets/mp_docvqa/
/root/autodl-tmp/datasets/infographicvqa/
```

Convert local annotations into DocAgent samples:

```bash
python scripts/build_vqa_subset.py \
  --source mp_docvqa \
  --input /root/autodl-tmp/datasets/mp_docvqa/train.json \
  --output data/benchmark/mp_docvqa_train_subset.jsonl \
  --split train \
  --limit 100

python scripts/build_vqa_subset.py \
  --source infographicvqa \
  --input /root/autodl-tmp/datasets/infographicvqa/train.json \
  --output data/benchmark/infographicvqa_train_subset.jsonl \
  --split train \
  --limit 100
```

For Hugging Face subsets with image columns, export a very small shard first:

```bash
python scripts/build_hf_vqa_subset.py \
  --source infographicvqa \
  --dataset kenza-ily/infographicvqa_disco \
  --split train \
  --output data/benchmark/infographicvqa_disco_subset.jsonl \
  --image-output-dir data/images/infographicvqa_disco \
  --limit 50 \
  --allow-image-only
```

Image-only samples are marked with `metadata.needs_ocr=true` and should go
through OCR/VLM parsing plus LLM audit before being used for SFT/GRPO.

Then mix dataset shards for schema-level experiments:

```bash
python scripts/build_mixed_dataset.py \
  --input data/benchmark/tatqa_train_subset_1000.jsonl:300 \
  --input data/benchmark/mp_docvqa_train_subset.jsonl:100 \
  --input data/benchmark/infographicvqa_train_subset.jsonl:100 \
  --output data/benchmark/mixed_docagent_train_subset.jsonl
```

## LLM-assisted sample audit

Rule-based checks catch schema and simple evidence errors. Complex cross-source
samples should go through an LLM audit queue before SFT/GRPO construction.

Export audit tasks without calling any API:

```bash
python scripts/llm_audit_samples.py \
  --input data/benchmark/mixed_docagent_train_subset.jsonl \
  --tasks-output outputs/audit/mixed_docagent_audit_tasks.jsonl \
  --mode export \
  --limit 20
```

If an OpenAI-compatible endpoint is configured, run automatic audit:

```bash
OPENAI_API_KEY=... \
OPENAI_MODEL=gpt-4.1-mini \
python scripts/llm_audit_samples.py \
  --input data/benchmark/mixed_docagent_train_subset.jsonl \
  --tasks-output outputs/audit/mixed_docagent_audit_tasks.jsonl \
  --decisions-output outputs/audit/mixed_docagent_audit_decisions.jsonl \
  --audited-output data/benchmark/mixed_docagent_train_audited.jsonl \
  --report-output outputs/audit/mixed_docagent_audit_report.json \
  --mode api
```

The LLM decision schema is `keep | repair | drop`. Repaired samples preserve
the original record and add `metadata.llm_audit` for traceability.

## TAT-QA subset smoke

This can run in no-card mode:

```bash
python scripts/build_tatqa_subset.py \
  --split dev \
  --limit 100 \
  --raw-dir /root/autodl-tmp/datasets/tatqa

python scripts/eval_retrieval.py --input data/benchmark/tatqa_dev_subset.jsonl
```

The script expects a local file such as
`/root/autodl-tmp/datasets/tatqa/tatqa_dataset_dev.json`. It only downloads
from Hugging Face when `--allow-download` is passed explicitly.

Keep raw datasets outside the repository:

```bash
mkdir -p /root/autodl-tmp/datasets/tatqa
python scripts/build_tatqa_subset.py \
  --split dev \
  --limit 100 \
  --raw-dir ../datasets/tatqa \
  --output data/benchmark/tatqa_dev_subset.jsonl
```

Recommended AutoDL layout:

```text
/root/autodl-tmp/docagent   # code and small processed artifacts
/root/autodl-tmp/datasets   # raw datasets
/root/autodl-tmp/models     # model weights
```

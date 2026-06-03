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

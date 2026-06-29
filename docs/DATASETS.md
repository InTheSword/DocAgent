# DocAgent Dataset Policy

> Dataset sources, accepted artifacts, split policy, and download rules only.

## 1. Current policy

During the active Phase 5 final-delivery track:

```text
prepare small reproducible validation subsets locally
-> keep source files, hashes, filter reports, manifests, and previews
-> run formal retrieval/final-answer benchmarks only after the subset contract is accepted
```

Do not silently download large datasets. Do not treat subset preparation as
benchmark evaluation. Training data rebuilds, SFT, GRPO, and model-quality
claims still require explicit approval.

The Phase 5 MP-DocVQA and TAT-QA validation subsets are diagnostic/evaluation
artifacts only. Do not convert them into SFT/GRPO training records; future
training must use separate training-set data or an explicitly approved
training split.

## 2. MP-DocVQA

Current role:

- multi-page document QA;
- retrieval evaluation;
- retrieved-reader SFT;
- grounded GRPO;
- answer and location evaluation.

Authoritative sources:

```text
RRC imdb_val.npy:
  QA metadata
  official OCR tokens and boxes
  answer-page information

lmms-lab/MP-DocVQA val Parquet:
  selected page images when required
```

Current Phase 1 training/evaluation evidence is mainly based on official OCR.

Do not describe it as full MinerU-parsed MP-DocVQA.

Do not download the full RRC image archive unless explicitly approved.

Phase 5 final-delivery local subset preparation:

```text
prepare_script = scripts/prepare_final_eval_subset.py
diagnostic_runner = scripts/run_final_eval_subset.py
local_input_dir = data/benchmark/mp_docvqa/val
local_inputs = val-00001-of-00029.parquet, val-00002-of-00029.parquet
output_root = outputs/final_eval/mpdocvqa_val_subset
status = implemented
benchmark_status = not_started
```

The local smoke on 2026-06-29 restored 10 page-window documents and 55 QA
records from two validation parquet shards. This produces page-window PDFs,
`qa.jsonl`, `sample_manifest.jsonl`, `filter_report.json`,
`source_manifest.json`, and previews. It is suitable for raw PDF / OCR /
page-attribution preparation, but it is not yet a MinerU OCR acceptance run or
final answer-quality benchmark.

`scripts/run_final_eval_subset.py` currently treats MP-DocVQA as page-manifest
readiness only unless MinerU/OCR/retrieval artifacts are provided later. It
does not evaluate MP-DocVQA answer quality by itself.

## 3. Frozen Phase 1 artifacts

Representative artifacts:

```text
data/benchmark/mp_docvqa_train_sft_retrieved_clean.jsonl
data/benchmark/mp_docvqa_dev_sft_retrieved_clean.jsonl
data/benchmark/mp_docvqa_train_grpo_retrieved_clean.jsonl
```

During Phase 2:

- do not change document split;
- do not rebuild SFT/GRPO data;
- do not change gold answer/location fields;
- do not restart hard-subset mining or GRPO sweeps.

## 4. Real-document ScenarioSet

Phase 2B should use a small public smoke set:

```text
3-5 documents
3-5 manually checked questions per document
```

Cover:

1. text-heavy PDF;
2. scanned/image PDF;
3. PDF containing a standard table and figure.

The ScenarioSet is for functional validation, not training.

Store only safe metadata, hashes, expected evidence, and reports in Git.

## 5. Deferred datasets

### TAT-QA

Status: `implemented` for local subset preparation; benchmark evaluation is
`not_started`.

Current role:

- table + paragraph QA;
- calculator;
- numeric normalization;
- Numeric Accuracy;
- type-aware reward.

Phase 5 final-delivery local subset preparation:

```text
prepare_script = scripts/prepare_final_eval_subset.py
diagnostic_runner = scripts/run_final_eval_subset.py
local_input = data/benchmark/tatqa/tatqa_dataset_dev.json
output_root = outputs/final_eval/tatqa_dev_subset
status = implemented
benchmark_status = not_started
```

The local smoke on 2026-06-29 selected 80 validation questions balanced across
`table_arithmetic`, `table_lookup`, `table_text`, and `text` buckets. TAT-QA is
structured table/text QA data; it is not raw PDF and must not be described as
MinerU-parsed evidence. It is used to test table lookup, simple calculation,
and evidence-use behavior before final model training or evaluation.

The local diagnostic runner may execute deterministic table tools for TAT-QA
samples. These diagnostics can expose answer/citation gaps, but they are not a
formal TAT-QA benchmark and do not validate Qwen answer quality. The current
diagnostic artifact set is `results.jsonl`, `summary.json`, `summary.md`,
`preview.json`, and `manual_review.md`.

### InfographicVQA

Status: `deferred`

Future role:

- OCR + visual review;
- image-region evidence;
- OCR-only vs OCR+VLM comparison.

Do not add InfographicVQA until visual reasoning / VLM work is explicitly
started.

## 6. Split and leakage policy

All benchmark splits must remain document-level.

The same `doc_id` must not cross train/dev/test.

Inference and repair must never receive:

- gold answer;
- gold location;
- assistant target.

Distinguish:

```text
retrieval success
reader success conditioned on retrieved evidence
end-to-end success
```

## 7. Data-quality requirements

For any future dataset addition, record:

- source and version;
- field mapping;
- normalization;
- evidence/location mapping;
- document-level split;
- schema validation;
- answer coverage;
- accepted/deferred/dropped counts.

Do not describe schema/rule validation pass rate as manual quality approval.

## 8. Download policy

Default behavior:

```text
offline/local-only
```

Any large download requires explicit user confirmation.

Do not silently download:

- full image archives;
- complete dataset shards;
- model weights;
- signed temporary URLs.

# DocAgent Dataset Policy

> Dataset sources, accepted artifacts, split policy, and download rules only.

## 1. Current policy

During the active Phase 3A milestone:

```text
reuse accepted MP-DocVQA corpus-backed benchmark artifacts
→ validate BM25 vs Hybrid on a fixed subset
→ generate fixed Hybrid evidence for SFT vs GRPO
```

Do not rebuild training data, change splits, or add a new dataset.

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

Status: `deferred`

Future role:

- table + paragraph QA;
- calculator;
- numeric normalization;
- Numeric Accuracy;
- type-aware reward.

### InfographicVQA

Status: `deferred`

Future role:

- OCR + visual review;
- image-region evidence;
- OCR-only vs OCR+VLM comparison.

Do not add these datasets until Phase 2 real retrieval and real-document ingestion are accepted.

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

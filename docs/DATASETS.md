# DocAgent Dataset Notes

> This document records current dataset sources, authoritative fields, frozen Phase 1 artifacts, and deferred data work.  
> During the active Phase 2 retrieval milestone, do not rebuild or expand training datasets.

---

## 1. Current dataset policy

Current priority:

```text
reuse accepted MP-DocVQA Phase 1 artifacts
→ complete real hybrid retrieval
→ complete real MinerU/PDF loop
→ only then add table or visual datasets
```

Large datasets are downloaded manually on AutoDL. Scripts must not silently download full datasets or models.

Raw data stays outside the repository:

```text
/root/autodl-tmp/datasets/
```

Small processed JSONL files, indexes, and reports may remain under the project directory.

---

## 2. MP-DocVQA

### 2.1 Current role

MP-DocVQA is the accepted Phase 1 source for:

- multi-page document QA;
- page/evidence retrieval;
- retrieved-reader SFT;
- grounded GRPO;
- Answer EM/F1 and Location Accuracy evaluation.

### 2.2 Authoritative sources

Current preferred source combination:

```text
RRC imdb_val.npy:
  question/answer metadata
  official OCR tokens
  OCR boxes
  answer page information

lmms-lab/MP-DocVQA val Parquet:
  page images when a selected image subset is required
```

Do not download the RRC 22GB+ full image archive for the active milestone unless explicitly approved.

Do not scrape temporary Hugging Face Dataset Viewer image URLs. Use the dataset/Parquet interface if image extraction is required.

### 2.3 Current parser statement

Current Phase 1 training/evaluation data are based mainly on official OCR-derived evidence.

They are not full MinerU-parsed MP-DocVQA data.

Parser roles:

```text
official OCR: current MP-DocVQA training/eval source
MinerU: real uploaded PDF/image parsing
PaddleOCR: optional fallback/comparison only
```

### 2.4 Frozen Phase 1 artifacts

Representative accepted artifacts include:

```text
data/benchmark/mp_docvqa_train_sft_retrieved_clean.jsonl
data/benchmark/mp_docvqa_dev_sft_retrieved_clean.jsonl
data/benchmark/mp_docvqa_train_grpo_retrieved_clean.jsonl
```

Exact file existence must be checked in the repository/server before use.

During Phase 2:

- do not change document split;
- do not rebuild SFT/GRPO data;
- do not alter gold answer/location fields;
- do not mine new hard subsets;
- do not resume GRPO sweeps.

---

## 3. Phase 2 real-document smoke set

Phase 2 should use a small public ScenarioSet for real-document validation.

Initial target:

```text
3-5 public documents
```

Cover:

1. text-heavy PDF;
2. scanned/image PDF;
3. PDF containing a standard table and one or more figures.

Each document needs only 3-5 manually checked questions.

Store source documents outside Git when licensing or file size requires it. Store only manifests, hashes, expected page/block evidence, and reports in the repository.

Suggested metadata:

```json
{
  "doc_id": "...",
  "source_url_or_reference": "...",
  "license_note": "...",
  "sha256": "...",
  "question": "...",
  "expected_answer": "...",
  "expected_page": 3
}
```

The ScenarioSet is a functional smoke set, not a training dataset.

---

## 4. TAT-QA

Status:

```text
deferred until real hybrid retrieval and real PDF ingestion are accepted
```

Future role:

- table + paragraph QA;
- numeric normalization;
- calculator;
- Numeric Accuracy;
- type-aware answer reward.

Preferred source:

```text
official/local TAT-QA release
```

No TAT-QA expansion is part of the current Phase 2 milestone.

---

## 5. InfographicVQA and other visual datasets

Status:

```text
deferred
```

Potential later role:

- OCR + visual review;
- image-region evidence;
- OCR-only vs OCR+VLM ablation.

Do not add InfographicVQA, TAT-DQA, M3DocVQA, or another visual dataset until the active Phase 2 milestone is accepted and a reliable local source is confirmed.

---

## 6. Data split and leakage policy

All benchmark splits must remain document-level.

Do not allow the same `doc_id` to appear across train/dev/test.

Inference and repair must never receive:

- gold answer;
- gold location;
- assistant target.

Retrieved-reader evaluation must distinguish:

```text
retrieval success
reader success conditioned on retrieved evidence
end-to-end success
```

---

## 7. Data quality policy

For any future dataset addition, record:

- source and version;
- raw field mapping;
- answer normalization;
- evidence/location mapping;
- document-level split;
- schema validation;
- answer coverage;
- audit report;
- accepted/deferred/drop count.

`clean_rate = 1.0` should be described as schema/rule validation pass rate unless manually reviewed.

---

## 8. Download policy

Scripts must use explicit flags for network access, for example:

```text
--allow-download
```

Default behavior:

```text
offline/local-only
```

Any download of:

- large image archives;
- full dataset shards;
- model weights;
- signed URLs;

requires explicit user confirmation.

---

## 9. Current Phase 2 rule

The active milestone uses existing EvidenceBlock artifacts to verify real BGE-M3 and real reranker integration.

Therefore, no new dataset download or conversion is required before the Phase 2 preflight and real-model smoke.

# Phase 5E-A Document Summary Acceptance Pack

Updated: 2026-06-28  
Status: planned  
Owner role: Product Manager  
Target implementer: Codex

## 1. Context

Phase 5E Document Summary MVP has been locally implemented. The reported implementation adds a deterministic `document_summary` tool, routes summary requests to that tool, writes summary-related artifacts, and passes local Phase 5 tests.

The current PM status should remain:

```text
Phase 5E Document Summary MVP
Status: implemented
Acceptance state: local acceptance candidate
```

The next task is not a new product feature. It is an acceptance packaging task to make the Phase 5E implementation reproducible and reviewable.

## 2. Goal

Create a reproducible acceptance pack for Phase 5E Document Summary MVP.

The acceptance pack should prove that a non-dry-run summary request:

1. enters the `document_summary` tool;
2. does not return generic unsupported;
3. produces parseable JSON artifacts;
4. produces page/block citations grounded in loaded EvidenceBlock records;
5. does not call LLM answer generation, VLM, training, GRPO, table lookup, simple calculation, online MinerU OCR, or UI code.

## 3. In Scope

Implement or update a smoke runner for Phase 5E-A.

Expected new script:

```text
scripts/run_phase5e_document_summary_acceptance.py
```

The runner should execute at least one real non-dry-run summary case using local deterministic code.

Minimum supported smoke case:

```text
UTF-8 .txt file ingestion
-> summary question
-> Router
-> document_summary tool
-> result.json / summary.json / router_plan.json / trace.json
-> acceptance_report.json
```

Optional second smoke case if fixtures are already available locally:

```text
existing MinerU output ingestion
-> summary question
-> document_summary tool
-> same artifact checks
```

Do not require external datasets, model downloads, GPU, external APIs, or non-local services.

## 4. Out of Scope

Do not implement or modify:

- table lookup;
- simple calculation;
- VLM or visual pixel QA;
- LLM abstractive summary generation;
- AnswerPolicy prompt logic;
- SFT / GRPO / reward training;
- online MinerU OCR from raw PDF;
- FastAPI / Gradio / UI;
- final answer quality benchmark.

Do not report Phase 5E-A as final answer quality evaluation.

## 5. Files Likely to Change

Likely new file:

```text
scripts/run_phase5e_document_summary_acceptance.py
```

Likely updated docs:

```text
CURRENT_STATUS.md
docs/ACTIVE_PLAN.md
docs/PHASE5_ACTIVE_PLAN.md
```

Optional tests:

```text
tests/test_phase5e_document_summary_acceptance.py
```

Do not change large historical training scripts or model configs.

## 6. Implementation Requirements

### 6.1 Smoke Runner CLI

The smoke runner should support:

```bash
python scripts/run_phase5e_document_summary_acceptance.py \
  --output-dir outputs/phase5e_document_summary_acceptance
```

Optional arguments:

```bash
--db-path outputs/phase5e_document_summary_acceptance/docagent.db
--keep-existing-output
--include-mineru-existing-fixture
```

### 6.2 Fixture Document

The runner may create a temporary UTF-8 text document internally, for example:

```text
DocAgent Phase 5E acceptance document.
Page 1 introduces the system goal: grounded document question answering.
Page 2 describes EvidenceBlock storage, citations, router decisions, and trace artifacts.
Page 3 explains that summary output should be deterministic and extractive.
```

The content should be long enough to produce at least:

- one document-level answer;
- two or more key points;
- at least one page summary;
- at least one valid citation.

### 6.3 Required Execution Path

The runner must call the existing product CLI or the same CLI dispatch path used by users.

Preferred path:

```text
scripts/docagent_cli.py
```

The smoke should not bypass Router and call `summarize_document()` directly as the only validation path.

Tool-level validation can be added, but CLI-path validation is required.

### 6.4 Artifact Validation

For each smoke case, validate that the output directory contains:

```text
result.json
summary.json
router_plan.json
trace.json
```

The acceptance runner itself should additionally write:

```text
acceptance_report.json
```

All JSON files must be parseable.

### 6.5 Citation Validation

Validate that citations emitted by summary artifacts refer to loaded evidence.

Minimum validation:

- citation page exists in the document page set;
- citation block_id exists in loaded EvidenceBlock records when block_id is present;
- no citation page is greater than `documents.page_count` when page_count is available;
- no empty citation list for completed summary output unless the result is a structured error.

### 6.6 Router Validation

Validate that summary requests are not treated as unsupported.

Required checks:

- `router_plan.json` task type is `document_summary`, or equivalent schema field indicates document summary;
- `result.json` top-level status is success/completed according to existing CLI contract;
- summary-specific structured result status is `completed`;
- no generic unsupported result is returned for the summary case.

### 6.7 Boundary Flags

`acceptance_report.json` must include explicit boundary flags:

```json
{
  "used_llm_answer_generation": false,
  "used_vlm": false,
  "used_training": false,
  "used_grpo": false,
  "used_table_lookup": false,
  "used_simple_calculation": false,
  "used_online_mineru_ocr": false,
  "final_answer_quality_evaluated": false
}
```

These fields are acceptance metadata. They should not be inferred from marketing language.

## 7. Required Output Schema

`acceptance_report.json` should follow this structure as closely as possible:

```json
{
  "phase": "5E-A",
  "task": "document_summary_acceptance_pack",
  "status": "passed",
  "created_at": "<iso_timestamp>",
  "case_count": 1,
  "passed_count": 1,
  "failed_count": 0,
  "json_valid_count": 4,
  "artifact_write_count": 4,
  "citation_valid_count": 1,
  "unsupported_count": 0,
  "cases": [
    {
      "case_id": "txt_ingestion_summary",
      "status": "passed",
      "question": "总结这份文档的主要内容",
      "task_type": "document_summary",
      "result_json_valid": true,
      "summary_json_valid": true,
      "router_plan_json_valid": true,
      "trace_json_valid": true,
      "citations_valid": true,
      "artifact_paths": {
        "result": ".../result.json",
        "summary": ".../summary.json",
        "router_plan": ".../router_plan.json",
        "trace": ".../trace.json"
      },
      "warnings": []
    }
  ],
  "boundary": {
    "used_llm_answer_generation": false,
    "used_vlm": false,
    "used_training": false,
    "used_grpo": false,
    "used_table_lookup": false,
    "used_simple_calculation": false,
    "used_online_mineru_ocr": false,
    "final_answer_quality_evaluated": false
  }
}
```

If the existing CLI schema uses `success/error` top-level status, preserve it. Do not break existing CLI contract just to match this report schema.

## 8. Test Requirements

Add targeted tests if appropriate.

Minimum recommended test command:

```bash
pytest tests/test_phase5e_document_summary_tool.py tests/test_phase5e_document_summary_cli.py -q
```

Regression command:

```bash
pytest tests/test_phase5*.py -q
```

Acceptance runner command:

```bash
python scripts/run_phase5e_document_summary_acceptance.py \
  --output-dir outputs/phase5e_document_summary_acceptance
```

If a full `tests/test_phase5*.py` run is too slow in the local environment, report the reason and run the narrower Phase 5E and CLI regression tests instead.

## 9. Acceptance Criteria

| AC | Requirement |
|---|---|
| AC-1 | A Phase 5E-A acceptance runner exists and is runnable from the repo root. |
| AC-2 | At least one non-dry-run `.txt` ingestion + summary case passes. |
| AC-3 | The summary request routes to `document_summary`. |
| AC-4 | The summary request does not return generic unsupported. |
| AC-5 | `result.json`, `summary.json`, `router_plan.json`, and `trace.json` are written. |
| AC-6 | All required JSON artifacts are parseable. |
| AC-7 | Summary citations are validated against loaded EvidenceBlock records. |
| AC-8 | `acceptance_report.json` is written. |
| AC-9 | `acceptance_report.json` includes explicit boundary flags. |
| AC-10 | Docs are updated to mark Phase 5E as `implemented` and Phase 5E-A as acceptance evidence, not final answer quality benchmark. |
| AC-11 | No out-of-scope feature is implemented or modified. |

## 10. Stop Conditions

Stop after Phase 5E-A acceptance packaging.

Do not continue into:

- table lookup;
- simple calculation;
- VLM;
- AnswerPolicy prompt modification;
- SFT / GRPO;
- online OCR;
- UI;
- final answer quality benchmark.

## 11. Required Return Report

Codex must return the following Markdown report.

```markdown
# Codex Implementation Report: Phase 5E-A Document Summary Acceptance Pack

## 1. Conclusion

- Status: implemented / partially_implemented / blocked / failed
- One-sentence summary:

## 2. Changed Files

| File | Change Summary |
|---|---|
| `scripts/run_phase5e_document_summary_acceptance.py` | ... |
| `CURRENT_STATUS.md` | ... |
| `docs/ACTIVE_PLAN.md` | ... |
| `docs/PHASE5_ACTIVE_PLAN.md` | ... |

## 3. Implemented Behavior

- ...

## 4. Commands Run

| Command | Result |
|---|---|
| `python scripts/run_phase5e_document_summary_acceptance.py --output-dir outputs/phase5e_document_summary_acceptance` | passed / failed |
| `pytest tests/test_phase5e_document_summary_tool.py tests/test_phase5e_document_summary_cli.py -q` | passed / failed / not run |
| `pytest tests/test_phase5*.py -q` | passed / failed / not run |

## 5. Generated Artifacts

| Artifact | Path | JSON Valid |
|---|---|---|
| `result.json` | ... | yes/no |
| `summary.json` | ... | yes/no |
| `router_plan.json` | ... | yes/no |
| `trace.json` | ... | yes/no |
| `acceptance_report.json` | ... | yes/no |

## 6. Acceptance Criteria Mapping

| AC | Result | Evidence |
|---|---|---|
| AC-1 | pass/fail | ... |
| AC-2 | pass/fail | ... |
| AC-3 | pass/fail | ... |
| AC-4 | pass/fail | ... |
| AC-5 | pass/fail | ... |
| AC-6 | pass/fail | ... |
| AC-7 | pass/fail | ... |
| AC-8 | pass/fail | ... |
| AC-9 | pass/fail | ... |
| AC-10 | pass/fail | ... |
| AC-11 | pass/fail | ... |

## 7. Boundary Confirmation

- used LLM answer generation: yes/no
- used VLM: yes/no
- used training: yes/no
- used GRPO: yes/no
- used table lookup: yes/no
- used simple calculation: yes/no
- used online MinerU OCR: yes/no
- evaluated final answer quality: yes/no

## 8. Deviations from Spec

- None, or list deviations.

## 9. Known Risks / Limitations

- ...

## 10. Recommended Next Step

- ...
```

from __future__ import annotations

import json
from pathlib import Path

from scripts.audit_phase5i_case_quality import audit_phase5i_case_quality


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_phase5i_case_quality_flags_type_marker_keywords(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "date_case",
                "user_request": "Extract the date.",
                "request_form": "imperative",
                "expected_task_type": "local_fact_qa",
                "expected_answer_type": "extractive",
                "answerable": True,
                "unsupported_ok": False,
                "expected_page": 3,
                "expected_evidence_keywords": ["notice"],
                "expected_answer_keywords": ["date"],
                "forbidden_answer_keywords": [],
            }
        ],
    )
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _write_jsonl(
        run_dir / "predictions.jsonl",
        [
            {
                "case_id": "date_case",
                "pass_fail": "failed",
                "failure_reasons": ["answer_keyword_missing"],
                "citations": [{"page": 3}],
            }
        ],
    )

    summary = audit_phase5i_case_quality(
        cases_path=cases_path,
        run_dirs=[run_dir],
        output_dir=tmp_path / "out",
        run_id="audit_test",
    )

    assert summary["review_case_count"] == 1
    assert summary["flag_counts"]["answer_keywords_are_type_markers_not_answer_values"] == 1
    assert summary["flag_counts"]["all_observed_runs_fail_weak_answer_keyword_check"] == 1


def test_phase5i_case_quality_flags_repeated_non_expected_page(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "page_case",
                "user_request": "Find the financial year.",
                "request_form": "interrogative",
                "expected_task_type": "local_fact_qa",
                "expected_answer_type": "extractive",
                "answerable": True,
                "unsupported_ok": False,
                "expected_page": 24,
                "expected_evidence_keywords": ["dividend"],
                "expected_answer_keywords": ["2000-01"],
                "forbidden_answer_keywords": [],
            }
        ],
    )
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    run_a.mkdir()
    run_b.mkdir()
    row = {
        "case_id": "page_case",
        "pass_fail": "failed",
        "failure_reasons": ["citation_page_mismatch"],
        "citations": [{"page": 1}],
    }
    _write_jsonl(run_a / "predictions.jsonl", [row])
    _write_jsonl(run_b / "predictions.jsonl", [row])

    summary = audit_phase5i_case_quality(
        cases_path=cases_path,
        run_dirs=[run_a, run_b],
        output_dir=tmp_path / "out",
        run_id="audit_test",
    )
    rows = [json.loads(line) for line in (tmp_path / "out" / "rows.jsonl").read_text(encoding="utf-8").splitlines()]

    assert summary["flag_counts"]["all_observed_runs_cite_non_expected_page"] == 1
    assert rows[0]["observed_non_expected_page_counts"] == {"1": 2}

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
    assert summary["accepted_case_count"] == 0
    assert summary["flag_counts"]["answer_keywords_are_type_markers_not_answer_values"] == 1
    assert summary["flag_counts"]["all_observed_runs_fail_weak_answer_keyword_check"] == 1
    assert (tmp_path / "out" / "accepted_cases.jsonl").read_text(encoding="utf-8").strip() == ""
    review_case = json.loads((tmp_path / "out" / "review_cases.jsonl").read_text(encoding="utf-8").strip())
    assert review_case["case_quality_severity"] == "review"
    assert "case_quality_flags" in review_case


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


def test_phase5i_case_quality_writes_clean_accepted_cases(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "clean_case",
                "user_request": "How many pages does this document have?",
                "request_form": "interrogative",
                "expected_task_type": "document_statistics",
                "expected_answer_type": "numeric",
                "answerable": True,
                "unsupported_ok": False,
                "expected_page": None,
                "expected_evidence_keywords": [],
                "expected_answer_keywords": ["5"],
                "forbidden_answer_keywords": [],
            }
        ],
    )

    summary = audit_phase5i_case_quality(
        cases_path=cases_path,
        run_dirs=[],
        output_dir=tmp_path / "out",
        run_id="audit_test",
    )
    accepted = json.loads((tmp_path / "out" / "accepted_cases.jsonl").read_text(encoding="utf-8").strip())

    assert summary["accepted_case_count"] == 1
    assert summary["accepted_answer_quality_case_count"] == 0
    assert summary["review_case_count"] == 0
    assert accepted["case_id"] == "clean_case"
    assert "case_quality_flags" not in accepted
    assert (tmp_path / "out" / "accepted_answer_quality_cases.jsonl").read_text(encoding="utf-8").strip() == ""


def test_phase5i_case_quality_writes_answer_quality_ready_cases(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "clean_fact_case",
                "user_request": "Find the financial year related to unclaimed dividend.",
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

    summary = audit_phase5i_case_quality(
        cases_path=cases_path,
        run_dirs=[],
        output_dir=tmp_path / "out",
        run_id="audit_test",
    )
    answer_quality_case = json.loads(
        (tmp_path / "out" / "accepted_answer_quality_cases.jsonl").read_text(encoding="utf-8").strip()
    )

    assert summary["accepted_case_count"] == 1
    assert summary["accepted_answer_quality_case_count"] == 1
    assert answer_quality_case["case_id"] == "clean_fact_case"

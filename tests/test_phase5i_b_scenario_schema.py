from __future__ import annotations

import json
from pathlib import Path

import pytest

from docagent.eval.scenario_schema import ScenarioValidationError, read_scenario_jsonl, summarize_scenarios


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_PATH = ROOT / "data" / "scenario_sets" / "phase5i_b" / "phase5i_b_cases.jsonl"


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_phase5i_b_default_scenario_set_has_required_mix() -> None:
    cases = read_scenario_jsonl(SCENARIO_PATH)
    summary = summarize_scenarios(cases)

    assert summary["case_count"] >= 12
    assert summary["extractive_count"] >= 10
    assert summary["refusal_count"] >= 2
    assert summary["zh_question_count"] >= 2
    assert summary["en_question_count"] >= 2
    assert all(case.expected_task_type == "local_fact_qa" for case in cases)


def test_scenario_schema_rejects_missing_required_field(tmp_path: Path) -> None:
    path = tmp_path / "bad.jsonl"
    _write_jsonl(
        path,
        [
            {
                "case_id": "bad",
                "doc_key": "doc",
                "file": "doc.txt",
                "parser": "text",
                "expected_task_type": "local_fact_qa",
                "gold_answer": "x",
                "answer_type": "extractive",
                "eval_method": "normalized_exact_or_contains",
            }
        ],
    )

    with pytest.raises(ScenarioValidationError, match="question"):
        read_scenario_jsonl(path)


def test_scenario_schema_rejects_duplicate_case_id(tmp_path: Path) -> None:
    row = {
        "case_id": "dup",
        "doc_key": "doc",
        "file": "doc.txt",
        "parser": "text",
        "question": "What is named?",
        "expected_task_type": "local_fact_qa",
        "gold_answer": "x",
        "answer_type": "extractive",
        "eval_method": "normalized_exact_or_contains",
    }
    path = tmp_path / "dup.jsonl"
    _write_jsonl(path, [row, row])

    with pytest.raises(ScenarioValidationError, match="duplicate"):
        read_scenario_jsonl(path)

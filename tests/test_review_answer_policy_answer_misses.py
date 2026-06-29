from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.review_answer_policy_answer_misses import review_answer_policy_answer_misses


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_baseline(tmp_path: Path) -> Path:
    run_dir = tmp_path / "baseline" / "qwen_run"
    summary = {
        "status": "success",
        "run_id": "qwen_run",
        "used_qwen": True,
        "case_count": 8,
        "evaluated_count": 7,
        "pass_rate": 0.25,
        "answer_hit_rate": 0.25,
        "citation_block_hit_rate": 1.0,
    }
    rows = [
        {
            "sample_id": "metric",
            "dataset": "tatqa",
            "question": "How much was invested?",
            "answers": ["approximately USD500 million"],
            "prediction_answer": "USD500 million",
            "expected_tools": ["retrieval", "local_fact_qa"],
            "evaluation_mode": "answer_policy_generation",
            "pass_fail": "failed",
            "failure_reasons": ["answer_miss"],
            "tool_status": "not_run",
            "format_valid": True,
            "citation_block_hit": True,
        },
        {
            "sample_id": "calc",
            "dataset": "tatqa",
            "question": "What was the percentage change?",
            "answers": ["4.07"],
            "prediction_answer": "227.8",
            "expected_tools": ["table_lookup", "simple_calculation"],
            "evaluation_mode": "answer_policy_with_tool_results",
            "pass_fail": "failed",
            "failure_reasons": ["answer_miss"],
            "tool_status": "success",
            "format_valid": True,
            "citation_block_hit": True,
        },
        {
            "sample_id": "table",
            "dataset": "tatqa",
            "question": "What is the as reported value?",
            "answers": ["$708"],
            "prediction_answer": "$657",
            "expected_tools": ["table_lookup"],
            "evaluation_mode": "answer_policy_with_tool_results",
            "pass_fail": "failed",
            "failure_reasons": ["answer_miss"],
            "tool_status": "success",
            "format_valid": True,
            "citation_block_hit": True,
        },
        {
            "sample_id": "generation",
            "dataset": "tatqa",
            "question": "What does revenue comprise of?",
            "answers": ["customer support services"],
            "prediction_answer": "cloud licensing",
            "expected_tools": ["retrieval", "local_fact_qa"],
            "evaluation_mode": "answer_policy_generation",
            "pass_fail": "failed",
            "failure_reasons": ["answer_miss"],
            "tool_status": "not_run",
            "format_valid": True,
            "citation_block_hit": True,
        },
        {
            "sample_id": "repaired_parse",
            "dataset": "tatqa",
            "question": "What is the rationale?",
            "answers": ["liquefied natural gas and upstream markets"],
            "prediction_answer": "liquefied natural gas, upstream markets, and project approvals",
            "expected_tools": ["retrieval", "local_fact_qa"],
            "evaluation_mode": "answer_policy_generation",
            "pass_fail": "failed",
            "failure_reasons": ["answer_miss"],
            "tool_status": "not_run",
            "format_valid": True,
            "parse_result": {"raw_json_ok": True, "schema_ok": False},
            "citation_block_hit": True,
        },
        {
            "sample_id": "tool_error",
            "dataset": "tatqa",
            "question": "What changed?",
            "answers": ["5"],
            "prediction_answer": "",
            "expected_tools": ["table_lookup", "simple_calculation"],
            "evaluation_mode": "answer_policy_with_tool_results",
            "pass_fail": "failed",
            "failure_reasons": ["answer_miss"],
            "tool_status": "error",
            "format_valid": False,
            "citation_block_hit": False,
        },
        {
            "sample_id": "passed",
            "dataset": "tatqa",
            "pass_fail": "passed",
            "failure_reasons": [],
            "expected_tools": ["table_lookup"],
            "tool_status": "success",
        },
    ]
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "result.json", {"status": "success", "run_id": "qwen_run", "used_qwen": True, "metrics": summary})
    write_jsonl(run_dir / "results.jsonl", rows)
    return run_dir


def test_review_answer_misses_writes_buckets_and_artifacts(tmp_path: Path) -> None:
    run_dir = _write_baseline(tmp_path)

    result = review_answer_policy_answer_misses(
        run_dir=run_dir,
        output_root=tmp_path / "answer_miss_reviews",
        run_id="answer_miss_review",
    )

    assert result["status"] == "success"
    assert result["quality_status"] == "diagnostic_only"
    assert result["used_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["answer_miss_count"] == 6
    assert result["bucket_counts"] == {
        "answer_granularity_or_metric_review": 1,
        "calculation_reasoning_or_operand_review": 1,
        "model_extractive_precision_review": 1,
        "repaired_parse_plus_answer_miss": 1,
        "table_selection_or_column_review": 1,
        "tool_execution_review": 1,
    }
    assert result["evaluation_mode_counts"] == {
        "answer_policy_generation": 3,
        "answer_policy_with_tool_results": 3,
    }
    assert result["expected_tools_counts"] == {
        "retrieval+local_fact_qa": 3,
        "table_lookup": 1,
        "table_lookup+simple_calculation": 2,
    }
    assert result["tool_status_counts"] == {"error": 1, "not_run": 3, "success": 2}
    assert result["recommendation"]["next_action"] == "inspect_generic_tool_outputs_before_training"

    artifact_dir = tmp_path / "answer_miss_reviews" / "answer_miss_review"
    assert (artifact_dir / "result.json").is_file()
    assert (artifact_dir / "summary.json").is_file()
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "answer_miss_rows.jsonl").is_file()
    assert (artifact_dir / "preview.json").is_file()
    assert (artifact_dir / "manifest.json").is_file()
    reviewed_rows = read_jsonl(artifact_dir / "answer_miss_rows.jsonl")
    assert [row["sample_id"] for row in reviewed_rows] == [
        "metric",
        "calc",
        "table",
        "generation",
        "repaired_parse",
        "tool_error",
    ]
    assert reviewed_rows[0]["bucket"] == "answer_granularity_or_metric_review"
    assert reviewed_rows[4]["bucket"] == "repaired_parse_plus_answer_miss"


def test_review_answer_misses_returns_structured_missing_artifacts(tmp_path: Path) -> None:
    result = review_answer_policy_answer_misses(
        run_dir=tmp_path / "missing",
        output_root=tmp_path / "answer_miss_reviews",
        run_id="missing_review",
    )

    assert result["status"] == "failed"
    assert result["quality_status"] == "blocked"
    assert result["missing"]
    assert result["used_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert (tmp_path / "answer_miss_reviews" / "missing_review" / "result.json").is_file()

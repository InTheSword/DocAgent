from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.inspect_answer_policy_tool_outputs import inspect_answer_policy_tool_outputs


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _tool_result(
    *,
    answer: str,
    operation: str = "table_lookup",
    warnings: list[str] | None = None,
    error: dict | None = None,
) -> dict:
    return {
        "status": "success" if not error else "error",
        "tool": "table_lookup_or_calculation",
        "answer": answer,
        "citations": [{"block_id": "table_block", "text_preview": "table preview"}],
        "warnings": warnings or [],
        "error": error or {},
        "structured_result": {
            "status": "success",
            "operation": operation,
            "selected_table": {
                "doc_id": "doc",
                "page": 1,
                "block_id": "table_block",
                "block_type": "table",
                "header": ["Metric", "2019"],
                "row_count": 3,
            },
            "selected_value": {"value": answer, "column": "2019", "row_label": "Metric"},
            "calculation": {"operation": "difference", "expression": "10 - 8", "result_text": answer},
            "inputs": [{"label": "2019", "column": "2019"}, {"label": "2018", "column": "2018"}],
        },
    }


def _write_baseline(tmp_path: Path) -> Path:
    run_dir = tmp_path / "baseline" / "qwen_run"
    summary = {
        "status": "success",
        "run_id": "qwen_run",
        "used_qwen": True,
        "case_count": 8,
        "evaluated_count": 7,
        "answer_hit_rate": 0.25,
    }
    rows = [
        {
            "sample_id": "tool_good_model_miss",
            "dataset": "tatqa",
            "question": "What is the 2019 value?",
            "answers": ["10"],
            "prediction_answer": "8",
            "expected_answer_type": "numeric",
            "expected_tools": ["table_lookup"],
            "evaluation_mode": "answer_policy_with_tool_results",
            "failure_reasons": ["answer_miss"],
            "tool_status": "success",
            "tool_answer": "10",
            "tool_results_compact": [_tool_result(answer="10")],
            "citation_block_ids": ["table_block"],
        },
        {
            "sample_id": "table_wrong",
            "dataset": "tatqa",
            "question": "What is the as reported value?",
            "answers": ["$708"],
            "prediction_answer": "$657",
            "expected_answer_type": "numeric",
            "expected_tools": ["table_lookup"],
            "evaluation_mode": "answer_policy_with_tool_results",
            "failure_reasons": ["answer_miss"],
            "tool_status": "success",
            "tool_answer": "$657",
            "tool_results_compact": [_tool_result(answer="$657", warnings=["column_ambiguous"])],
            "citation_block_ids": ["table_block"],
        },
        {
            "sample_id": "calc_wrong",
            "dataset": "tatqa",
            "question": "What is the percentage change?",
            "answers": ["4.07"],
            "prediction_answer": "227.8",
            "expected_answer_type": "numeric",
            "expected_tools": ["table_lookup", "simple_calculation"],
            "evaluation_mode": "answer_policy_with_tool_results",
            "failure_reasons": ["answer_miss"],
            "tool_status": "success",
            "tool_answer": "227.8",
            "tool_results_compact": [_tool_result(answer="227.8", operation="simple_calculation")],
        },
        {
            "sample_id": "tool_error",
            "dataset": "tatqa",
            "question": "What changed?",
            "answers": ["5"],
            "prediction_answer": "",
            "expected_answer_type": "numeric",
            "expected_tools": ["table_lookup", "simple_calculation"],
            "evaluation_mode": "answer_policy_with_tool_results",
            "failure_reasons": ["answer_miss"],
            "tool_status": "error",
            "tool_error_type": "simple_calculation_unsupported",
            "tool_results_compact": [_tool_result(answer="", operation="simple_calculation", error={"type": "simple_calculation_unsupported"})],
        },
        {
            "sample_id": "missing_tool_result",
            "dataset": "tatqa",
            "question": "What was the total?",
            "answers": ["12"],
            "prediction_answer": "0",
            "expected_answer_type": "numeric",
            "expected_tools": ["table_lookup"],
            "evaluation_mode": "answer_policy_with_tool_results",
            "failure_reasons": ["answer_miss"],
            "tool_status": "success",
        },
        {
            "sample_id": "metric",
            "dataset": "tatqa",
            "question": "How much was invested?",
            "answers": ["approximately USD500 million"],
            "prediction_answer": "USD500 million",
            "expected_answer_type": "extractive",
            "expected_tools": ["table_lookup"],
            "evaluation_mode": "answer_policy_with_tool_results",
            "failure_reasons": ["answer_miss"],
            "tool_status": "success",
            "tool_answer": "USD500 million",
            "tool_results_compact": [_tool_result(answer="USD500 million")],
        },
        {
            "sample_id": "text_generation",
            "dataset": "tatqa",
            "question": "What does revenue comprise of?",
            "answers": ["customer support services"],
            "prediction_answer": "cloud licensing",
            "expected_answer_type": "extractive",
            "expected_tools": ["retrieval", "local_fact_qa"],
            "evaluation_mode": "answer_policy_generation",
            "failure_reasons": ["answer_miss"],
            "tool_status": "not_run",
        },
        {
            "sample_id": "passed",
            "dataset": "tatqa",
            "failure_reasons": [],
            "expected_tools": ["table_lookup"],
            "tool_status": "success",
        },
    ]
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "result.json", {"status": "success", "run_id": "qwen_run", "used_qwen": True, "metrics": summary})
    write_jsonl(run_dir / "results.jsonl", rows)
    return run_dir


def test_inspect_tool_outputs_writes_generic_diagnostic_artifacts(tmp_path: Path) -> None:
    run_dir = _write_baseline(tmp_path)

    result = inspect_answer_policy_tool_outputs(
        run_dir=run_dir,
        output_root=tmp_path / "tool_reviews",
        run_id="tool_review",
    )

    assert result["status"] == "success"
    assert result["quality_status"] == "diagnostic_only"
    assert result["used_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["answer_miss_count"] == 7
    assert result["tool_expected_answer_miss_count"] == 6
    assert result["non_tool_answer_miss_count"] == 1
    assert result["bucket_counts"] == {
        "generic_calculation_operand_or_operation_review": 1,
        "generic_table_selection_or_column_review": 1,
        "metric_or_answer_granularity_review": 1,
        "model_did_not_use_correct_tool_output": 1,
        "tool_execution_or_unsupported": 1,
        "tool_result_missing_or_empty": 1,
    }
    assert result["all_answer_miss_bucket_counts"]["non_table_tool_answer_miss_excluded"] == 1
    assert result["expected_tools_counts"] == {
        "table_lookup": 4,
        "table_lookup+simple_calculation": 2,
    }
    assert result["tool_status_counts"] == {"error": 1, "success": 5}
    assert result["tool_operation_counts"] == {"simple_calculation": 2, "table_lookup": 4}
    assert result["tool_warning_counts"] == {"column_ambiguous": 1}
    assert result["tool_error_type_counts"] == {"simple_calculation_unsupported": 1}
    assert result["tool_answer_gold_hit_hint_count"] == 2
    assert result["tool_answer_gold_miss_hint_count"] == 4
    assert result["model_did_not_use_correct_tool_output_count"] == 1
    assert result["generic_tool_output_review_count"] == 2
    assert result["recommendation"]["next_action"] == "fix_generic_tool_execution_or_contract_before_training"

    artifact_dir = tmp_path / "tool_reviews" / "tool_review"
    assert (artifact_dir / "result.json").is_file()
    assert (artifact_dir / "summary.json").is_file()
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "tool_output_rows.jsonl").is_file()
    assert (artifact_dir / "preview.json").is_file()
    assert (artifact_dir / "manifest.json").is_file()
    inspected_rows = read_jsonl(artifact_dir / "tool_output_rows.jsonl")
    assert [row["sample_id"] for row in inspected_rows] == [
        "tool_good_model_miss",
        "table_wrong",
        "calc_wrong",
        "tool_error",
        "missing_tool_result",
        "metric",
    ]
    assert inspected_rows[0]["bucket"] == "model_did_not_use_correct_tool_output"
    assert inspected_rows[0]["tool_hits_gold_hint"] is True
    assert inspected_rows[1]["selected_table"]["block_id"] == "table_block"
    assert inspected_rows[2]["calculation"]["expression"] == "10 - 8"
    assert inspected_rows[5]["bucket"] == "metric_or_answer_granularity_review"


def test_inspect_tool_outputs_returns_structured_missing_artifacts(tmp_path: Path) -> None:
    result = inspect_answer_policy_tool_outputs(
        run_dir=tmp_path / "missing",
        output_root=tmp_path / "tool_reviews",
        run_id="missing_tool_review",
    )

    assert result["status"] == "failed"
    assert result["quality_status"] == "blocked"
    assert result["missing"]
    assert result["used_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert result["validation_subset_used_for_training"] is False
    assert (tmp_path / "tool_reviews" / "missing_tool_review" / "result.json").is_file()

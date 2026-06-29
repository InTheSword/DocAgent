from __future__ import annotations

import json
from pathlib import Path

from scripts.review_answer_policy_baseline import review_answer_policy_baseline


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def test_review_qwen_baseline_recommends_sft_candidate(tmp_path: Path) -> None:
    run_dir = tmp_path / "baseline" / "qwen_run"
    summary = {
        "status": "success",
        "run_id": "qwen_run",
        "answer_policy_mode": "base",
        "used_qwen": True,
        "case_count": 4,
        "evaluated_count": 4,
        "passed_count": 1,
        "failed_count": 3,
        "skipped_count": 0,
        "pass_rate": 0.25,
        "tool_success_rate": 1.0,
        "format_valid_rate": 1.0,
        "location_valid_rate": 1.0,
        "answer_hit_rate": 0.25,
        "citation_block_hit_rate": 1.0,
        "failure_reason_distribution": {"answer_miss": 3},
        "failure_stage_distribution": {"answer_quality": 3},
    }
    rows = [
        {
            "sample_id": "q1",
            "dataset": "tatqa",
            "evaluation_mode": "answer_policy_generation",
            "pass_fail": "failed",
            "failure_stage": "answer_quality",
            "failure_reasons": ["answer_miss"],
            "answer_evaluated": True,
            "citation_evaluated": True,
            "citation_block_ids": ["b1"],
            "parse_result": {"raw_json_ok": True, "schema_ok": True},
            "final_answer_compact": {
                "answer": "wrong",
                "citation_block_ids": ["b1"],
                "citation_validation": {"invalid_block_ids": [], "allowlist_size": 1},
            },
            "answers": ["right"],
            "raw_model_output_preview": "{\"answer\":\"wrong\"}",
        },
        {
            "sample_id": "q2",
            "dataset": "tatqa",
            "evaluation_mode": "answer_policy_with_tool_results",
            "pass_fail": "passed",
            "failure_reasons": [],
            "answer_evaluated": True,
            "citation_evaluated": True,
            "citation_block_ids": ["b2"],
            "parse_result": {"raw_json_ok": True, "schema_ok": True},
            "final_answer_compact": {
                "answer": "10",
                "citation_block_ids": ["b2"],
                "citation_validation": {"invalid_block_ids": [], "allowlist_size": 1},
            },
            "answers": ["10"],
        },
    ]
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "result.json", {"status": "success", "run_id": "qwen_run", "used_qwen": True, "metrics": summary})
    _write_jsonl(run_dir / "results.jsonl", rows)

    review = review_answer_policy_baseline(run_dir=run_dir, output_root=tmp_path / "reviews", run_id="review_qwen")

    assert review["status"] == "success"
    assert review["sample_scope"] == "full_results"
    assert review["used_qwen"] is True
    assert review["training_gate"]["recommendation"] == "sft_data_design_candidate"
    assert review["training_gate"]["sft_gate"] == "candidate"
    assert review["training_gate"]["grpo_gate"] == "defer_until_sft_result"
    assert review["row_analysis"]["answer_miss_count_in_rows"] == 1
    assert (tmp_path / "reviews" / "review_qwen" / "review.json").is_file()
    assert "recommendation: `sft_data_design_candidate`" in (tmp_path / "reviews" / "review_qwen" / "review.md").read_text(encoding="utf-8")


def test_review_does_not_block_filtered_invalid_citations_when_final_citations_hit(tmp_path: Path) -> None:
    run_dir = tmp_path / "baseline" / "qwen_filtered_invalid"
    summary = {
        "status": "success",
        "run_id": "qwen_filtered_invalid",
        "answer_policy_mode": "base",
        "used_qwen": True,
        "case_count": 4,
        "evaluated_count": 4,
        "passed_count": 3,
        "failed_count": 1,
        "skipped_count": 0,
        "pass_rate": 0.75,
        "tool_success_rate": 1.0,
        "format_valid_rate": 1.0,
        "location_valid_rate": 1.0,
        "answer_hit_rate": 0.75,
        "citation_block_hit_rate": 1.0,
        "failure_reason_distribution": {"answer_miss": 1},
        "failure_stage_distribution": {"answer_quality": 1},
    }
    rows = [
        {
            "sample_id": "q1",
            "dataset": "tatqa",
            "evaluation_mode": "answer_policy_with_tool_results",
            "pass_fail": "passed",
            "failure_reasons": [],
            "answer_evaluated": True,
            "citation_evaluated": True,
            "citation_block_ids": ["table"],
            "parse_result": {"raw_json_ok": True, "schema_ok": True},
            "final_answer_compact": {
                "answer": "10",
                "citation_block_ids": ["table"],
                "citation_validation": {
                    "requested_block_ids": ["not_in_allowlist"],
                    "valid_block_ids": ["table"],
                    "invalid_block_ids": ["not_in_allowlist"],
                    "preferred_block_ids": ["table"],
                    "added_preferred_block_ids": ["table"],
                    "allowlist_size": 2,
                },
            },
            "answers": ["10"],
        },
        {
            "sample_id": "q2",
            "dataset": "tatqa",
            "evaluation_mode": "answer_policy_generation",
            "pass_fail": "failed",
            "failure_stage": "answer_quality",
            "failure_reasons": ["answer_miss"],
            "answer_evaluated": True,
            "citation_evaluated": True,
            "citation_block_ids": ["b1"],
            "parse_result": {"raw_json_ok": True, "schema_ok": True},
            "final_answer_compact": {
                "answer": "wrong",
                "citation_block_ids": ["b1"],
                "citation_validation": {"invalid_block_ids": [], "allowlist_size": 1},
            },
            "answers": ["right"],
        },
    ]
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "result.json", {"status": "success", "run_id": "qwen_filtered_invalid", "used_qwen": True, "metrics": summary})
    _write_jsonl(run_dir / "results.jsonl", rows)

    review = review_answer_policy_baseline(run_dir=run_dir, output_root=tmp_path / "reviews", run_id="review_filtered_invalid")

    assert review["row_analysis"]["invalid_citation_id_count_in_rows"] == 1
    assert review["training_gate"]["recommendation"] == "continue_qwen_eval_before_training"
    assert review["training_gate"]["sft_gate"] == "defer"
    assert "invalid_model_selected_citation_ids_filtered_by_allowlist" in review["training_gate"]["reasons"]


def test_review_blocks_invalid_citations_when_final_citation_misses(tmp_path: Path) -> None:
    run_dir = tmp_path / "baseline" / "qwen_invalid_miss"
    summary = {
        "status": "success",
        "run_id": "qwen_invalid_miss",
        "answer_policy_mode": "base",
        "used_qwen": True,
        "case_count": 4,
        "evaluated_count": 4,
        "passed_count": 3,
        "failed_count": 1,
        "skipped_count": 0,
        "pass_rate": 0.75,
        "tool_success_rate": 1.0,
        "format_valid_rate": 1.0,
        "location_valid_rate": 1.0,
        "answer_hit_rate": 1.0,
        "citation_block_hit_rate": 0.80,
        "failure_reason_distribution": {"citation_block_miss": 1},
        "failure_stage_distribution": {"attribution": 1},
    }
    rows = [
        {
            "sample_id": "q1",
            "dataset": "tatqa",
            "evaluation_mode": "answer_policy_generation",
            "pass_fail": "failed",
            "failure_stage": "attribution",
            "failure_reasons": ["citation_block_miss"],
            "answer_evaluated": True,
            "citation_evaluated": True,
            "citation_block_ids": ["wrong"],
            "parse_result": {"raw_json_ok": True, "schema_ok": True},
            "final_answer_compact": {
                "answer": "10",
                "citation_block_ids": ["wrong"],
                "citation_validation": {
                    "requested_block_ids": ["missing", "wrong"],
                    "valid_block_ids": ["wrong"],
                    "invalid_block_ids": ["missing"],
                    "allowlist_size": 1,
                },
            },
            "answers": ["10"],
        }
    ]
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "result.json", {"status": "success", "run_id": "qwen_invalid_miss", "used_qwen": True, "metrics": summary})
    _write_jsonl(run_dir / "results.jsonl", rows)

    review = review_answer_policy_baseline(run_dir=run_dir, output_root=tmp_path / "reviews", run_id="review_invalid_miss")

    assert review["training_gate"]["recommendation"] == "citation_contract_repair_before_training"
    assert review["training_gate"]["next_action"] == "fix_citation_allowlist_use_before_sft"


def test_review_sync_bundle_without_qwen_defers_training(tmp_path: Path) -> None:
    run_dir = tmp_path / "sync" / "heuristic_run"
    summary = {
        "status": "success",
        "run_id": "heuristic_run",
        "answer_policy_mode": "heuristic",
        "used_qwen": False,
        "evaluated_count": 2,
        "pass_rate": 0.0,
        "format_valid_rate": 1.0,
        "answer_hit_rate": 0.0,
        "citation_block_hit_rate": 0.5,
    }
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "result.json", {"status": "success", "run_id": "heuristic_run", "used_qwen": False, "metrics": summary})
    _write_jsonl(
        run_dir / "failures_sample.jsonl",
        [
            {
                "sample_id": "q1",
                "dataset": "tatqa",
                "pass_fail": "failed",
                "failure_stage": "answer_quality",
                "failure_reasons": ["answer_miss"],
            }
        ],
    )

    review = review_answer_policy_baseline(run_dir=run_dir, output_root=tmp_path / "reviews")

    assert review["sample_scope"] == "failure_sample_only"
    assert review["training_gate"]["recommendation"] == "needs_real_qwen_baseline"
    assert review["training_gate"]["sft_gate"] == "not_started"
    assert review["artifact_paths"][0].endswith("review.json")


def test_review_missing_artifacts_returns_structured_failure(tmp_path: Path) -> None:
    review = review_answer_policy_baseline(
        run_dir=tmp_path / "missing_baseline",
        output_root=tmp_path / "reviews",
        run_id="review_missing",
    )

    assert review["status"] == "failed"
    assert review["quality_status"] == "blocked"
    assert review["sample_scope"] == "missing"
    assert review["training_gate"]["recommendation"] == "blocked_missing_baseline_artifacts"
    assert review["error"]["type"] == "missing_baseline_artifacts"
    assert (tmp_path / "reviews" / "review_missing" / "review.json").is_file()

from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.review_answer_policy_sft_candidates import review_answer_policy_sft_candidates


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _candidate_record(
    sample_id: str,
    *,
    expected_tools: list[str] | None = None,
    tool_results_attached: int = 0,
    answer: str = "10",
    citation_block_ids: list[str] | None = None,
) -> dict:
    target = {
        "answer": answer,
        "reasoning_summary": "The cited evidence gives the answer.",
        "citation_block_ids": citation_block_ids if citation_block_ids is not None else ["b1"],
        "evidence_used": [{"block_id": "b1", "text_preview": "2019 | 10"}],
    }
    return {
        "id": f"baseline__{sample_id}",
        "source": "answer_policy_baseline_sft_candidate",
        "prompt_version": "docagent_answer_v2_candidate_citations",
        "messages": [
            {"role": "system", "content": "answer from evidence"},
            {"role": "user", "content": "Question: what is the value?\nEvidence: 2019 | 10"},
            {"role": "assistant", "content": json.dumps(target, ensure_ascii=False)},
        ],
        "metadata": {
            "source_sample_id": sample_id,
            "doc_id": "doc1",
            "dataset": "tatqa",
            "evaluation_mode": "answer_policy_with_tool_results",
            "failure_reasons": ["answer_miss"],
            "prediction_answer": "8",
            "expected_tools": expected_tools or ["table_lookup"],
            "gold_block_ids": ["b1"],
            "tool_results_attached": tool_results_attached,
            "selected_block_ids": ["b1"],
            "dropped_block_ids": [],
        },
    }


def _write_baseline(tmp_path: Path) -> Path:
    run_dir = tmp_path / "baseline" / "qwen_run"
    summary = {
        "status": "success",
        "run_id": "qwen_run",
        "used_qwen": True,
        "case_count": 5,
        "evaluated_count": 4,
        "pass_rate": 0.5,
        "answer_hit_rate": 0.5,
        "citation_block_hit_rate": 1.0,
        "format_valid_rate": 1.0,
        "failure_reason_distribution": {"answer_miss": 3},
    }
    rows = [
        {
            "sample_id": "q_table",
            "dataset": "tatqa",
            "question": "What is the 2019 value?",
            "answers": ["10"],
            "prediction_answer": "8",
            "expected_answer_type": "numeric",
            "expected_tools": ["table_lookup"],
            "evaluation_mode": "answer_policy_with_tool_results",
            "pass_fail": "failed",
            "failure_reasons": ["answer_miss"],
            "tool_status": "success",
            "tool_answer": "8",
            "citation_block_ids": ["b1"],
            "tool_citation_block_ids": ["b1"],
            "final_answer_compact": {"citation_validation": {"invalid_block_ids": []}},
        },
        {
            "sample_id": "q_text",
            "dataset": "tatqa",
            "question": "What is the policy?",
            "answers": ["policy"],
            "prediction_answer": "the policy",
            "expected_answer_type": "extractive",
            "expected_tools": ["retrieval", "local_fact_qa"],
            "evaluation_mode": "answer_policy_generation",
            "pass_fail": "failed",
            "failure_reasons": ["answer_miss"],
            "tool_status": "not_run",
            "citation_block_ids": ["b2"],
        },
        {
            "sample_id": "q_tool_error",
            "dataset": "tatqa",
            "question": "What changed?",
            "answers": ["5"],
            "prediction_answer": "",
            "expected_answer_type": "numeric",
            "expected_tools": ["table_lookup", "simple_calculation"],
            "evaluation_mode": "answer_policy_with_tool_results",
            "pass_fail": "failed",
            "failure_reasons": ["answer_miss"],
            "tool_status": "error",
        },
        {
            "sample_id": "q_pass",
            "dataset": "tatqa",
            "pass_fail": "passed",
            "failure_reasons": [],
            "expected_tools": ["table_lookup"],
            "tool_status": "success",
        },
        {"sample_id": "mp_q", "dataset": "mp_docvqa", "pass_fail": "skipped"},
    ]
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "result.json", {"status": "success", "run_id": "qwen_run", "used_qwen": True, "metrics": summary})
    write_jsonl(run_dir / "results.jsonl", rows)
    return run_dir


def _write_candidates(tmp_path: Path, records: list[dict]) -> Path:
    run_dir = tmp_path / "candidates" / "candidate_run"
    summary = {
        "status": "success",
        "run_id": "candidate_run",
        "record_count": len(records),
        "skip_reason_distribution": {"tool_execution_failed": 1},
        "candidate_failure_reason_distribution": {"answer_miss": len(records)},
        "records_path": "sft_candidates.jsonl",
    }
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "result.json", {"status": "success", "run_id": "candidate_run", "record_count": len(records)})
    write_jsonl(run_dir / "sft_candidates.jsonl", records)
    return run_dir


def test_review_sft_candidates_writes_alignment_and_preview_artifacts(tmp_path: Path) -> None:
    baseline_dir = _write_baseline(tmp_path)
    candidate_dir = _write_candidates(
        tmp_path,
        [
            _candidate_record("q_table", expected_tools=["table_lookup"], tool_results_attached=1),
            _candidate_record(
                "q_text",
                expected_tools=["retrieval", "local_fact_qa"],
                tool_results_attached=0,
                answer="policy",
                citation_block_ids=["b2"],
            ),
        ],
    )

    result = review_answer_policy_sft_candidates(
        baseline_run_dir=baseline_dir,
        candidate_run_dir=candidate_dir,
        output_root=tmp_path / "reviews",
        run_id="review_run",
    )

    assert result["status"] == "success"
    assert result["quality_status"] == "diagnostic_only"
    assert result["used_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert result["candidate_alignment"]["candidate_record_count"] == 2
    assert result["candidate_alignment"]["failed_without_candidate"] == ["q_tool_error"]
    assert result["candidate_alignment"]["candidate_without_failed"] == []
    assert result["failure_analysis"]["failure_by_expected_tools"] == {
        "retrieval+local_fact_qa": 1,
        "table_lookup": 1,
        "table_lookup+simple_calculation": 1,
    }
    assert result["candidate_quality_flags"]["failed_without_candidate_count"] == 1
    assert result["candidate_quality_flags"]["tool_expected_without_tool_results_count"] == 0
    assert result["manual_review_summary"]["bucket_counts"] == {
        "generation_answer_miss_review": 1,
        "table_lookup_answer_miss_with_tool": 1,
        "tool_failure_without_candidate": 1,
    }
    assert result["manual_review_summary"]["tool_answer_miss_with_candidate_count"] == 1
    assert result["manual_review_summary"]["tool_answer_miss_with_candidate_sample_ids"] == ["q_table"]
    assert result["manual_review_summary"]["metric_normalization_candidate_count"] == 1
    assert result["manual_review_summary"]["metric_normalization_candidate_sample_ids"] == ["q_text"]
    assert result["manual_review_summary"]["tool_failure_without_candidate_count"] == 1
    assert result["recommendation"]["next_action"] == "inspect_tool_and_metric_failures_before_sft"
    review_dir = tmp_path / "reviews" / "review_run"
    assert (review_dir / "result.json").is_file()
    assert (review_dir / "summary.json").is_file()
    assert (review_dir / "summary.md").is_file()
    assert (review_dir / "failure_preview.json").is_file()
    assert (review_dir / "candidate_preview.json").is_file()
    assert (review_dir / "manual_review.jsonl").is_file()
    assert (review_dir / "manifest.json").is_file()
    manual_rows = read_jsonl(review_dir / "manual_review.jsonl")
    assert [row["sample_id"] for row in manual_rows] == ["q_table", "q_text", "q_tool_error"]
    assert manual_rows[0]["review_bucket"] == "table_lookup_answer_miss_with_tool"
    assert manual_rows[0]["candidate_target_answer"] == "10"
    assert manual_rows[0]["tool_hits_gold_hint"] is False
    assert manual_rows[0]["candidate_hits_gold_hint"] is True
    assert manual_rows[1]["review_bucket"] == "generation_answer_miss_review"
    assert manual_rows[1]["prediction_hits_gold_hint"] is True
    assert manual_rows[2]["review_bucket"] == "tool_failure_without_candidate"
    assert manual_rows[2]["candidate_record_available"] is False


def test_review_sft_candidates_blocks_missing_artifacts(tmp_path: Path) -> None:
    result = review_answer_policy_sft_candidates(
        baseline_run_dir=tmp_path / "missing_baseline",
        candidate_run_dir=tmp_path / "missing_candidates",
        output_root=tmp_path / "reviews",
        run_id="blocked",
    )

    assert result["status"] == "failed"
    assert result["quality_status"] == "blocked"
    assert result["missing"]
    assert (tmp_path / "reviews" / "blocked" / "result.json").is_file()


def test_review_sft_candidates_flags_malformed_candidate_targets(tmp_path: Path) -> None:
    baseline_dir = _write_baseline(tmp_path)
    candidate_dir = _write_candidates(
        tmp_path,
        [
            _candidate_record(
                "q_table",
                expected_tools=["table_lookup"],
                tool_results_attached=0,
                answer="",
                citation_block_ids=[],
            )
        ],
    )

    result = review_answer_policy_sft_candidates(
        baseline_run_dir=baseline_dir,
        candidate_run_dir=candidate_dir,
        output_root=tmp_path / "reviews",
        run_id="malformed",
    )

    flags = result["candidate_quality_flags"]
    assert flags["candidate_missing_answer_count"] == 1
    assert flags["candidate_missing_citation_count"] == 1
    assert flags["tool_expected_without_tool_results_count"] == 1
    assert result["recommendation"]["next_action"] == "repair_sft_candidate_records_before_training"

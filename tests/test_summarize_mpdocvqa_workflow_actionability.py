from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.summarize_mpdocvqa_workflow_actionability import summarize_mpdocvqa_workflow_actionability


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def compare_row(sample_id: str, bucket: str) -> dict:
    return {
        "sample_id": sample_id,
        "doc_id": "window_doc",
        "source_document": "source_doc",
        "bucket": bucket,
        "question": f"Question {sample_id}?",
        "answers": ["alpha"],
        "gold_pages": [2],
        "retrieved_pages": [1],
        "selected_pages": [1],
        "citation_pages": [1],
    }


def review_row(sample_id: str, actionability_bucket: str) -> dict:
    return {
        "sample_id": sample_id,
        "actionability_bucket": actionability_bucket,
        "review_bucket": "manual_compare_gold_and_adjacent_page_images",
        "page_index_bucket": "answer_on_gold_minus_one_page",
        "answer_hit_pages": [1],
        "workflow_answer_page_hits": {
            "retrieved_answer_page_hit": actionability_bucket != "retrieval_or_duplicate_answer_review",
            "selected_answer_page_hit": actionability_bucket != "retrieval_or_duplicate_answer_review",
            "citation_answer_page_hit": actionability_bucket != "retrieval_or_duplicate_answer_review",
        },
    }


def test_summarize_mpdocvqa_workflow_actionability_overlays_manual_review(tmp_path: Path) -> None:
    compare_dir = tmp_path / "compare"
    manual_dir = tmp_path / "manual"
    write_json(
        compare_dir / "summary.json",
        {
            "run_id": "compare_source",
            "status": "success",
            "used_qwen": True,
            "bucket_counts": {
                "answer_generation_or_metric_miss": 1,
                "passed": 1,
                "retrieval_gold_page_miss": 3,
                "task_type_not_local_fact_qa": 1,
            },
        },
    )
    write_jsonl(
        compare_dir / "rows.jsonl",
        [
            compare_row("passed", "passed"),
            compare_row("answer_miss", "answer_generation_or_metric_miss"),
            compare_row("alignment", "retrieval_gold_page_miss"),
            compare_row("ocr_alias", "retrieval_gold_page_miss"),
            compare_row("retrieval", "retrieval_gold_page_miss"),
            compare_row("router", "task_type_not_local_fact_qa"),
        ],
    )
    write_json(
        manual_dir / "summary.json",
        {
            "run_id": "manual_source",
            "status": "success",
            "actionability_bucket_counts": {
                "gold_page_alignment_review_not_retrieval_defect": 1,
                "ocr_or_answer_alias_review": 1,
                "retrieval_or_duplicate_answer_review": 1,
            },
        },
    )
    write_jsonl(
        manual_dir / "manual_review.jsonl",
        [
            review_row("alignment", "gold_page_alignment_review_not_retrieval_defect"),
            review_row("ocr_alias", "ocr_or_answer_alias_review"),
            review_row("retrieval", "retrieval_or_duplicate_answer_review"),
        ],
    )

    result = summarize_mpdocvqa_workflow_actionability(
        compare_run_dir=compare_dir,
        manual_review_dir=manual_dir,
        output_root=tmp_path / "out",
        run_id="actionability",
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["quality_status"] == "diagnostic_only"
    assert result["used_training"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["evaluated_count"] == 6
    assert result["reviewed_retrieval_miss_count"] == 3
    assert result["original_bucket_counts"] == {
        "answer_generation_or_metric_miss": 1,
        "passed": 1,
        "retrieval_gold_page_miss": 3,
        "task_type_not_local_fact_qa": 1,
    }
    assert result["adjusted_bucket_counts"] == {
        "answer_generation_or_metric_miss": 1,
        "gold_page_alignment_review_not_retrieval_defect": 1,
        "ocr_or_answer_alias_review": 1,
        "passed": 1,
        "retrieval_or_duplicate_answer_review": 1,
        "task_type_not_local_fact_qa": 1,
    }
    assert result["manual_actionability_bucket_counts"] == {
        "gold_page_alignment_review_not_retrieval_defect": 1,
        "ocr_or_answer_alias_review": 1,
        "retrieval_or_duplicate_answer_review": 1,
    }
    assert result["actionable_retrieval_issue_count"] == 1
    assert result["recommendation"]["next_action"] == "inspect_ocr_alias_and_remaining_retrieval_rows_before_more_eval"
    assert (tmp_path / "sync" / "actionability" / "summary.json").is_file()

    rows = read_jsonl(tmp_path / "out" / "actionability" / "rows.jsonl")
    assert [row["adjusted_bucket"] for row in rows] == [
        "passed",
        "answer_generation_or_metric_miss",
        "gold_page_alignment_review_not_retrieval_defect",
        "ocr_or_answer_alias_review",
        "retrieval_or_duplicate_answer_review",
        "task_type_not_local_fact_qa",
    ]
    assert rows[2]["workflow_answer_page_hits"]["citation_answer_page_hit"] is True

from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.compare_mpdocvqa_full_workflow_runs import compare_mpdocvqa_full_workflow_runs


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def row(sample_id: str, bucket: str, *, task_type: str = "local_fact_qa") -> dict:
    hit = bucket == "passed"
    retrieved_hit = bucket in {"passed", "answer_generation_or_metric_miss", "citation_selection_page_miss"}
    citation_hit = bucket in {"passed", "answer_generation_or_metric_miss"}
    return {
        "sample_id": sample_id,
        "doc_id": "source_doc",
        "ingested_doc_id": "ingested_doc",
        "source_document": "source",
        "bucket": bucket,
        "pass_fail": "passed" if bucket == "passed" else "failed",
        "question": f"Question {sample_id}?",
        "answers": ["alpha"],
        "gold_pages": [2],
        "task_type": task_type,
        "answer_hit": hit,
        "retrieved_gold_page_hit": retrieved_hit,
        "selected_gold_page_hit": retrieved_hit,
        "citation_page_hit": citation_hit,
        "retrieved_gold_page_rank": 1 if retrieved_hit else None,
        "retrieved_pages": [2] if retrieved_hit else [1],
        "selected_pages": [2] if retrieved_hit else [1],
        "citation_pages": [2] if citation_hit else [1],
        "retrieval_candidate_count": 3,
        "citation_count": 1,
        "full_model_path": task_type == "local_fact_qa",
        "used_llm_router": task_type == "local_fact_qa",
        "used_llm_query_rewriter": task_type == "local_fact_qa",
        "used_qwen_answer_policy": task_type == "local_fact_qa",
        "used_dense_retrieval": task_type == "local_fact_qa",
        "used_reranker": task_type == "local_fact_qa",
        "retriever_mode": "hybrid_rerank",
    }


def write_run(run_dir: Path, run_id: str, rows: list[dict]) -> None:
    bucket_counts: dict[str, int] = {}
    for item in rows:
        bucket_counts[item["bucket"]] = bucket_counts.get(item["bucket"], 0) + 1
    qwen_count = sum(1 for item in rows if item.get("used_qwen_answer_policy"))
    write_json(
        run_dir / "summary.json",
        {
            "run_id": run_id,
            "status": "success",
            "cli_success_count": len(rows),
            "cli_success_rate": 1.0,
            "used_qwen_answer_policy_count": qwen_count,
            "used_dense_retrieval_count": qwen_count,
            "used_reranker_count": qwen_count,
            "bucket_counts": bucket_counts,
        },
    )
    write_json(run_dir / "result.json", {"run_id": run_id, "status": "success"})
    write_jsonl(run_dir / "results.jsonl", rows)


def test_compare_mpdocvqa_full_workflow_runs_aggregates_chunks(tmp_path: Path) -> None:
    run_a = tmp_path / "run_a"
    run_b = tmp_path / "run_b"
    write_run(
        run_a,
        "chunk_a",
        [
            row("a1", "passed"),
            row("a2", "answer_generation_or_metric_miss"),
        ],
    )
    write_run(
        run_b,
        "chunk_b",
        [
            row("b1", "retrieval_gold_page_miss"),
            row("b2", "retrieval_gold_page_miss"),
            row("b3", "task_type_not_local_fact_qa", task_type="document_statistics"),
        ],
    )

    result = compare_mpdocvqa_full_workflow_runs(
        run_dirs=[run_a, run_b],
        output_root=tmp_path / "compare",
        run_id="compare_runs",
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["quality_status"] == "diagnostic_only"
    assert result["source_run_count"] == 2
    assert result["evaluated_count"] == 5
    assert result["unique_sample_count"] == 5
    assert result["used_training"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["cli_success_rate"] == 1.0
    assert result["retrieved_gold_page_hit_rate"] == 0.4
    assert result["citation_page_hit_rate"] == 0.4
    assert result["answer_hit_rate"] == 0.2
    assert result["bucket_counts"] == {
        "answer_generation_or_metric_miss": 1,
        "passed": 1,
        "retrieval_gold_page_miss": 2,
        "task_type_not_local_fact_qa": 1,
    }
    assert result["recommendation"]["next_action"] == "inspect_retrieval_query_or_block_granularity_before_training"
    assert (tmp_path / "sync" / "compare_runs" / "summary.json").is_file()

    rows = read_jsonl(tmp_path / "compare" / "compare_runs" / "rows.jsonl")
    assert [item["source_run_id"] for item in rows] == ["chunk_a", "chunk_a", "chunk_b", "chunk_b", "chunk_b"]
    assert rows[-1]["task_type"] == "document_statistics"

from __future__ import annotations

import json
from pathlib import Path

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.inspect_mpdocvqa_query_block_granularity import inspect_mpdocvqa_query_block_granularity


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def block(page: int, suffix: str, text: str, *, block_type: str = "text") -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="mp_doc",
        block_id=f"p{page}_{suffix}",
        block_type=block_type,
        text=text,
        page_id=page,
        location=EvidenceLocation(page=page, block_id=f"p{page}_{suffix}"),
    )


def write_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "docagent.db"
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        blocks = [block(page, "page", f"page {page}", block_type="page") for page in range(1, 5)]
        blocks.extend(
            [
                block(1, "text", "Budget Estimate unrelated retrieved page"),
                block(2, "text", "Budget Estimate for Pharmaceutical Compendia Surveillance is $100,000."),
                block(3, "text", "The final approved allocation is AlphaValue."),
                block(4, "text", "Budget Estimate for Other Work is pending."),
            ]
        )
        repository.save_evidence_blocks(blocks)
    finally:
        conn.close()
    return db_path


def write_compare_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "compare"
    write_json(run_dir / "summary.json", {"run_id": "compare_run", "status": "success", "used_qwen": True})
    write_json(run_dir / "result.json", {"run_id": "compare_run", "status": "success"})
    write_jsonl(
        run_dir / "rows.jsonl",
        [
            {
                "source_run_id": "chunk_a",
                "sample_id": "ranker_miss",
                "doc_id": "source",
                "ingested_doc_id": "mp_doc",
                "bucket": "retrieval_gold_page_miss",
                "question": "What is the Budget Estimate for Pharmaceutical Compendia Surveillance?",
                "answers": ["$100,000"],
                "task_type": "local_fact_qa",
                "gold_pages": [2],
                "retrieved_pages": [1],
                "selected_pages": [1],
                "citation_pages": [1],
            },
            {
                "source_run_id": "chunk_a",
                "sample_id": "bridge_miss",
                "doc_id": "source",
                "ingested_doc_id": "mp_doc",
                "bucket": "retrieval_gold_page_miss",
                "question": "What is the program amount?",
                "answers": ["AlphaValue"],
                "task_type": "local_fact_qa",
                "gold_pages": [3],
                "retrieved_pages": [1],
                "selected_pages": [1],
                "citation_pages": [1],
            },
            {
                "source_run_id": "chunk_a",
                "sample_id": "gold_answer_absent",
                "doc_id": "source",
                "ingested_doc_id": "mp_doc",
                "bucket": "retrieval_gold_page_miss",
                "question": "What is the Budget Estimate for Other Work?",
                "answers": ["$500"],
                "task_type": "local_fact_qa",
                "gold_pages": [4],
                "retrieved_pages": [1],
                "selected_pages": [1],
                "citation_pages": [1],
            },
            {
                "source_run_id": "chunk_a",
                "sample_id": "passed",
                "doc_id": "source",
                "ingested_doc_id": "mp_doc",
                "bucket": "passed",
                "question": "What is the Budget Estimate?",
                "answers": ["$100,000"],
                "task_type": "local_fact_qa",
                "gold_pages": [2],
                "retrieved_pages": [2],
                "selected_pages": [2],
                "citation_pages": [2],
                "answer_hit": True,
            },
        ],
    )
    return run_dir


def test_inspect_mpdocvqa_query_block_granularity_buckets(tmp_path: Path) -> None:
    db_path = write_db(tmp_path)
    run_dir = write_compare_run(tmp_path)

    result = inspect_mpdocvqa_query_block_granularity(
        run_dir=run_dir,
        mpdocvqa_db_path=db_path,
        output_root=tmp_path / "inspect",
        run_id="query_block",
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["quality_status"] == "diagnostic_only"
    assert result["used_training"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["evaluated_count"] == 4
    assert result["retrieval_miss_count"] == 3
    assert result["gold_page_answer_text_hit_rate"] == 0.6667
    assert result["gold_page_question_overlap_rate"] == 0.6667
    assert result["retrieval_miss_diagnostic_bucket_counts"] == {
        "gold_page_answer_text_not_found": 1,
        "query_answer_bridge_or_question_terms_absent": 1,
        "retrieval_ranker_or_block_scoring_miss": 1,
    }
    assert result["recommendation"]["next_action"] == "inspect_ocr_or_gold_page_text_before_training"
    assert (tmp_path / "sync" / "query_block" / "summary.json").is_file()

    rows = read_jsonl(tmp_path / "inspect" / "query_block" / "rows.jsonl")
    buckets = {row["sample_id"]: row["diagnostic_bucket"] for row in rows}
    assert buckets["ranker_miss"] == "retrieval_ranker_or_block_scoring_miss"
    assert buckets["bridge_miss"] == "query_answer_bridge_or_question_terms_absent"
    assert buckets["gold_answer_absent"] == "gold_page_answer_text_not_found"
    assert buckets["passed"] == "passed"

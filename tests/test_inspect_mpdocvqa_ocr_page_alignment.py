from __future__ import annotations

import json
from pathlib import Path

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.inspect_mpdocvqa_ocr_page_alignment import inspect_mpdocvqa_ocr_page_alignment


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
        blocks = [block(page, "page", f"page {page}", block_type="page") for page in range(1, 7)]
        blocks.extend(
            [
                block(1, "text", "Gold page text without the answer"),
                block(2, "text", "Budget Estimate is $100,000."),
                block(3, "text", "Another gold page text without answer"),
                block(5, "text", "The allocation is AlphaValue."),
                block(6, "text", "No requested answer here."),
            ]
        )
        repository.save_evidence_blocks(blocks)
    finally:
        conn.close()
    return db_path


def write_query_inspect_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "query"
    write_json(run_dir / "summary.json", {"run_id": "query_run", "status": "success", "used_qwen": True})
    write_json(run_dir / "result.json", {"run_id": "query_run", "status": "success"})
    write_jsonl(
        run_dir / "rows.jsonl",
        [
            {
                "source_run_id": "compare",
                "sample_id": "plus_one",
                "ingested_doc_id": "mp_doc",
                "row_bucket": "retrieval_gold_page_miss",
                "diagnostic_bucket": "gold_page_answer_text_not_found",
                "question": "What is the Budget Estimate?",
                "answers": ["$100,000"],
                "gold_pages": [1],
                "retrieved_pages": [3],
            },
            {
                "source_run_id": "compare",
                "sample_id": "elsewhere",
                "ingested_doc_id": "mp_doc",
                "row_bucket": "retrieval_gold_page_miss",
                "diagnostic_bucket": "gold_page_answer_text_not_found",
                "question": "What is the allocation?",
                "answers": ["AlphaValue"],
                "gold_pages": [3],
                "retrieved_pages": [1],
            },
            {
                "source_run_id": "compare",
                "sample_id": "not_found",
                "ingested_doc_id": "mp_doc",
                "row_bucket": "retrieval_gold_page_miss",
                "diagnostic_bucket": "gold_page_answer_text_not_found",
                "question": "What is missing?",
                "answers": ["MissingValue"],
                "gold_pages": [6],
                "retrieved_pages": [1],
            },
            {
                "source_run_id": "compare",
                "sample_id": "ignored",
                "ingested_doc_id": "mp_doc",
                "row_bucket": "answer_generation_or_metric_miss",
                "diagnostic_bucket": "answer_generation_or_metric_miss",
                "question": "Ignored?",
                "answers": ["$100,000"],
                "gold_pages": [2],
                "retrieved_pages": [2],
            },
        ],
    )
    return run_dir


def test_inspect_mpdocvqa_ocr_page_alignment_buckets(tmp_path: Path) -> None:
    db_path = write_db(tmp_path)
    run_dir = write_query_inspect_run(tmp_path)

    result = inspect_mpdocvqa_ocr_page_alignment(
        run_dir=run_dir,
        mpdocvqa_db_path=db_path,
        output_root=tmp_path / "inspect",
        run_id="alignment",
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["quality_status"] == "diagnostic_only"
    assert result["used_training"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["inspected_count"] == 3
    assert result["answer_found_anywhere_rate"] == 0.6667
    assert result["answer_found_adjacent_page_rate"] == 0.3333
    assert result["alignment_bucket_counts"] == {
        "answer_elsewhere_in_document": 1,
        "answer_not_found_in_document_text": 1,
        "answer_on_gold_plus_one_page": 1,
    }
    assert result["recommendation"]["next_action"] == "inspect_mpdocvqa_page_index_alignment_before_retrieval_changes"
    assert (tmp_path / "sync" / "alignment" / "summary.json").is_file()

    rows = read_jsonl(tmp_path / "inspect" / "alignment" / "rows.jsonl")
    buckets = {row["sample_id"]: row["alignment_bucket"] for row in rows}
    assert buckets["plus_one"] == "answer_on_gold_plus_one_page"
    assert buckets["elsewhere"] == "answer_elsewhere_in_document"
    assert buckets["not_found"] == "answer_not_found_in_document_text"

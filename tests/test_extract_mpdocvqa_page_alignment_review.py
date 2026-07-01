from __future__ import annotations

import json
from pathlib import Path

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.extract_mpdocvqa_page_alignment_review import extract_mpdocvqa_page_alignment_review


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def block(page: int, suffix: str, text: str, *, block_type: str = "text") -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="ingested_doc",
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
                block(1, "text", "Gold page text without the requested budget."),
                block(2, "text", "The Budget Estimate is $100,000 for this program."),
                block(3, "text", "Other program notes."),
                block(4, "text", "No requested answer appears here."),
            ]
        )
        repository.save_evidence_blocks(blocks)
    finally:
        conn.close()
    return db_path


def write_subset(tmp_path: Path) -> Path:
    subset = tmp_path / "subset"
    doc_dir = subset / "documents" / "window_doc"
    pages_dir = doc_dir / "pages"
    pages_dir.mkdir(parents=True)
    for index in range(1, 5):
        (pages_dir / f"{index:04d}.jpg").write_bytes(b"jpg")
    (doc_dir / "document.pdf").write_bytes(b"pdf")
    page_records = [
        {
            "page_ordinal": index,
            "page_id": f"source_doc_p{index + 10}",
            "page_file": f"documents/window_doc/pages/{index:04d}.jpg",
        }
        for index in range(1, 5)
    ]
    write_json(
        doc_dir / "document_manifest.json",
        {
            "doc_id": "window_doc",
            "source_doc_id": "source_doc",
            "page_count": 4,
            "ordered_page_ids": [record["page_id"] for record in page_records],
            "ordered_page_files": [record["page_file"] for record in page_records],
            "pages": page_records,
            "pdf_path": "documents/window_doc/document.pdf",
        },
    )
    write_jsonl(
        subset / "documents.jsonl",
        [
            {
                "doc_id": "window_doc",
                "source_doc_id": "source_doc",
                "document_manifest": "documents/window_doc/document_manifest.json",
            }
        ],
    )
    return subset


def write_page_index_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "page_index"
    write_json(
        run_dir / "summary.json",
        {
            "run_id": "page_index_source",
            "status": "success",
            "used_qwen": True,
            "qa_gold_page_ordinal_consistent_with_answer_page_idx_rate": 1.0,
            "manifest_consistent_with_qa_gold_page_rate": 1.0,
            "sample_evidence_consistent_with_manifest_gold_page_rate": 1.0,
            "recommendation": {"next_action": "manual_review_answer_text_hits_before_retrieval_changes"},
        },
    )
    write_json(run_dir / "result.json", {"run_id": "page_index_source", "status": "success"})
    write_jsonl(
        run_dir / "rows.jsonl",
        [
            {
                "sample_id": "q_budget",
                "doc_id": "window_doc",
                "ingested_doc_id": "ingested_doc",
                "source_document": "source_doc",
                "question": "What is the Budget Estimate?",
                "answers": ["$100,000"],
                "page_index_bucket": "answer_on_gold_minus_one_page",
                "alignment_gold_pages": [3],
                "answer_hit_pages": [2],
                "retrieved_pages": [2],
                "selected_pages": [2],
                "citation_pages": [2],
                "retrieved_answer_page_hit": True,
                "selected_answer_page_hit": True,
                "citation_answer_page_hit": True,
                "current_gold_source_page_ids": ["source_doc_p13"],
                "answer_hit_source_page_ids": ["source_doc_p12"],
                "qa_answer_page_idx": 2,
                "qa_gold_page_ordinal": 3,
                "qa_gold_page_id": "source_doc_p13",
                "document_window_page_count": 4,
                "document_window_ordered_page_ids": [
                    "source_doc_p11",
                    "source_doc_p12",
                    "source_doc_p13",
                    "source_doc_p14",
                ],
                "answer_page_minus_alignment_gold_page_delta": -1,
                "qa_ordinal_minus_answer_idx": 1,
                "final_manifest_minus_qa_gold_page_delta": 0,
                "sample_evidence_minus_manifest_gold_page_delta": 0,
            },
            {
                "sample_id": "q_missing",
                "doc_id": "window_doc",
                "ingested_doc_id": "ingested_doc",
                "source_document": "source_doc",
                "question": "What is missing?",
                "answers": ["MissingValue"],
                "page_index_bucket": "answer_not_found_in_document_text",
                "alignment_gold_pages": [4],
                "answer_hit_pages": [],
                "retrieved_pages": [1],
                "selected_pages": [1],
                "citation_pages": [1],
                "current_gold_source_page_ids": ["source_doc_p14"],
                "answer_hit_source_page_ids": [],
                "document_window_page_count": 4,
            },
            {
                "sample_id": "q_exact",
                "doc_id": "window_doc",
                "ingested_doc_id": "ingested_doc",
                "question": "Already aligned",
                "answers": ["$100,000"],
                "page_index_bucket": "answer_on_current_gold_page",
                "alignment_gold_pages": [2],
                "answer_hit_pages": [2],
            },
        ],
    )
    return run_dir


def test_extract_mpdocvqa_page_alignment_review_writes_manual_rows(tmp_path: Path) -> None:
    db_path = write_db(tmp_path)
    subset = write_subset(tmp_path)
    page_index_run = write_page_index_run(tmp_path)

    result = extract_mpdocvqa_page_alignment_review(
        page_index_run_dir=page_index_run,
        subset_root=subset,
        mpdocvqa_db_path=db_path,
        output_root=tmp_path / "review",
        run_id="manual_review",
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["quality_status"] == "diagnostic_only"
    assert result["used_training"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["review_row_count"] == 2
    assert result["review_bucket_counts"] == {
        "manual_check_ocr_text_or_answer_alias": 1,
        "manual_compare_gold_and_adjacent_page_images": 1,
    }
    assert result["actionability_bucket_counts"] == {
        "gold_page_alignment_review_not_retrieval_defect": 1,
        "ocr_or_answer_alias_review": 1,
    }
    assert result["source_page_index_mapping_rates"] == {
        "qa_gold_page_ordinal_consistent_with_answer_page_idx_rate": 1.0,
        "manifest_consistent_with_qa_gold_page_rate": 1.0,
        "sample_evidence_consistent_with_manifest_gold_page_rate": 1.0,
    }
    assert result["recommendation"]["next_action"] == "manual_check_page_alignment_review_rows_before_retrieval_changes"
    assert (tmp_path / "sync" / "manual_review" / "manual_review.md").is_file()

    rows = read_jsonl(tmp_path / "review" / "manual_review" / "manual_review.jsonl")
    assert [row["sample_id"] for row in rows] == ["q_budget", "q_missing"]
    budget = rows[0]
    assert budget["document_pdf"]["exists"] is True
    assert budget["review_bucket"] == "manual_compare_gold_and_adjacent_page_images"
    assert budget["actionability_bucket"] == "gold_page_alignment_review_not_retrieval_defect"
    assert budget["workflow_answer_page_hits"] == {
        "retrieved_answer_page_hit": True,
        "selected_answer_page_hit": True,
        "citation_answer_page_hit": True,
    }
    assert budget["retrieved_pages"] == [2]
    assert any(page["page"] == 2 and page["page_file_exists"] for page in budget["page_reviews"])
    assert any("$100,000" in page["ocr_text_preview"] for page in budget["page_reviews"])
    assert rows[1]["review_bucket"] == "manual_check_ocr_text_or_answer_alias"

from __future__ import annotations

import json
from pathlib import Path

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.inspect_mpdocvqa_page_index_alignment import inspect_mpdocvqa_page_index_alignment


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
        blocks = [block(page, "page", f"page {page}", block_type="page") for page in range(1, 6)]
        blocks.extend(
            [
                block(2, "text", "Budget Estimate is $100,000."),
                block(3, "text", "No requested budget answer here."),
                block(4, "text", "Total award amount is $250,000."),
                block(5, "text", "No requested award answer here."),
            ]
        )
        repository.save_evidence_blocks(blocks)
    finally:
        conn.close()
    return db_path


def write_subset(tmp_path: Path) -> Path:
    subset = tmp_path / "subset"
    doc_dir = subset / "documents" / "window_doc"
    doc_dir.mkdir(parents=True)
    write_json(
        doc_dir / "document_manifest.json",
        {
            "doc_id": "window_doc",
            "source_doc_id": "source_doc",
            "page_count": 5,
            "ordered_page_ids": ["source_doc_p12", "source_doc_p13", "source_doc_p14", "source_doc_p15", "source_doc_p16"],
            "pages": [
                {"page_ordinal": 1, "page_id": "source_doc_p12"},
                {"page_ordinal": 2, "page_id": "source_doc_p13"},
                {"page_ordinal": 3, "page_id": "source_doc_p14"},
                {"page_ordinal": 4, "page_id": "source_doc_p15"},
                {"page_ordinal": 5, "page_id": "source_doc_p16"},
            ],
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
    write_jsonl(
        subset / "qa.jsonl",
        [
            {
                "qid": "q_budget",
                "doc_id": "window_doc",
                "source_doc_id": "source_doc",
                "question": "What is the Budget Estimate?",
                "answers": ["$100,000"],
                "answer_page_idx": 2,
                "gold_page_ordinal": 3,
                "gold_page_id": "source_p3",
            },
            {
                "qid": "q_award",
                "doc_id": "window_doc",
                "source_doc_id": "source_doc",
                "question": "What is the award amount?",
                "answers": ["$250,000"],
                "answer_page_idx": 4,
                "gold_page_ordinal": 5,
                "gold_page_id": "source_p5",
            },
            {
                "qid": "q_exact",
                "doc_id": "window_doc",
                "source_doc_id": "source_doc",
                "question": "What is also on page two?",
                "answers": ["$100,000"],
                "answer_page_idx": 1,
                "gold_page_ordinal": 2,
                "gold_page_id": "source_p2",
            },
        ],
    )
    write_jsonl(
        subset / "sample_manifest.jsonl",
        [
            {"sample_id": "q_budget", "doc_id": "window_doc", "gold_evidence": [{"page": 3}]},
            {"sample_id": "q_award", "doc_id": "window_doc", "gold_evidence": [{"page": 5}]},
            {"sample_id": "q_exact", "doc_id": "window_doc", "gold_evidence": [{"page": 2}]},
        ],
    )
    return subset


def write_sample_evidence(tmp_path: Path) -> Path:
    path = tmp_path / "evidence" / "sample_evidence_manifest.jsonl"
    write_jsonl(
        path,
        [
            {
                "sample_id": "q_budget",
                "doc_id": "window_doc",
                "ingested_doc_id": "ingested_doc",
                "source_document": "source_doc",
                "answers": ["$100,000"],
                "gold_pages": [3],
            },
            {
                "sample_id": "q_award",
                "doc_id": "window_doc",
                "ingested_doc_id": "ingested_doc",
                "source_document": "source_doc",
                "answers": ["$250,000"],
                "gold_pages": [5],
            },
            {
                "sample_id": "q_exact",
                "doc_id": "window_doc",
                "ingested_doc_id": "ingested_doc",
                "source_document": "source_doc",
                "answers": ["$100,000"],
                "gold_pages": [2],
            },
        ],
    )
    return path


def write_alignment_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "alignment"
    write_json(run_dir / "summary.json", {"run_id": "alignment_run", "status": "success", "used_qwen": True})
    write_json(run_dir / "result.json", {"run_id": "alignment_run", "status": "success"})
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
                "alignment_bucket": "answer_on_gold_minus_one_page",
                "gold_pages": [3],
                "answer_hit_pages": [2],
            },
            {
                "sample_id": "q_award",
                "doc_id": "window_doc",
                "ingested_doc_id": "ingested_doc",
                "source_document": "source_doc",
                "question": "What is the award amount?",
                "answers": ["$250,000"],
                "alignment_bucket": "answer_on_gold_minus_one_page",
                "gold_pages": [5],
                "answer_hit_pages": [4],
            },
            {
                "sample_id": "q_exact",
                "doc_id": "window_doc",
                "ingested_doc_id": "ingested_doc",
                "source_document": "source_doc",
                "question": "What is also on page two?",
                "answers": ["$100,000"],
                "alignment_bucket": "answer_on_gold_page",
                "gold_pages": [2],
                "answer_hit_pages": [2],
            },
        ],
    )
    return run_dir


def test_inspect_mpdocvqa_page_index_alignment_detects_generic_shift(tmp_path: Path) -> None:
    db_path = write_db(tmp_path)
    subset = write_subset(tmp_path)
    sample_evidence = write_sample_evidence(tmp_path)
    alignment_run = write_alignment_run(tmp_path)

    result = inspect_mpdocvqa_page_index_alignment(
        alignment_run_dir=alignment_run,
        subset_root=subset,
        sample_evidence_manifest_path=sample_evidence,
        mpdocvqa_db_path=db_path,
        output_root=tmp_path / "inspect",
        run_id="page_index",
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["quality_status"] == "diagnostic_only"
    assert result["used_training"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["inspected_count"] == 3
    assert result["dominant_answer_page_shift"] == -1
    assert result["dominant_answer_page_shift_rate"] == 0.6667
    assert result["qa_ordinal_minus_answer_idx_distribution"] == {"1": 3}
    assert result["final_manifest_minus_qa_gold_page_delta_distribution"] == {"0": 3}
    assert result["sample_evidence_minus_manifest_gold_page_delta_distribution"] == {"0": 3}
    assert result["answer_page_minus_alignment_gold_page_delta_distribution"] == {"-1": 2, "0": 1}
    assert result["current_gold_page_answer_hit_rate"] == 0.3333
    assert result["shifted_gold_page_answer_hit_rates"]["-1"] == 0.6667
    assert result["qa_gold_page_ordinal_consistent_with_answer_page_idx_rate"] == 1.0
    assert (
        result["recommendation"]["next_action"]
        == "manual_review_answer_text_hits_before_retrieval_changes"
    )
    assert (tmp_path / "sync" / "page_index" / "summary.json").is_file()

    rows = read_jsonl(tmp_path / "inspect" / "page_index" / "rows.jsonl")
    assert {row["page_index_bucket"] for row in rows} == {"answer_on_current_gold_page", "answer_on_gold_minus_one_page"}
    budget = next(row for row in rows if row["sample_id"] == "q_budget")
    assert budget["document_window_page_count"] == 5
    assert budget["current_gold_source_page_ids"] == ["source_doc_p14"]
    assert budget["answer_hit_source_page_ids"] == ["source_doc_p13"]

from __future__ import annotations

import json
from pathlib import Path

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.inspect_mpdocvqa_retrieval import inspect_mpdocvqa_retrieval


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_baseline_run(tmp_path: Path) -> Path:
    run_dir = tmp_path / "baseline"
    write_json(
        run_dir / "summary.json",
        {
            "run_id": "baseline_run",
            "status": "success",
            "case_count": 6,
            "evaluated_count": 6,
            "used_qwen": True,
        },
    )
    write_json(run_dir / "result.json", {"run_id": "baseline_run", "status": "success"})
    write_jsonl(
        run_dir / "results.jsonl",
        [
            {"sample_id": "tatqa_ignored", "dataset": "tatqa", "answer_evaluated": True},
            {
                "sample_id": "mp_passed",
                "dataset": "mp_docvqa",
                "doc_id": "source_doc",
                "ingested_doc_id": "mp_doc",
                "answer_evaluated": True,
                "pass_fail": "passed",
                "question": "What is on page 2?",
                "answers": ["alpha"],
                "answer_hit": True,
                "gold_pages": [2],
                "retrieved_block_ids": ["p2_text"],
                "selected_block_ids": ["p2_text"],
                "citation_block_ids": ["p2_text"],
                "failure_reasons": [],
            },
            {
                "sample_id": "mp_retrieval_miss",
                "dataset": "mp_docvqa",
                "doc_id": "source_doc",
                "ingested_doc_id": "mp_doc",
                "answer_evaluated": True,
                "pass_fail": "failed",
                "question": "What is on page 3?",
                "answers": ["bravo"],
                "answer_hit": False,
                "gold_pages": [3],
                "retrieved_block_ids": ["p1_text"],
                "selected_block_ids": ["p1_text"],
                "citation_block_ids": ["p1_text"],
                "failure_reasons": ["answer_miss", "citation_block_miss"],
            },
            {
                "sample_id": "mp_selected_miss",
                "dataset": "mp_docvqa",
                "doc_id": "source_doc",
                "ingested_doc_id": "mp_doc",
                "answer_evaluated": True,
                "pass_fail": "failed",
                "question": "What is on page 4?",
                "answers": ["charlie"],
                "answer_hit": True,
                "gold_pages": [4],
                "retrieved_block_ids": ["p4_text", "p1_text"],
                "selected_block_ids": ["p1_text"],
                "citation_block_ids": ["p4_text"],
                "failure_reasons": ["citation_block_miss"],
            },
            {
                "sample_id": "mp_answer_miss",
                "dataset": "mp_docvqa",
                "doc_id": "source_doc",
                "ingested_doc_id": "mp_doc",
                "answer_evaluated": True,
                "pass_fail": "failed",
                "question": "What is on page 5?",
                "answers": ["delta"],
                "answer_hit": False,
                "gold_pages": [5],
                "retrieved_block_ids": ["p5_text"],
                "selected_block_ids": ["p5_text"],
                "citation_block_ids": ["p5_text"],
                "failure_reasons": ["answer_miss"],
            },
            {
                "sample_id": "mp_no_retrievable_gold_page",
                "dataset": "mp_docvqa",
                "doc_id": "source_doc",
                "ingested_doc_id": "mp_doc",
                "answer_evaluated": True,
                "pass_fail": "failed",
                "question": "What is on page 6?",
                "answers": ["echo"],
                "answer_hit": False,
                "gold_pages": [6],
                "retrieved_block_ids": ["p1_text"],
                "selected_block_ids": ["p1_text"],
                "citation_block_ids": ["p1_text"],
                "failure_reasons": ["answer_miss"],
            },
        ],
    )
    return run_dir


def block(page: int, suffix: str, text: str, *, block_type: str = "text", exclude: bool = False) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="mp_doc",
        block_id=f"p{page}_{suffix}",
        block_type=block_type,
        text=text,
        page_id=page,
        location=EvidenceLocation(page=page, block_id=f"p{page}_{suffix}"),
        metadata={"exclude_from_retrieval": True} if exclude else {},
    )


def write_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "docagent.db"
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        blocks = [block(page, "page", f"page {page} text", block_type="page") for page in range(1, 7)]
        blocks.extend(
            [
                block(1, "text", "page one distractor"),
                block(2, "text", "alpha appears here"),
                block(3, "text", "bravo appears here"),
                block(4, "text", "charlie appears here"),
                block(5, "text", "delta appears here"),
                block(6, "empty", "echo hidden from retrieval", exclude=True),
            ]
        )
        repository.save_evidence_blocks(blocks)
    finally:
        conn.close()
    return db_path


def test_inspect_mpdocvqa_retrieval_buckets_generic_signals(tmp_path: Path) -> None:
    run_dir = write_baseline_run(tmp_path)
    db_path = write_db(tmp_path)

    result = inspect_mpdocvqa_retrieval(
        run_dir=run_dir,
        mpdocvqa_db_path=db_path,
        output_root=tmp_path / "inspect",
        run_id="mp_retrieval",
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["quality_status"] == "diagnostic_only"
    assert result["used_training"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["mpdocvqa_evaluated_count"] == 5
    assert result["retrieved_gold_page_hit_rate"] == 0.6
    assert result["gold_page_has_retrievable_blocks_rate"] == 0.8
    assert result["retrieval_recall_at_1"] == 0.6
    assert result["bucket_counts"] == {
        "answer_generation_or_metric_miss": 1,
        "gold_page_without_retrievable_blocks": 1,
        "passed": 1,
        "retrieval_gold_page_miss": 1,
        "selected_context_gold_page_miss": 1,
    }
    assert result["recommendation"]["next_action"] == "inspect_mineru_evidence_mapping_or_block_text_before_training"
    assert (tmp_path / "sync" / "mp_retrieval" / "summary.json").is_file()

    rows = read_jsonl(tmp_path / "inspect" / "mp_retrieval" / "mpdocvqa_retrieval_rows.jsonl")
    buckets = {row["sample_id"]: row["bucket"] for row in rows}
    assert buckets["mp_retrieval_miss"] == "retrieval_gold_page_miss"
    assert buckets["mp_selected_miss"] == "selected_context_gold_page_miss"
    assert buckets["mp_no_retrievable_gold_page"] == "gold_page_without_retrievable_blocks"
    assert rows[0]["retrieved_gold_page_rank"] == 1

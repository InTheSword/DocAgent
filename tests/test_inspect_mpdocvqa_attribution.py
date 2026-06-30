from __future__ import annotations

import json
from pathlib import Path

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.inspect_mpdocvqa_attribution import inspect_mpdocvqa_attribution


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
            "case_count": 5,
            "evaluated_count": 5,
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
                "ingested_doc_id": "mp_doc",
                "answer_evaluated": True,
                "pass_fail": "passed",
                "question": "What is on page 2?",
                "answers": ["alpha"],
                "prediction_answer": "alpha",
                "answer_hit": True,
                "citation_page_hit": True,
                "gold_pages": [2],
                "retrieved_block_ids": ["p2_text"],
                "selected_block_ids": ["p2_text"],
                "citation_block_ids": ["p2_text"],
                "failure_reasons": [],
            },
            {
                "sample_id": "mp_retrieval_miss",
                "dataset": "mp_docvqa",
                "ingested_doc_id": "mp_doc",
                "answer_evaluated": True,
                "pass_fail": "failed",
                "question": "What is on page 3?",
                "answers": ["bravo"],
                "prediction_answer": "wrong",
                "answer_hit": False,
                "citation_page_hit": False,
                "gold_pages": [3],
                "retrieved_block_ids": ["p1_text"],
                "selected_block_ids": ["p1_text"],
                "citation_block_ids": ["p1_text"],
                "failure_reasons": ["answer_miss", "citation_block_miss"],
            },
            {
                "sample_id": "mp_citation_miss",
                "dataset": "mp_docvqa",
                "ingested_doc_id": "mp_doc",
                "answer_evaluated": True,
                "pass_fail": "failed",
                "question": "What is on page 4?",
                "answers": ["charlie"],
                "prediction_answer": "charlie",
                "answer_hit": True,
                "citation_page_hit": False,
                "gold_pages": [4],
                "retrieved_block_ids": ["p4_text"],
                "selected_block_ids": ["p4_text"],
                "citation_block_ids": ["p1_text"],
                "failure_reasons": ["citation_block_miss"],
            },
            {
                "sample_id": "mp_answer_miss",
                "dataset": "mp_docvqa",
                "ingested_doc_id": "mp_doc",
                "answer_evaluated": True,
                "pass_fail": "failed",
                "question": "What is on page 5?",
                "answers": ["delta"],
                "prediction_answer": "wrong",
                "answer_hit": False,
                "citation_page_hit": True,
                "gold_pages": [5],
                "retrieved_block_ids": ["p5_text"],
                "selected_block_ids": ["p5_text"],
                "citation_block_ids": ["p5_text"],
                "failure_reasons": ["answer_miss"],
            },
        ],
    )
    return run_dir


def write_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "docagent.db"
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        repository.save_evidence_blocks(
            [
                EvidenceBlock(
                    doc_id="mp_doc",
                    block_id=f"p{page}_text",
                    block_type="text",
                    text=f"page {page}",
                    page_id=page,
                    location=EvidenceLocation(page=page, block_id=f"p{page}_text"),
                )
                for page in (1, 2, 3, 4, 5)
            ]
        )
    finally:
        conn.close()
    return db_path


def test_inspect_mpdocvqa_attribution_buckets_page_signals(tmp_path: Path) -> None:
    run_dir = write_baseline_run(tmp_path)
    db_path = write_db(tmp_path)

    result = inspect_mpdocvqa_attribution(
        run_dir=run_dir,
        output_root=tmp_path / "inspect",
        run_id="mp_attr",
        mpdocvqa_db_path=db_path,
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["used_training"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["mpdocvqa_evaluated_count"] == 4
    assert result["mpdocvqa_answer_hit_rate"] == 0.5
    assert result["mpdocvqa_citation_page_hit_rate"] == 0.5
    assert result["retrieved_gold_page_hit_rate"] == 0.75
    assert result["bucket_counts"] == {
        "answer_generation_or_metric_miss": 1,
        "citation_selection_page_miss": 1,
        "passed": 1,
        "retrieval_gold_page_miss": 1,
    }
    assert result["recommendation"]["next_action"] == "inspect_mpdocvqa_retrieval_before_training"
    assert (tmp_path / "sync" / "mp_attr" / "summary.json").is_file()

    rows = read_jsonl(tmp_path / "inspect" / "mp_attr" / "mpdocvqa_attribution_rows.jsonl")
    buckets = {row["sample_id"]: row["bucket"] for row in rows}
    assert buckets["mp_retrieval_miss"] == "retrieval_gold_page_miss"
    assert buckets["mp_citation_miss"] == "citation_selection_page_miss"
    assert buckets["mp_answer_miss"] == "answer_generation_or_metric_miss"

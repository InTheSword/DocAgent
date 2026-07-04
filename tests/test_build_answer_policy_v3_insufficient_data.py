from __future__ import annotations

import json
from pathlib import Path

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl
from scripts.build_answer_policy_v3_insufficient_data import build_mpdocvqa_insufficient_data, build_tatqa_insufficient_data
from scripts.build_answer_policy_v3_training_data import text_contains_answer
from scripts.run_answer_policy_v3_sft_warmup import validate_sft_record


def _tatqa_train_records() -> list[dict]:
    return [
        {
            "uid": "doc_train_1",
            "table": {
                "uid": "table_1",
                "table": [
                    ["Metric", "2019", "2018"],
                    ["Revenue", "$100", "$90"],
                ],
            },
            "paragraphs": [
                {"order": 1, "text": "The invoice date is March 12, 2020."},
                {"order": 2, "text": "The company filed its annual report."},
            ],
            "questions": [
                {
                    "uid": "q_invoice_date",
                    "question": "What is the invoice date?",
                    "answer": "March 12, 2020",
                    "answer_type": "span",
                    "answer_from": "text",
                    "rel_paragraphs": [1],
                    "derivation": "",
                    "scale": "",
                }
            ],
        },
        {
            "uid": "doc_train_2",
            "table": {
                "uid": "table_2",
                "table": [
                    ["Metric", "2020", "2019"],
                    ["Assets", "$500", "$450"],
                ],
            },
            "paragraphs": [
                {"order": 1, "text": "The board approved a dividend on May 5, 2021."},
                {"order": 2, "text": "The note discusses treasury shares."},
            ],
            "questions": [
                {
                    "uid": "q_dividend_date",
                    "question": "When did the board approve a dividend?",
                    "answer": "May 5, 2021",
                    "answer_type": "span",
                    "answer_from": "text",
                    "rel_paragraphs": [1],
                    "derivation": "",
                    "scale": "",
                }
            ],
        },
    ]


def _write_raw(path: Path, records: list[dict] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(records or _tatqa_train_records(), ensure_ascii=False), encoding="utf-8")


def test_build_tatqa_insufficient_data_writes_valid_v3_records(tmp_path: Path) -> None:
    raw_path = tmp_path / "train" / "tatqa_dataset_train.json"
    _write_raw(raw_path)

    result = build_tatqa_insufficient_data(
        tatqa_raw=raw_path,
        output_root=tmp_path / "out",
        run_id="insufficient",
        limit=2,
    )

    artifact_dir = tmp_path / "out" / "insufficient"
    records = read_jsonl(artifact_dir / "insufficient_evidence.jsonl")
    aligned = read_jsonl(artifact_dir / "aligned_records.jsonl")
    sft = read_jsonl(artifact_dir / "sft_train.jsonl")

    assert result["status"] == "success"
    assert result["insufficient_record_count"] == 2
    assert result["sft_record_count"] == 2
    assert result["bucket_counts"] == {"insufficient_confirmed": 2}
    assert result["used_training"] is False
    assert result["validation_subset_used_for_training"] is False
    assert records == aligned
    assert len(sft) == 2

    for record, sft_record in zip(records, sft):
        target = record["target_model_output"]
        assert target["answer"] == "Insufficient evidence."
        assert target["support_status"] == "insufficient"
        assert target["supporting_refs"] == []
        assert record["bucket"] == "insufficient_confirmed"
        assert record["metadata"]["source_doc_id"] != record["metadata"]["decoy_doc_id"]
        assert record["evidence_candidates"]
        assert set(record["evidence_ref_map"]) == {item["ref"] for item in record["evidence_candidates"]}
        assert validate_sft_record(sft_record) == (True, "")

    first_candidate_text = "\n".join(item["display_text"] for item in records[0]["evidence_candidates"])
    assert not text_contains_answer(first_candidate_text, "March 12, 2020")
    assistant_target = json.loads(sft[0]["messages"][-1]["content"])
    assert assistant_target["support_status"] == "insufficient"
    assert assistant_target["supporting_refs"] == []
    assert "citation_block_ids" not in assistant_target


def test_build_tatqa_insufficient_data_blocks_validation_like_paths(tmp_path: Path) -> None:
    raw_path = tmp_path / "final_eval" / "tatqa_dataset_train.json"
    _write_raw(raw_path)

    result = build_tatqa_insufficient_data(
        tatqa_raw=raw_path,
        output_root=tmp_path / "out",
        run_id="blocked",
    )

    artifact_dir = tmp_path / "out" / "blocked"
    assert result["status"] == "blocked"
    assert result["insufficient_record_count"] == 0
    assert result["block_reasons"] == ["validation_like_input_path:final_eval"]
    assert read_jsonl(artifact_dir / "sft_train.jsonl") == []
    assert read_jsonl(artifact_dir / "insufficient_evidence.jsonl") == []


def test_build_tatqa_insufficient_data_records_alignment_failure_without_decoy(tmp_path: Path) -> None:
    raw_path = tmp_path / "train" / "tatqa_dataset_train.json"
    _write_raw(raw_path, [_tatqa_train_records()[0]])

    result = build_tatqa_insufficient_data(
        tatqa_raw=raw_path,
        output_root=tmp_path / "out",
        run_id="no_decoy",
        limit=5,
    )

    artifact_dir = tmp_path / "out" / "no_decoy"
    assert result["status"] == "success"
    assert result["insufficient_record_count"] == 0
    assert result["scan_counts"]["alignment_failed"] == 1
    assert read_jsonl(artifact_dir / "sft_train.jsonl") == []
    assert read_jsonl(artifact_dir / "alignment_failed.jsonl")[0]["reason"] == "no_decoy_board_without_gold_answer"


def _write_mpdocvqa_insufficient_fixture(tmp_path: Path, *, manifest_dir_name: str = "train") -> tuple[Path, Path]:
    db_path = tmp_path / "db" / "docagent.db"
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        repository.save_evidence_blocks(
            [
                EvidenceBlock(
                    doc_id="source_ingested",
                    block_id="source_ingested_p001_b0001",
                    block_type="text",
                    text="The answer code is Alpha Budget.",
                    page_id=1,
                    location=EvidenceLocation(page=1, block_id="source_ingested_p001_b0001"),
                    metadata={"raw_mineru_type": "text"},
                ),
                EvidenceBlock(
                    doc_id="decoy_ingested",
                    block_id="decoy_ingested_p001_b0001",
                    block_type="text",
                    text="This page discusses unrelated filing procedures and board notices.",
                    page_id=1,
                    location=EvidenceLocation(page=1, block_id="decoy_ingested_p001_b0001"),
                    metadata={"raw_mineru_type": "text"},
                ),
            ]
        )
    finally:
        conn.close()

    rows = [
        {
            "sample_id": "mp_source",
            "dataset": "mp_docvqa",
            "split": "train",
            "doc_id": "source_window",
            "ingested_doc_id": "source_ingested",
            "source_document": "source_pdf",
            "question": "What is the answer code?",
            "answers": ["Alpha Budget"],
            "gold_pages": [1],
            "evidence_ready": True,
        },
        {
            "sample_id": "mp_decoy",
            "dataset": "mp_docvqa",
            "split": "train",
            "doc_id": "decoy_window",
            "ingested_doc_id": "decoy_ingested",
            "source_document": "decoy_pdf",
            "question": "What does this page discuss?",
            "answers": ["board notices"],
            "gold_pages": [1],
            "evidence_ready": True,
        },
    ]
    manifest_path = tmp_path / manifest_dir_name / "sample_evidence_manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    return manifest_path, db_path


def test_build_mpdocvqa_insufficient_data_writes_valid_v3_records(tmp_path: Path) -> None:
    manifest_path, db_path = _write_mpdocvqa_insufficient_fixture(tmp_path)

    result = build_mpdocvqa_insufficient_data(
        evidence_manifest=manifest_path,
        db_path=db_path,
        output_root=tmp_path / "out",
        run_id="mp_insufficient",
        limit=1,
    )

    artifact_dir = tmp_path / "out" / "mp_insufficient"
    records = read_jsonl(artifact_dir / "insufficient_evidence.jsonl")
    sft = read_jsonl(artifact_dir / "sft_train.jsonl")

    assert result["status"] == "success"
    assert result["source"] == "mp_docvqa"
    assert result["insufficient_record_count"] == 1
    assert result["sft_record_count"] == 1
    assert result["bucket_counts"] == {"insufficient_confirmed": 1}
    assert result["mpdocvqa_evidence_manifest"].endswith("sample_evidence_manifest.jsonl")
    assert result["mpdocvqa_db_path"].endswith("docagent.db")
    assert result["validation_subset_used_for_training"] is False

    record = records[0]
    assert record["source"] == "mp_docvqa"
    assert record["target_model_output"]["support_status"] == "insufficient"
    assert record["target_model_output"]["supporting_refs"] == []
    assert record["metadata"]["source_ingested_doc_id"] != record["metadata"]["decoy_ingested_doc_id"]
    assert record["metadata"]["negative_sampling"] == "different_window_no_gold_answer_text_match"
    assert set(record["evidence_ref_map"]) == {item["ref"] for item in record["evidence_candidates"]}
    assert not text_contains_answer("\n".join(item["display_text"] for item in record["evidence_candidates"]), "Alpha Budget")
    assert validate_sft_record(sft[0]) == (True, "")

    assistant_target = json.loads(sft[0]["messages"][-1]["content"])
    assert assistant_target["support_status"] == "insufficient"
    assert assistant_target["supporting_refs"] == []
    assert "citation_block_ids" not in assistant_target


def test_build_mpdocvqa_insufficient_data_blocks_validation_like_paths(tmp_path: Path) -> None:
    manifest_path, db_path = _write_mpdocvqa_insufficient_fixture(tmp_path, manifest_dir_name="final_eval")

    result = build_mpdocvqa_insufficient_data(
        evidence_manifest=manifest_path,
        db_path=db_path,
        output_root=tmp_path / "out",
        run_id="blocked_mp",
    )

    assert result["status"] == "blocked"
    assert result["insufficient_record_count"] == 0
    assert result["block_reasons"] == ["validation_like_input_path:final_eval"]
    assert read_jsonl(tmp_path / "out" / "blocked_mp" / "sft_train.jsonl") == []

from __future__ import annotations

import json
from pathlib import Path

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl
from scripts.build_answer_policy_v3_training_data import build_answer_policy_v3_mpdocvqa_data, build_answer_policy_v3_tatqa_data


def _tatqa_context() -> dict:
    return {
        "uid": "doc_train_1",
        "table": {
            "uid": "table_1",
            "table": [
                ["Metric", "2019", "2018"],
                ["Revenue", "$100", "$90"],
                ["Operating income", "$30", "$20"],
            ],
        },
        "paragraphs": [
            {"order": 1, "text": "The invoice date is March 12, 2020."},
            {"order": 2, "text": "Unrelated filing text."},
        ],
        "questions": [
            {
                "uid": "q_extract",
                "question": "What is the invoice date?",
                "answer": "March 12, 2020",
                "answer_type": "span",
                "answer_from": "text",
                "rel_paragraphs": [1],
                "derivation": "",
                "scale": "",
            },
            {
                "uid": "q_calc",
                "question": "What is total revenue across 2019 and 2018?",
                "answer": "190",
                "answer_type": "arithmetic",
                "answer_from": "table",
                "rel_paragraphs": [],
                "derivation": "100 + 90",
                "scale": "",
            },
            {
                "uid": "q_failed",
                "question": "What is the CEO name?",
                "answer": "Ada Lovelace",
                "answer_type": "span",
                "answer_from": "text",
                "rel_paragraphs": [2],
                "derivation": "",
                "scale": "",
            },
        ],
    }


def _write_raw(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([_tatqa_context()], ensure_ascii=False), encoding="utf-8")


def test_build_answer_policy_v3_tatqa_data_writes_schema_artifacts(tmp_path: Path) -> None:
    raw_path = tmp_path / "train" / "tatqa_dataset_train.json"
    _write_raw(raw_path)

    result = build_answer_policy_v3_tatqa_data(
        tatqa_raw=raw_path,
        output_root=tmp_path / "out",
        run_id="trial",
        limit=10,
        allow_non_train_source=True,
    )

    artifact_dir = tmp_path / "out" / "trial"
    assert result["status"] == "success"
    assert result["used_training"] is False
    assert result["training_started"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["formal_benchmark_acceptance"] is False
    assert result["bucket_counts"] == {
        "deterministic_tool_supported": 1,
        "evidence_extractive_supported": 1,
    }

    aligned = read_jsonl(artifact_dir / "aligned_records.jsonl")
    sft = read_jsonl(artifact_dir / "sft_train.jsonl")
    failed = read_jsonl(artifact_dir / "alignment_failed.jsonl")

    assert len(aligned) == 2
    assert len(sft) == 2
    assert len(failed) == 1
    assert (artifact_dir / "summary.md").is_file()
    assert (artifact_dir / "manifest.json").is_file()
    assert (artifact_dir / "preview.json").is_file()

    assistant_target = json.loads(sft[0]["messages"][-1]["content"])
    assert set(assistant_target) == {"answer", "supporting_refs", "support_status", "reasoning_summary"}
    assert "citation_block_ids" not in assistant_target
    assert "evidence_used" not in assistant_target
    assert "under 300 characters" in sft[0]["messages"][0]["content"]
    assert "under 300 characters" in sft[0]["messages"][1]["content"]
    user_prompt = sft[0]["messages"][1]["content"]
    assert "## Task\nAnswer the question from the numbered evidence candidates." in user_prompt
    assert "Return JSON matching this schema" in user_prompt
    assert "[E1] kind=table page=1" in user_prompt
    assert "For tables, lists, and key-value blocks" in user_prompt
    assert "Table, page 1:" not in user_prompt

    calc_record = next(record for record in aligned if record["bucket"] == "deterministic_tool_supported")
    assert calc_record["target_model_output"]["supporting_refs"] == ["E4"]
    assert calc_record["evidence_candidates"][-1]["kind"] == "calculation_result"
    assert calc_record["evidence_ref_map"]["E4"]["source_kind"] == "calculation_result"
    assert calc_record["evidence_ref_map"]["E4"]["derived_from_refs"] == ["E1"]
    calc_sft = next(record for record in sft if record["id"] == "q_calc")
    assert "[E4] kind=calculation_result\nCalculation result:" in calc_sft["messages"][1]["content"]
    assert "## Answer Type\nnumeric" in calc_sft["messages"][1]["content"]


def test_answer_policy_v3_tatqa_data_blocks_validation_like_paths(tmp_path: Path) -> None:
    raw_path = tmp_path / "final_eval" / "tatqa_dataset_train.json"
    _write_raw(raw_path)

    result = build_answer_policy_v3_tatqa_data(
        tatqa_raw=raw_path,
        output_root=tmp_path / "out",
        run_id="blocked",
    )

    artifact_dir = tmp_path / "out" / "blocked"
    assert result["status"] == "blocked"
    assert result["sft_record_count"] == 0
    assert result["block_reasons"] == ["validation_like_input_path:final_eval"]
    assert read_jsonl(artifact_dir / "sft_train.jsonl") == []
    assert read_jsonl(artifact_dir / "aligned_records.jsonl") == []


def test_answer_policy_v3_tatqa_data_blocks_non_train_split(tmp_path: Path) -> None:
    raw_path = tmp_path / "train" / "tatqa_dataset_train.json"
    _write_raw(raw_path)

    result = build_answer_policy_v3_tatqa_data(
        tatqa_raw=raw_path,
        output_root=tmp_path / "out",
        run_id="blocked_split",
        split="dev",
    )

    assert result["status"] == "blocked"
    assert result["block_reasons"] == ["non_train_split:dev"]


def _write_mpdocvqa_fixture(tmp_path: Path, *, manifest_dir_name: str = "train") -> tuple[Path, Path]:
    db_path = tmp_path / "db" / "docagent.db"
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        repository.save_evidence_blocks(
            [
                EvidenceBlock(
                    doc_id="ingested_doc",
                    block_id="ingested_doc_p002_b0001",
                    block_type="text",
                    text="The Budget Estimate for Pharmaceutical Compendia Surveillance is $100,000.",
                    page_id=2,
                    location=EvidenceLocation(page=2, block_id="ingested_doc_p002_b0001"),
                    metadata={"raw_mineru_type": "text"},
                ),
                EvidenceBlock(
                    doc_id="ingested_doc",
                    block_id="ingested_doc_p001_b0001",
                    block_type="text",
                    text="Other page text.",
                    page_id=1,
                    location=EvidenceLocation(page=1, block_id="ingested_doc_p001_b0001"),
                ),
            ]
        )
    finally:
        conn.close()

    manifest_path = tmp_path / manifest_dir_name / "sample_evidence_manifest.jsonl"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(
            {
                "sample_id": "16999",
                "dataset": "mp_docvqa",
                "split": "train",
                "doc_id": "window_doc",
                "ingested_doc_id": "ingested_doc",
                "source_document": "fpbw0217",
                "question": "What is the Budget Estimate for Pharmaceutical Compendia Surveillance?",
                "answers": ["$100,000"],
                "gold_pages": [2],
                "evidence_ready": True,
                "expected_tools": ["retrieval", "local_fact_qa"],
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    return manifest_path, db_path


def test_build_answer_policy_v3_mpdocvqa_data_writes_supported_records(tmp_path: Path) -> None:
    manifest_path, db_path = _write_mpdocvqa_fixture(tmp_path)

    result = build_answer_policy_v3_mpdocvqa_data(
        evidence_manifest=manifest_path,
        db_path=db_path,
        output_root=tmp_path / "out",
        run_id="mp_trial",
        limit=10,
    )

    artifact_dir = tmp_path / "out" / "mp_trial"
    aligned = read_jsonl(artifact_dir / "aligned_records.jsonl")
    sft = read_jsonl(artifact_dir / "sft_train.jsonl")

    assert result["status"] == "success"
    assert result["source"] == "mp_docvqa"
    assert result["aligned_record_count"] == 1
    assert result["sft_record_count"] == 1
    assert result["validation_subset_used_for_training"] is False
    assert result["mpdocvqa_evidence_manifest"].endswith("sample_evidence_manifest.jsonl")
    assert result["mpdocvqa_db_path"].endswith("docagent.db")
    assert aligned[0]["target_model_output"]["supporting_refs"] == ["E1"]
    assert aligned[0]["evidence_candidates"][0]["kind"] == "ocr"
    assert aligned[0]["evidence_ref_map"]["E1"]["block_id"] == "ingested_doc_p002_b0001"
    assistant_target = json.loads(sft[0]["messages"][-1]["content"])
    assert set(assistant_target) == {"answer", "supporting_refs", "support_status", "reasoning_summary"}


def test_build_answer_policy_v3_mpdocvqa_blocks_validation_like_manifest_paths(tmp_path: Path) -> None:
    manifest_path, db_path = _write_mpdocvqa_fixture(tmp_path, manifest_dir_name="final_eval")

    result = build_answer_policy_v3_mpdocvqa_data(
        evidence_manifest=manifest_path,
        db_path=db_path,
        output_root=tmp_path / "out",
        run_id="blocked_mp",
    )

    assert result["status"] == "blocked"
    assert result["aligned_record_count"] == 0
    assert result["block_reasons"] == ["validation_like_input_path:final_eval"]
    assert read_jsonl(tmp_path / "out" / "blocked_mp" / "sft_train.jsonl") == []

from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl
from scripts.build_answer_policy_v3_training_data import build_answer_policy_v3_tatqa_data


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

    calc_record = next(record for record in aligned if record["bucket"] == "deterministic_tool_supported")
    assert calc_record["target_model_output"]["supporting_refs"] == ["E4"]
    assert calc_record["evidence_candidates"][-1]["kind"] == "calculation_result"
    assert calc_record["evidence_ref_map"]["E4"]["source_kind"] == "calculation_result"
    assert calc_record["evidence_ref_map"]["E4"]["derived_from_refs"] == ["E1"]


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

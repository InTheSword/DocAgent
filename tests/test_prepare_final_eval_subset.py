from __future__ import annotations

import json
from pathlib import Path

from docagent.utils.jsonl import read_jsonl
from scripts.prepare_final_eval_subset import mpdocvqa_manifest_row, prepare_mpdocvqa_subset, prepare_tatqa_subset


def _write_tatqa_fixture(path: Path) -> None:
    payload = [
        {
            "table": {
                "uid": "table_a",
                "table": [
                    ["USDm", "2019", "2018"],
                    ["Total loan", "828.8", "885.3"],
                    ["LTV ratio", "46.0%", "52.9%"],
                ],
            },
            "paragraphs": [
                {
                    "uid": "para_a",
                    "order": 1,
                    "text": "TORM defines Loan-to-value ratio as vessel values divided by net borrowings.",
                }
            ],
            "questions": [
                {
                    "uid": "q_text",
                    "question": "How does TORM define LTV?",
                    "answer": ["vessel values divided by net borrowings"],
                    "derivation": "",
                    "answer_type": "span",
                    "answer_from": "text",
                    "rel_paragraphs": ["1"],
                    "scale": "",
                },
                {
                    "uid": "q_table",
                    "question": "In which year was the LTV ratio largest?",
                    "answer": ["2018"],
                    "derivation": "52.9%>46.0%",
                    "answer_type": "span",
                    "answer_from": "table",
                    "rel_paragraphs": [],
                    "scale": "",
                },
                {
                    "uid": "q_calc",
                    "question": "What was the change in Total loan in 2019 from 2018?",
                    "answer": -56.5,
                    "derivation": "828.8-885.3",
                    "answer_type": "arithmetic",
                    "answer_from": "table",
                    "rel_paragraphs": [],
                    "scale": "million",
                },
            ],
        }
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_prepare_tatqa_subset_writes_manifest_and_reports(tmp_path: Path) -> None:
    raw_path = tmp_path / "tatqa_dataset_dev.json"
    output_root = tmp_path / "tatqa_out"
    _write_tatqa_fixture(raw_path)

    payload = prepare_tatqa_subset(
        raw_path=raw_path,
        output_root=output_root,
        split="dev",
        limit=3,
        seed="fixture-seed",
        overwrite=False,
    )

    samples = read_jsonl(output_root / "samples.jsonl")
    manifests = read_jsonl(output_root / "sample_manifest.jsonl")
    report = json.loads((output_root / "filter_report.json").read_text(encoding="utf-8"))
    source_manifest = json.loads((output_root / "source_manifest.json").read_text(encoding="utf-8"))

    assert payload["status"] == "success"
    assert report["selected_sample_count"] == 3
    assert source_manifest["download_performed"] is False
    assert len(samples) == 3
    assert len(manifests) == 3
    assert samples[0]["evidence"][0]["block_type"] == "table"
    assert samples[0]["evidence"][0]["table_html"].startswith("<table>")
    calc_manifest = next(item for item in manifests if item["sample_id"] == "q_calc")
    assert calc_manifest["expected_tools"] == ["table_lookup", "simple_calculation"]
    assert calc_manifest["gold_evidence"][0]["block_type"] == "table"
    text_manifest = next(item for item in manifests if item["sample_id"] == "q_text")
    assert text_manifest["gold_evidence"][0]["block_id"] == "table_a_paragraph_1"


def test_prepare_mpdocvqa_subset_blocks_when_no_parquet(tmp_path: Path) -> None:
    parquet_dir = tmp_path / "mp_docvqa" / "val"
    parquet_dir.mkdir(parents=True)
    (parquet_dir / "partial.crdownload").write_bytes(b"incomplete")

    payload = prepare_mpdocvqa_subset(
        parquet_dir=parquet_dir,
        parquet_paths=None,
        output_root=tmp_path / "mp_out",
        target_qa_count=5,
        min_qa_count=1,
        max_qa_count=10,
        seed="fixture-seed",
        split="val",
        validate_only=False,
        overwrite=False,
        baseline_doc_ids=[],
    )
    report = json.loads((tmp_path / "mp_out" / "filter_report.json").read_text(encoding="utf-8"))

    assert payload["status"] == "blocked"
    assert payload["reason"] == "missing_parquet_shards"
    assert report["temporary_download_files"] == ["partial.crdownload"]


def test_mpdocvqa_manifest_row_uses_explicit_split_when_source_split_missing() -> None:
    row = mpdocvqa_manifest_row(
        {
            "qid": "q1",
            "doc_id": "window_doc",
            "source_doc_id": "source_doc",
            "question": "What is shown?",
            "answers": ["answer"],
            "gold_page_ordinal": 1,
        },
        split="train",
    )

    assert row["split"] == "train"

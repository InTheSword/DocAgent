from __future__ import annotations

import io
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
from PIL import Image
from pypdf import PdfReader

from docagent.utils.jsonl import read_jsonl
from scripts.build_mpdocvqa_raw_documents import window_identity
from scripts.build_phase4b_expanded_sample import parse_args, run_expanded_sample


IMAGE_STRUCT = pa.struct([("bytes", pa.binary()), ("path", pa.string())])


def _image_bytes(color: str) -> bytes:
    image = Image.new("RGB", (32, 24), color=color)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


def _row(qid: str, *, source_doc_id: str, page_count: int, answer_page_idx: int, color: str) -> dict[str, object]:
    page_ids = [f"{source_doc_id}_p{index}" for index in range(1, page_count + 1)]
    payload: dict[str, object] = {
        "questionId": qid,
        "question": f"Question {qid}?",
        "doc_id": source_doc_id,
        "page_ids": repr(page_ids),
        "answers": repr([f"answer-{qid}"]),
        "answer_page_idx": str(answer_page_idx),
        "data_split": "val",
    }
    for index in range(1, 21):
        payload[f"image_{index}"] = None
    for index, page_id in enumerate(page_ids, start=1):
        payload[f"image_{index}"] = {"bytes": _image_bytes(color), "path": f"{page_id}.jpg"}
    return payload


def _write_parquet(path: Path, rows: list[dict[str, object]]) -> Path:
    columns = ["questionId", "question", "doc_id", "page_ids", "answers", "answer_page_idx", "data_split"] + [
        f"image_{index}" for index in range(1, 21)
    ]
    arrays = []
    for name in columns:
        values = [row.get(name) for row in rows]
        arrays.append(pa.array(values, type=IMAGE_STRUCT) if name.startswith("image_") else pa.array(values))
    table = pa.Table.from_arrays(arrays, names=columns)
    pq.write_table(table, path)
    return path


def test_expanded_sample_manifest_preserves_baseline_and_prefers_new_shards(tmp_path: Path) -> None:
    baseline_row = _row("q_base", source_doc_id="doc_base", page_count=1, answer_page_idx=0, color="red")
    baseline_doc_id = window_identity("doc_base", ["doc_base_p1"])[1]
    shard1 = _write_parquet(tmp_path / "val-00001-of-00029.parquet", [baseline_row])
    shard2 = _write_parquet(
        tmp_path / "val-00002-of-00029.parquet",
        [
            _row("q_short", source_doc_id="doc_short", page_count=3, answer_page_idx=1, color="green"),
            _row("q_medium", source_doc_id="doc_medium", page_count=7, answer_page_idx=4, color="blue"),
            _row("q_long", source_doc_id="doc_long", page_count=12, answer_page_idx=10, color="purple"),
        ],
    )
    args = parse_args(
        [
            "--input-parquet",
            str(shard1),
            str(shard2),
            "--output-root",
            str(tmp_path / "expanded"),
            "--baseline-doc-id",
            baseline_doc_id,
            "--target-qa-count",
            "4",
            "--min-qa-count",
            "4",
            "--max-qa-count",
            "4",
            "--overwrite",
        ]
    )

    payload = run_expanded_sample(args)
    output_root = tmp_path / "expanded"
    manifest_rows = read_jsonl(output_root / "expanded_sample_manifest.jsonl")
    summary = json.loads((output_root / "selection_summary.json").read_text(encoding="utf-8"))

    assert payload["status"] == "success"
    assert summary["selected_qa_count"] == 4
    assert summary["baseline_windows_count"] == 1
    assert summary["newly_selected_windows_count"] == 3
    assert summary["page_bucket_distribution"]["pages_1"] == 1
    assert summary["page_bucket_distribution"]["pages_2_5"] == 1
    assert summary["page_bucket_distribution"]["pages_6_9"] == 1
    assert summary["page_bucket_distribution"]["pages_10_plus"] == 1
    assert manifest_rows[0]["doc_id"] == baseline_doc_id
    assert manifest_rows[0]["selection_reason"] == "baseline_verified"
    assert all("window_signature" in row and "answer_page_idx" in row for row in manifest_rows)
    assert (output_root / "qa.jsonl").is_file()
    doc_pdf = output_root / "documents" / manifest_rows[-1]["doc_id"] / "document.pdf"
    assert len(PdfReader(str(doc_pdf)).pages) == manifest_rows[-1]["page_count"]


def test_expanded_sample_validate_only_writes_selection_without_assets(tmp_path: Path) -> None:
    shard = _write_parquet(
        tmp_path / "val-00002-of-00029.parquet",
        [_row("q1", source_doc_id="doc_a", page_count=2, answer_page_idx=0, color="orange")],
    )
    args = parse_args(
        [
            "--input-parquet",
            str(shard),
            "--output-root",
            str(tmp_path / "expanded"),
            "--target-qa-count",
            "1",
            "--min-qa-count",
            "1",
            "--max-qa-count",
            "1",
            "--validate-only",
            "--overwrite",
        ]
    )

    payload = run_expanded_sample(args)
    output_root = tmp_path / "expanded"

    assert payload["status"] == "success"
    assert payload["validate_only"] is True
    assert (output_root / "expanded_sample_manifest.jsonl").is_file()
    assert (output_root / "selection_summary.json").is_file()
    assert not (output_root / "documents").exists()

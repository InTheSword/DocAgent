from __future__ import annotations

import io
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from PIL import Image
from pypdf import PdfReader

from docagent.utils.jsonl import read_jsonl
from scripts.build_mpdocvqa_raw_documents import (
    BuildError,
    DEFAULT_OUTPUT_ROOT,
    INPUT_SCOPE,
    REPEATED_CONTENT_WARNING,
    audit_parquet,
    build_outputs,
    parse_row,
    window_identity,
)


IMAGE_STRUCT = pa.struct([("bytes", pa.binary()), ("path", pa.string())])


def _image_bytes(color: str, *, size: tuple[int, int] = (32, 24), image_format: str = "JPEG") -> bytes:
    image = Image.new("RGB", size, color=color)
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


def _row(
    qid: str,
    *,
    source_doc_id: str,
    page_ids: list[str] | Any,
    answers: list[str] | Any,
    answer_page_idx: int | str,
    images: list[bytes],
    stringify_lists: bool = True,
    question: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "questionId": qid,
        "question": question or f"Question {qid}?",
        "doc_id": source_doc_id,
        "page_ids": repr(page_ids) if stringify_lists else page_ids,
        "answers": repr(answers) if stringify_lists else answers,
        "answer_page_idx": str(answer_page_idx) if stringify_lists else answer_page_idx,
        "data_split": "val",
    }
    ordered_page_ids = page_ids if isinstance(page_ids, list) else list(page_ids)
    for index in range(1, 21):
        payload[f"image_{index}"] = None
    for index, raw in enumerate(images, start=1):
        payload[f"image_{index}"] = {"bytes": raw, "path": f"{ordered_page_ids[index - 1]}.jpg"}
    return payload


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> Path:
    columns = ["questionId", "question", "doc_id", "page_ids", "answers", "answer_page_idx", "data_split"] + [
        f"image_{index}" for index in range(1, 21)
    ]
    arrays = []
    for name in columns:
        values = [row.get(name) for row in rows]
        if name.startswith("image_"):
            arrays.append(pa.array(values, type=IMAGE_STRUCT))
        else:
            arrays.append(pa.array(values))
    table = pa.Table.from_arrays(arrays, names=columns)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)
    return path


def _run_build(
    tmp_path: Path,
    rows: list[dict[str, Any]],
    *,
    sample_documents: int = 5,
    seed: str = "42",
    validate_only: bool = False,
    doc_ids: list[str] | None = None,
    overwrite: bool = False,
) -> tuple[list[Path], Path, dict[str, Any]]:
    parquet_path = _write_parquet(tmp_path / "fixture.parquet", rows)
    output_root = tmp_path / "out"
    audit = audit_parquet(parquet_path)
    payload = build_outputs(
        audit=audit,
        input_parquets=[parquet_path],
        output_root=output_root,
        sample_documents=sample_documents,
        seed=seed,
        requested_doc_ids=doc_ids or [],
        validate_only=validate_only,
        overwrite=overwrite,
    )
    return [parquet_path], output_root, payload


def test_single_page_window_recovery_and_pdf_page_count(tmp_path: Path) -> None:
    image = _image_bytes("red")
    _, output_root, payload = _run_build(
        tmp_path,
        [
            _row(
                "q1",
                source_doc_id="doc_single",
                page_ids=["doc_single_p1"],
                answers=["alpha"],
                answer_page_idx=0,
                images=[image],
            )
        ],
    )

    expected_signature, expected_window_id = window_identity("doc_single", ["doc_single_p1"])
    qa_records = read_jsonl(output_root / "qa.jsonl")
    manifest = json.loads((output_root / "documents" / expected_window_id / "document_manifest.json").read_text(encoding="utf-8"))
    reader = PdfReader(str(output_root / "documents" / expected_window_id / "document.pdf"))

    assert payload["status"] == "success"
    assert len(reader.pages) == 1
    assert qa_records[0]["doc_id"] == expected_window_id
    assert qa_records[0]["source_doc_id"] == "doc_single"
    assert qa_records[0]["gold_page_id"] == "doc_single_p1"
    assert qa_records[0]["gold_page_ordinal"] == 1
    assert manifest["window_signature"] == expected_signature
    assert manifest["ordered_page_files"] == [f"documents/{expected_window_id}/pages/0001.jpg"]


def test_same_source_same_window_same_images_are_merged(tmp_path: Path) -> None:
    page1 = _image_bytes("blue")
    page2 = _image_bytes("green")
    _, output_root, _ = _run_build(
        tmp_path,
        [
            _row(
                "q_date",
                source_doc_id="doc_a",
                page_ids=["doc_a_p1", "doc_a_p2"],
                answers=["March 12"],
                answer_page_idx=0,
                images=[page1, page2],
            ),
            _row(
                "q_total",
                source_doc_id="doc_a",
                page_ids=["doc_a_p1", "doc_a_p2"],
                answers=["$42"],
                answer_page_idx=1,
                images=[page1, page2],
            ),
        ],
    )

    _, window_id = window_identity("doc_a", ["doc_a_p1", "doc_a_p2"])
    documents = read_jsonl(output_root / "documents.jsonl")
    qa_records = read_jsonl(output_root / "qa.jsonl")

    assert len(documents) == 1
    assert documents[0]["doc_id"] == window_id
    assert [record["doc_id"] for record in qa_records] == [window_id, window_id]
    assert qa_records[1]["gold_page_id"] == "doc_a_p2"


def test_same_source_different_page_windows_generate_two_documents(tmp_path: Path) -> None:
    parquet_path = _write_parquet(
        tmp_path / "fixture.parquet",
        [
            _row(
                "q1",
                source_doc_id="snbx0223",
                page_ids=["p11", "p12", "p13"],
                answers=["a"],
                answer_page_idx=1,
                images=[_image_bytes("red"), _image_bytes("green"), _image_bytes("blue")],
            ),
            _row(
                "q2",
                source_doc_id="snbx0223",
                page_ids=["p43", "p44", "p45"],
                answers=["b"],
                answer_page_idx=2,
                images=[_image_bytes("purple"), _image_bytes("yellow"), _image_bytes("cyan")],
            ),
        ],
    )

    audit = audit_parquet(parquet_path)

    assert len(audit.valid_windows) == 2
    assert len(audit.invalid_windows) == 0
    assert audit.schema_audit["doc_audit"]["same_source_multiple_window_count"] == 1
    assert audit.schema_audit["doc_audit"]["unique_document_window_count"] == 2


def test_same_source_overlapping_windows_still_generate_two_documents(tmp_path: Path) -> None:
    parquet_path = _write_parquet(
        tmp_path / "fixture.parquet",
        [
            _row(
                "q1",
                source_doc_id="doc_overlap",
                page_ids=["p1", "p2", "p3"],
                answers=["a"],
                answer_page_idx=0,
                images=[_image_bytes("red"), _image_bytes("green"), _image_bytes("blue")],
            ),
            _row(
                "q2",
                source_doc_id="doc_overlap",
                page_ids=["p3", "p4"],
                answers=["b"],
                answer_page_idx=1,
                images=[_image_bytes("blue"), _image_bytes("black")],
            ),
        ],
    )

    audit = audit_parquet(parquet_path)

    assert len(audit.valid_windows) == 2
    assert len(audit.invalid_windows) == 0


def test_same_source_same_window_different_hashes_is_rejected(tmp_path: Path) -> None:
    page1 = _image_bytes("purple")
    page2 = _image_bytes("yellow")
    bad_page2 = _image_bytes("black")
    parquet_path = _write_parquet(
        tmp_path / "fixture.parquet",
        [
            _row(
                "good1",
                source_doc_id="doc_bad",
                page_ids=["doc_bad_p1", "doc_bad_p2"],
                answers=["ok"],
                answer_page_idx=1,
                images=[page1, page2],
            ),
            _row(
                "good2",
                source_doc_id="doc_bad",
                page_ids=["doc_bad_p1", "doc_bad_p2"],
                answers=["ok2"],
                answer_page_idx=0,
                images=[page1, bad_page2],
            ),
        ],
    )

    _, window_id = window_identity("doc_bad", ["doc_bad_p1", "doc_bad_p2"])
    audit = audit_parquet(parquet_path)

    assert window_id in audit.invalid_windows
    assert any("conflicting page image sha256" in reason for reason in audit.invalid_windows[window_id])


def test_parse_row_accepts_direct_bytes_storage_and_detects_format() -> None:
    image = _image_bytes("orange")
    raw_row = {
        "questionId": "q1",
        "question": "Direct bytes?",
        "doc_id": "doc_bytes",
        "page_ids": ["doc_bytes_p1"],
        "answers": ["yes"],
        "answer_page_idx": 0,
        "data_split": "val",
        "image_1": image,
    }
    for index in range(2, 21):
        raw_row[f"image_{index}"] = None

    row = parse_row(raw_row, source_shard="fixture.parquet", include_raw_bytes=True)
    _, expected_window_id = window_identity("doc_bytes", ["doc_bytes_p1"])

    assert row.pages[0].image_format == "JPEG"
    assert row.pages[0].extension == ".jpg"
    assert row.pages[0].raw_bytes == image
    assert row.window_doc_id == expected_window_id


def test_null_trailing_images_and_native_lists_are_supported(tmp_path: Path) -> None:
    image1 = _image_bytes("pink")
    image2 = _image_bytes("white")
    parquet_path = _write_parquet(
        tmp_path / "fixture.parquet",
        [
            _row(
                "q1",
                source_doc_id="doc_lists",
                page_ids=["doc_lists_p1", "doc_lists_p2"],
                answers=["a1", "a2"],
                answer_page_idx=1,
                images=[image1, image2],
                stringify_lists=False,
            )
        ],
    )

    audit = audit_parquet(parquet_path)
    _, window_id = window_identity("doc_lists", ["doc_lists_p1", "doc_lists_p2"])

    assert window_id in audit.valid_windows
    row = audit.valid_windows[window_id].qa_rows[0]
    assert row.page_ids == ["doc_lists_p1", "doc_lists_p2"]
    assert row.answers == ["a1", "a2"]


def test_answer_page_idx_mapping_is_window_local(tmp_path: Path) -> None:
    _, output_root, _ = _run_build(
        tmp_path,
        [
            _row(
                "q1",
                source_doc_id="doc_map",
                page_ids=["doc_map_p5", "doc_map_p6", "doc_map_p7"],
                answers=["x"],
                answer_page_idx=2,
                images=[_image_bytes("red"), _image_bytes("green"), _image_bytes("blue")],
            )
        ],
    )

    qa_records = read_jsonl(output_root / "qa.jsonl")

    assert qa_records[0]["answer_page_idx"] == 2
    assert qa_records[0]["gold_page_id"] == "doc_map_p7"
    assert qa_records[0]["gold_page_ordinal"] == 3


def test_out_of_range_answer_page_idx_is_rejected(tmp_path: Path) -> None:
    parquet_path = _write_parquet(
        tmp_path / "fixture.parquet",
        [
            _row(
                "q1",
                source_doc_id="doc_bad_idx",
                page_ids=["doc_bad_idx_p1"],
                answers=["x"],
                answer_page_idx=3,
                images=[_image_bytes("red")],
            )
        ],
    )

    audit = audit_parquet(parquet_path)

    assert not audit.valid_windows
    assert audit.schema_audit["invalid_row_examples"]
    assert "answer_page_idx 3 is out of range" in audit.schema_audit["invalid_row_examples"][0]["reason"]


def test_page_ids_and_image_count_mismatch_is_reported(tmp_path: Path) -> None:
    parquet_path = _write_parquet(
        tmp_path / "fixture.parquet",
        [
            _row(
                "q1",
                source_doc_id="doc_mismatch",
                page_ids=["doc_mismatch_p1", "doc_mismatch_p2"],
                answers=["x"],
                answer_page_idx=0,
                images=[_image_bytes("red")],
            )
        ],
    )

    audit = audit_parquet(parquet_path)

    assert "does not match non-null image count" in audit.schema_audit["invalid_row_examples"][0]["reason"]


def test_multi_answer_preserved_and_paths_are_relative_posix(tmp_path: Path) -> None:
    _, output_root, _ = _run_build(
        tmp_path,
        [
            _row(
                "q1",
                source_doc_id="doc_answers",
                page_ids=["doc_answers_p1"],
                answers=["31", "(31)"],
                answer_page_idx=0,
                images=[_image_bytes("cyan")],
            )
        ],
    )

    _, window_id = window_identity("doc_answers", ["doc_answers_p1"])
    qa_records = read_jsonl(output_root / "qa.jsonl")
    manifest = json.loads((output_root / "documents" / window_id / "document_manifest.json").read_text(encoding="utf-8"))

    assert qa_records[0]["answers"] == ["31", "(31)"]
    assert manifest["pdf_path"] == f"documents/{window_id}/document.pdf"
    assert manifest["input_scope"] == INPUT_SCOPE
    assert manifest["source_doc_id"] == "doc_answers"
    assert all("\\" not in path for path in manifest["ordered_page_files"])
    assert ":" not in manifest["pdf_path"]


def test_manifest_contains_window_identity_and_pdf_page_count_matches_pages(tmp_path: Path) -> None:
    _, output_root, _ = _run_build(
        tmp_path,
        [
            _row(
                "q1",
                source_doc_id="doc_sha",
                page_ids=["doc_sha_p1", "doc_sha_p2", "doc_sha_p3"],
                answers=["x"],
                answer_page_idx=2,
                images=[_image_bytes("red"), _image_bytes("green"), _image_bytes("blue")],
            )
        ],
    )

    signature, window_id = window_identity("doc_sha", ["doc_sha_p1", "doc_sha_p2", "doc_sha_p3"])
    manifest = json.loads((output_root / "documents" / window_id / "document_manifest.json").read_text(encoding="utf-8"))
    reader = PdfReader(str(output_root / "documents" / window_id / "document.pdf"))

    assert len(reader.pages) == 3
    assert manifest["window_signature"] == signature
    assert manifest["document_instance_id"] == window_id
    assert manifest["document_is_full_source_document"] is False
    assert len(manifest["pdf_sha256"]) == 64
    assert all(len(page["sha256"]) == 64 for page in manifest["pages"])


def test_window_id_does_not_depend_on_input_row_order(tmp_path: Path) -> None:
    rows = [
        _row(
            "q1",
            source_doc_id="doc_order",
            page_ids=["doc_order_p1", "doc_order_p2"],
            answers=["a"],
            answer_page_idx=0,
            images=[_image_bytes("red"), _image_bytes("green")],
        ),
        _row(
            "q2",
            source_doc_id="doc_order",
            page_ids=["doc_order_p3"],
            answers=["b"],
            answer_page_idx=0,
            images=[_image_bytes("blue")],
        ),
    ]
    first = audit_parquet(_write_parquet(tmp_path / "first.parquet", rows))
    second = audit_parquet(_write_parquet(tmp_path / "second.parquet", list(reversed(rows))))

    assert sorted(first.valid_windows) == sorted(second.valid_windows)


def test_same_seed_produces_same_window_selection(tmp_path: Path) -> None:
    rows = [
        _row("q1", source_doc_id="doc_single", page_ids=["doc_single_p1"], answers=["a"], answer_page_idx=0, images=[_image_bytes("red")]),
        _row(
            "q2",
            source_doc_id="doc_short",
            page_ids=["doc_short_p1", "doc_short_p2", "doc_short_p3"],
            answers=["b"],
            answer_page_idx=1,
            images=[_image_bytes("green"), _image_bytes("blue"), _image_bytes("cyan")],
        ),
        _row(
            "q3",
            source_doc_id="doc_long",
            page_ids=[f"doc_long_p{i}" for i in range(1, 7)],
            answers=["c"],
            answer_page_idx=5,
            images=[_image_bytes(color) for color in ["black", "white", "pink", "purple", "yellow", "orange"]],
        ),
    ]
    parquet_path = _write_parquet(tmp_path / "fixture.parquet", rows)
    audit = audit_parquet(parquet_path)

    first = build_outputs(
        audit=audit,
        input_parquets=[parquet_path],
        output_root=tmp_path / "first",
        sample_documents=2,
        seed="same-seed",
        requested_doc_ids=[],
        validate_only=True,
        overwrite=False,
    )
    second = build_outputs(
        audit=audit,
        input_parquets=[parquet_path],
        output_root=tmp_path / "second",
        sample_documents=2,
        seed="same-seed",
        requested_doc_ids=[],
        validate_only=True,
        overwrite=False,
    )

    assert first["build_report"]["selected_window_ids"] == second["build_report"]["selected_window_ids"]


def test_validate_only_does_not_generate_document_assets(tmp_path: Path) -> None:
    _, output_root, payload = _run_build(
        tmp_path,
        [
            _row(
                "q1",
                source_doc_id="doc_validate",
                page_ids=["doc_validate_p1"],
                answers=["x"],
                answer_page_idx=0,
                images=[_image_bytes("gray")],
            )
        ],
        validate_only=True,
    )

    assert payload["status"] == "success"
    assert not output_root.exists()


def test_duplicate_image_content_warning_is_reported(tmp_path: Path) -> None:
    repeated = _image_bytes("navy")
    _, output_root, _ = _run_build(
        tmp_path,
        [
            _row(
                "q1",
                source_doc_id="doc_repeat",
                page_ids=["doc_repeat_p1", "doc_repeat_p2"],
                answers=["x"],
                answer_page_idx=0,
                images=[repeated, repeated],
            )
        ],
    )

    _, window_id = window_identity("doc_repeat", ["doc_repeat_p1", "doc_repeat_p2"])
    manifest = json.loads((output_root / "documents" / window_id / "document_manifest.json").read_text(encoding="utf-8"))

    assert manifest["warnings"] == [REPEATED_CONTENT_WARNING]


def test_explicit_doc_ids_select_requested_windows_only(tmp_path: Path) -> None:
    rows = [
        _row("q1", source_doc_id="doc_a", page_ids=["doc_a_p1"], answers=["a"], answer_page_idx=0, images=[_image_bytes("red")]),
        _row("q2", source_doc_id="doc_b", page_ids=["doc_b_p1"], answers=["b"], answer_page_idx=0, images=[_image_bytes("green")]),
    ]
    parquet_path = _write_parquet(tmp_path / "fixture.parquet", rows)
    audit = audit_parquet(parquet_path)
    _, target_window_id = window_identity("doc_b", ["doc_b_p1"])

    payload = build_outputs(
        audit=audit,
        input_parquets=[parquet_path],
        output_root=tmp_path / "out",
        sample_documents=5,
        seed="42",
        requested_doc_ids=[target_window_id],
        validate_only=True,
        overwrite=False,
    )

    assert payload["build_report"]["selected_window_ids"] == [target_window_id]


def test_same_window_across_two_shards_is_deduped_and_source_shards_are_merged(tmp_path: Path) -> None:
    shared_rows_one = [
        _row(
            "q1",
            source_doc_id="doc_multi",
            page_ids=["doc_multi_p1", "doc_multi_p2"],
            answers=["a"],
            answer_page_idx=0,
            images=[_image_bytes("red"), _image_bytes("green")],
        )
    ]
    shared_rows_two = [
        _row(
            "q2",
            source_doc_id="doc_multi",
            page_ids=["doc_multi_p1", "doc_multi_p2"],
            answers=["b"],
            answer_page_idx=1,
            images=[_image_bytes("red"), _image_bytes("green")],
        )
    ]
    shard_one = _write_parquet(tmp_path / "shard_a.parquet", shared_rows_one)
    shard_two = _write_parquet(tmp_path / "shard_b.parquet", shared_rows_two)
    audit = audit_parquet([shard_two, shard_one])
    _, window_id = window_identity("doc_multi", ["doc_multi_p1", "doc_multi_p2"])

    assert audit.schema_audit["doc_audit"]["unique_document_window_count"] == 1
    assert audit.schema_audit["doc_audit"]["duplicate_window_count"] == 1
    assert window_id in audit.valid_windows

    output_root = tmp_path / "out"
    payload = build_outputs(
        audit=audit,
        input_parquets=[shard_two, shard_one],
        output_root=output_root,
        sample_documents=5,
        seed="42",
        requested_doc_ids=[],
        validate_only=False,
        overwrite=False,
    )
    manifest = json.loads((output_root / "documents" / window_id / "document_manifest.json").read_text(encoding="utf-8"))
    qa_records = read_jsonl(output_root / "qa.jsonl")

    assert payload["status"] == "success"
    assert manifest["source_shards"] == ["shard_a.parquet", "shard_b.parquet"]
    assert len(qa_records) == 2
    assert {record["source_shard"] for record in qa_records} == {"shard_a.parquet", "shard_b.parquet"}


def test_unknown_image_format_is_rejected() -> None:
    raw_row = {
        "questionId": "q1",
        "question": "Broken?",
        "doc_id": "doc_broken",
        "page_ids": ["doc_broken_p1"],
        "answers": ["x"],
        "answer_page_idx": 0,
        "data_split": "val",
        "image_1": b"not an image",
    }
    for index in range(2, 21):
        raw_row[f"image_{index}"] = None

    with pytest.raises(BuildError, match="unknown image format"):
        parse_row(raw_row, source_shard="fixture.parquet", include_raw_bytes=False)


def test_cli_help_starts() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/build_mpdocvqa_raw_documents.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--input-parquet" in result.stdout
    assert DEFAULT_OUTPUT_ROOT in result.stdout


def test_cli_validate_only_stdout_does_not_dump_raw_image_bytes(tmp_path: Path) -> None:
    parquet_path = _write_parquet(
        tmp_path / "fixture.parquet",
        [
            _row(
                "q1",
                source_doc_id="doc_stdout",
                page_ids=["doc_stdout_p1"],
                answers=["x"],
                answer_page_idx=0,
                images=[_image_bytes("lime")],
            )
        ],
    )
    root = Path(__file__).resolve().parents[1]
    output_root = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_mpdocvqa_raw_documents.py",
            "--input-parquet",
            str(parquet_path),
            "--output-root",
            str(output_root),
            "--validate-only",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert '"raw_bytes"' not in result.stdout
    assert "JFIF" not in result.stdout


def test_output_root_requires_overwrite_for_existing_assets(tmp_path: Path) -> None:
    rows = [
        _row("q1", source_doc_id="doc_a", page_ids=["doc_a_p1"], answers=["a"], answer_page_idx=0, images=[_image_bytes("red")]),
    ]
    parquet_path = _write_parquet(tmp_path / "fixture.parquet", rows)
    audit = audit_parquet(parquet_path)
    build_outputs(
        audit=audit,
        input_parquets=[parquet_path],
        output_root=tmp_path / "out",
        sample_documents=5,
        seed="42",
        requested_doc_ids=[],
        validate_only=False,
        overwrite=False,
    )

    with pytest.raises(BuildError, match="output root already exists"):
        build_outputs(
            audit=audit,
            input_parquets=[parquet_path],
            output_root=tmp_path / "out",
            sample_documents=5,
            seed="42",
            requested_doc_ids=[],
            validate_only=False,
            overwrite=False,
        )

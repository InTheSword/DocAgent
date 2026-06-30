from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image

from docagent.ingestion.hashing import sha256_file
from docagent.storage.db import connect
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_phase4b_mpdocvqa_ingestion import (
    _looks_like_local_absolute_path,
    _scan_json_artifacts,
    parse_args,
    run_phase4b_ingestion,
)


TARGET_DOC_ID = "hqvw0217__bc714cf4181a5632"


class FakeMinerUApi:
    def __init__(
        self,
        *,
        page_indices: list[int],
        raw_type: str = "text",
        manifest_payload: dict[str, Any] | None = None,
        fail: bool = False,
    ) -> None:
        self.page_indices = page_indices
        self.raw_type = raw_type
        self.manifest_payload = manifest_payload
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def run(self, *, file_path: Path, data_id: str, output_dir: Path) -> dict[str, Any]:
        self.calls.append({"file_path": file_path, "data_id": data_id, "output_dir": output_dir})
        if self.fail:
            raise RuntimeError("API failed Authorization: Bearer secret-token https://download.example/signed.zip")
        output_dir.mkdir(parents=True, exist_ok=True)
        records = [
            {
                "type": self.raw_type,
                "page_idx": page_idx,
                "text": f"content for page {page_idx + 1}",
                "bbox": [0, 0, 10, 10],
            }
            for page_idx in self.page_indices
        ]
        (output_dir / "sample_content_list.json").write_text(json.dumps(records), encoding="utf-8")
        layout = {
            "_backend": "fake-live-api",
            "_version_name": "test",
            "_ocr_enable": False,
            "_vlm_ocr_enable": False,
            "pdf_info": [{} for _ in self.page_indices],
        }
        (output_dir / "layout.json").write_text(json.dumps(layout), encoding="utf-8")
        if self.manifest_payload is not None:
            (output_dir / "mineru_api_manifest.json").write_text(
                json.dumps(self.manifest_payload, ensure_ascii=False),
                encoding="utf-8",
            )
        return {"status": "success"}


def _make_pdf(path: Path, page_count: int) -> None:
    images = [Image.new("RGB", (36, 24), color=(index * 30 % 255, 40, 120)) for index in range(page_count)]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        first, *rest = images
        first.save(path, format="PDF", save_all=bool(rest), append_images=rest)
    finally:
        for image in images:
            image.close()


def _sample_root(
    tmp_path: Path,
    *,
    doc_id: str = TARGET_DOC_ID,
    source_doc_id: str = "hqvw0217",
    page_count: int = 1,
    qa_records: list[dict[str, Any]] | None = None,
) -> Path:
    root = tmp_path / "sample"
    doc_dir = root / "documents" / doc_id
    pdf_path = doc_dir / "document.pdf"
    _make_pdf(pdf_path, page_count)
    ordered_page_ids = [f"{source_doc_id}_p{index}" for index in range(1, page_count + 1)]
    manifest = {
        "builder_version": "phase4a-mpdocvqa-raw-v2",
        "doc_id": doc_id,
        "document_instance_id": doc_id,
        "source_doc_id": source_doc_id,
        "window_signature": "fixture",
        "input_scope": "page_window",
        "document_is_full_source_document": False,
        "page_count": page_count,
        "ordered_page_ids": ordered_page_ids,
        "pages": [
            {
                "page_id": page_id,
                "page_ordinal": ordinal,
                "page_file": f"documents/{doc_id}/pages/{ordinal:04d}.jpg",
                "sha256": f"{ordinal:064d}"[-64:],
            }
            for ordinal, page_id in enumerate(ordered_page_ids, start=1)
        ],
        "pdf_path": f"documents/{doc_id}/document.pdf",
        "pdf_sha256": sha256_file(pdf_path),
        "qa_count": 1 if qa_records is None else len(qa_records),
        "warnings": [],
    }
    (doc_dir / "document_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    if qa_records is None:
        qa_records = [
            {
                "qid": "q1",
                "raw_question_id": "q1",
                "doc_id": doc_id,
                "source_doc_id": source_doc_id,
                "question": "What is on the page?",
                "answers": ["content"],
                "answer_page_idx": 0,
                "raw_answer_page_idx": 0,
                "gold_page_id": ordered_page_ids[0],
                "gold_page_ordinal": 1,
                "source_split": "val",
                "source_shard": "fixture.parquet",
            }
        ]
    write_jsonl(root / "qa.jsonl", qa_records)
    return root


def _args(*items: str):
    return parse_args(
        [
            "--sample-root",
            items[0],
            "--doc-id",
            items[1],
            "--output-root",
            items[2],
            *items[3:],
        ]
    )


def test_validate_only_checks_assets_without_api(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    sample = _sample_root(tmp_path)
    fake = FakeMinerUApi(page_indices=[0])
    args = _args(str(sample), TARGET_DOC_ID, str(tmp_path / "out"), "--live-api", "--validate-only")

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: fake)

    assert payload["status"] == "success"
    assert payload["validate_only"] is True
    assert payload["expected_page_count"] == 1
    assert payload["pdf_page_count"] == 1
    assert payload["qa_count"] == 1
    assert fake.calls == []
    assert not (tmp_path / "out").exists()


def test_validate_only_accepts_mineru_env_file_without_global_env(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    env_file = tmp_path / "mineru.env"
    env_file.write_text("MINERU_TOKEN=file-secret-token\n", encoding="utf-8")
    sample = _sample_root(tmp_path)
    fake = FakeMinerUApi(page_indices=[0])
    args = _args(
        str(sample),
        TARGET_DOC_ID,
        str(tmp_path / "out"),
        "--live-api",
        "--validate-only",
        "--mineru-env-file",
        str(env_file),
    )

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: fake)

    assert payload["status"] == "success"
    assert payload["mineru_token_set"] is True
    assert fake.calls == []
    assert not (tmp_path / "out").exists()


def test_validate_only_accepts_api_token_key_from_mineru_env_file(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MINERU_TOKEN", raising=False)
    env_file = tmp_path / "mineru.env"
    env_file.write_text("API_TOKEN=file-secret-token\n", encoding="utf-8")
    sample = _sample_root(tmp_path)
    fake = FakeMinerUApi(page_indices=[0])
    args = _args(
        str(sample),
        TARGET_DOC_ID,
        str(tmp_path / "out"),
        "--live-api",
        "--validate-only",
        "--mineru-env-file",
        str(env_file),
    )

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: fake)

    assert payload["status"] == "success"
    assert payload["mineru_token_set"] is True
    assert fake.calls == []
    assert not (tmp_path / "out").exists()


def test_single_page_fake_live_ingestion_writes_acceptance_and_mapping(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    sample = _sample_root(tmp_path)
    fake = FakeMinerUApi(page_indices=[0])
    args = _args(str(sample), TARGET_DOC_ID, str(tmp_path / "out"), "--live-api")

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: fake)

    work_dir = tmp_path / "out" / TARGET_DOC_ID
    qa_mapping = read_jsonl(work_dir / "qa_page_mapping.jsonl")
    page_mapping = read_jsonl(work_dir / "page_identity_mapping.jsonl")
    report = json.loads((work_dir / "acceptance_report.json").read_text(encoding="utf-8"))

    assert payload["status"] == "success"
    assert report["expected_page_count"] == 1
    assert report["parsed_page_count"] == 1
    assert report["page_document_count"] == 1
    assert report["gold_page_mapping_valid_count"] == 1
    assert report["gold_page_mapping_invalid_count"] == 0
    assert report["missing_image_reference_count"] == 0
    assert report["persisted_absolute_path_count"] == 0
    assert report["no_mock_fallback"] is True
    assert qa_mapping[0]["parsed_page_number"] == 1
    assert qa_mapping[0]["page_aggregate_id"] == page_mapping[0]["page_aggregate_id"]
    assert qa_mapping[0]["child_block_ids"]
    assert all("\\" not in value and ":" not in value for value in report["artifact_paths"].values())


def test_multi_page_gold_ordinal_mapping(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    doc_id = "rzbj0037__e09400dd12a9c549"
    source_doc_id = "rzbj0037"
    page_ids = [f"{source_doc_id}_p{index}" for index in range(1, 5)]
    qa_records = [
        {
            "qid": "q_first",
            "doc_id": doc_id,
            "source_doc_id": source_doc_id,
            "question": "first?",
            "answers": ["one"],
            "answer_page_idx": 0,
            "gold_page_id": page_ids[0],
            "gold_page_ordinal": 1,
        },
        {
            "qid": "q_last",
            "doc_id": doc_id,
            "source_doc_id": source_doc_id,
            "question": "last?",
            "answers": ["four"],
            "answer_page_idx": 3,
            "gold_page_id": page_ids[3],
            "gold_page_ordinal": 4,
        },
    ]
    sample = _sample_root(tmp_path, doc_id=doc_id, source_doc_id=source_doc_id, page_count=4, qa_records=qa_records)
    fake = FakeMinerUApi(page_indices=[0, 1, 2, 3])
    args = _args(str(sample), doc_id, str(tmp_path / "out"), "--live-api")

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: fake)
    rows = read_jsonl(tmp_path / "out" / doc_id / "qa_page_mapping.jsonl")

    assert payload["status"] == "success"
    assert [row["parsed_page_number"] for row in rows] == [1, 4]
    assert [row["mapping_valid"] for row in rows] == [True, True]
    assert all(row["child_block_ids"] for row in rows)


def test_answer_page_idx_gold_ordinal_mismatch_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    sample = _sample_root(
        tmp_path,
        page_count=2,
        qa_records=[
            {
                "qid": "bad",
                "doc_id": TARGET_DOC_ID,
                "source_doc_id": "hqvw0217",
                "question": "bad?",
                "answers": ["x"],
                "answer_page_idx": 0,
                "gold_page_id": "hqvw0217_p1",
                "gold_page_ordinal": 2,
            }
        ],
    )
    fake = FakeMinerUApi(page_indices=[0, 1])
    args = _args(str(sample), TARGET_DOC_ID, str(tmp_path / "out"), "--live-api")

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: fake)

    assert payload["status"] == "failed"
    assert "inconsistent" in payload["exception"]
    assert fake.calls == []


def test_gold_ordinal_out_of_bounds_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    sample = _sample_root(
        tmp_path,
        qa_records=[
            {
                "qid": "bad",
                "doc_id": TARGET_DOC_ID,
                "source_doc_id": "hqvw0217",
                "question": "bad?",
                "answers": ["x"],
                "answer_page_idx": 0,
                "gold_page_id": "hqvw0217_p1",
                "gold_page_ordinal": 3,
            }
        ],
    )
    args = _args(str(sample), TARGET_DOC_ID, str(tmp_path / "out"), "--live-api")

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: FakeMinerUApi(page_indices=[0]))

    assert payload["status"] == "failed"
    assert "out of bounds" in payload["exception"]


def test_qa_wrong_doc_id_is_rejected(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    sample = _sample_root(
        tmp_path,
        qa_records=[
            {
                "qid": "wrong",
                "doc_id": "other_doc",
                "source_doc_id": "hqvw0217",
                "question": "wrong?",
                "answers": ["x"],
                "answer_page_idx": 0,
                "gold_page_id": "hqvw0217_p1",
                "gold_page_ordinal": 1,
            }
        ],
    )
    args = _args(str(sample), TARGET_DOC_ID, str(tmp_path / "out"), "--live-api")

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: FakeMinerUApi(page_indices=[0]))

    assert payload["status"] == "failed"
    assert "no records" in payload["exception"]


def test_parsed_and_page_document_count_mismatch_fails(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    sample = _sample_root(tmp_path, page_count=2)
    fake = FakeMinerUApi(page_indices=[0])
    args = _args(str(sample), TARGET_DOC_ID, str(tmp_path / "out"), "--live-api")

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: fake)

    assert payload["status"] == "failed"
    assert "parsed_page_count_mismatch" in payload["failures"]
    assert "page_document_count_mismatch" in payload["failures"]


def test_missing_page_aggregate_fails_even_when_page_count_matches(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    sample = _sample_root(tmp_path, page_count=2)
    fake = FakeMinerUApi(page_indices=[0, 2])
    args = _args(str(sample), TARGET_DOC_ID, str(tmp_path / "out"), "--live-api")

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: fake)
    rows = read_jsonl(tmp_path / "out" / TARGET_DOC_ID / "page_identity_mapping.jsonl")

    assert payload["status"] == "failed"
    assert any("missing_page_aggregate" in row["mapping_errors"] for row in rows)
    assert "page_identity_mapping_invalid" in payload["failures"]


def test_structure_quality_failed_blocks_acceptance(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    sample = _sample_root(tmp_path)
    fake = FakeMinerUApi(page_indices=[])
    args = _args(str(sample), TARGET_DOC_ID, str(tmp_path / "out"), "--live-api")

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: fake)

    assert payload["status"] == "failed"
    assert "structure_quality_failed" in payload["failures"]


def test_structure_quality_passed_with_warnings_can_pass(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    sample = _sample_root(tmp_path)
    fake = FakeMinerUApi(page_indices=[0], raw_type="captionish_unknown")
    args = _args(str(sample), TARGET_DOC_ID, str(tmp_path / "out"), "--live-api")

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: fake)

    assert payload["status"] == "success"
    assert payload["structure_quality_status"] == "passed_with_warnings"
    assert "unknown_raw_types_present" in payload["warnings"]


def test_json_sqlite_path_scan_ignores_ocr_latex_escapes(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    write_jsonl(
        work_dir / "evidence_blocks.jsonl",
        [
            {"block_id": "jsonl-text-1", "block_type": "text", "text": "/jc"},
            {"block_id": "jsonl-text-2", "block_type": "text", "text": "$34.20"},
        ],
    )
    sqlite_path = work_dir / "docagent.sqlite"
    conn = connect(sqlite_path)
    try:
        conn.execute(
            """
            INSERT INTO evidence_blocks(block_id, doc_id, page_id, block_type, text, payload_json, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "b1",
                "doc",
                1,
                "text",
                r"for \$34.20",
                json.dumps(
                    {
                        "text": r"Meetings \$34.20",
                        "ocr_short_slash_token": "/jc",
                        "json_encoded": r"\\$34.20",
                        "semantic_backslash": r"ordinary \ marker",
                    }
                ),
                json.dumps({"note": r"Many thanks ... \$34.20"}),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    absolute_hits, sensitive_hits = _scan_json_artifacts(work_dir, sqlite_path)
    with sqlite3.connect(sqlite_path) as verify_conn:
        stored_payload = verify_conn.execute(
            "SELECT payload_json FROM evidence_blocks WHERE block_id = 'b1'"
        ).fetchone()[0]

    assert absolute_hits == []
    assert sensitive_hits == []
    assert r"\\$34.20" in stored_payload
    assert json.loads(stored_payload)["ocr_short_slash_token"] == "/jc"


def test_json_sqlite_path_scan_detects_real_absolute_paths_with_compact_examples(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    sqlite_path = work_dir / "docagent.sqlite"
    conn = connect(sqlite_path)
    try:
        conn.execute(
            """
            INSERT INTO evidence_blocks(block_id, doc_id, page_id, block_type, text, payload_json, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "b1",
                "doc",
                1,
                "text",
                "content",
                json.dumps(
                    {
                        "posix": "/root/data/file.pdf",
                        "image_path": "/root/autodl-tmp/images/page.png",
                        "win_c": r"C:\Users\name\file.pdf",
                        "win_d": r"D:\Projects\docagent\file.pdf",
                    }
                ),
                json.dumps({"unc": r"\\server\share\file.pdf"}),
            ),
        )
        conn.execute(
            """
            INSERT INTO document_indexes(doc_id, index_type, model_id, artifact_path, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("doc", "bm25", "", "indexes/bm25.json", json.dumps({"source": "/root/metadata/file.json"})),
        )
        conn.commit()
    finally:
        conn.close()

    absolute_hits, _ = _scan_json_artifacts(work_dir, sqlite_path)

    reasons = {hit["reason"] for hit in absolute_hits}
    assert {
        "posix_absolute_path",
        "windows_drive_absolute_path",
        "unc_absolute_path",
    }.issubset(reasons)
    assert all(set(hit) == {"where", "reason", "value_preview"} for hit in absolute_hits)
    assert all(len(hit["value_preview"]) <= 160 for hit in absolute_hits)
    assert not any("payload_json" in hit["value_preview"] for hit in absolute_hits)
    assert any(hit["where"].endswith(".image_path") for hit in absolute_hits)


def test_invalid_json_sqlite_path_scan_uses_safe_string_fallback(tmp_path: Path) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    sqlite_path = work_dir / "docagent.sqlite"
    conn = connect(sqlite_path)
    try:
        conn.execute(
            """
            INSERT INTO evidence_blocks(block_id, doc_id, page_id, block_type, text, payload_json, metadata_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("b1", "doc", 1, "text", "content", r"C:\Users\name\file.pdf", None),
        )
        conn.commit()
    finally:
        conn.close()

    absolute_hits, _ = _scan_json_artifacts(work_dir, sqlite_path)

    assert len(absolute_hits) == 1
    assert absolute_hits[0]["reason"] == "windows_drive_absolute_path"
    assert absolute_hits[0]["value_preview"] == r"C:\Users\name\file.pdf"


def test_absolute_path_detection_is_platform_independent() -> None:
    assert _looks_like_local_absolute_path("/root/data/file.pdf")
    assert _looks_like_local_absolute_path("/mnt/data/file.pdf")
    assert _looks_like_local_absolute_path("/home/user/file.pdf")
    assert _looks_like_local_absolute_path("/tmp/file.pdf")
    assert _looks_like_local_absolute_path("/var/tmp/file.pdf")
    assert _looks_like_local_absolute_path(r"C:\Users\name\file.pdf")
    assert _looks_like_local_absolute_path(r"D:\Projects\docagent\file.pdf")
    assert _looks_like_local_absolute_path(r"\\server\share\file.pdf")
    assert _looks_like_local_absolute_path("file:///root/data/file.pdf")
    assert not _looks_like_local_absolute_path("/jc")
    assert not _looks_like_local_absolute_path(r"\$34.20")
    assert not _looks_like_local_absolute_path(r"\\$34.20")
    assert not _looks_like_local_absolute_path(r"ordinary \ marker")
    assert not _looks_like_local_absolute_path(r"price C:\Users\name\file.pdf mentioned in text")


def test_absolute_paths_tokens_and_signed_urls_are_not_persisted(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    sample = _sample_root(tmp_path)
    fake = FakeMinerUApi(
        page_indices=[0],
        manifest_payload={
            "status": "success",
            "source_file": "C:\\secret\\document.pdf",
            "Authorization": "Bearer secret-token",
            "batch_result": {"extract_result": [{"full_zip_url": "https://download.example/signed.zip?token=abc"}]},
        },
    )
    args = _args(str(sample), TARGET_DOC_ID, str(tmp_path / "out"), "--live-api")

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: fake)
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (tmp_path / "out" / TARGET_DOC_ID).rglob("*.json")
    )

    assert payload["status"] == "success"
    assert payload["persisted_absolute_path_count"] == 0
    assert "secret-token" not in text
    assert "download.example" not in text
    assert "Authorization" not in text
    assert "C:\\secret" not in text


def test_revalidate_existing_does_not_call_api_and_clears_latex_escape_false_positive(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    sample = _sample_root(tmp_path)
    fake = FakeMinerUApi(page_indices=[0])
    out = tmp_path / "out"
    args = _args(str(sample), TARGET_DOC_ID, str(out), "--live-api")
    initial = run_phase4b_ingestion(args, api_client_factory=lambda: fake)
    assert initial["status"] == "success"
    assert initial["gate"] == "Gate 1"

    sqlite_path = out / TARGET_DOC_ID / "docagent.sqlite"
    with sqlite3.connect(sqlite_path) as conn:
        block_id, payload_json = conn.execute(
            "SELECT block_id, payload_json FROM evidence_blocks WHERE block_type = 'text' LIMIT 1"
        ).fetchone()
        payload = json.loads(payload_json)
        payload["text"] = r"for \$34.20"
        conn.execute(
            "UPDATE evidence_blocks SET text = ?, payload_json = ? WHERE block_id = ?",
            (payload["text"], json.dumps(payload, ensure_ascii=False), block_id),
        )
        conn.commit()
    original_payload = sqlite_path.read_bytes()

    def fail_if_called() -> FakeMinerUApi:
        raise AssertionError("revalidate-existing must not call MinerU client")

    revalidate_args = _args(
        str(sample),
        TARGET_DOC_ID,
        str(out),
        "--gate",
        "Gate 2",
        "--revalidate-existing",
    )
    payload = run_phase4b_ingestion(revalidate_args, api_client_factory=fail_if_called)

    assert payload["status"] == "success"
    assert payload["gate"] == "Gate 2"
    assert payload["revalidate_existing"] is True
    assert payload["persisted_absolute_path_count"] == 0
    assert payload["no_mock_fallback"] is True
    assert sqlite_path.read_bytes() == original_payload
    with sqlite3.connect(sqlite_path) as conn:
        stored_text, stored_payload = conn.execute(
            "SELECT text, payload_json FROM evidence_blocks WHERE block_id = ?",
            (block_id,),
        ).fetchone()
    assert stored_text == r"for \$34.20"
    assert json.loads(stored_payload)["text"] == r"for \$34.20"


def test_skip_existing_revalidates_when_current_sample_qa_count_changes(tmp_path: Path) -> None:
    sample = _sample_root(tmp_path)
    fake = FakeMinerUApi(page_indices=[0])
    out = tmp_path / "out"
    args = _args(str(sample), TARGET_DOC_ID, str(out), "--live-api")
    initial = run_phase4b_ingestion(args, api_client_factory=lambda: fake)
    assert initial["status"] == "success"
    assert initial["qa_count"] == 1

    qa_path = sample / "qa.jsonl"
    records = read_jsonl(qa_path)
    records.append({**records[0], "qid": "q2", "raw_question_id": "q2", "question": "What else is on the page?"})
    write_jsonl(qa_path, records)
    manifest_path = sample / "documents" / TARGET_DOC_ID / "document_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["qa_count"] = 2
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")

    def fail_if_called() -> FakeMinerUApi:
        raise AssertionError("stale skip-existing must revalidate existing artifacts, not call MinerU")

    skip_args = _args(str(sample), TARGET_DOC_ID, str(out), "--gate", "Gate 4", "--skip-existing")
    payload = run_phase4b_ingestion(skip_args, api_client_factory=fail_if_called)
    mapping_rows = read_jsonl(out / TARGET_DOC_ID / "qa_page_mapping.jsonl")

    assert payload["status"] == "success"
    assert payload["gate"] == "Gate 4"
    assert payload["qa_count"] == 2
    assert payload["skip_existing"] is False
    assert payload["revalidated_due_to_existing_mismatch"] is True
    assert "acceptance_report_qa_count_mismatch" in payload["existing_artifact_check"]["failures"]
    assert "qa_page_mapping_count_mismatch" in payload["existing_artifact_check"]["failures"]
    assert len(mapping_rows) == 2


def test_skip_existing_reuses_current_artifact_without_api(tmp_path: Path) -> None:
    sample = _sample_root(tmp_path)
    fake = FakeMinerUApi(page_indices=[0])
    out = tmp_path / "out"
    args = _args(str(sample), TARGET_DOC_ID, str(out), "--live-api")
    initial = run_phase4b_ingestion(args, api_client_factory=lambda: fake)
    assert initial["status"] == "success"

    def fail_if_called() -> FakeMinerUApi:
        raise AssertionError("current skip-existing must not call MinerU")

    skip_args = _args(str(sample), TARGET_DOC_ID, str(out), "--gate", "Gate 4", "--skip-existing")
    payload = run_phase4b_ingestion(skip_args, api_client_factory=fail_if_called)

    assert payload["status"] == "success"
    assert payload["skip_existing"] is True
    assert payload["existing_artifact_check"]["current"] is True


def test_api_exception_writes_compact_sanitized_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("MINERU_TOKEN", "secret-token")
    sample = _sample_root(tmp_path)
    fake = FakeMinerUApi(page_indices=[0], fail=True)
    args = _args(str(sample), TARGET_DOC_ID, str(tmp_path / "out"), "--live-api")

    payload = run_phase4b_ingestion(args, api_client_factory=lambda: fake)
    failure_log = tmp_path / "out" / TARGET_DOC_ID / "logs" / "failure.json"
    log_text = failure_log.read_text(encoding="utf-8")

    assert payload["status"] == "failed"
    assert payload["log_path"] == "logs/failure.json"
    assert "download.example" not in json.dumps(payload)
    assert "secret-token" not in json.dumps(payload)
    assert "download.example" not in log_text
    assert "secret-token" not in log_text


def test_cli_help_starts() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/run_phase4b_mpdocvqa_ingestion.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--sample-root" in result.stdout
    assert "--validate-only" in result.stdout
    assert "--skip-existing" in result.stdout

from __future__ import annotations

import json
from pathlib import Path

from docagent.ingestion.document_registry import DocumentRecord
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.audit_answer_prompt_media_metadata import audit_answer_prompt_media_metadata


def test_audit_answer_prompt_media_metadata_tracks_safe_media_fields(tmp_path: Path) -> None:
    evidence_run = tmp_path / "evidence_run"
    document_root = tmp_path / "documents"
    db_path = tmp_path / "docagent.db"
    evidence_run.mkdir()
    document_dir = document_root / "ingested_doc"
    document_dir.mkdir(parents=True)
    write_jsonl(
        evidence_run / "documents.jsonl",
        [{"doc_id": "sample_doc", "ingested_doc_id": "ingested_doc", "pass_fail": "passed"}],
    )
    (evidence_run / "summary.json").write_text(
        json.dumps({"document_root": str(document_root), "db_path": str(db_path)}),
        encoding="utf-8",
    )
    remote_table_image = "https://mineru.example/signed/table.png"
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        repository.upsert_document(
            DocumentRecord(
                doc_id="ingested_doc",
                sha256="c" * 64,
                original_name="document.pdf",
                mime_type="application/pdf",
                file_size=10,
                file_path=str(document_dir / "source" / "original.pdf"),
                document_dir=str(document_dir),
                page_count=1,
                parser_backend="mineru_api",
                parse_status="parsed",
                index_status="not_started",
            )
        )
        repository.save_evidence_blocks(
            [
                EvidenceBlock(
                    doc_id="ingested_doc",
                    block_id="table1",
                    block_type="table",
                    text="Budget Estimate $100,000",
                    table_html="<table><tr><td>Budget Estimate</td><td>$100,000</td></tr></table>",
                    image_path=remote_table_image,
                    page_id=1,
                    location=EvidenceLocation(page=1, block_id="table1"),
                    metadata={"table_caption": ["Budget table"], "resource_key": "table_image_url"},
                ),
                EvidenceBlock(
                    doc_id="ingested_doc",
                    block_id="image1",
                    block_type="image",
                    text="Revenue chart says 9.9",
                    image_path="mineru/images/chart.png",
                    page_id=1,
                    location=EvidenceLocation(page=1, block_id="image1"),
                    metadata={"image_caption": "Revenue chart"},
                ),
                EvidenceBlock(
                    doc_id="ingested_doc",
                    block_id="image_abs",
                    block_type="image",
                    text="Absolute path should not be exposed",
                    image_path="C:\\private\\chart.png",
                    page_id=1,
                    location=EvidenceLocation(page=1, block_id="image_abs"),
                ),
                EvidenceBlock(
                    doc_id="ingested_doc",
                    block_id="page1",
                    block_type="page",
                    text="Page aggregate",
                    page_id=1,
                    location=EvidenceLocation(page=1, block_id="page1"),
                ),
            ]
        )
    finally:
        conn.close()

    result = audit_answer_prompt_media_metadata(
        evidence_run_dir=evidence_run,
        output_root=tmp_path / "audit",
        run_id="prompt_media",
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["contract_status"] == "passed"
    assert result["media_block_count"] == 3
    assert result["prompt_eligible_media_block_count"] == 3
    assert result["context_media_item_count"] == 2
    assert result["formatted_media_header_count"] == 2
    assert result["remote_resource_redacted_count"] == 1
    assert result["relative_image_path_count"] == 1
    assert result["absolute_resource_suppressed_count"] == 1
    assert result["raw_remote_url_leak_count"] == 0
    assert result["media_missing_in_context_count"] == 0
    rows = read_jsonl(tmp_path / "audit" / "prompt_media" / "rows.jsonl")
    media_by_id = {item["block_id"]: item["media"] for item in rows[0]["sample_context_media"]}
    assert media_by_id["table1"]["image_path"] == "<remote_image_resource>"
    assert media_by_id["image1"]["image_path"] == "mineru/images/chart.png"
    assert remote_table_image not in json.dumps(rows[0], ensure_ascii=False)
    assert "mineru/images/chart.png" in json.dumps(rows[0], ensure_ascii=False)
    assert (tmp_path / "sync" / "prompt_media" / "summary.json").is_file()

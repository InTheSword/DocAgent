from __future__ import annotations

import json
from pathlib import Path

from docagent.ingestion.document_registry import DocumentRecord
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.audit_mineru_evidence_artifacts import audit_mineru_evidence_artifacts


def test_audit_mineru_evidence_artifacts_separates_raw_and_db_text(tmp_path: Path) -> None:
    evidence_run = tmp_path / "evidence_run"
    document_root = tmp_path / "documents"
    db_path = tmp_path / "docagent.db"
    evidence_run.mkdir()
    mineru_dir = document_root / "ingested_doc" / "mineru"
    mineru_dir.mkdir(parents=True)
    (mineru_dir / "mineru_api_manifest.json").write_text(
        json.dumps(
            {
                "status": "success",
                "parse_options": {"model_version": "vlm", "is_ocr": True},
                "submission_payload": {"files": [{"name": "document.pdf", "data_id": "sample_doc", "is_ocr": True}]},
            }
        ),
        encoding="utf-8",
    )
    (mineru_dir / "sample_content_list.json").write_text(
        json.dumps(
            [
                {"type": "text", "page_idx": 0, "text": "Cover page"},
                {"type": "text", "page_idx": 1, "text": "Budget Estimate $100,000"},
            ]
        ),
        encoding="utf-8",
    )
    (mineru_dir / "full.md").write_text("Budget Estimate $100,000", encoding="utf-8")
    write_jsonl(
        evidence_run / "documents.jsonl",
        [{"doc_id": "sample_doc", "ingested_doc_id": "ingested_doc", "pass_fail": "passed"}],
    )
    write_jsonl(
        evidence_run / "sample_evidence_manifest.jsonl",
        [
            {
                "sample_id": "q1",
                "doc_id": "sample_doc",
                "ingested_doc_id": "ingested_doc",
                "question": "What is the budget estimate?",
                "answers": ["$100,000"],
                "gold_pages": [2],
            }
        ],
    )
    (evidence_run / "summary.json").write_text(
        json.dumps({"document_root": str(document_root), "db_path": str(db_path)}),
        encoding="utf-8",
    )
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        repository.upsert_document(
            DocumentRecord(
                doc_id="ingested_doc",
                sha256="a" * 64,
                original_name="document.pdf",
                mime_type="application/pdf",
                file_size=10,
                file_path=str(document_root / "ingested_doc" / "source" / "original.pdf"),
                document_dir=str(document_root / "ingested_doc"),
                page_count=2,
                parser_backend="mineru_api",
                parse_status="parsed",
                index_status="not_started",
            )
        )
        repository.save_evidence_blocks(
            [
                EvidenceBlock(
                    doc_id="ingested_doc",
                    block_id="ingested_doc_p002_page",
                    block_type="page",
                    text="Budget Estimate missing after conversion",
                    page_id=2,
                    location=EvidenceLocation(page=2, block_id="ingested_doc_p002_page"),
                )
            ]
        )
    finally:
        conn.close()

    result = audit_mineru_evidence_artifacts(
        evidence_run_dir=evidence_run,
        output_root=tmp_path / "audit",
        run_id="audit_run",
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["row_count"] == 1
    assert result["manifest_ocr_enabled_or_requested_rate"] == 1.0
    assert result["ordinary_gold_page_answer_hit_rate"] == 1.0
    assert result["markdown_answer_hit_rate"] == 1.0
    assert result["db_gold_page_answer_hit_rate"] == 0.0
    rows = read_jsonl(tmp_path / "audit" / "audit_run" / "rows.jsonl")
    assert rows[0]["diagnostic_bucket"] == "raw_content_list_gold_page_has_answer_but_db_missing"
    assert (tmp_path / "sync" / "audit_run" / "summary.json").is_file()

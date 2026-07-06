from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from docagent.ingestion.document_registry import DocumentRecord
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository


ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> tuple[dict, str]:
    cli_args = list(args)
    if "--execution-profile" not in cli_args:
        cli_args = ["--execution-profile", "self_test", *cli_args]
    completed = subprocess.run(
        [sys.executable, "scripts/docagent_cli.py", *cli_args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    output = completed.stdout.strip()
    assert output.startswith("{")
    assert output.endswith("}")
    return json.loads(output), output


def _paths(tmp_path: Path) -> tuple[Path, Path, Path]:
    return tmp_path / "docagent.db", tmp_path / "documents", tmp_path / "cli"


def test_file_not_found_returns_structured_error(tmp_path: Path) -> None:
    db_path, document_root, output_dir = _paths(tmp_path)

    payload, raw = _run_cli(
        "--db-path",
        str(db_path),
        "--document-root",
        str(document_root),
        "--file",
        str(tmp_path / "missing.txt"),
        "--question",
        "How many pages are in this document?",
        "--output-dir",
        str(output_dir),
    )

    assert raw.count("{") >= 1
    assert payload["status"] == "error"
    assert payload["error"]["type"] == "file_not_found"
    assert payload["source"]["type"] == "file"
    assert payload["source"]["was_ingested"] is False
    assert payload["source"]["reused_existing"] is False
    assert Path(payload["artifact_dir"], "result.json").is_file()


def test_file_new_text_ingestion_routes_to_document_statistics(tmp_path: Path) -> None:
    db_path, document_root, output_dir = _paths(tmp_path)
    source = tmp_path / "memo.txt"
    source.write_text("Project memo\nThis document has one page.", encoding="utf-8")

    payload, raw = _run_cli(
        "--db-path",
        str(db_path),
        "--document-root",
        str(document_root),
        "--file",
        str(source),
        "--question",
        "How many pages are in this document?",
        "--output-dir",
        str(output_dir),
    )

    assert raw.startswith("{") and raw.endswith("}")
    assert payload["status"] == "success"
    assert payload["doc_id"]
    assert payload["source"]["was_ingested"] is True
    assert payload["source"]["reused_existing"] is False
    assert payload["source"]["ingestion_status"] == "parsed"
    assert payload["task_type"] == "document_statistics"
    assert payload["tools_used"] == ["count_pages"]
    assert "1 pages" in payload["answer"]
    for name in ("result.json", "summary.json", "router_plan.json", "trace.json"):
        assert Path(payload["artifact_dir"], name).is_file()
    summary = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["used_file_ingestion"] is True
    assert summary["reused_existing_document"] is False
    assert summary["ingestion_status"] == "parsed"
    assert summary["used_external_api"] is False
    assert summary["used_vlm"] is False
    assert summary["used_training"] is False
    assert summary["used_full_e2e"] is False


def test_file_second_run_reuses_existing_doc_id(tmp_path: Path) -> None:
    db_path, document_root, output_dir = _paths(tmp_path)
    source = tmp_path / "memo.txt"
    source.write_text("Project memo\nThis document has one page.", encoding="utf-8")

    first, _ = _run_cli(
        "--db-path",
        str(db_path),
        "--document-root",
        str(document_root),
        "--file",
        str(source),
        "--question",
        "How many pages are in this document?",
        "--output-dir",
        str(output_dir),
    )
    second, _ = _run_cli(
        "--db-path",
        str(db_path),
        "--document-root",
        str(document_root),
        "--file",
        str(source),
        "--question",
        "How many pages are in this document?",
        "--output-dir",
        str(output_dir),
    )

    assert second["status"] == "success"
    assert second["doc_id"] == first["doc_id"]
    assert second["source"]["was_ingested"] is False
    assert second["source"]["reused_existing"] is True
    assert "file_reused_existing_doc_id" in second["warnings"]
    summary = json.loads(Path(second["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["used_file_ingestion"] is False
    assert summary["reused_existing_document"] is True
    assert summary["ingestion_status"] == "reused_existing"


def test_file_new_text_ingestion_local_fact_qa_dry_run(tmp_path: Path) -> None:
    db_path, document_root, output_dir = _paths(tmp_path)
    source = tmp_path / "invoice.txt"
    source.write_text("Invoice Date: March 12, 2020\nTotal: 42 USD", encoding="utf-8")

    payload, _ = _run_cli(
        "--db-path",
        str(db_path),
        "--document-root",
        str(document_root),
        "--file",
        str(source),
        "--question",
        "What is the invoice date?",
        "--dry-run",
        "--output-dir",
        str(output_dir),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "local_fact_qa"
    assert payload["tools_used"] == ["local_fact_qa"]
    assert payload["source"]["was_ingested"] is True
    assert payload["supporting_evidence_ids"]
    assert "dry_run_no_answer_generated" in payload["warnings"]
    summary = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["used_external_api"] is False
    assert summary["used_vlm"] is False
    assert summary["used_training"] is False
    assert summary["used_full_e2e"] is False


def test_file_parser_backend_unavailable_is_structured(tmp_path: Path) -> None:
    db_path, document_root, output_dir = _paths(tmp_path)
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\nsample")

    payload, _ = _run_cli(
        "--db-path",
        str(db_path),
        "--document-root",
        str(document_root),
        "--file",
        str(source),
        "--question",
        "How many pages are in this document?",
        "--output-dir",
        str(output_dir),
    )

    assert payload["status"] == "error"
    assert payload["doc_id"] == ""
    assert payload["source"]["was_ingested"] is False
    assert payload["source"]["reused_existing"] is False
    assert payload["source"]["ingestion_status"] == "failed"
    assert payload["error"]["type"] == "parser_backend_unavailable"
    summary = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["ingestion_error"]["type"] == "parser_backend_unavailable"


def test_page_metadata_inconsistent_warning(tmp_path: Path) -> None:
    db_path, _document_root, output_dir = _paths(tmp_path)
    conn = connect(db_path)
    repository = DocumentRepository(conn)
    repository.upsert_document(
        DocumentRecord(
            doc_id="bad_pages",
            sha256="b" * 64,
            original_name="bad.txt",
            mime_type="text/plain",
            file_size=10,
            file_path=str(tmp_path / "bad.txt"),
            document_dir=str(tmp_path / "documents" / "bad_pages"),
            page_count=1,
            parser_backend="text",
            parse_status="parsed",
            index_status="not_started",
        )
    )
    repository.save_evidence_blocks(
        [
            EvidenceBlock(
                doc_id="bad_pages",
                block_id="bad_pages_p002_text",
                block_type="text",
                text="Invoice Date: March 12, 2020",
                page_id=2,
                location=EvidenceLocation(page=2, block_id="bad_pages_p002_text"),
            )
        ]
    )
    conn.close()

    payload, _ = _run_cli(
        "--db-path",
        str(db_path),
        "--doc-id",
        "bad_pages",
        "--question",
        "What is the invoice date?",
        "--dry-run",
        "--output-dir",
        str(output_dir),
    )

    assert payload["status"] == "success"
    assert "page_metadata_inconsistent" in payload["warnings"]

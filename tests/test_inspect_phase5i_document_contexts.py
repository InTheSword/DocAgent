from __future__ import annotations

import json
from pathlib import Path

from docagent.ingestion.document_registry import DocumentRecord
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from scripts.inspect_phase5i_document_contexts import expand_db_paths, inspect_phase5i_document_contexts
from scripts.run_phase5i_answer_quality_benchmark import GoldenCase


def _write_document_context(tmp_path: Path, *, doc_id: str = "doc1") -> Path:
    db_path = tmp_path / "docagent.db"
    source = tmp_path / "source.txt"
    source.write_text("unclaimed dividend for financial year 2019", encoding="utf-8")
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        repository.upsert_document(
            DocumentRecord(
                doc_id=doc_id,
                sha256="2" * 64,
                original_name="source.txt",
                mime_type="text/plain",
                file_size=source.stat().st_size,
                file_path=str(source),
                document_dir=str(tmp_path / doc_id),
                page_count=24,
                parser_backend="text",
                parse_status="success",
                index_status="not_started",
            )
        )
        repository.save_evidence_blocks(
            [
                EvidenceBlock(
                    doc_id=doc_id,
                    block_id=f"{doc_id}_p024_b0001",
                    block_type="text",
                    text="unclaimed dividend for financial year 2019",
                    page_id=24,
                    location=EvidenceLocation(page=24, block_id=f"{doc_id}_p024_b0001"),
                )
            ]
        )
    finally:
        conn.close()
    return db_path


def _case() -> GoldenCase:
    return GoldenCase(
        case_id="fact_unclaimed_dividend_financial_year",
        user_request="What date or financial year is mentioned in the shareholder notice about unclaimed dividend?",
        request_form="interrogative",
        expected_task_type="local_fact_qa",
        expected_answer_type="extractive",
        answerable=True,
        unsupported_ok=False,
        expected_page=24,
        expected_evidence_keywords=["unclaimed", "dividend"],
        expected_answer_keywords=["financial year"],
        forbidden_answer_keywords=[],
    )


def test_phase5i_document_context_inventory_finds_ready_candidate(tmp_path: Path) -> None:
    db_path = _write_document_context(tmp_path, doc_id="doc1")

    result = inspect_phase5i_document_contexts(
        run_id="context_inventory_ready",
        output_root=tmp_path / "out",
        db_paths=[db_path],
        explicit_doc_ids=["doc1"],
        cases=[_case()],
        max_documents=10,
        include_default_doc_id=False,
        sync_output_dir=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["ready_document_count"] == 1
    assert result["candidate_document_count"] == 1
    assert result["best_candidates"][0]["doc_id"] == "doc1"
    assert result["best_candidates"][0]["case_context_ready_count"] == 1
    assert result["used_qwen"] is False
    assert result["used_training"] is False
    assert result["sync_bundle_path"]
    summary = json.loads((tmp_path / "out" / "context_inventory_ready" / "summary.json").read_text(encoding="utf-8"))
    assert summary["candidate_document_count"] == 1
    rows = [
        json.loads(line)
        for line in (tmp_path / "out" / "context_inventory_ready" / "case_context_rows.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[0]["context_ready_for_case"] is True


def test_phase5i_document_context_inventory_reports_missing_db(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing.db"

    result = inspect_phase5i_document_contexts(
        run_id="context_inventory_missing",
        output_root=tmp_path / "out",
        db_paths=[missing_db],
        explicit_doc_ids=["doc1"],
        cases=[_case()],
        max_documents=10,
        include_default_doc_id=False,
    )

    assert result["status"] == "success"
    assert result["ready_document_count"] == 0
    assert result["candidate_document_count"] == 0
    assert result["blocker_counts"] == {"db_path_not_found": 1}
    rows = [
        json.loads(line)
        for line in (tmp_path / "out" / "context_inventory_missing" / "document_context_rows.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert rows[0]["blocker_type"] == "db_path_not_found"


def test_expand_db_paths_uses_default_when_no_inputs() -> None:
    paths = expand_db_paths(None, None)

    assert len(paths) == 1
    assert paths[0].name == "docagent.db"

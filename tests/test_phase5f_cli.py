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


def _repository_with_document(tmp_path: Path) -> Path:
    db_path = tmp_path / "docagent.sqlite"
    conn = connect(db_path)
    repository = DocumentRepository(conn)
    repository.upsert_document(
        DocumentRecord(
            doc_id="doc1",
            sha256="a" * 64,
            original_name="invoice.pdf",
            mime_type="application/pdf",
            file_size=123,
            file_path=str(tmp_path / "documents" / "doc1" / "source" / "original.pdf"),
            document_dir=str(tmp_path / "documents" / "doc1"),
            page_count=2,
            parser_backend="mineru_existing",
            parse_status="parsed",
            index_status="not_started",
        )
    )
    repository.save_evidence_blocks(
        [
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_page",
                block_type="page",
                text="Invoice Date: March 12, 2020. Total: 42 USD.",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_page"),
                metadata={"child_block_ids": ["doc1_p001_date", "doc1_p001_table"]},
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p002_page",
                block_type="page",
                text="Second page contains supporting notes.",
                page_id=2,
                location=EvidenceLocation(page=2, block_id="doc1_p002_page"),
                metadata={"child_block_ids": ["doc1_p002_text"]},
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_date",
                block_type="text",
                text="Invoice Date: March 12, 2020",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_date"),
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_table",
                block_type="table",
                text="Year Revenue 2020 10 2021 15",
                table_html="<table><tr><td>2020</td><td>10</td></tr></table>",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_table"),
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p002_text",
                block_type="text",
                text="Payment terms are due on receipt.",
                page_id=2,
                location=EvidenceLocation(page=2, block_id="doc1_p002_text"),
            ),
        ]
    )
    conn.close()
    return db_path


def _run_cli(tmp_path: Path, *args: str) -> dict:
    completed = subprocess.run(
        [sys.executable, "scripts/docagent_cli.py", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    output = completed.stdout.strip()
    assert output.startswith("{")
    assert output.endswith("}")
    return json.loads(output)


def test_list_documents_outputs_json_with_doc_id_and_page_count(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--list-documents",
        "--limit",
        "20",
    )

    assert payload["status"] == "success"
    assert payload["mode"] == "list_documents"
    assert payload["documents"][0]["doc_id"] == "doc1"
    assert payload["documents"][0]["page_count"] == 2
    json.dumps(payload)


def test_doc_id_document_statistics_routes_to_deterministic_tools(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "How many pages and tables are in this document?",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "document_statistics"
    assert payload["router_plan"]["task_type"] == "document_statistics"
    assert set(payload["tools_used"]) == {"count_pages", "count_tables"}
    assert "2 pages" in payload["answer"]
    assert Path(payload["artifact_dir"], "summary.json").is_file()
    summary = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["used_external_api"] is False
    assert summary["used_vlm"] is False
    assert summary["used_training"] is False
    assert summary["used_full_e2e"] is False


def test_doc_id_page_lookup_returns_page_text(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "Show the text from page 1.",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "page_lookup"
    assert payload["tools_used"] == ["get_page_text"]
    assert "Invoice Date" in payload["answer"]
    assert payload["citations"][0]["page"] == 1


def test_doc_id_page_lookup_missing_page_returns_structured_error(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "Show page 99.",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "error"
    assert payload["task_type"] == "page_lookup"
    assert payload["error"]["type"] == "page_not_found"
    json.dumps(payload)


def test_doc_id_local_fact_qa_dry_run_returns_unified_json(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "What is the invoice date?",
        "--dry-run",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "local_fact_qa"
    assert payload["tools_used"] == ["local_fact_qa"]
    assert payload["answer"] == ""
    assert payload["answer_policy_mode"] == "heuristic"
    assert payload["used_qwen_answer_policy"] is False
    assert payload["used_external_answer_api"] is False
    assert payload["retrieval_candidate_count"] == len(payload["supporting_evidence_ids"])
    assert payload["citation_count"] == len(payload["citations"])
    assert "dry_run_no_answer_generated" in payload["warnings"]
    assert payload["supporting_evidence_ids"]


def test_full_model_path_missing_llm_config_returns_structured_error(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "What is the invoice date?",
        "--full-model-path",
        "--router-llm-env-file",
        str(tmp_path / "missing-router.env"),
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "error"
    assert payload["error"]["type"] == "llm_planning_config_missing"
    assert payload["full_model_path"] is True
    assert "full_model_path_requires_llm_planning_config" in payload["warnings"]
    assert payload["answer_policy_mode"] == "heuristic"
    summary = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["full_model_path"] is True
    assert summary["used_llm_router"] is False
    assert summary["used_llm_query_rewriter"] is False


def test_file_argument_missing_file_returns_structured_error(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)
    file_path = tmp_path / "missing.pdf"

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--file",
        str(file_path),
        "--question",
        "What is this document about?",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "error"
    assert payload["error"]["type"] == "file_not_found"
    assert payload["source"]["was_ingested"] is False
    assert payload["source"]["reused_existing"] is False
    assert payload["router_plan"] == {}
    assert Path(payload["artifact_dir"], "result.json").is_file()


def test_document_summary_question_runs_summary_tool(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "Summarize this document.",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "document_summary"
    assert payload["router_plan"]["selected_tools"] == ["document_summary"]
    assert payload["tools_used"] == ["document_summary"]
    assert payload["summary"]["key_points"]
    assert payload["citations"]
    assert payload["error"] == {}


def test_structured_extraction_dates_runs_deterministic_tool(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "List all dates mentioned in this document.",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "structured_extraction"
    assert payload["router_plan"]["selected_tools"] == ["extract_all_dates"]
    assert payload["tools_used"] == ["extract_all_dates"]
    assert payload["structured_result"]["item_count"] >= 1
    assert payload["structured_result"]["counts_by_type"]["date"] >= 1
    assert any(item["value"] == "March 12, 2020" for item in payload["structured_result"]["items"])
    assert payload["citations"]
    assert Path(payload["artifact_dir"], "trace.json").is_file()


def test_structured_extraction_tables_runs_deterministic_tool(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "Extract all tables from this document.",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "structured_extraction"
    assert payload["router_plan"]["selected_tools"] == ["extract_all_tables"]
    assert payload["tools_used"] == ["extract_all_tables"]
    assert payload["structured_result"]["counts_by_type"]["table"] == 1
    assert payload["structured_result"]["items"][0]["block_id"] == "doc1_p001_table"
    assert payload["citations"][0]["block_id"] == "doc1_p001_table"


def test_table_calculation_question_returns_not_implemented(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "What is the difference between 2020 and 2021 revenue?",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "error"
    assert payload["task_type"] == "table_lookup_or_calculation"
    assert payload["error"]["type"] == "table_lookup_not_implemented"
    assert "table_lookup_not_implemented" in payload["warnings"]

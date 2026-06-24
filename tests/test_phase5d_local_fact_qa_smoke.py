from __future__ import annotations

import json
from pathlib import Path

from docagent.ingestion.document_registry import DocumentRecord
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from scripts.run_phase5d_local_fact_qa_smoke import SmokeQuestion, load_questions, run_smoke


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
            page_count=1,
            parser_backend="mineru_existing",
            parse_status="parsed",
            index_status="not_started",
        )
    )
    repository.save_evidence_blocks(
        [
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
                block_id="doc1_p001_total",
                block_type="text",
                text="Total: 42 USD",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_total"),
            ),
        ]
    )
    conn.close()
    return db_path


def _read_jsonl(path: str | Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def test_dry_run_writes_required_artifacts_and_result_fields(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    summary = run_smoke(
        db_path=db_path,
        doc_id="doc1",
        questions=[SmokeQuestion("What is the invoice date?")],
        output_dir=tmp_path / "smoke",
        dry_run=True,
        top_k=1,
    )

    assert summary["status"] == "success"
    assert summary["completed_count"] == 1
    assert summary["failed_count"] == 0
    assert summary["used_dry_run"] is True
    assert summary["used_real_workflow"] is False
    assert summary["used_external_api"] is False
    assert summary["used_vlm"] is False
    assert summary["used_training"] is False
    assert summary["used_full_e2e"] is False

    for key in ("summary_path", "summary_md_path", "results_path", "preview_path"):
        assert Path(summary[key]).is_file()

    rows = _read_jsonl(summary["results_path"])
    assert len(rows) == 1
    row = rows[0]
    assert row["run_id"] == summary["run_id"]
    assert row["doc_id"] == "doc1"
    assert row["question"] == "What is the invoice date?"
    assert row["status"] == "success"
    assert row["answer"] == ""
    assert row["supporting_evidence_ids"] == ["doc1_p001_date"]
    assert row["tools_used"] == ["local_fact_qa"]
    assert "dry_run_no_answer_generated" in row["warnings"]
    json.dumps(summary)


def test_real_workflow_heuristic_smoke_records_trace_path(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    summary = run_smoke(
        db_path=db_path,
        doc_id="doc1",
        questions=[SmokeQuestion("What is the invoice date?")],
        output_dir=tmp_path / "smoke",
        dry_run=False,
        answer_policy="heuristic",
    )

    rows = _read_jsonl(summary["results_path"])
    assert summary["status"] == "success"
    assert summary["used_real_workflow"] is True
    assert rows[0]["answer"] == "March 12, 2020"
    assert rows[0]["trace_path"] == str(db_path)
    assert rows[0]["tool_run_id"]


def test_missing_doc_id_returns_structured_failure_artifact(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    summary = run_smoke(
        db_path=db_path,
        doc_id=None,
        questions=[SmokeQuestion("What is the invoice date?")],
        output_dir=tmp_path / "smoke",
        dry_run=True,
    )

    rows = _read_jsonl(summary["results_path"])
    assert summary["status"] == "failed"
    assert rows[0]["error"]["type"] == "missing_doc_id"
    assert Path(summary["summary_md_path"]).is_file()


def test_missing_db_path_returns_structured_failure_without_creating_db(tmp_path: Path) -> None:
    missing_db = tmp_path / "missing.sqlite"

    summary = run_smoke(
        db_path=missing_db,
        doc_id="doc1",
        questions=[SmokeQuestion("What is the invoice date?")],
        output_dir=tmp_path / "smoke",
        dry_run=True,
    )

    rows = _read_jsonl(summary["results_path"])
    assert summary["status"] == "failed"
    assert rows[0]["error"]["type"] == "db_path_not_found"
    assert not missing_db.exists()


def test_load_questions_supports_cli_question_and_jsonl_limit(tmp_path: Path) -> None:
    questions_path = tmp_path / "questions.jsonl"
    questions_path.write_text(
        "\n".join(
            [
                json.dumps({"qid": "q1", "doc_id": "doc-json", "question": "What is the invoice date?"}),
                json.dumps({"qid": "q2", "question": "What is the total?"}),
            ]
        ),
        encoding="utf-8",
    )

    questions = load_questions(
        question=["What is the vendor?"],
        questions_jsonl=questions_path,
        limit=2,
    )

    assert [item.question for item in questions] == ["What is the vendor?", "What is the invoice date?"]
    assert questions[1].doc_id == "doc-json"
    assert questions[1].qid == "q1"

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docagent.ingestion.document_registry import DocumentRecord
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.prepare_mpdocvqa_evidence import CommandResult, prepare_mpdocvqa_evidence


def _write_subset(tmp_path: Path) -> Path:
    subset_root = tmp_path / "subset"
    pdf_dir = subset_root / "documents" / "mp_doc"
    pdf_dir.mkdir(parents=True)
    (pdf_dir / "document.pdf").write_bytes(b"%PDF-1.4\n")
    write_jsonl(
        subset_root / "documents.jsonl",
        [
            {
                "doc_id": "mp_doc",
                "source_doc_id": "mp_source",
                "pdf_path": "documents/mp_doc/document.pdf",
                "pdf_sha256": "fake-sha",
                "page_count": 2,
                "qa_count": 1,
            }
        ],
    )
    write_jsonl(
        subset_root / "sample_manifest.jsonl",
        [
            {
                "sample_id": "mp_q",
                "dataset": "mp_docvqa",
                "split": "val",
                "doc_id": "mp_doc",
                "source_document": "mp_source",
                "question": "What is the budget estimate?",
                "answers": ["$100,000"],
                "expected_answer_type": "extractive",
                "expected_tools": ["retrieval", "local_fact_qa"],
                "gold_evidence": [{"doc_id": "mp_doc", "page": 2, "block_id": "mp_doc_page_2", "block_type": "page"}],
            }
        ],
    )
    return subset_root


def test_prepare_mpdocvqa_evidence_writes_mapping_artifacts(tmp_path: Path) -> None:
    subset_root = _write_subset(tmp_path)
    ingested_doc_id = "ingested_mp_doc"
    seen_commands: list[list[str]] = []

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        seen_commands.append(command)
        db_path = Path(command[command.index("--db-path") + 1])
        document_root = Path(command[command.index("--document-root") + 1])
        artifact_dir = tmp_path / "cli_artifacts" / "run"
        artifact_dir.mkdir(parents=True)
        conn = connect(db_path)
        try:
            repository = DocumentRepository(conn)
            repository.upsert_document(
                DocumentRecord(
                    doc_id=ingested_doc_id,
                    sha256="a" * 64,
                    original_name="document.pdf",
                    mime_type="application/pdf",
                    file_size=10,
                    file_path=str(document_root / ingested_doc_id / "source" / "original.pdf"),
                    document_dir=str(document_root / ingested_doc_id),
                    page_count=2,
                    parser_backend="mineru_api",
                    parse_status="parsed",
                    index_status="not_started",
                )
            )
            repository.save_evidence_blocks(
                [
                    EvidenceBlock(
                        doc_id=ingested_doc_id,
                        block_id=f"{ingested_doc_id}_p002_b0001",
                        block_type="text",
                        text="Budget Estimate: $100,000",
                        page_id=2,
                        location=EvidenceLocation(page=2, block_id=f"{ingested_doc_id}_p002_b0001"),
                    ),
                    EvidenceBlock(
                        doc_id=ingested_doc_id,
                        block_id=f"{ingested_doc_id}_p002_page",
                        block_type="page",
                        text="Budget Estimate: $100,000",
                        page_id=2,
                        location=EvidenceLocation(page=2, block_id=f"{ingested_doc_id}_p002_page"),
                        metadata={"child_block_ids": [f"{ingested_doc_id}_p002_b0001"]},
                    ),
                ]
            )
        finally:
            conn.close()
        payload: dict[str, Any] = {
            "status": "success",
            "doc_id": ingested_doc_id,
            "artifact_dir": str(artifact_dir),
            "source": {
                "was_ingested": True,
                "reused_existing": False,
                "parser": "mineru_api",
                "parser_mode": "parse_existing",
                "used_mineru_api": True,
                "mineru_api": {"api_status": "submitted"},
                "ingestion": {"parse_status": "parsed", "page_count": 2, "block_count": 2},
            },
        }
        return CommandResult(0, json.dumps(payload))

    summary = prepare_mpdocvqa_evidence(
        subset_root=subset_root,
        output_root=tmp_path / "evidence",
        run_id="mpdocvqa_evidence_test",
        live_api=True,
        mineru_env_file=tmp_path / "mineru.env",
        command_runner=fake_runner,
        sync_output_root=tmp_path / "sync",
    )

    assert summary["status"] == "success"
    assert summary["document_count"] == 1
    assert summary["sample_count"] == 1
    assert summary["sample_evidence_ready_count"] == 1
    assert summary["answer_text_gold_page_hit_count"] == 1
    assert summary["used_mineru_api"] is True
    assert summary["used_online_mineru_ocr"] is True
    assert summary["formal_benchmark_acceptance"] is False
    assert summary["db_path"].endswith("docagent.db")
    assert summary["document_root"].endswith("documents")
    assert summary["cli_artifact_dir"].endswith("cli_artifacts")
    assert summary["sync_bundle_path"].endswith("mpdocvqa_evidence_test")
    assert seen_commands[0][seen_commands[0].index("--parser") + 1] == "mineru_api"
    assert "--live-api" in seen_commands[0]
    assert "--mineru-env-file" in seen_commands[0]
    assert seen_commands[0][seen_commands[0].index("--mineru-api-max-attempts") + 1] == "3"
    assert seen_commands[0][seen_commands[0].index("--mineru-api-retry-delay-seconds") + 1] == "10.0"
    assert "--mineru-ocr" in seen_commands[0]
    assert "--no-mineru-ocr" not in seen_commands[0]

    run_dir = tmp_path / "evidence" / "mpdocvqa_evidence_test"
    assert (run_dir / "documents.jsonl").is_file()
    assert (run_dir / "sample_evidence_manifest.jsonl").is_file()
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "summary.md").is_file()
    assert (run_dir / "preview.json").is_file()
    assert (run_dir / "manifest.json").is_file()
    rows = read_jsonl(run_dir / "sample_evidence_manifest.jsonl")
    assert rows[0]["ingested_doc_id"] == ingested_doc_id
    assert rows[0]["gold_page_block_ids"] == [f"{ingested_doc_id}_p002_page"]
    assert rows[0]["candidate_block_count_on_gold_pages"] == 1
    assert (tmp_path / "sync" / "mpdocvqa_evidence_test" / "manifest.json").is_file()
    summary_file = json.loads((run_dir / "summary.json").read_text(encoding="utf-8"))
    assert summary_file["db_path"] == summary["db_path"]
    assert summary_file["sync_bundle_path"] == summary["sync_bundle_path"]


def test_prepare_mpdocvqa_evidence_requires_live_api(tmp_path: Path) -> None:
    subset_root = _write_subset(tmp_path)

    try:
        prepare_mpdocvqa_evidence(subset_root=subset_root, output_root=tmp_path / "evidence", live_api=False)
    except ValueError as exc:
        assert "--live-api" in str(exc)
    else:
        raise AssertionError("expected live API preflight failure")


def test_prepare_mpdocvqa_evidence_retries_failed_previous_documents(tmp_path: Path) -> None:
    subset_root = tmp_path / "subset"
    for doc_id in ("doc_ok", "doc_fail"):
        doc_dir = subset_root / "documents" / doc_id
        doc_dir.mkdir(parents=True)
        (doc_dir / "document.pdf").write_bytes(b"%PDF-1.4\n")
    write_jsonl(
        subset_root / "documents.jsonl",
        [
            {"doc_id": "doc_ok", "source_doc_id": "source_ok", "pdf_path": "documents/doc_ok/document.pdf"},
            {"doc_id": "doc_fail", "source_doc_id": "source_fail", "pdf_path": "documents/doc_fail/document.pdf"},
        ],
    )
    write_jsonl(
        subset_root / "sample_manifest.jsonl",
        [
            {
                "sample_id": "q_ok",
                "dataset": "mp_docvqa",
                "doc_id": "doc_ok",
                "source_document": "source_ok",
                "question": "What is the approved amount?",
                "answers": ["$10"],
                "gold_evidence": [{"page": 1}],
            },
            {
                "sample_id": "q_fail",
                "dataset": "mp_docvqa",
                "doc_id": "doc_fail",
                "source_document": "source_fail",
                "question": "What is the budget estimate?",
                "answers": ["$100,000"],
                "gold_evidence": [{"page": 1}],
            },
        ],
    )

    previous_run = tmp_path / "previous"
    previous_run.mkdir()
    db_path = tmp_path / "shared" / "docagent.db"
    document_root = tmp_path / "shared" / "documents"
    document_root.mkdir(parents=True)
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        repository.upsert_document(
            DocumentRecord(
                doc_id="ingested_ok",
                sha256="b" * 64,
                original_name="ok.pdf",
                mime_type="application/pdf",
                file_size=10,
                file_path=str(document_root / "ingested_ok" / "source" / "original.pdf"),
                document_dir=str(document_root / "ingested_ok"),
                page_count=1,
                parser_backend="mineru_api",
                parse_status="parsed",
                index_status="not_started",
            )
        )
        repository.save_evidence_blocks(
            [
                EvidenceBlock(
                    doc_id="ingested_ok",
                    block_id="ingested_ok_p001_b0001",
                    block_type="text",
                    text="Approved amount $10",
                    page_id=1,
                    location=EvidenceLocation(page=1, block_id="ingested_ok_p001_b0001"),
                ),
                EvidenceBlock(
                    doc_id="ingested_ok",
                    block_id="ingested_ok_p001_page",
                    block_type="page",
                    text="Approved amount $10",
                    page_id=1,
                    location=EvidenceLocation(page=1, block_id="ingested_ok_p001_page"),
                    metadata={"child_block_ids": ["ingested_ok_p001_b0001"]},
                ),
            ]
        )
    finally:
        conn.close()
    write_jsonl(
        previous_run / "documents.jsonl",
        [
            {"doc_id": "doc_ok", "ingested_doc_id": "ingested_ok", "pass_fail": "passed", "failure_reasons": []},
            {
                "doc_id": "doc_fail",
                "ingested_doc_id": "",
                "pass_fail": "failed",
                "failure_reasons": ["status_not_success:file_ingestion_failed"],
            },
        ],
    )
    (previous_run / "summary.json").write_text(
        json.dumps({"db_path": str(db_path), "document_root": str(document_root)}),
        encoding="utf-8",
    )
    seen_commands: list[list[str]] = []

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        seen_commands.append(command)
        assert "doc_fail" in command[command.index("--file") + 1]
        conn = connect(db_path)
        try:
            repository = DocumentRepository(conn)
            repository.upsert_document(
                DocumentRecord(
                    doc_id="ingested_fail",
                    sha256="c" * 64,
                    original_name="fail.pdf",
                    mime_type="application/pdf",
                    file_size=10,
                    file_path=str(document_root / "ingested_fail" / "source" / "original.pdf"),
                    document_dir=str(document_root / "ingested_fail"),
                    page_count=1,
                    parser_backend="mineru_api",
                    parse_status="parsed",
                    index_status="not_started",
                )
            )
            repository.save_evidence_blocks(
                [
                    EvidenceBlock(
                        doc_id="ingested_fail",
                        block_id="ingested_fail_p001_b0001",
                        block_type="text",
                        text="Budget Estimate $100,000",
                        page_id=1,
                        location=EvidenceLocation(page=1, block_id="ingested_fail_p001_b0001"),
                    ),
                    EvidenceBlock(
                        doc_id="ingested_fail",
                        block_id="ingested_fail_p001_page",
                        block_type="page",
                        text="Budget Estimate $100,000",
                        page_id=1,
                        location=EvidenceLocation(page=1, block_id="ingested_fail_p001_page"),
                        metadata={"child_block_ids": ["ingested_fail_p001_b0001"]},
                    ),
                ]
            )
        finally:
            conn.close()
        return CommandResult(
            0,
            json.dumps(
                {
                    "status": "success",
                    "doc_id": "ingested_fail",
                    "source": {
                        "was_ingested": True,
                        "reused_existing": False,
                        "parser": "mineru_api",
                        "parser_mode": "parse_existing",
                        "used_mineru_api": True,
                        "mineru_api": {"api_status": "submitted"},
                        "ingestion": {"parse_status": "parsed", "page_count": 1, "block_count": 2},
                    },
                }
            ),
        )

    summary = prepare_mpdocvqa_evidence(
        subset_root=subset_root,
        output_root=tmp_path / "evidence",
        run_id="retry_failed",
        live_api=True,
        previous_run_dir=previous_run,
        retry_failed_only=True,
        mineru_env_file=tmp_path / "mineru.env",
        command_runner=fake_runner,
    )

    assert len(seen_commands) == 1
    assert summary["status"] == "success"
    assert summary["document_count"] == 2
    assert summary["document_passed_count"] == 2
    assert summary["sample_count"] == 2
    assert summary["sample_evidence_ready_count"] == 2
    assert summary["retried_document_count"] == 1
    rows = read_jsonl(tmp_path / "evidence" / "retry_failed" / "sample_evidence_manifest.jsonl")
    assert {row["sample_id"] for row in rows if row["evidence_ready"]} == {"q_ok", "q_fail"}


def test_prepare_mpdocvqa_evidence_can_disable_mineru_ocr(tmp_path: Path) -> None:
    subset_root = _write_subset(tmp_path)
    seen_commands: list[list[str]] = []

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        seen_commands.append(command)
        return CommandResult(
            0,
            json.dumps(
                {
                    "status": "success",
                    "doc_id": "ingested_doc",
                    "source": {
                        "parser": "mineru_api",
                        "parser_mode": "parse_existing",
                        "used_mineru_api": True,
                        "mineru_api": {"api_status": "submitted"},
                        "ingestion": {"parse_status": "parsed", "page_count": 1, "block_count": 0},
                    },
                }
            ),
        )

    summary = prepare_mpdocvqa_evidence(
        subset_root=subset_root,
        output_root=tmp_path / "evidence",
        run_id="no_ocr",
        live_api=True,
        mineru_ocr=False,
        command_runner=fake_runner,
    )

    assert "--no-mineru-ocr" in seen_commands[0]
    assert "--mineru-ocr" not in seen_commands[0]
    assert summary["used_online_mineru_ocr"] is False


def test_prepare_mpdocvqa_evidence_can_request_evidence_rebuild(tmp_path: Path) -> None:
    subset_root = _write_subset(tmp_path)
    seen_commands: list[list[str]] = []

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        seen_commands.append(command)
        db_path = Path(command[command.index("--db-path") + 1])
        document_root = Path(command[command.index("--document-root") + 1])
        conn = connect(db_path)
        try:
            repository = DocumentRepository(conn)
            repository.upsert_document(
                DocumentRecord(
                    doc_id="ingested_doc",
                    sha256="d" * 64,
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
                        text="Budget Estimate $100,000",
                        page_id=2,
                        location=EvidenceLocation(page=2, block_id="ingested_doc_p002_page"),
                    )
                ]
            )
        finally:
            conn.close()
        return CommandResult(
            0,
            json.dumps(
                {
                    "status": "success",
                    "doc_id": "ingested_doc",
                    "source": {
                        "was_ingested": True,
                        "reused_existing": False,
                        "parser": "mineru_api",
                        "parser_mode": "parse_existing",
                        "used_mineru_api": True,
                        "mineru_api": {"api_status": "cached_existing_output"},
                        "ingestion": {"parse_status": "parsed", "page_count": 2, "block_count": 1},
                    },
                }
            ),
        )

    summary = prepare_mpdocvqa_evidence(
        subset_root=subset_root,
        output_root=tmp_path / "evidence",
        run_id="rebuild",
        live_api=True,
        rebuild_evidence_blocks=True,
        command_runner=fake_runner,
    )

    assert summary["status"] == "success"
    assert summary["rebuild_evidence_blocks"] is True
    assert "--force-parse" in seen_commands[0]

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_final_raw_pdf_smoke import CommandResult, run_final_raw_pdf_smoke


def _write_cli_artifacts(artifact_dir: Path, payload: dict) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for name in ("result.json", "summary.json", "router_plan.json", "trace.json"):
        (artifact_dir / name).write_text(json.dumps(payload), encoding="utf-8")


def _payload(
    *,
    tmp_path: Path,
    case_id: str,
    doc_id: str,
    task_type: str,
    tools_used: list[str],
    was_ingested: bool = False,
    parser: str = "",
    parser_mode: str = "",
    citations: list[dict] | None = None,
    evidence_used: list[dict] | None = None,
) -> dict:
    artifact_dir = tmp_path / "cli" / case_id
    payload = {
        "status": "success",
        "doc_id": doc_id,
        "task_type": task_type,
        "tools_used": tools_used,
        "answer": "ok",
        "source": {
            "was_ingested": was_ingested,
            "reused_existing": not was_ingested,
            "parser": parser,
            "parser_mode": parser_mode,
            "resolved_doc_id": doc_id,
            "ingestion": {
                "parse_status": "parsed",
                "page_count": 2,
                "block_count": 5,
            },
        },
        "citations": citations or [],
        "evidence_used": evidence_used or [],
        "artifact_dir": str(artifact_dir),
        "trace_path": str(artifact_dir / "trace.json"),
    }
    _write_cli_artifacts(artifact_dir, payload)
    return payload


def test_final_raw_pdf_smoke_validates_cli_contract(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    document_root = tmp_path / "documents"
    doc_id = "doc_raw_pdf"
    mineru_dir = document_root / doc_id / "mineru"
    mineru_dir.mkdir(parents=True)
    (mineru_dir / "mineru_cli_result.json").write_text(
        json.dumps({"command_found": True, "timed_out": False, "returncode": 0}),
        encoding="utf-8",
    )
    seen_commands: list[list[str]] = []

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        seen_commands.append(command)
        question = command[command.index("--question") + 1]
        citation = {
            "doc_id": doc_id,
            "page": 1,
            "block_id": "b1",
            "block_type": "text",
            "text_preview": "AFRICA",
        }
        evidence = [dict(citation)]
        if question == "How many pages are in this document?":
            payload = _payload(
                tmp_path=tmp_path,
                case_id="stats",
                doc_id=doc_id,
                task_type="document_statistics",
                tools_used=["count_pages"],
                was_ingested=True,
                parser="mineru",
                parser_mode="local_cli",
            )
            return CommandResult(0, json.dumps(payload))
        if question == "Show the text from page 1.":
            payload = _payload(
                tmp_path=tmp_path,
                case_id="page",
                doc_id=doc_id,
                task_type="page_lookup",
                tools_used=["get_page_text"],
                citations=[citation],
                evidence_used=evidence,
            )
            return CommandResult(0, json.dumps(payload))
        if question == "Summarize this document.":
            payload = _payload(
                tmp_path=tmp_path,
                case_id="summary",
                doc_id=doc_id,
                task_type="document_summary",
                tools_used=["document_summary"],
                citations=[citation],
                evidence_used=evidence,
            )
            return CommandResult(0, json.dumps(payload))
        payload = _payload(
            tmp_path=tmp_path,
            case_id="fact",
            doc_id=doc_id,
            task_type="local_fact_qa",
            tools_used=["local_fact_qa"],
            citations=[citation],
            evidence_used=evidence,
        )
        return CommandResult(0, json.dumps(payload))

    summary = run_final_raw_pdf_smoke(
        pdf_path=pdf_path,
        output_root=tmp_path / "smoke",
        document_root=document_root,
        mineru_command="fake_mineru",
        command_runner=fake_runner,
        run_id="raw_pdf_smoke_test",
    )

    assert summary["status"] == "success"
    assert summary["passed_count"] == 4
    assert summary["failed_count"] == 0
    assert summary["used_mineru_local_cli"] is True
    assert summary["used_qwen"] is False
    assert summary["formal_benchmark_acceptance"] is False
    assert summary["task_type_distribution"] == {
        "document_statistics": 1,
        "document_summary": 1,
        "local_fact_qa": 1,
        "page_lookup": 1,
    }
    assert len(seen_commands) == 4
    for command in seen_commands:
        assert "--parser" in command
        assert command[command.index("--parser") + 1] == "mineru"
        assert command[command.index("--parser-mode") + 1] == "local_cli"
        assert command[command.index("--mineru-command") + 1] == "fake_mineru"

    run_dir = Path(summary["artifact_dir"])
    assert (run_dir / "cases.jsonl").is_file()
    assert (run_dir / "results.jsonl").is_file()
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "summary.md").is_file()
    assert (run_dir / "preview.json").is_file()
    assert (run_dir / "manifest.json").is_file()


def test_final_raw_pdf_smoke_fails_on_missing_citation_contract(tmp_path: Path) -> None:
    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n")
    document_root = tmp_path / "documents"
    doc_id = "doc_raw_pdf"
    mineru_dir = document_root / doc_id / "mineru"
    mineru_dir.mkdir(parents=True)
    (mineru_dir / "mineru_cli_result.json").write_text(
        json.dumps({"command_found": True, "timed_out": False, "returncode": 0}),
        encoding="utf-8",
    )

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        question = command[command.index("--question") + 1]
        if question == "How many pages are in this document?":
            payload = _payload(
                tmp_path=tmp_path,
                case_id="stats",
                doc_id=doc_id,
                task_type="document_statistics",
                tools_used=["count_pages"],
                was_ingested=True,
                parser="mineru",
                parser_mode="local_cli",
            )
        else:
            payload = _payload(
                tmp_path=tmp_path,
                case_id=question.split()[0].lower(),
                doc_id=doc_id,
                task_type="page_lookup" if "page 1" in question else "document_summary",
                tools_used=["get_page_text"] if "page 1" in question else ["document_summary"],
            )
        return CommandResult(0, json.dumps(payload))

    summary = run_final_raw_pdf_smoke(
        pdf_path=pdf_path,
        output_root=tmp_path / "smoke",
        document_root=document_root,
        command_runner=fake_runner,
        run_id="raw_pdf_smoke_missing_citation",
    )

    assert summary["status"] == "failed"
    assert summary["failed_count"] == 3
    assert summary["failure_reason_distribution"]["citations_empty"] == 3
    assert summary["failure_reason_distribution"]["evidence_used_empty"] == 3

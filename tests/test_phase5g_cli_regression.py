from __future__ import annotations

import json
from pathlib import Path

from scripts.run_phase5g_cli_regression import CommandResult, run_phase5g_regression


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _payload(
    *,
    status: str = "success",
    task_type: str = "",
    tools_used: list[str] | None = None,
    warnings: list[str] | None = None,
    error: dict | None = None,
    artifact_dir: str = "",
    documents: list[dict] | None = None,
) -> str:
    return json.dumps(
        {
            "status": status,
            "mode": "list_documents" if documents is not None else "qa",
            "doc_id": "doc1",
            "task_type": task_type,
            "router_plan": {"task_type": task_type, "warnings": warnings or []},
            "tools_used": tools_used or [],
            "warnings": warnings or [],
            "error": error or {},
            "artifact_dir": artifact_dir,
            "documents": documents or [],
        },
        ensure_ascii=False,
    )


def test_phase5g_runner_reads_cases_and_writes_reports(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    missing_mineru = tmp_path / "missing_mineru"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "list_documents",
                "mode": "list_documents",
                "expected_status": "success",
                "capture_first_doc_id": True,
            },
            {
                "case_id": "stats_pages_docid",
                "mode": "doc_id",
                "doc_id": "$FIRST_DOC_ID",
                "question": "How many pages are in this document?",
                "expected_status": "success",
                "expected_task_type": "document_statistics",
                "expected_tools_any": ["count_pages"],
            },
            {
                "case_id": "summary",
                "mode": "doc_id",
                "doc_id": "$FIRST_DOC_ID",
                "question": "Summarize this document.",
                "expected_status": "success",
                "expected_task_type": "document_summary",
                "expected_tools_any": ["document_summary"],
            },
            {
                "case_id": "structured_dates",
                "mode": "doc_id",
                "doc_id": "$FIRST_DOC_ID",
                "question": "List all dates mentioned in this document.",
                "expected_status": "success",
                "expected_task_type": "structured_extraction",
                "expected_tools_any": ["extract_all_dates"],
            },
            {
                "case_id": "table_lookup_or_calculation",
                "mode": "doc_id",
                "doc_id": "$FIRST_DOC_ID",
                "question": "What is the difference between 2020 and 2021 revenue?",
                "expected_status": "success",
                "expected_task_type": "table_lookup_or_calculation",
                "expected_tools_any": ["simple_calculation"],
            },
            {
                "case_id": "mineru_missing",
                "mode": "file",
                "file": str(tmp_path / "missing.pdf"),
                "question": "How many pages are in this document?",
                "skip_if_missing_paths": [str(missing_mineru)],
                "known_limitation_allowed": True,
            },
            {
                "case_id": "bad_stdout",
                "mode": "doc_id",
                "doc_id": "$FIRST_DOC_ID",
                "question": "Return bad stdout.",
                "expected_status": "success",
            },
        ],
    )

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        output_dir = Path(command[command.index("--output-dir") + 1])
        if "--list-documents" in command:
            return CommandResult(
                0,
                _payload(
                    documents=[{"doc_id": "doc1", "page_count": 2}],
                ),
            )
        question = command[command.index("--question") + 1]
        if question == "How many pages are in this document?":
            artifact_dir = output_dir / "stats_case"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "result.json").write_text("{}", encoding="utf-8")
            return CommandResult(
                0,
                _payload(task_type="document_statistics", tools_used=["count_pages"], artifact_dir=str(artifact_dir)),
            )
        if question == "Summarize this document.":
            artifact_dir = output_dir / "summary_case"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "result.json").write_text("{}", encoding="utf-8")
            return CommandResult(
                0,
                _payload(
                    task_type="document_summary",
                    tools_used=["document_summary"],
                    artifact_dir=str(artifact_dir),
                ),
            )
        if question == "List all dates mentioned in this document.":
            artifact_dir = output_dir / "structured_case"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "result.json").write_text("{}", encoding="utf-8")
            return CommandResult(
                0,
                _payload(
                    task_type="structured_extraction",
                    tools_used=["extract_all_dates"],
                    artifact_dir=str(artifact_dir),
                ),
            )
        if question == "What is the difference between 2020 and 2021 revenue?":
            artifact_dir = output_dir / "table_case"
            artifact_dir.mkdir(parents=True)
            (artifact_dir / "result.json").write_text("{}", encoding="utf-8")
            return CommandResult(
                0,
                _payload(
                    status="success",
                    task_type="table_lookup_or_calculation",
                    tools_used=["table_lookup", "simple_calculation"],
                    artifact_dir=str(artifact_dir),
                ),
            )
        return CommandResult(0, "debug line\nnot json\n")

    summary = run_phase5g_regression(
        db_path=tmp_path / "docagent.db",
        output_root=tmp_path / "regression",
        document_root=tmp_path / "documents",
        cases_jsonl=cases_path,
        command_runner=fake_runner,
        run_id="phase5g_test",
    )

    assert summary["status"] == "failed"
    assert summary["case_count"] == 7
    assert summary["completed_count"] == 5
    assert summary["unsupported_count"] == 0
    assert summary["skipped_count"] == 1
    assert summary["failed_count"] == 1
    assert summary["json_valid_count"] == 5
    assert summary["artifact_write_count"] == 4
    assert summary["task_type_distribution"] == {
        "document_statistics": 1,
        "document_summary": 1,
        "structured_extraction": 1,
        "table_lookup_or_calculation": 1,
    }
    assert summary["tools_used_distribution"] == {
        "count_pages": 1,
        "document_summary": 1,
        "extract_all_dates": 1,
        "simple_calculation": 1,
        "table_lookup": 1,
    }
    assert summary["failure_taxonomy"] == {"stdout_not_json": 1}
    assert summary["unsupported_taxonomy"] == {}
    assert summary["skipped_taxonomy"]["mineru_fixture_missing"] == 1
    assert summary["failure_taxonomy"]["stdout_not_json"] == 1
    assert summary["used_external_api"] is False
    assert summary["used_vlm"] is False
    assert summary["used_training"] is False
    assert summary["used_full_e2e"] is False

    run_dir = Path(summary["artifact_dir"])
    assert (run_dir / "regression_cases.jsonl").is_file()
    assert (run_dir / "regression_results.jsonl").is_file()
    assert (run_dir / "regression_summary.json").is_file()
    assert (run_dir / "regression_summary.md").is_file()
    assert (run_dir / "preview.json").is_file()
    json.loads((run_dir / "regression_summary.json").read_text(encoding="utf-8"))
    assert "execution regression baseline" in (run_dir / "regression_summary.md").read_text(encoding="utf-8")


def test_phase5g_runner_records_visual_known_limitation(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "visual_pixel_qa_boundary",
                "mode": "doc_id",
                "doc_id": "doc1",
                "question": "In the chart, what color is shown?",
                "dry_run": True,
                "expected_status": "success",
                "expected_task_type": "local_fact_qa",
                "expected_tools_any": ["local_fact_qa"],
                "expected_warnings_any": ["visual_understanding_unsupported"],
                "known_limitation_allowed": True,
            }
        ],
    )

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        output_dir = Path(command[command.index("--output-dir") + 1])
        artifact_dir = output_dir / "visual_case"
        artifact_dir.mkdir(parents=True)
        (artifact_dir / "result.json").write_text("{}", encoding="utf-8")
        return CommandResult(
            0,
            _payload(
                task_type="local_fact_qa",
                tools_used=["local_fact_qa"],
                warnings=["visual_understanding_unsupported", "fallback_to_local_fact_qa", "dry_run_no_answer_generated"],
                artifact_dir=str(artifact_dir),
            ),
        )

    summary = run_phase5g_regression(
        db_path=tmp_path / "docagent.db",
        output_root=tmp_path / "regression",
        document_root=tmp_path / "documents",
        cases_jsonl=cases_path,
        command_runner=fake_runner,
        run_id="phase5g_visual",
    )

    assert summary["status"] == "success"
    assert summary["completed_count"] == 1
    assert summary["known_limitation_counts"]["visual_understanding_unsupported"] == 1
    assert summary["known_limitation_counts"]["fallback_to_local_fact_qa"] == 1
    assert summary["known_limitation_counts"]["dry_run_no_answer_generated"] == 1

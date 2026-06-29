from __future__ import annotations

import json
from pathlib import Path

from scripts.run_phase5f_full_cli_acceptance import run_phase5f_full_cli_acceptance
from scripts.run_phase5g_cli_regression import CommandResult


def _write_cli_artifacts(artifact_dir: Path, payload: dict, *, omit_trace: bool = False) -> None:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "result.json").write_text(json.dumps(payload), encoding="utf-8")
    (artifact_dir / "summary.json").write_text(
        json.dumps(
            {
                "used_external_api": False,
                "used_vlm": False,
                "used_training": False,
                "used_full_e2e": False,
                "result_status": payload.get("status"),
                "tools_used": payload.get("tools_used") or [],
            }
        ),
        encoding="utf-8",
    )
    (artifact_dir / "router_plan.json").write_text(json.dumps(payload.get("router_plan") or {}), encoding="utf-8")
    if not omit_trace:
        (artifact_dir / "trace.json").write_text(json.dumps({"tools_used": payload.get("tools_used") or []}), encoding="utf-8")


def _payload(
    *,
    output_dir: Path,
    case_name: str,
    status: str = "success",
    task_type: str = "",
    tools_used: list[str] | None = None,
    warnings: list[str] | None = None,
    error: dict | None = None,
    documents: list[dict] | None = None,
    omit_trace: bool = False,
) -> str:
    artifact_dir = "" if documents is not None else str(output_dir / case_name)
    payload = {
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
    }
    if artifact_dir:
        _write_cli_artifacts(Path(artifact_dir), payload, omit_trace=omit_trace)
    return json.dumps(payload, ensure_ascii=False)


def _fake_runner(*, omit_summary_trace: bool = False):
    def run(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        output_dir = Path(command[command.index("--output-dir") + 1])
        if "--list-documents" in command:
            return CommandResult(0, _payload(output_dir=output_dir, case_name="list", documents=[{"doc_id": "doc1"}]))
        question = command[command.index("--question") + 1]
        file_arg = command[command.index("--file") + 1] if "--file" in command else ""
        if file_arg.endswith("missing_input.txt"):
            return CommandResult(
                0,
                _payload(
                    output_dir=output_dir,
                    case_name="file_not_found",
                    status="error",
                    error={"type": "file_not_found", "message": "missing"},
                ),
            )
        if question == "How many pages are in this document?":
            return CommandResult(
                0,
                _payload(
                    output_dir=output_dir,
                    case_name="stats",
                    task_type="document_statistics",
                    tools_used=["count_pages"],
                ),
            )
        if question == "Show the text from page 1.":
            return CommandResult(
                0,
                _payload(output_dir=output_dir, case_name="page", task_type="page_lookup", tools_used=["get_page_text"]),
            )
        if question == "What date is mentioned in this document?":
            return CommandResult(
                0,
                _payload(
                    output_dir=output_dir,
                    case_name="fact",
                    task_type="local_fact_qa",
                    tools_used=["local_fact_qa"],
                    warnings=["dry_run_no_answer_generated"],
                ),
            )
        if question == "Summarize this document.":
            return CommandResult(
                0,
                _payload(
                    output_dir=output_dir,
                    case_name="summary",
                    task_type="document_summary",
                    tools_used=["document_summary"],
                    omit_trace=omit_summary_trace,
                ),
            )
        if question == "List all dates mentioned in this document.":
            return CommandResult(
                0,
                _payload(
                    output_dir=output_dir,
                    case_name="structured",
                    task_type="structured_extraction",
                    tools_used=["extract_all_dates"],
                ),
            )
        if question == "What is the difference between 2020 and 2021 revenue?":
            return CommandResult(
                0,
                _payload(
                    output_dir=output_dir,
                    case_name="table",
                    status="success",
                    task_type="table_lookup_or_calculation",
                    tools_used=["table_lookup", "simple_calculation"],
                ),
            )
        if question == "In the chart, what color is shown?":
            return CommandResult(
                0,
                _payload(
                    output_dir=output_dir,
                    case_name="visual",
                    task_type="local_fact_qa",
                    tools_used=["local_fact_qa"],
                    warnings=[
                        "visual_understanding_unsupported",
                        "fallback_to_local_fact_qa",
                        "dry_run_no_answer_generated",
                    ],
                ),
            )
        return CommandResult(0, "{}")

    return run


def test_phase5f_full_cli_acceptance_passes_required_contract(tmp_path: Path) -> None:
    result = run_phase5f_full_cli_acceptance(
        db_path=tmp_path / "docagent.db",
        output_root=tmp_path / "acceptance",
        document_root=tmp_path / "documents",
        command_runner=_fake_runner(),
        run_id="phase5f_acceptance_test",
    )

    assert result["status"] == "success"
    assert result["acceptance_status"] == "ready"
    assert result["checks"]["server_acceptance_required"] is True
    assert result["checks"]["final_answer_quality_evaluated"] is False
    assert result["checks"]["artifact_checked_count"] == result["checks"]["artifact_pass_count"]
    assert set(result["checks"]["missing_task_types"]) == set()
    assert result["not_evaluated"] == [
        "final_answer_quality",
        "visual_pixel_qa",
        "online_mineru_ocr",
        "training",
        "full_grpo_e2e",
    ]

    run_dir = Path(result["artifact_dir"])
    assert (run_dir / "acceptance_result.json").is_file()
    assert (run_dir / "acceptance_summary.md").is_file()
    assert (run_dir / "artifact_checks.jsonl").is_file()


def test_phase5f_full_cli_acceptance_fails_on_artifact_contract_gap(tmp_path: Path) -> None:
    result = run_phase5f_full_cli_acceptance(
        db_path=tmp_path / "docagent.db",
        output_root=tmp_path / "acceptance",
        document_root=tmp_path / "documents",
        command_runner=_fake_runner(omit_summary_trace=True),
        run_id="phase5f_acceptance_artifact_gap",
    )

    assert result["status"] == "failed"
    assert "artifact_contract_failed:document_summary" in result["failures"]

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "regression" / "phase5g_cli"
DEFAULT_DB_PATH = ROOT / "outputs" / "docagent.db"
DEFAULT_DOCUMENT_ROOT = ROOT / "data" / "documents"
DEFAULT_MINERU_FILE = ROOT / "data" / "real_documents" / "globocan_africa_2022" / "source" / "original.pdf"
DEFAULT_MINERU_OUTPUT = ROOT / "data" / "real_documents" / "globocan_africa_2022" / "mineru_raw"
DEFAULT_CLI_PATH = ROOT / "scripts" / "docagent_cli.py"

UNSUPPORTED_ERROR_TYPES = {
    "document_summary_not_implemented",
    "table_lookup_not_implemented",
    "structured_extraction_not_implemented",
    "unsupported_task_type",
}
KNOWN_LIMITATION_MARKERS = {
    "document_summary_not_implemented",
    "table_lookup_not_implemented",
    "structured_extraction_not_implemented",
    "visual_understanding_unsupported",
    "fallback_to_local_fact_qa",
    "dry_run_no_answer_generated",
    "mineru_fixture_missing",
}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


CommandRunner = Callable[[list[str], Path, int], CommandResult]


def _now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"phase5g_cli_{stamp}_{uuid.uuid4().hex[:8]}"


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object at {path}:{line_number}")
            rows.append(payload)
    return rows


def _default_command_runner(command: list[str], cwd: Path, timeout_seconds: int) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    return CommandResult(returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)


def _ensure_default_txt_fixture(run_dir: Path) -> Path:
    fixture = run_dir / "fixtures" / "phase5g_memo.txt"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    if not fixture.exists():
        fixture.write_text(
            "Phase 5G CLI regression memo\n"
            "Invoice Date: March 12, 2020\n"
            "Total: 42 USD\n",
            encoding="utf-8",
        )
    return fixture


def _load_cases(cases_jsonl: Path | None, *, run_dir: Path, doc_id: str, txt_fixture: Path | None) -> list[dict[str, Any]]:
    if cases_jsonl is not None:
        return _read_jsonl(cases_jsonl)

    txt_path = txt_fixture or _ensure_default_txt_fixture(run_dir)
    dynamic_doc_id = doc_id or "$FIRST_DOC_ID"
    return [
        {
            "case_id": "list_documents",
            "mode": "list_documents",
            "expected_status": "success",
            "capture_first_doc_id": True,
        },
        {
            "case_id": "stats_pages_docid",
            "mode": "doc_id",
            "doc_id": dynamic_doc_id,
            "question": "How many pages are in this document?",
            "expected_status": "success",
            "expected_task_type": "document_statistics",
            "expected_tools_any": ["count_pages"],
        },
        {
            "case_id": "page_lookup_docid",
            "mode": "doc_id",
            "doc_id": dynamic_doc_id,
            "question": "Show the text from page 1.",
            "expected_status": "success",
            "expected_task_type": "page_lookup",
            "expected_tools_any": ["get_page_text"],
        },
        {
            "case_id": "local_fact_qa_dry_run_docid",
            "mode": "doc_id",
            "doc_id": dynamic_doc_id,
            "question": "What date is mentioned in this document?",
            "dry_run": True,
            "expected_status": "success",
            "expected_task_type": "local_fact_qa",
            "expected_tools_any": ["local_fact_qa"],
            "expected_warnings_any": ["dry_run_no_answer_generated"],
            "known_limitation_allowed": True,
        },
        {
            "case_id": "txt_file_to_answer",
            "mode": "file",
            "file": str(txt_path),
            "question": "How many pages are in this document?",
            "expected_status": "success",
            "expected_task_type": "document_statistics",
            "expected_tools_any": ["count_pages"],
            "parser": "text",
        },
        {
            "case_id": "mineru_existing_file_to_answer",
            "mode": "file",
            "file": str(DEFAULT_MINERU_FILE),
            "question": "How many pages are in this document?",
            "expected_status": "success",
            "expected_task_type": "document_statistics",
            "expected_tools_any": ["count_pages"],
            "parser": "mineru_existing",
            "mineru_output_dir": str(DEFAULT_MINERU_OUTPUT),
            "skip_if_missing_paths": [str(DEFAULT_MINERU_FILE), str(DEFAULT_MINERU_OUTPUT)],
        },
        {
            "case_id": "document_summary_not_implemented",
            "mode": "doc_id",
            "doc_id": dynamic_doc_id,
            "question": "Summarize this document.",
            "expected_status": "error",
            "expected_task_type": "document_summary",
            "expected_error_type": "document_summary_not_implemented",
            "known_limitation_allowed": True,
        },
        {
            "case_id": "table_lookup_not_implemented",
            "mode": "doc_id",
            "doc_id": dynamic_doc_id,
            "question": "What is the difference between 2020 and 2021 revenue?",
            "expected_status": "error",
            "expected_task_type": "table_lookup_or_calculation",
            "expected_error_type": "table_lookup_not_implemented",
            "known_limitation_allowed": True,
        },
        {
            "case_id": "visual_pixel_qa_boundary",
            "mode": "doc_id",
            "doc_id": dynamic_doc_id,
            "question": "In the chart, what color is shown?",
            "dry_run": True,
            "expected_status": "success",
            "expected_task_type": "local_fact_qa",
            "expected_tools_any": ["local_fact_qa"],
            "expected_warnings_any": ["visual_understanding_unsupported"],
            "known_limitation_allowed": True,
        },
        {
            "case_id": "file_not_found",
            "mode": "file",
            "file": str(run_dir / "fixtures" / "missing_input.txt"),
            "question": "How many pages are in this document?",
            "expected_status": "error",
            "expected_error_type": "file_not_found",
        },
    ]


def _resolve_dynamic_value(value: Any, context: dict[str, Any]) -> Any:
    if value == "$FIRST_DOC_ID":
        return context.get("first_doc_id") or ""
    return value


def _skip_reason(case: dict[str, Any], context: dict[str, Any]) -> str:
    for raw_path in case.get("skip_if_missing_paths") or []:
        if not _project_path(str(raw_path)).exists():
            return "mineru_fixture_missing" if "mineru" in str(raw_path).lower() else "fixture_missing"
    if case.get("mode") == "doc_id" and not _resolve_dynamic_value(case.get("doc_id") or "", context):
        return "doc_id_unavailable"
    return ""


def _build_cli_command(
    case: dict[str, Any],
    *,
    db_path: Path,
    document_root: Path,
    cli_output_dir: Path,
    cli_path: Path,
    python_executable: str,
    limit: int,
    context: dict[str, Any],
) -> list[str]:
    command = [
        python_executable,
        str(cli_path),
        "--db-path",
        str(db_path),
        "--output-dir",
        str(cli_output_dir),
    ]
    mode = str(case.get("mode") or "")
    if mode == "list_documents":
        command.extend(["--list-documents", "--limit", str(int(case.get("limit") or limit))])
        return command

    question = str(case.get("question") or "")
    if mode == "doc_id":
        command.extend(["--doc-id", str(_resolve_dynamic_value(case.get("doc_id") or "", context))])
    elif mode == "file":
        command.extend(["--document-root", str(document_root), "--file", str(_project_path(str(case.get("file") or "")))])
        if case.get("parser"):
            command.extend(["--parser", str(case["parser"])])
        if case.get("parser_mode"):
            command.extend(["--parser-mode", str(case["parser_mode"])])
        if case.get("mineru_output_dir"):
            command.extend(["--mineru-output-dir", str(_project_path(str(case["mineru_output_dir"])))])
    else:
        raise ValueError(f"Unsupported regression case mode: {mode}")

    command.extend(["--question", question])
    if bool(case.get("dry_run")):
        command.append("--dry-run")
    for extra_arg in case.get("extra_args") or []:
        command.append(str(extra_arg))
    return command


def _parse_stdout(stdout: str) -> tuple[dict[str, Any] | None, str]:
    stripped = stdout.strip()
    if not stripped:
        return None, "stdout_empty"
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None, "stdout_not_json"
    if not isinstance(payload, dict):
        return None, "stdout_json_not_object"
    return payload, ""


def _all_warnings(payload: dict[str, Any]) -> list[str]:
    warnings = [str(item) for item in payload.get("warnings") or []]
    router = payload.get("router_plan") if isinstance(payload.get("router_plan"), dict) else {}
    warnings.extend(str(item) for item in router.get("warnings") or [])
    return list(dict.fromkeys(warnings))


def _validate_case(case: dict[str, Any], payload: dict[str, Any] | None, parse_error: str, returncode: int) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if parse_error:
        failures.append(parse_error)
        return False, failures
    assert payload is not None
    expected_status = case.get("expected_status")
    if expected_status and payload.get("status") != expected_status:
        failures.append(f"status_mismatch:{payload.get('status')}!={expected_status}")
    expected_task_type = case.get("expected_task_type")
    if expected_task_type and payload.get("task_type") != expected_task_type:
        failures.append(f"task_type_mismatch:{payload.get('task_type')}!={expected_task_type}")
    expected_error_type = case.get("expected_error_type")
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    if expected_error_type and error.get("type") != expected_error_type:
        failures.append(f"error_type_mismatch:{error.get('type')}!={expected_error_type}")
    expected_tools = set(str(item) for item in case.get("expected_tools_any") or [])
    if expected_tools:
        actual_tools = set(str(item) for item in payload.get("tools_used") or [])
        if expected_tools.isdisjoint(actual_tools):
            failures.append("expected_tool_missing")
    expected_warnings = set(str(item) for item in case.get("expected_warnings_any") or [])
    if expected_warnings:
        actual_warnings = set(_all_warnings(payload))
        if expected_warnings.isdisjoint(actual_warnings):
            failures.append("expected_warning_missing")
    if returncode != 0:
        failures.append(f"nonzero_returncode:{returncode}")
    return not failures, failures


def _artifact_written(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    artifact_dir = payload.get("artifact_dir")
    if not artifact_dir:
        return False
    path = Path(str(artifact_dir))
    return path.is_dir() and (path / "result.json").is_file()


def _known_limitations(case: dict[str, Any], payload: dict[str, Any] | None, skip_reason: str) -> list[str]:
    markers: list[str] = []
    if skip_reason in KNOWN_LIMITATION_MARKERS:
        markers.append(skip_reason)
    if payload:
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        if error.get("type") in KNOWN_LIMITATION_MARKERS:
            markers.append(str(error["type"]))
        for warning in _all_warnings(payload):
            if warning in KNOWN_LIMITATION_MARKERS:
                markers.append(warning)
    if not bool(case.get("known_limitation_allowed")):
        return []
    return list(dict.fromkeys(markers))


def _result_row_for_skip(case: dict[str, Any], reason: str) -> dict[str, Any]:
    limitations = [reason] if reason in KNOWN_LIMITATION_MARKERS and bool(case.get("known_limitation_allowed", True)) else []
    return {
        "case_id": case.get("case_id") or "",
        "outcome": "skipped",
        "skip_reason": reason,
        "json_valid": False,
        "artifact_written": False,
        "expected_status": case.get("expected_status") or "",
        "expected_task_type": case.get("expected_task_type") or "",
        "task_type": "",
        "router_task_type": "",
        "tools_used": [],
        "warnings": [],
        "error": {"type": reason, "message": "Regression case prerequisite was not available."},
        "known_limitations": limitations,
        "validation_failures": [],
        "returncode": None,
        "stdout_preview": "",
        "stderr_preview": "",
        "command": [],
    }


def _result_row_for_command(
    case: dict[str, Any],
    *,
    command: list[str],
    completed: CommandResult,
) -> dict[str, Any]:
    payload, parse_error = _parse_stdout(completed.stdout)
    valid, failures = _validate_case(case, payload, parse_error, completed.returncode)
    error = payload.get("error") if payload and isinstance(payload.get("error"), dict) else {}
    error_type = str(error.get("type") or "")
    if valid and error_type in UNSUPPORTED_ERROR_TYPES:
        outcome = "unsupported"
    elif valid:
        outcome = "completed"
    else:
        outcome = "failed"
    router = payload.get("router_plan") if payload and isinstance(payload.get("router_plan"), dict) else {}
    return {
        "case_id": case.get("case_id") or "",
        "outcome": outcome,
        "json_valid": payload is not None,
        "artifact_written": _artifact_written(payload),
        "expected_status": case.get("expected_status") or "",
        "expected_task_type": case.get("expected_task_type") or "",
        "task_type": payload.get("task_type") if payload else "",
        "router_task_type": router.get("task_type") or "",
        "tools_used": payload.get("tools_used") if payload else [],
        "warnings": _all_warnings(payload) if payload else [],
        "error": error,
        "known_limitations": _known_limitations(case, payload, ""),
        "validation_failures": failures,
        "returncode": completed.returncode,
        "stdout_preview": completed.stdout.strip()[:500],
        "stderr_preview": completed.stderr.strip()[:500],
        "command": command,
        "artifact_dir": payload.get("artifact_dir") if payload else "",
    }


def _summarize(run_id: str, run_dir: Path, cases: list[dict[str, Any]], rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcome_counts = Counter(str(row.get("outcome") or "") for row in rows)
    task_types = Counter(str(row.get("task_type") or "unknown") for row in rows if row.get("task_type"))
    tools = Counter(tool for row in rows for tool in (row.get("tools_used") or []))
    failures = Counter()
    unsupported = Counter()
    skipped = Counter()
    known = Counter()
    for row in rows:
        error = row.get("error") if isinstance(row.get("error"), dict) else {}
        reason = str(row.get("skip_reason") or error.get("type") or (row.get("validation_failures") or ["unknown"])[0])
        if row.get("outcome") == "failed":
            failures[reason] += 1
        elif row.get("outcome") == "unsupported":
            unsupported[reason] += 1
        elif row.get("outcome") == "skipped":
            skipped[reason] += 1
        for marker in row.get("known_limitations") or []:
            known[str(marker)] += 1
    summary = {
        "status": "success" if outcome_counts.get("failed", 0) == 0 else "failed",
        "run_id": run_id,
        "artifact_dir": str(run_dir),
        "case_count": len(cases),
        "completed_count": outcome_counts.get("completed", 0),
        "failed_count": outcome_counts.get("failed", 0),
        "skipped_count": outcome_counts.get("skipped", 0),
        "unsupported_count": outcome_counts.get("unsupported", 0),
        "json_valid_count": sum(1 for row in rows if row.get("json_valid")),
        "artifact_write_count": sum(1 for row in rows if row.get("artifact_written")),
        "task_type_distribution": dict(sorted(task_types.items())),
        "tools_used_distribution": dict(sorted(tools.items())),
        "failure_taxonomy": dict(sorted(failures.items())),
        "unsupported_taxonomy": dict(sorted(unsupported.items())),
        "skipped_taxonomy": dict(sorted(skipped.items())),
        "known_limitation_counts": dict(sorted(known.items())),
        "used_external_api": False,
        "used_vlm": False,
        "used_training": False,
        "used_full_e2e": False,
    }
    summary["cases_path"] = str(run_dir / "regression_cases.jsonl")
    summary["results_path"] = str(run_dir / "regression_results.jsonl")
    summary["summary_path"] = str(run_dir / "regression_summary.json")
    summary["summary_md_path"] = str(run_dir / "regression_summary.md")
    summary["preview_path"] = str(run_dir / "preview.json")
    return summary


def _write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Phase 5G CLI Regression Summary",
        "",
        f"- run_id: `{summary['run_id']}`",
        f"- status: `{summary['status']}`",
        f"- case_count: {summary['case_count']}",
        f"- completed_count: {summary['completed_count']}",
        f"- failed_count: {summary['failed_count']}",
        f"- skipped_count: {summary['skipped_count']}",
        f"- unsupported_count: {summary['unsupported_count']}",
        f"- json_valid_count: {summary['json_valid_count']}",
        f"- artifact_write_count: {summary['artifact_write_count']}",
        "",
        "This is an execution regression baseline, not a benchmark accuracy report.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_phase5g_regression(
    *,
    db_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    document_root: Path = DEFAULT_DOCUMENT_ROOT,
    cli_path: Path = DEFAULT_CLI_PATH,
    cases_jsonl: Path | None = None,
    doc_id: str = "",
    txt_fixture: Path | None = None,
    limit: int = 20,
    python_executable: str = sys.executable,
    timeout_seconds: int = 120,
    command_runner: CommandRunner = _default_command_runner,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or _now_run_id()
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    cli_output_dir = run_dir / "cli_artifacts"
    document_root.mkdir(parents=True, exist_ok=True)

    cases = _load_cases(cases_jsonl, run_dir=run_dir, doc_id=doc_id, txt_fixture=txt_fixture)
    context: dict[str, Any] = {"first_doc_id": doc_id}
    rows: list[dict[str, Any]] = []
    for case in cases:
        reason = _skip_reason(case, context)
        if reason:
            rows.append(_result_row_for_skip(case, reason))
            continue
        command = _build_cli_command(
            case,
            db_path=db_path,
            document_root=document_root,
            cli_output_dir=cli_output_dir,
            cli_path=cli_path,
            python_executable=python_executable,
            limit=limit,
            context=context,
        )
        completed = command_runner(command, ROOT, timeout_seconds)
        row = _result_row_for_command(case, command=command, completed=completed)
        rows.append(row)
        if case.get("capture_first_doc_id") and row.get("json_valid"):
            payload, _parse_error = _parse_stdout(completed.stdout)
            documents = payload.get("documents") if payload else None
            if isinstance(documents, list) and documents:
                first = documents[0]
                if isinstance(first, dict) and first.get("doc_id") and not context.get("first_doc_id"):
                    context["first_doc_id"] = str(first["doc_id"])

    summary = _summarize(run_id, run_dir, cases, rows)
    preview = {"run_id": run_id, "summary": summary, "results": rows[:5]}
    _write_jsonl(run_dir / "regression_cases.jsonl", cases)
    _write_jsonl(run_dir / "regression_results.jsonl", rows)
    _write_json(run_dir / "regression_summary.json", summary)
    _write_summary_md(run_dir / "regression_summary.md", summary)
    _write_json(run_dir / "preview.json", preview)
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Phase 5G multi-task CLI regression baseline.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--document-root", default=str(DEFAULT_DOCUMENT_ROOT))
    parser.add_argument("--cli-path", default=str(DEFAULT_CLI_PATH))
    parser.add_argument("--cases-jsonl")
    parser.add_argument("--doc-id", default="")
    parser.add_argument("--txt-fixture")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    summary = run_phase5g_regression(
        db_path=_project_path(args.db_path),
        output_root=_project_path(args.output_dir),
        document_root=_project_path(args.document_root),
        cli_path=_project_path(args.cli_path),
        cases_jsonl=_project_path(args.cases_jsonl) if args.cases_jsonl else None,
        doc_id=str(args.doc_id or ""),
        txt_fixture=_project_path(args.txt_fixture) if args.txt_fixture else None,
        limit=int(args.limit),
        python_executable=str(args.python_executable),
        timeout_seconds=int(args.timeout_seconds),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if summary.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

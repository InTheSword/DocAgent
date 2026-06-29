from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_phase5g_cli_regression import (  # noqa: E402
    DEFAULT_CLI_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_DOCUMENT_ROOT,
    CommandRunner,
    _default_command_runner,
    run_phase5g_regression,
)

DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "acceptance" / "phase5f_full_cli"
REQUIRED_COMPLETED_CASES = {
    "list_documents",
    "stats_pages_docid",
    "page_lookup_docid",
    "local_fact_qa_dry_run_docid",
    "txt_file_to_answer",
    "document_summary",
    "structured_extract_dates",
    "visual_pixel_qa_boundary",
    "file_not_found",
}
REQUIRED_UNSUPPORTED_CASES = {
    "table_lookup_not_implemented": "table_lookup_not_implemented",
}
OPTIONAL_CASES = {"mineru_existing_file_to_answer"}
REQUIRED_TASK_TYPES = {
    "document_statistics",
    "page_lookup",
    "local_fact_qa",
    "document_summary",
    "structured_extraction",
    "table_lookup_or_calculation",
}
REQUIRED_ARTIFACT_FILES = ("result.json", "summary.json", "router_plan.json", "trace.json")


def _now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"phase5f_full_cli_{stamp}_{uuid.uuid4().hex[:8]}"


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return payload


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


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


def _case_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("case_id") or ""): row for row in rows}


def _artifact_check_for_row(row: dict[str, Any]) -> dict[str, Any]:
    case_id = str(row.get("case_id") or "")
    if case_id == "list_documents" or row.get("outcome") == "skipped":
        return {
            "case_id": case_id,
            "checked": False,
            "ok": True,
            "reason": "artifact_not_required",
        }

    artifact_dir = Path(str(row.get("artifact_dir") or ""))
    missing = [name for name in REQUIRED_ARTIFACT_FILES if not (artifact_dir / name).is_file()]
    summary_flags: dict[str, Any] = {}
    summary_flags_ok = False
    if not missing:
        summary = _read_json(artifact_dir / "summary.json")
        summary_flags = {
            "used_external_api": bool(summary.get("used_external_api", False)),
            "used_vlm": bool(summary.get("used_vlm", False)),
            "used_training": bool(summary.get("used_training", False)),
            "used_full_e2e": bool(summary.get("used_full_e2e", False)),
        }
        summary_flags_ok = not any(summary_flags.values())

    return {
        "case_id": case_id,
        "checked": True,
        "ok": bool(artifact_dir.is_dir() and not missing and summary_flags_ok),
        "artifact_dir": str(artifact_dir),
        "missing_files": missing,
        "summary_flags": summary_flags,
    }


def _evaluate_acceptance(
    *,
    regression_summary: dict[str, Any],
    rows: list[dict[str, Any]],
    require_mineru_existing: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    failures: list[str] = []
    by_case = _case_map(rows)

    if regression_summary.get("status") != "success":
        failures.append("phase5g_regression_status_not_success")

    for case_id in sorted(REQUIRED_COMPLETED_CASES):
        row = by_case.get(case_id)
        if row is None:
            failures.append(f"required_case_missing:{case_id}")
            continue
        if row.get("outcome") != "completed":
            failures.append(f"required_case_not_completed:{case_id}:{row.get('outcome')}")

    for case_id, expected_error in REQUIRED_UNSUPPORTED_CASES.items():
        row = by_case.get(case_id)
        if row is None:
            failures.append(f"unsupported_boundary_case_missing:{case_id}")
            continue
        error = row.get("error") if isinstance(row.get("error"), dict) else {}
        if row.get("outcome") != "unsupported" or error.get("type") != expected_error:
            failures.append(f"unsupported_boundary_mismatch:{case_id}:{row.get('outcome')}:{error.get('type')}")

    for case_id in sorted(OPTIONAL_CASES):
        row = by_case.get(case_id)
        if require_mineru_existing and (row is None or row.get("outcome") != "completed"):
            failures.append(f"optional_case_required_but_not_completed:{case_id}:{row.get('outcome') if row else 'missing'}")

    task_types = {str(row.get("task_type") or "") for row in rows if row.get("task_type")}
    missing_task_types = sorted(REQUIRED_TASK_TYPES - task_types)
    for task_type in missing_task_types:
        failures.append(f"required_task_type_missing:{task_type}")

    artifact_checks = [_artifact_check_for_row(row) for row in rows]
    for item in artifact_checks:
        if item.get("checked") and not item.get("ok"):
            failures.append(f"artifact_contract_failed:{item.get('case_id')}")

    outcome_counts = Counter(str(row.get("outcome") or "") for row in rows)
    checks = {
        "required_completed_cases": sorted(REQUIRED_COMPLETED_CASES),
        "required_unsupported_cases": REQUIRED_UNSUPPORTED_CASES,
        "optional_cases": sorted(OPTIONAL_CASES),
        "require_mineru_existing": require_mineru_existing,
        "required_task_types": sorted(REQUIRED_TASK_TYPES),
        "missing_task_types": missing_task_types,
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "artifact_checked_count": sum(1 for item in artifact_checks if item.get("checked")),
        "artifact_pass_count": sum(1 for item in artifact_checks if item.get("checked") and item.get("ok")),
        "server_acceptance_required": True,
        "final_answer_quality_evaluated": False,
        "used_external_api": bool(regression_summary.get("used_external_api", False)),
        "used_vlm": bool(regression_summary.get("used_vlm", False)),
        "used_training": bool(regression_summary.get("used_training", False)),
        "used_full_e2e": bool(regression_summary.get("used_full_e2e", False)),
    }
    result = {
        "status": "success" if not failures else "failed",
        "acceptance_status": "ready" if not failures else "blocked",
        "phase": "Phase 5F full CLI acceptance",
        "evaluation_scope": "full_cli_entrypoint_acceptance",
        "regression_status": regression_summary.get("status"),
        "regression_run_id": regression_summary.get("run_id"),
        "regression_artifact_dir": regression_summary.get("artifact_dir"),
        "case_count": len(rows),
        "checks": checks,
        "failures": failures,
        "artifact_checks": artifact_checks,
        "not_evaluated": [
            "final_answer_quality",
            "table_lookup",
            "simple_calculation",
            "visual_pixel_qa",
            "online_mineru_ocr",
            "training",
            "full_grpo_e2e",
        ],
    }
    return result, artifact_checks


def _write_summary_md(path: Path, payload: dict[str, Any]) -> None:
    lines = [
        "# Phase 5F Full CLI Acceptance",
        "",
        f"- status: `{payload['status']}`",
        f"- acceptance_status: `{payload['acceptance_status']}`",
        f"- regression_run_id: `{payload.get('regression_run_id')}`",
        f"- case_count: {payload['case_count']}",
        f"- artifact_checked_count: {payload['checks']['artifact_checked_count']}",
        f"- artifact_pass_count: {payload['checks']['artifact_pass_count']}",
        f"- server_acceptance_required: `{payload['checks']['server_acceptance_required']}`",
        f"- final_answer_quality_evaluated: `{payload['checks']['final_answer_quality_evaluated']}`",
        "",
        "This acceptance runner validates the unified CLI contract and artifacts; it does not evaluate answer correctness.",
    ]
    if payload["failures"]:
        lines.extend(["", "## Failures"])
        lines.extend(f"- `{item}`" for item in payload["failures"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_phase5f_full_cli_acceptance(
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
    command_runner: CommandRunner | None = None,
    run_id: str | None = None,
    require_mineru_existing: bool = False,
) -> dict[str, Any]:
    run_id = run_id or _now_run_id()
    regression_summary = run_phase5g_regression(
        db_path=db_path,
        output_root=output_root,
        document_root=document_root,
        cli_path=cli_path,
        cases_jsonl=cases_jsonl,
        doc_id=doc_id,
        txt_fixture=txt_fixture,
        limit=limit,
        python_executable=python_executable,
        timeout_seconds=timeout_seconds,
        command_runner=command_runner or _default_command_runner,
        run_id=run_id,
    )
    run_dir = Path(str(regression_summary["artifact_dir"]))
    rows = _read_jsonl(run_dir / "regression_results.jsonl")
    acceptance, artifact_checks = _evaluate_acceptance(
        regression_summary=regression_summary,
        rows=rows,
        require_mineru_existing=require_mineru_existing,
    )
    acceptance["artifact_dir"] = str(run_dir)
    acceptance["artifact_paths"] = {
        "acceptance_result": str(run_dir / "acceptance_result.json"),
        "acceptance_summary": str(run_dir / "acceptance_summary.md"),
        "artifact_checks": str(run_dir / "artifact_checks.jsonl"),
        "regression_summary": str(run_dir / "regression_summary.json"),
        "regression_results": str(run_dir / "regression_results.jsonl"),
    }
    _write_json(run_dir / "acceptance_result.json", acceptance)
    _write_jsonl(run_dir / "artifact_checks.jsonl", artifact_checks)
    _write_summary_md(run_dir / "acceptance_summary.md", acceptance)
    return acceptance


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase 5F full CLI acceptance over the unified DocAgent CLI.")
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
    parser.add_argument("--require-mineru-existing", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run_phase5f_full_cli_acceptance(
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
            require_mineru_existing=bool(args.require_mineru_existing),
        )
    except Exception as exc:
        result = {
            "status": "failed",
            "acceptance_status": "blocked",
            "phase": "Phase 5F full CLI acceptance",
            "error": {"type": type(exc).__name__, "message": str(exc)},
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

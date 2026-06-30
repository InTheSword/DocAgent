from __future__ import annotations

import argparse
import hashlib
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

DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "smoke" / "final_raw_pdf"
DEFAULT_CLI_PATH = ROOT / "scripts" / "docagent_cli.py"
REQUIRED_ARTIFACT_FILES = ("result.json", "summary.json", "router_plan.json", "trace.json")


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


CommandRunner = Callable[[list[str], Path, int], CommandResult]


@dataclass(frozen=True)
class RawPdfSmokeCase:
    case_id: str
    question: str
    expected_task_type: str
    expected_tools_any: tuple[str, ...]
    require_citation: bool = False
    require_evidence_used: bool = False
    require_first_ingestion: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "expected_task_type": self.expected_task_type,
            "expected_tools_any": list(self.expected_tools_any),
            "require_citation": self.require_citation,
            "require_evidence_used": self.require_evidence_used,
            "require_first_ingestion": self.require_first_ingestion,
        }


def default_cases() -> list[RawPdfSmokeCase]:
    return [
        RawPdfSmokeCase(
            case_id="raw_pdf_document_statistics",
            question="How many pages are in this document?",
            expected_task_type="document_statistics",
            expected_tools_any=("count_pages",),
            require_first_ingestion=True,
        ),
        RawPdfSmokeCase(
            case_id="raw_pdf_page_lookup",
            question="Show the text from page 1.",
            expected_task_type="page_lookup",
            expected_tools_any=("get_page_text",),
            require_citation=True,
            require_evidence_used=True,
        ),
        RawPdfSmokeCase(
            case_id="raw_pdf_document_summary",
            question="Summarize this document.",
            expected_task_type="document_summary",
            expected_tools_any=("document_summary",),
            require_citation=True,
            require_evidence_used=True,
        ),
        RawPdfSmokeCase(
            case_id="raw_pdf_local_fact_qa",
            question="What information is mentioned in the document?",
            expected_task_type="local_fact_qa",
            expected_tools_any=("local_fact_qa",),
            require_citation=True,
            require_evidence_used=True,
        ),
    ]


def _now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"final_raw_pdf_smoke_{stamp}_{uuid.uuid4().hex[:8]}"


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


def _safe_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _default_command_runner(command: list[str], cwd: Path, timeout_seconds: int) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
        timeout=timeout_seconds,
    )
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


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


def _build_cli_command(
    *,
    case: RawPdfSmokeCase,
    pdf_path: Path,
    db_path: Path,
    document_root: Path,
    cli_output_dir: Path,
    cli_path: Path,
    parser_name: str,
    mineru_command: str,
    mineru_timeout_seconds: int,
    live_api: bool,
    mineru_env_file: Path | None,
    mineru_api_timeout_seconds: int,
    mineru_api_poll_interval_seconds: float,
    python_executable: str,
) -> list[str]:
    command = [
        python_executable,
        str(cli_path),
        "--db-path",
        str(db_path),
        "--document-root",
        str(document_root),
        "--file",
        str(pdf_path),
        "--parser",
        parser_name,
    ]
    if parser_name == "mineru":
        command.extend(
            [
                "--parser-mode",
                "local_cli",
                "--mineru-command",
                mineru_command,
                "--mineru-timeout-seconds",
                str(mineru_timeout_seconds),
            ]
        )
    elif parser_name == "mineru_api":
        if live_api:
            command.append("--live-api")
        if mineru_env_file is not None:
            command.extend(["--mineru-env-file", str(mineru_env_file)])
        command.extend(
            [
                "--mineru-api-timeout-seconds",
                str(mineru_api_timeout_seconds),
                "--mineru-api-poll-interval-seconds",
                str(mineru_api_poll_interval_seconds),
            ]
        )
    command.extend(
        [
        "--question",
        case.question,
        "--output-dir",
        str(cli_output_dir),
        ]
    )
    return command


def _artifact_failures(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return ["artifact_payload_missing"]
    artifact_dir = Path(str(payload.get("artifact_dir") or ""))
    if not artifact_dir.is_dir():
        return ["artifact_dir_missing"]
    missing = [name for name in REQUIRED_ARTIFACT_FILES if not (artifact_dir / name).is_file()]
    failures = [f"artifact_file_missing:{name}" for name in missing]
    trace_path = Path(str(payload.get("trace_path") or artifact_dir / "trace.json"))
    if not trace_path.is_file():
        failures.append("trace_path_missing")
    return failures


def _citation_contract_failures(payload: dict[str, Any], *, require_citation: bool, require_evidence_used: bool) -> list[str]:
    failures: list[str] = []
    citations = payload.get("citations") if isinstance(payload.get("citations"), list) else []
    evidence_used = payload.get("evidence_used") if isinstance(payload.get("evidence_used"), list) else []
    if require_citation and not citations:
        failures.append("citations_empty")
    if require_evidence_used and not evidence_used:
        failures.append("evidence_used_empty")
    for index, citation in enumerate(citations):
        if not isinstance(citation, dict):
            failures.append(f"citation_not_object:{index}")
            continue
        for key in ("doc_id", "page", "block_id", "block_type", "text_preview"):
            if citation.get(key) in (None, ""):
                failures.append(f"citation_missing_{key}:{index}")
    return failures


def _first_ingestion_failures(payload: dict[str, Any], *, document_root: Path, parser_name: str) -> list[str]:
    failures: list[str] = []
    source = payload.get("source") if isinstance(payload.get("source"), dict) else {}
    doc_id = str(payload.get("doc_id") or source.get("resolved_doc_id") or "")
    if source.get("was_ingested") is not True:
        failures.append("source_was_ingested_false")
    if source.get("parser") != parser_name:
        failures.append(f"source_parser_mismatch:{source.get('parser')}!={parser_name}")
    expected_mode = "local_cli" if parser_name == "mineru" else "parse_existing"
    if source.get("parser_mode") != expected_mode:
        failures.append(f"source_parser_mode_mismatch:{source.get('parser_mode')}!={expected_mode}")
    ingestion = source.get("ingestion") if isinstance(source.get("ingestion"), dict) else {}
    if ingestion.get("parse_status") != "parsed":
        failures.append(f"ingestion_parse_status_not_parsed:{ingestion.get('parse_status')}")
    if int(ingestion.get("block_count") or 0) <= 0:
        failures.append("ingestion_block_count_empty")
    if int(ingestion.get("page_count") or 0) <= 0:
        failures.append("ingestion_page_count_empty")
    mineru_dir = document_root / doc_id / "mineru"
    if parser_name == "mineru_api":
        if source.get("used_mineru_api") is not True:
            failures.append("source_used_mineru_api_false")
        api_summary = source.get("mineru_api") if isinstance(source.get("mineru_api"), dict) else {}
        if api_summary.get("api_status") not in {"submitted", "cached"}:
            failures.append(f"mineru_api_status_unexpected:{api_summary.get('api_status')}")
        if not (mineru_dir / "mineru_api_manifest.json").is_file():
            failures.append("mineru_api_manifest_missing")
        return failures
    cli_result_path = mineru_dir / "mineru_cli_result.json"
    if not cli_result_path.is_file():
        failures.append("mineru_cli_result_missing")
        return failures
    try:
        cli_result = json.loads(cli_result_path.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        failures.append(f"mineru_cli_result_unreadable:{type(exc).__name__}")
        return failures
    if cli_result.get("command_found") is not True:
        failures.append("mineru_command_not_found")
    if cli_result.get("timed_out") is True:
        failures.append("mineru_command_timed_out")
    if cli_result.get("returncode") != 0:
        failures.append(f"mineru_returncode_not_zero:{cli_result.get('returncode')}")
    return failures


def _validate_case(
    *,
    case: RawPdfSmokeCase,
    payload: dict[str, Any] | None,
    parse_error: str,
    returncode: int,
    document_root: Path,
    parser_name: str,
) -> list[str]:
    failures: list[str] = []
    if parse_error:
        failures.append(parse_error)
        return failures
    assert payload is not None
    if returncode != 0:
        failures.append(f"nonzero_returncode:{returncode}")
    if payload.get("status") != "success":
        error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
        failures.append(f"status_not_success:{payload.get('status')}:{error.get('type')}")
    if payload.get("task_type") != case.expected_task_type:
        failures.append(f"task_type_mismatch:{payload.get('task_type')}!={case.expected_task_type}")
    actual_tools = set(str(item) for item in payload.get("tools_used") or [])
    if actual_tools.isdisjoint(set(case.expected_tools_any)):
        failures.append("expected_tool_missing")
    failures.extend(_artifact_failures(payload))
    failures.extend(
        _citation_contract_failures(
            payload,
            require_citation=case.require_citation,
            require_evidence_used=case.require_evidence_used,
        )
    )
    if case.require_first_ingestion:
        failures.extend(_first_ingestion_failures(payload, document_root=document_root, parser_name=parser_name))
    return failures


def _row_for_case(
    *,
    case: RawPdfSmokeCase,
    command: list[str],
    completed: CommandResult,
    document_root: Path,
    parser_name: str,
) -> dict[str, Any]:
    payload, parse_error = _parse_stdout(completed.stdout)
    failures = _validate_case(
        case=case,
        payload=payload,
        parse_error=parse_error,
        returncode=completed.returncode,
        document_root=document_root,
        parser_name=parser_name,
    )
    source = payload.get("source") if payload and isinstance(payload.get("source"), dict) else {}
    ingestion = source.get("ingestion") if isinstance(source.get("ingestion"), dict) else {}
    return {
        **case.to_dict(),
        "pass_fail": "failed" if failures else "passed",
        "failure_reasons": failures,
        "returncode": completed.returncode,
        "json_valid": payload is not None,
        "status": payload.get("status") if payload else "",
        "doc_id": payload.get("doc_id") if payload else "",
        "task_type": payload.get("task_type") if payload else "",
        "tools_used": payload.get("tools_used") if payload else [],
        "artifact_dir": payload.get("artifact_dir") if payload else "",
        "trace_path": payload.get("trace_path") if payload else "",
        "citation_count": len(payload.get("citations") or []) if payload else 0,
        "evidence_used_count": len(payload.get("evidence_used") or []) if payload else 0,
        "source_was_ingested": source.get("was_ingested"),
        "source_reused_existing": source.get("reused_existing"),
        "source_parser": source.get("parser") or "",
        "source_parser_mode": source.get("parser_mode") or "",
        "ingestion_parse_status": ingestion.get("parse_status") or "",
        "ingestion_page_count": ingestion.get("page_count"),
        "ingestion_block_count": ingestion.get("block_count"),
        "stdout_preview": completed.stdout.strip()[:1000],
        "stderr_preview": completed.stderr.strip()[:1000],
        "command": command,
    }


def _build_summary(
    *,
    run_id: str,
    run_dir: Path,
    pdf_path: Path,
    db_path: Path,
    document_root: Path,
    parser_name: str,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    pass_counts = Counter(str(row.get("pass_fail") or "") for row in rows)
    task_counts = Counter(str(row.get("task_type") or "") for row in rows if row.get("task_type"))
    failure_counts = Counter(reason for row in rows for reason in row.get("failure_reasons") or [])
    doc_ids = sorted({str(row.get("doc_id") or "") for row in rows if row.get("doc_id")})
    return {
        "command": "final_raw_pdf_smoke",
        "status": "success" if pass_counts.get("failed", 0) == 0 else "failed",
        "quality_status": "execution_smoke_only",
        "run_id": run_id,
        "artifact_dir": _safe_relpath(run_dir),
        "pdf_path": str(pdf_path),
        "db_path": str(db_path),
        "document_root": str(document_root),
        "doc_ids": doc_ids,
        "case_count": len(rows),
        "passed_count": pass_counts.get("passed", 0),
        "failed_count": pass_counts.get("failed", 0),
        "json_valid_count": sum(1 for row in rows if row.get("json_valid")),
        "artifact_write_count": sum(1 for row in rows if row.get("artifact_dir")),
        "citation_case_count": sum(1 for row in rows if int(row.get("citation_count") or 0) > 0),
        "evidence_used_case_count": sum(1 for row in rows if int(row.get("evidence_used_count") or 0) > 0),
        "task_type_distribution": dict(sorted(task_counts.items())),
        "failure_reason_distribution": dict(sorted(failure_counts.items())),
        "parser": parser_name,
        "used_mineru_local_cli": parser_name == "mineru",
        "used_mineru_api": parser_name == "mineru_api",
        "used_online_mineru_ocr": parser_name == "mineru_api",
        "used_external_api": parser_name == "mineru_api",
        "used_qwen": False,
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "acceptance_note": "Raw PDF execution smoke validates CLI parsing, ingestion, citation/artifact contract, and MinerU parser integration; it does not evaluate answer correctness.",
    }


def _write_summary_md(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Final Raw PDF Smoke",
        "",
        f"- status: `{summary['status']}`",
        f"- quality_status: `{summary['quality_status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- case_count: {summary['case_count']}",
        f"- passed_count: {summary['passed_count']}",
        f"- failed_count: {summary['failed_count']}",
        f"- parser: `{summary['parser']}`",
        f"- used_mineru_local_cli: `{str(summary['used_mineru_local_cli']).lower()}`",
        f"- used_mineru_api: `{str(summary['used_mineru_api']).lower()}`",
        f"- used_qwen: `{str(summary['used_qwen']).lower()}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
        "",
        summary["acceptance_note"],
    ]
    if summary.get("failure_reason_distribution"):
        lines.extend(["", "## Failures"])
        lines.extend(f"- {key}: {value}" for key, value in sorted(summary["failure_reason_distribution"].items()))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files: list[dict[str, Any]] = []
    for artifact in artifact_paths:
        if not artifact.is_file():
            continue
        data = artifact.read_bytes()
        files.append({"path": _safe_relpath(artifact), "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    _write_json(path, {"run_id": run_id, "files": files})


def run_final_raw_pdf_smoke(
    *,
    pdf_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    db_path: Path | None = None,
    document_root: Path | None = None,
    cli_path: Path = DEFAULT_CLI_PATH,
    parser_name: str = "mineru",
    mineru_command: str = "mineru",
    mineru_timeout_seconds: int = 600,
    live_api: bool = False,
    mineru_env_file: Path | None = None,
    mineru_api_timeout_seconds: int = 900,
    mineru_api_poll_interval_seconds: float = 5.0,
    python_executable: str = sys.executable,
    timeout_seconds: int = 900,
    command_runner: CommandRunner = _default_command_runner,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or _now_run_id()
    if parser_name not in {"mineru", "mineru_api"}:
        raise ValueError(f"unsupported parser for raw PDF smoke: {parser_name}")
    run_dir = output_root / run_id
    cli_output_dir = run_dir / "cli_artifacts"
    db_path = db_path or (run_dir / "docagent.db")
    document_root = document_root or (run_dir / "documents")
    run_dir.mkdir(parents=True, exist_ok=True)
    cli_output_dir.mkdir(parents=True, exist_ok=True)
    document_root.mkdir(parents=True, exist_ok=True)

    cases = default_cases()
    rows: list[dict[str, Any]] = []
    for case in cases:
        command = _build_cli_command(
            case=case,
            pdf_path=pdf_path,
            db_path=db_path,
            document_root=document_root,
            cli_output_dir=cli_output_dir,
            cli_path=cli_path,
            parser_name=parser_name,
            mineru_command=mineru_command,
            mineru_timeout_seconds=mineru_timeout_seconds,
            live_api=live_api,
            mineru_env_file=mineru_env_file,
            mineru_api_timeout_seconds=mineru_api_timeout_seconds,
            mineru_api_poll_interval_seconds=mineru_api_poll_interval_seconds,
            python_executable=python_executable,
        )
        completed = command_runner(command, ROOT, timeout_seconds)
        rows.append(
            _row_for_case(
                case=case,
                command=command,
                completed=completed,
                document_root=document_root,
                parser_name=parser_name,
            )
        )

    summary = _build_summary(
        run_id=run_id,
        run_dir=run_dir,
        pdf_path=pdf_path,
        db_path=db_path,
        document_root=document_root,
        parser_name=parser_name,
        rows=rows,
    )
    paths = {
        "cases": run_dir / "cases.jsonl",
        "results": run_dir / "results.jsonl",
        "summary": run_dir / "summary.json",
        "summary_md": run_dir / "summary.md",
        "preview": run_dir / "preview.json",
        "manifest": run_dir / "manifest.json",
    }
    summary.update(
        {
            "cases_path": _safe_relpath(paths["cases"]),
            "results_path": _safe_relpath(paths["results"]),
            "summary_path": _safe_relpath(paths["summary"]),
            "summary_markdown_path": _safe_relpath(paths["summary_md"]),
            "preview_path": _safe_relpath(paths["preview"]),
            "manifest_path": _safe_relpath(paths["manifest"]),
            "artifact_paths": [_safe_relpath(path) for path in paths.values()],
        }
    )
    _write_jsonl(paths["cases"], [case.to_dict() for case in cases])
    _write_jsonl(paths["results"], rows)
    _write_json(paths["summary"], summary)
    _write_summary_md(paths["summary_md"], summary)
    _write_json(paths["preview"], {"summary": summary, "results": rows[:4]})
    _write_manifest(paths["manifest"], run_id=run_id, artifact_paths=list(paths.values()))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a final-delivery raw PDF -> MinerU parser -> CLI QA smoke.")
    parser.add_argument("--pdf-path", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--db-path")
    parser.add_argument("--document-root")
    parser.add_argument("--cli-path", default=str(DEFAULT_CLI_PATH))
    parser.add_argument("--parser", choices=["mineru", "mineru_api"], default="mineru")
    parser.add_argument("--mineru-command", default="mineru")
    parser.add_argument("--mineru-timeout-seconds", type=int, default=600)
    parser.add_argument("--live-api", action="store_true")
    parser.add_argument("--mineru-env-file")
    parser.add_argument("--mineru-api-timeout-seconds", type=int, default=900)
    parser.add_argument("--mineru-api-poll-interval-seconds", type=float, default=5.0)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--run-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_final_raw_pdf_smoke(
            pdf_path=_project_path(args.pdf_path),
            output_root=_project_path(args.output_dir),
            db_path=_project_path(args.db_path) if args.db_path else None,
            document_root=_project_path(args.document_root) if args.document_root else None,
            cli_path=_project_path(args.cli_path),
            parser_name=str(args.parser),
            mineru_command=str(args.mineru_command),
            mineru_timeout_seconds=int(args.mineru_timeout_seconds),
            live_api=bool(args.live_api),
            mineru_env_file=_project_path(args.mineru_env_file) if args.mineru_env_file else None,
            mineru_api_timeout_seconds=int(args.mineru_api_timeout_seconds),
            mineru_api_poll_interval_seconds=float(args.mineru_api_poll_interval_seconds),
            python_executable=str(args.python_executable),
            timeout_seconds=int(args.timeout_seconds),
            run_id=str(args.run_id or "") or None,
        )
    except Exception as exc:
        result = {
            "command": "final_raw_pdf_smoke",
            "status": "failed",
            "quality_status": "blocked",
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "parser": str(getattr(args, "parser", "mineru")),
            "used_mineru_local_cli": str(getattr(args, "parser", "mineru")) == "mineru",
            "used_mineru_api": str(getattr(args, "parser", "mineru")) == "mineru_api",
            "used_qwen": False,
            "used_training": False,
            "used_vlm": False,
            "formal_benchmark_acceptance": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository


DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "phase5e_document_summary_acceptance"
DEFAULT_MINERU_FILE = ROOT / "data" / "real_documents" / "globocan_africa_2022" / "source" / "original.pdf"
DEFAULT_MINERU_OUTPUT = ROOT / "data" / "real_documents" / "globocan_africa_2022" / "mineru_raw"
QUESTION = "总结这份文档的主要内容"
BOUNDARY = {
    "used_llm_answer_generation": False,
    "used_vlm": False,
    "used_training": False,
    "used_grpo": False,
    "used_table_lookup": False,
    "used_simple_calculation": False,
    "used_online_mineru_ocr": False,
    "final_answer_quality_evaluated": False,
}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def run_acceptance(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    db_path: Path | None = None,
    keep_existing_output: bool = False,
    include_mineru_existing_fixture: bool = False,
    python_executable: str = sys.executable,
) -> dict[str, Any]:
    output_dir = _project_path(output_dir)
    db_path = _project_path(db_path) if db_path is not None else output_dir / "docagent.db"
    if output_dir.exists() and not keep_existing_output:
        _clear_known_outputs(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cases: list[dict[str, Any]] = []
    cases.append(
        _run_case(
            case_id="txt_ingestion_summary",
            output_dir=output_dir,
            db_path=db_path,
            file_path=_write_txt_fixture(output_dir),
            question=QUESTION,
            parser_args=[],
            python_executable=python_executable,
        )
    )
    if include_mineru_existing_fixture:
        if DEFAULT_MINERU_FILE.is_file() and DEFAULT_MINERU_OUTPUT.is_dir():
            cases.append(
                _run_case(
                    case_id="mineru_existing_summary",
                    output_dir=output_dir,
                    db_path=db_path,
                    file_path=DEFAULT_MINERU_FILE,
                    question="Summarize this document.",
                    parser_args=[
                        "--parser",
                        "mineru_existing",
                        "--mineru-output-dir",
                        str(DEFAULT_MINERU_OUTPUT),
                    ],
                    python_executable=python_executable,
                )
            )
        else:
            cases.append(
                {
                    "case_id": "mineru_existing_summary",
                    "status": "skipped",
                    "question": "Summarize this document.",
                    "task_type": "",
                    "skip_reason": "mineru_fixture_missing",
                    "warnings": ["mineru_fixture_missing"],
                    "artifact_paths": {},
                }
            )

    passed_count = sum(1 for case in cases if case.get("status") == "passed")
    failed_count = sum(1 for case in cases if case.get("status") == "failed")
    unsupported_count = sum(1 for case in cases if case.get("unsupported_returned"))
    report = {
        "phase": "5E-A",
        "task": "document_summary_acceptance_pack",
        "status": "passed" if failed_count == 0 and passed_count >= 1 else "failed",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(cases),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "json_valid_count": sum(int(case.get("json_valid_count") or 0) for case in cases),
        "artifact_write_count": sum(int(case.get("artifact_write_count") or 0) for case in cases),
        "citation_valid_count": sum(1 for case in cases if case.get("citations_valid") is True),
        "unsupported_count": unsupported_count,
        "cases": cases,
        "boundary": dict(BOUNDARY),
    }
    _write_json(output_dir / "acceptance_report.json", report)
    return report


def _run_case(
    *,
    case_id: str,
    output_dir: Path,
    db_path: Path,
    file_path: Path,
    question: str,
    parser_args: list[str],
    python_executable: str,
) -> dict[str, Any]:
    cli_output_dir = output_dir / "cli_artifacts" / case_id
    document_root = output_dir / "documents"
    command = [
        python_executable,
        str(ROOT / "scripts" / "docagent_cli.py"),
        "--db-path",
        str(db_path),
        "--document-root",
        str(document_root),
        "--file",
        str(file_path),
        "--question",
        question,
        "--output-dir",
        str(cli_output_dir),
        *parser_args,
    ]
    completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
    command_result = CommandResult(completed.returncode, completed.stdout, completed.stderr)
    payload, stdout_error = _parse_json_text(command_result.stdout)
    case = {
        "case_id": case_id,
        "status": "failed",
        "question": question,
        "task_type": "",
        "result_json_valid": False,
        "summary_json_valid": False,
        "router_plan_json_valid": False,
        "trace_json_valid": False,
        "citations_valid": False,
        "artifact_paths": {},
        "warnings": [],
        "validation_errors": [],
        "json_valid_count": 0,
        "artifact_write_count": 0,
        "unsupported_returned": False,
        "command": command,
    }
    errors: list[str] = []
    if command_result.returncode != 0:
        errors.append(f"nonzero_returncode:{command_result.returncode}")
    if stdout_error:
        errors.append(stdout_error)
    if payload is None:
        case["validation_errors"] = errors
        case["stderr_preview"] = command_result.stderr.strip()[-1000:]
        return case

    artifact_dir = Path(str(payload.get("artifact_dir") or ""))
    artifact_paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "router_plan": artifact_dir / "router_plan.json",
        "trace": artifact_dir / "trace.json",
    }
    parsed_artifacts: dict[str, dict[str, Any] | None] = {}
    for key, path in artifact_paths.items():
        parsed, error = _read_json(path)
        parsed_artifacts[key] = parsed
        case[f"{key}_json_valid"] = error == ""
        if error:
            errors.append(f"{key}_json:{error}")

    router_plan = parsed_artifacts.get("router_plan") or {}
    result = parsed_artifacts.get("result") or payload
    summary_artifact = parsed_artifacts.get("summary") or {}
    trace_artifact = parsed_artifacts.get("trace") or {}
    structured = result.get("structured_result") if isinstance(result.get("structured_result"), dict) else {}
    error_payload = result.get("error") if isinstance(result.get("error"), dict) else {}
    warnings = _all_warnings(result, router_plan, summary_artifact)
    unsupported_returned = _is_unsupported(error_payload, warnings)
    tools_used = [str(tool) for tool in result.get("tools_used") or []]
    summary_tools_used = [str(tool) for tool in summary_artifact.get("tools_used") or []]
    trace_tools_used = [str(tool) for tool in trace_artifact.get("tools_used") or []]

    if router_plan.get("task_type") != "document_summary":
        errors.append(f"router_task_type:{router_plan.get('task_type') or 'missing'}")
    if result.get("task_type") != "document_summary":
        errors.append(f"result_task_type:{result.get('task_type') or 'missing'}")
    if tools_used != ["document_summary"]:
        errors.append(f"tools_used:{tools_used!r}")
    if summary_tools_used != ["document_summary"]:
        errors.append(f"summary_tools_used:{summary_tools_used!r}")
    if trace_tools_used != ["document_summary"]:
        errors.append(f"trace_tools_used:{trace_tools_used!r}")
    if result.get("status") not in {"success", "completed"}:
        errors.append(f"result_status:{result.get('status') or 'missing'}")
    if structured.get("status") != "completed":
        errors.append(f"structured_status:{structured.get('status') or 'missing'}")
    if unsupported_returned:
        errors.append("generic_unsupported_returned")

    citations = result.get("citations") if isinstance(result.get("citations"), list) else []
    citations_valid, citation_errors = _validate_citations(db_path=db_path, doc_id=str(result.get("doc_id") or ""), citations=citations)
    errors.extend(citation_errors)

    boundary_errors = _validate_boundary(summary_artifact=summary_artifact, trace_artifact=trace_artifact, result=result)
    errors.extend(boundary_errors)

    artifact_write_count = sum(1 for path in artifact_paths.values() if path.is_file())
    json_valid_count = sum(1 for key in artifact_paths if case.get(f"{key}_json_valid") is True)
    case.update(
        {
            "status": "passed" if not errors else "failed",
            "task_type": str(result.get("task_type") or ""),
            "tools_used": tools_used,
            "result_json_valid": bool(case["result_json_valid"]),
            "summary_json_valid": bool(case["summary_json_valid"]),
            "router_plan_json_valid": bool(case["router_plan_json_valid"]),
            "trace_json_valid": bool(case["trace_json_valid"]),
            "citations_valid": citations_valid,
            "artifact_paths": {key: str(path) for key, path in artifact_paths.items()},
            "warnings": warnings,
            "validation_errors": errors,
            "json_valid_count": json_valid_count,
            "artifact_write_count": artifact_write_count,
            "unsupported_returned": unsupported_returned,
        }
    )
    return case


def _write_txt_fixture(output_dir: Path) -> Path:
    fixture = output_dir / "fixtures" / "phase5e_acceptance_summary.txt"
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text(
        "\f".join(
            [
                "DocAgent Phase 5E acceptance document.\n"
                "Page 1 introduces the system goal: grounded document question answering for personal use.\n"
                "The summary should cite persisted evidence blocks rather than unsupported generic text.",
                "Page 2 describes EvidenceBlock storage, page and block citations, router decisions, and trace artifacts.\n"
                "The CLI writes result.json, summary.json, router_plan.json, and trace.json for review.",
                "Page 3 explains that summary output should be deterministic, extractive, bounded, and locally verifiable.\n"
                "The acceptance pack checks that no LLM answer generation, VLM, training, or GRPO path is used.",
            ]
        ),
        encoding="utf-8",
    )
    return fixture


def _validate_citations(*, db_path: Path, doc_id: str, citations: list[Any]) -> tuple[bool, list[str]]:
    if not citations:
        return False, ["citations_empty"]
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        document = repository.get_document(doc_id) or {}
        blocks = repository.load_evidence_blocks(doc_id, include_page_blocks=True)
    finally:
        conn.close()

    valid_block_ids = {block.block_id for block in blocks}
    pages = {int(block.page_id) for block in blocks if block.page_id is not None}
    pages.update(int(block.location.page) for block in blocks if block.location.page is not None)
    page_count = _optional_int(document.get("page_count"))
    errors: list[str] = []
    for citation in citations:
        if not isinstance(citation, dict):
            errors.append("citation_not_object")
            continue
        block_id = str(citation.get("block_id") or "")
        if not block_id:
            errors.append("citation_block_id_missing")
        elif block_id not in valid_block_ids:
            errors.append(f"citation_block_missing:{block_id}")
        page = _optional_int(citation.get("page"))
        if page is None:
            errors.append("citation_page_missing")
            continue
        if pages and page not in pages:
            errors.append(f"citation_page_missing_from_evidence:{page}")
        if page_count is not None and page > page_count:
            errors.append(f"citation_page_exceeds_document_page_count:{page}>{page_count}")
    return not errors, errors


def _validate_boundary(*, summary_artifact: dict[str, Any], trace_artifact: dict[str, Any], result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if summary_artifact.get("used_external_api") is not False:
        errors.append("used_external_api_not_false")
    for key in ("used_vlm", "used_training", "used_full_e2e"):
        if summary_artifact.get(key) is not False:
            errors.append(f"{key}_not_false")
    summary_trace = summary_artifact.get("trace") if isinstance(summary_artifact.get("trace"), dict) else {}
    result_trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
    document_trace = trace_artifact.get("document_summary") if isinstance(trace_artifact.get("document_summary"), dict) else {}
    for trace in (summary_trace, result_trace, document_trace):
        if not trace:
            continue
        if trace.get("used_llm") is not False:
            errors.append("summary_trace_used_llm_not_false")
        if trace.get("used_vlm") is not False:
            errors.append("summary_trace_used_vlm_not_false")
        if trace.get("used_training") is not False:
            errors.append("summary_trace_used_training_not_false")
    return list(dict.fromkeys(errors))


def _clear_known_outputs(output_dir: Path) -> None:
    for name in ("cli_artifacts", "documents", "fixtures"):
        path = output_dir / name
        if path.is_dir():
            shutil.rmtree(path)
    for name in ("acceptance_report.json", "docagent.db"):
        path = output_dir / name
        if path.is_file():
            path.unlink()


def _project_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def _parse_json_text(text: str) -> tuple[dict[str, Any] | None, str]:
    stripped = text.strip()
    if not stripped:
        return None, "stdout_empty"
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None, "stdout_not_json"
    if not isinstance(payload, dict):
        return None, "stdout_json_not_object"
    return payload, ""


def _read_json(path: Path) -> tuple[dict[str, Any] | None, str]:
    if not path.is_file():
        return None, "missing"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None, "invalid_json"
    if not isinstance(payload, dict):
        return None, "json_not_object"
    return payload, ""


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _all_warnings(*payloads: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    for payload in payloads:
        warnings.extend(str(item) for item in payload.get("warnings") or [])
    return list(dict.fromkeys(item for item in warnings if item))


def _is_unsupported(error: dict[str, Any], warnings: list[str]) -> bool:
    markers = {"unsupported_task", "unsupported_task_type", "document_summary_not_implemented"}
    error_type = str(error.get("type") or error.get("code") or "")
    if error_type in markers:
        return True
    return any(warning in markers for warning in warnings)


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase 5E-A document summary acceptance packaging.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--db-path")
    parser.add_argument("--keep-existing-output", action="store_true")
    parser.add_argument("--include-mineru-existing-fixture", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_acceptance(
        output_dir=Path(args.output_dir),
        db_path=Path(args.db_path) if args.db_path else None,
        keep_existing_output=bool(args.keep_existing_output),
        include_mineru_existing_fixture=bool(args.include_mineru_existing_fixture),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())

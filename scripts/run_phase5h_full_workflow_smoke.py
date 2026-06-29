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
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_DB_PATH = ROOT / "outputs" / "docagent.db"
DEFAULT_DOC_ID = "c1fc1c5e040ec894"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "smoke" / "phase5h_full_workflow"
DEFAULT_CLI_PATH = ROOT / "scripts" / "docagent_cli.py"

LOCAL_FACT_QA_TASK = "local_fact_qa"
DETERMINISTIC_TASKS = {"page_lookup", "document_statistics"}
UNSUPPORTED_ERROR_TYPES = {
    "document_summary_not_implemented",
    "table_lookup_not_implemented",
    "unsupported_task_type",
}


@dataclass(frozen=True)
class WorkflowCase:
    case_id: str
    user_request: str
    request_form: str
    expected_router_task_type: str
    expected_behavior: str
    semantic_query_expected: bool
    calculation_intent: bool = False
    answerable: bool = True
    unsupported_ok: bool = False
    notes: str = ""

    @property
    def cli_question_field(self) -> str:
        # The CLI field is still named "question", but semantically this value
        # is a user request and may be imperative, declarative, or task-like.
        return self.user_request

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "user_request": self.user_request,
            "cli_question_field": self.cli_question_field,
            "request_form": self.request_form,
            "expected_router_task_type": self.expected_router_task_type,
            "expected_behavior": self.expected_behavior,
            "semantic_query_expected": self.semantic_query_expected,
            "calculation_intent": self.calculation_intent,
            "answerable": self.answerable,
            "unsupported_ok": self.unsupported_ok,
            "notes": self.notes,
        }


def default_cases() -> list[WorkflowCase]:
    return [
        WorkflowCase(
            case_id="fact_unclaimed_dividend_year",
            user_request="What date or financial year is mentioned in the shareholder notice about unclaimed dividend?",
            request_form="interrogative",
            expected_router_task_type=LOCAL_FACT_QA_TASK,
            expected_behavior="full_workflow_answer_with_retrieval",
            semantic_query_expected=True,
            notes="Primary Phase 5C-3 accepted smoke question.",
        ),
        WorkflowCase(
            case_id="date_effective_notice",
            user_request="What effective date is stated in the notice?",
            request_form="interrogative",
            expected_router_task_type=LOCAL_FACT_QA_TASK,
            expected_behavior="full_workflow_answer_with_retrieval",
            semantic_query_expected=True,
            notes="Date request without using the invoice example.",
        ),
        WorkflowCase(
            case_id="amount_percentage_reported",
            user_request="What amount or percentage is reported in the document?",
            request_form="interrogative",
            expected_router_task_type=LOCAL_FACT_QA_TASK,
            expected_behavior="full_workflow_answer_with_retrieval",
            semantic_query_expected=True,
            notes="Numeric or percentage fact QA, not deterministic calculation.",
        ),
        WorkflowCase(
            case_id="page_one_information",
            user_request="What information appears on page 1?",
            request_form="interrogative",
            expected_router_task_type="page_lookup",
            expected_behavior="deterministic_page_lookup",
            semantic_query_expected=False,
            notes="Deterministic page lookup path; LLM semantic expansion is not required.",
        ),
        WorkflowCase(
            case_id="document_page_count",
            user_request="How many pages does this document have?",
            request_form="interrogative",
            expected_router_task_type="document_statistics",
            expected_behavior="deterministic_document_statistics",
            semantic_query_expected=False,
            notes="Deterministic statistics path.",
        ),
        WorkflowCase(
            case_id="summary_main_topic",
            user_request="What is this document mainly about?",
            request_form="summary",
            expected_router_task_type="document_summary",
            expected_behavior="structured_unsupported_or_stable_fallback",
            semantic_query_expected=False,
            answerable=False,
            unsupported_ok=True,
            notes="Phase 5E document_summary remains not_started.",
        ),
        WorkflowCase(
            case_id="chinese_summary",
            user_request="请概括这份文件的主要内容",
            request_form="summary",
            expected_router_task_type="document_summary",
            expected_behavior="structured_unsupported_or_stable_fallback",
            semantic_query_expected=False,
            answerable=False,
            unsupported_ok=True,
            notes="Chinese summary request; summary support is still a boundary.",
        ),
        WorkflowCase(
            case_id="chinese_unclaimed_dividend_year",
            user_request="请找出文件中提到的未领取股息相关年份",
            request_form="extraction",
            expected_router_task_type=LOCAL_FACT_QA_TASK,
            expected_behavior="full_workflow_answer_with_retrieval",
            semantic_query_expected=True,
            notes="Chinese extraction-style fact request.",
        ),
        WorkflowCase(
            case_id="declarative_find_financial_year",
            user_request="Find the financial year related to unclaimed dividend.",
            request_form="declarative",
            expected_router_task_type=LOCAL_FACT_QA_TASK,
            expected_behavior="full_workflow_answer_with_retrieval",
            semantic_query_expected=True,
            notes="Not a question syntactically; handled as a user request.",
        ),
        WorkflowCase(
            case_id="imperative_extract_notice_date",
            user_request="Extract the date mentioned in the shareholder notice.",
            request_form="imperative",
            expected_router_task_type=LOCAL_FACT_QA_TASK,
            expected_behavior="full_workflow_answer_with_retrieval",
            semantic_query_expected=True,
            notes="Imperative extraction request.",
        ),
        WorkflowCase(
            case_id="calculation_total_dividend",
            user_request="Calculate the total amount mentioned for the relevant dividend item.",
            request_form="calculation",
            expected_router_task_type="table_lookup_or_calculation",
            expected_behavior="retrieval_plus_unsupported_calculation_boundary",
            semantic_query_expected=True,
            calculation_intent=True,
            answerable=False,
            unsupported_ok=True,
            notes="Calculation intent validates routing/retrieval/boundary only; simple_calculation is not implemented.",
        ),
        WorkflowCase(
            case_id="calculation_difference_amounts",
            user_request="Calculate the difference between the two amounts mentioned in the document.",
            request_form="calculation",
            expected_router_task_type="table_lookup_or_calculation",
            expected_behavior="retrieval_plus_unsupported_calculation_boundary",
            semantic_query_expected=True,
            calculation_intent=True,
            answerable=False,
            unsupported_ok=True,
            notes="Calculation correctness is out of scope for Phase 5H.",
        ),
        WorkflowCase(
            case_id="table_financial_information",
            user_request="Which table contains the relevant financial information?",
            request_form="extraction",
            expected_router_task_type="table_lookup_or_calculation",
            expected_behavior="structured_unsupported_or_stable_fallback",
            semantic_query_expected=False,
            answerable=False,
            unsupported_ok=True,
            notes="table_lookup remains not_started.",
        ),
        WorkflowCase(
            case_id="short_date_question",
            user_request="What is the date?",
            request_form="ambiguous",
            expected_router_task_type=LOCAL_FACT_QA_TASK,
            expected_behavior="duplicate_retry_stability",
            semantic_query_expected=True,
            notes="Short request likely to trigger duplicate-query handling.",
        ),
        WorkflowCase(
            case_id="imperative_list_key_dates",
            user_request="List the key dates mentioned in this notice.",
            request_form="imperative",
            expected_router_task_type=LOCAL_FACT_QA_TASK,
            expected_behavior="full_workflow_answer_with_retrieval",
            semantic_query_expected=True,
            notes="Imperative broad date extraction request.",
        ),
    ]


def _now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"phase5h_full_workflow_{stamp}_{uuid.uuid4().hex[:8]}"


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _build_cli_command(
    *,
    case: WorkflowCase,
    db_path: Path,
    doc_id: str,
    router_llm_env_file: Path,
    cli_output_dir: Path,
    dry_run: bool,
    python_executable: str,
) -> list[str]:
    command = [
        python_executable,
        str(DEFAULT_CLI_PATH),
        "--db-path",
        str(db_path),
        "--doc-id",
        doc_id,
        "--question",
        case.cli_question_field,
        "--router-llm-env-file",
        str(router_llm_env_file),
        "--enable-query-planning",
        "--query-planner-mode",
        "hybrid",
        "--output-dir",
        str(cli_output_dir),
    ]
    if dry_run:
        command.append("--dry-run")
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


def _answer_preview(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    return str(payload.get("answer") or "").strip()[:500]


def _router_task_type(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    router_plan = payload.get("router_plan") if isinstance(payload.get("router_plan"), dict) else {}
    return str(router_plan.get("task_type") or "")


def _error_type(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    return str(error.get("type") or "")


def _warnings(payload: dict[str, Any] | None) -> list[str]:
    if not payload:
        return []
    warnings = [str(item) for item in payload.get("warnings") or []]
    router_plan = payload.get("router_plan") if isinstance(payload.get("router_plan"), dict) else {}
    warnings.extend(str(item) for item in router_plan.get("warnings") or [])
    query_planner = payload.get("query_planner") if isinstance(payload.get("query_planner"), dict) else {}
    warnings.extend(str(item) for item in query_planner.get("warnings") or [])
    return list(dict.fromkeys(item for item in warnings if item))


def _retrieved_evidence_count(payload: dict[str, Any] | None) -> int:
    if not payload:
        return 0
    evidence_ids = payload.get("supporting_evidence_ids") or []
    citations = payload.get("citations") or []
    return max(len(evidence_ids), len(citations))


def _retrieval_status(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "not_run"
    task_type = str(payload.get("task_type") or "")
    if task_type in DETERMINISTIC_TASKS:
        return "not_required_for_deterministic_tool"
    query_planner = payload.get("query_planner") if isinstance(payload.get("query_planner"), dict) else {}
    if query_planner.get("final_queries"):
        return "queries_planned"
    if _retrieved_evidence_count(payload) > 0:
        return "evidence_returned"
    return "not_observed"


def _answer_status(payload: dict[str, Any] | None, *, dry_run: bool) -> str:
    if not payload:
        return "not_run"
    if payload.get("status") == "error":
        return f"error:{_error_type(payload) or 'unknown'}"
    if dry_run:
        return "dry_run"
    if _answer_preview(payload):
        return "generated"
    return "empty_answer"


def _has_expected_tool(payload: dict[str, Any] | None, task_type: str) -> bool:
    tools = set(str(item) for item in ((payload or {}).get("tools_used") or []))
    if task_type == "document_statistics":
        return "count_pages" in tools
    if task_type == "page_lookup":
        return "get_page_text" in tools
    if task_type == LOCAL_FACT_QA_TASK:
        return "local_fact_qa" in tools
    return True


def _is_structured_unsupported(payload: dict[str, Any] | None) -> bool:
    return _error_type(payload) in UNSUPPORTED_ERROR_TYPES or any(
        warning in UNSUPPORTED_ERROR_TYPES for warning in _warnings(payload)
    )


def _stage_for_failure(reason: str) -> str:
    if reason.startswith("router_") or "task_type" in reason:
        return "router"
    if "query" in reason or "llm" in reason:
        return "query_planner"
    if "retrieval" in reason or "evidence" in reason:
        return "retrieval"
    if "answer" in reason:
        return "answer_generation"
    if "citation" in reason:
        return "citation"
    if "unsupported" in reason or "not_implemented" in reason:
        return "unsupported_boundary"
    if "stdout" in reason or "returncode" in reason:
        return "cli_execution"
    return "metadata"


def _evaluate_case(
    *,
    case: WorkflowCase,
    payload: dict[str, Any] | None,
    parse_error: str,
    returncode: int,
    dry_run: bool,
) -> tuple[str, str, str]:
    if parse_error:
        return "failed", parse_error, "cli_execution"
    if returncode != 0 and not payload:
        return "failed", f"nonzero_returncode:{returncode}", "cli_execution"

    assert payload is not None
    actual_task_type = str(payload.get("task_type") or "")
    router_task_type = _router_task_type(payload)
    effective_task_type = router_task_type or actual_task_type

    if case.unsupported_ok and _is_structured_unsupported(payload):
        return "passed", "structured_unsupported_boundary", "unsupported_boundary"

    if case.calculation_intent:
        query_planner = payload.get("query_planner") if isinstance(payload.get("query_planner"), dict) else {}
        if payload.get("status") in {"success", "error"} and (
            _is_structured_unsupported(payload) or query_planner.get("final_queries") or _retrieved_evidence_count(payload) > 0
        ):
            return "passed", "calculation_boundary_observed", "unsupported_boundary"
        return "failed", "calculation_boundary_not_observed", "unsupported_boundary"

    if case.expected_router_task_type in DETERMINISTIC_TASKS:
        if payload.get("status") != "success":
            return "failed", f"status_{payload.get('status') or 'unknown'}", "cli_execution"
        if actual_task_type != case.expected_router_task_type:
            return "failed", f"task_type_{actual_task_type or 'unknown'}", "router"
        if not _has_expected_tool(payload, case.expected_router_task_type):
            return "failed", "expected_deterministic_tool_missing", "retrieval"
        return "passed", "deterministic_tool_path_ok", "metadata"

    if case.expected_router_task_type == LOCAL_FACT_QA_TASK:
        if payload.get("status") != "success":
            return "failed", f"status_{payload.get('status') or 'unknown'}", "cli_execution"
        if actual_task_type != LOCAL_FACT_QA_TASK:
            return "failed", f"task_type_{actual_task_type or 'unknown'}", "router"
        if not _has_expected_tool(payload, LOCAL_FACT_QA_TASK):
            return "failed", "local_fact_qa_tool_missing", "answer_generation"
        query_planner = payload.get("query_planner") if isinstance(payload.get("query_planner"), dict) else {}
        if case.semantic_query_expected:
            if not query_planner.get("enabled"):
                return "failed", "query_planner_not_enabled", "query_planner"
            if not query_planner.get("final_queries"):
                return "failed", "final_queries_empty", "query_planner"
        if not dry_run and not _answer_preview(payload):
            return "failed", "answer_preview_empty", "answer_generation"
        return "passed", "local_fact_qa_full_workflow_ok", "answer_generation"

    if case.unsupported_ok and payload.get("status") in {"success", "error"}:
        return "passed", "stable_fallback_or_boundary", "unsupported_boundary"

    if effective_task_type != case.expected_router_task_type:
        return "failed", f"router_task_type_{effective_task_type or 'unknown'}", "router"
    return "passed", "case_boundary_ok", "metadata"


def run_case(
    *,
    case: WorkflowCase,
    db_path: Path,
    doc_id: str,
    router_llm_env_file: Path,
    cli_output_dir: Path,
    dry_run: bool,
    python_executable: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    command = _build_cli_command(
        case=case,
        db_path=db_path,
        doc_id=doc_id,
        router_llm_env_file=router_llm_env_file,
        cli_output_dir=cli_output_dir,
        dry_run=dry_run,
        python_executable=python_executable,
    )
    completed = subprocess.run(command, text=True, capture_output=True, check=False, timeout=timeout_seconds)
    payload, parse_error = _parse_stdout(completed.stdout)
    pass_fail, reason, stage = _evaluate_case(
        case=case,
        payload=payload,
        parse_error=parse_error,
        returncode=completed.returncode,
        dry_run=dry_run,
    )
    query_planner = payload.get("query_planner") if payload and isinstance(payload.get("query_planner"), dict) else {}
    router_plan = payload.get("router_plan") if payload and isinstance(payload.get("router_plan"), dict) else {}
    citations = payload.get("citations") if payload else []
    return {
        **case.to_dict(),
        "actual_task_type": payload.get("task_type") if payload else "",
        "router_task_type": router_plan.get("task_type") or "",
        "router_source": router_plan.get("router_source") or "",
        "query_planner_enabled": bool(query_planner.get("enabled")),
        "query_planner_mode": query_planner.get("mode") or "",
        "rule_queries": query_planner.get("rule_queries") or [],
        "llm_queries": query_planner.get("llm_queries") or [],
        "llm_unique_queries": query_planner.get("llm_unique_queries") or [],
        "llm_duplicate_queries": query_planner.get("llm_duplicate_queries") or [],
        "llm_added_unique_query_count": query_planner.get("llm_added_unique_query_count") or 0,
        "query_sources": query_planner.get("query_sources") or {},
        "final_queries": query_planner.get("final_queries") or [],
        "tools_used": payload.get("tools_used") if payload else [],
        "retrieval_status": _retrieval_status(payload),
        "retrieved_evidence_count": _retrieved_evidence_count(payload),
        "answer_status": _answer_status(payload, dry_run=dry_run),
        "answer_preview": _answer_preview(payload),
        "citations": citations or [],
        "warnings": _warnings(payload),
        "error": payload.get("error") if payload else {"type": parse_error, "message": "CLI stdout was not a JSON object."},
        "pass_fail": pass_fail,
        "failure_reason": "" if pass_fail == "passed" else reason,
        "pass_reason": reason if pass_fail == "passed" else "",
        "failure_stage": "" if pass_fail == "passed" else stage,
        "boundary_stage": stage if pass_fail == "passed" and stage == "unsupported_boundary" else "",
        "returncode": completed.returncode,
        "json_valid": payload is not None,
        "artifact_dir": payload.get("artifact_dir") if payload else "",
        "stdout_preview": completed.stdout.strip()[:1000],
        "stderr_preview": completed.stderr.strip()[:1000],
        "command": command,
    }


def build_summary(
    *,
    run_id: str,
    artifact_dir: Path,
    cases: list[WorkflowCase],
    results: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, Any]:
    pass_fail_counts = Counter(str(item.get("pass_fail") or "") for item in results)
    request_forms = Counter(case.request_form for case in cases)
    task_types = Counter(str(item.get("actual_task_type") or "unknown") for item in results)
    router_task_types = Counter(str(item.get("router_task_type") or "unknown") for item in results)
    failure_stages = Counter(str(item.get("failure_stage") or "") for item in results if item.get("failure_stage"))
    failure_reasons = Counter(str(item.get("failure_reason") or "") for item in results if item.get("failure_reason"))
    tools = Counter(tool for item in results for tool in (item.get("tools_used") or []))
    unsupported_boundaries = sum(1 for item in results if item.get("boundary_stage") == "unsupported_boundary")
    summary = {
        "command": "phase5h_full_workflow_smoke",
        "status": "success" if pass_fail_counts.get("failed", 0) == 0 else "failed",
        "run_id": run_id,
        "artifact_dir": str(artifact_dir),
        "case_count": len(cases),
        "passed_count": pass_fail_counts.get("passed", 0),
        "failed_count": pass_fail_counts.get("failed", 0),
        "dry_run_cases": len(cases) if dry_run else 0,
        "non_dry_run_cases": 0 if dry_run else len(cases),
        "semantic_query_expected_count": sum(1 for case in cases if case.semantic_query_expected),
        "calculation_intent_count": sum(1 for case in cases if case.calculation_intent),
        "unsupported_boundary_count": unsupported_boundaries,
        "json_valid_count": sum(1 for item in results if item.get("json_valid")),
        "artifact_write_count": sum(1 for item in results if item.get("artifact_dir")),
        "request_form_distribution": dict(sorted(request_forms.items())),
        "task_type_distribution": dict(sorted(task_types.items())),
        "router_task_type_distribution": dict(sorted(router_task_types.items())),
        "tools_used_distribution": dict(sorted(tools.items())),
        "failure_stage_distribution": dict(sorted(failure_stages.items())),
        "failure_reason_distribution": dict(sorted(failure_reasons.items())),
        "used_external_api": any(
            str(item.get("llm_added_unique_query_count") or 0) != "0" or (item.get("llm_queries") or [])
            for item in results
        ),
        "used_vlm": False,
        "used_training": False,
        "used_full_e2e": False,
    }
    summary["cases_path"] = str(artifact_dir / "phase5h_cases.jsonl")
    summary["results_path"] = str(artifact_dir / "phase5h_results.jsonl")
    summary["summary_path"] = str(artifact_dir / "phase5h_summary.json")
    summary["preview_path"] = str(artifact_dir / "preview.json")
    return summary


def run_phase5h_smoke(
    *,
    db_path: Path,
    doc_id: str,
    router_llm_env_file: Path,
    output_root: Path,
    max_cases: int | None,
    dry_run: bool,
    python_executable: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    run_id = _now_run_id()
    artifact_dir = output_root / run_id
    cli_output_dir = artifact_dir / "cli"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    cli_output_dir.mkdir(parents=True, exist_ok=True)

    cases = default_cases()
    if max_cases is not None:
        cases = cases[: max(0, int(max_cases))]

    results = [
        run_case(
            case=case,
            db_path=db_path,
            doc_id=doc_id,
            router_llm_env_file=router_llm_env_file,
            cli_output_dir=cli_output_dir,
            dry_run=dry_run,
            python_executable=python_executable,
            timeout_seconds=timeout_seconds,
        )
        for case in cases
    ]
    summary = build_summary(run_id=run_id, artifact_dir=artifact_dir, cases=cases, results=results, dry_run=dry_run)
    preview = {"summary": summary, "results": results[:5]}

    cases_path = artifact_dir / "phase5h_cases.jsonl"
    results_path = artifact_dir / "phase5h_results.jsonl"
    summary_path = artifact_dir / "phase5h_summary.json"
    preview_path = artifact_dir / "preview.json"
    _write_jsonl(cases_path, [case.to_dict() for case in cases])
    _write_jsonl(results_path, results)
    _write_json(summary_path, summary)
    _write_json(preview_path, preview)

    return {
        **summary,
        "artifact_paths": [str(cases_path), str(results_path), str(summary_path), str(preview_path)],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase 5H full workflow validation smoke.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--doc-id", default=DEFAULT_DOC_ID)
    parser.add_argument("--router-llm-env-file", default=".secrets/router_llm.env")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=False)
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    summary = run_phase5h_smoke(
        db_path=_project_path(args.db_path),
        doc_id=str(args.doc_id),
        router_llm_env_file=_project_path(args.router_llm_env_file),
        output_root=_project_path(args.output_dir),
        max_cases=args.max_cases,
        dry_run=bool(args.dry_run),
        python_executable=str(args.python_executable),
        timeout_seconds=int(args.timeout_seconds),
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

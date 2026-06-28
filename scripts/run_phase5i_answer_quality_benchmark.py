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

DEFAULT_DB_PATH = ROOT / "outputs" / "docagent.db"
DEFAULT_DOC_ID = "c1fc1c5e040ec894"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "benchmark" / "phase5i_answer_quality"
DEFAULT_CLI_PATH = ROOT / "scripts" / "docagent_cli.py"

UNSUPPORTED_ERROR_TYPES = {
    "document_summary_not_implemented",
    "table_lookup_not_implemented",
    "structured_extraction_not_implemented",
    "unsupported_task_type",
}
UNSUPPORTED_WARNING_MARKERS = {
    *UNSUPPORTED_ERROR_TYPES,
    "tool_unavailable",
    "table_tool_unavailable",
    "calculation_tool_unavailable",
    "fallback_to_local_fact_qa",
}
ABSTENTION_MARKERS = {
    "insufficient evidence",
    "not enough evidence",
    "cannot determine",
    "can't determine",
    "could not determine",
    "unable to determine",
    "unable to answer",
    "not provided",
    "not found",
    "no evidence",
    "does not mention",
    "无法确定",
    "无法回答",
    "没有足够",
    "未提及",
}


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


CommandRunner = Callable[[list[str], Path, int], CommandResult]


@dataclass(frozen=True)
class GoldenCase:
    case_id: str
    user_request: str
    request_form: str
    expected_task_type: str
    expected_answer_type: str
    answerable: bool
    unsupported_ok: bool
    expected_page: int | None
    expected_evidence_keywords: list[str]
    expected_answer_keywords: list[str]
    forbidden_answer_keywords: list[str]
    notes: str = ""

    @property
    def cli_question_field(self) -> str:
        return self.user_request

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "user_request": self.user_request,
            "cli_question_field": self.cli_question_field,
            "request_form": self.request_form,
            "expected_task_type": self.expected_task_type,
            "expected_answer_type": self.expected_answer_type,
            "answerable": self.answerable,
            "unsupported_ok": self.unsupported_ok,
            "expected_page": self.expected_page,
            "expected_evidence_keywords": self.expected_evidence_keywords,
            "expected_answer_keywords": self.expected_answer_keywords,
            "forbidden_answer_keywords": self.forbidden_answer_keywords,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GoldenCase":
        return cls(
            case_id=str(payload["case_id"]),
            user_request=str(payload["user_request"]),
            request_form=str(payload["request_form"]),
            expected_task_type=str(payload["expected_task_type"]),
            expected_answer_type=str(payload["expected_answer_type"]),
            answerable=bool(payload.get("answerable", True)),
            unsupported_ok=bool(payload.get("unsupported_ok", False)),
            expected_page=_optional_int(payload.get("expected_page")),
            expected_evidence_keywords=[str(item) for item in payload.get("expected_evidence_keywords") or []],
            expected_answer_keywords=[str(item) for item in payload.get("expected_answer_keywords") or []],
            forbidden_answer_keywords=[str(item) for item in payload.get("forbidden_answer_keywords") or []],
            notes=str(payload.get("notes") or ""),
        )


def default_cases() -> list[GoldenCase]:
    return [
        GoldenCase(
            case_id="fact_unclaimed_dividend_financial_year",
            user_request="What date or financial year is mentioned in the shareholder notice about unclaimed dividend?",
            request_form="interrogative",
            expected_task_type="local_fact_qa",
            expected_answer_type="extractive",
            answerable=True,
            unsupported_ok=False,
            expected_page=24,
            expected_evidence_keywords=["unclaimed", "dividend"],
            expected_answer_keywords=["financial year"],
            forbidden_answer_keywords=[],
            notes="Primary accepted Phase 5C-3/5H question; page 24 is based on accepted server citation metadata.",
        ),
        GoldenCase(
            case_id="fact_shareholder_notice_date",
            user_request="Extract the date mentioned in the shareholder notice.",
            request_form="imperative",
            expected_task_type="local_fact_qa",
            expected_answer_type="extractive",
            answerable=True,
            unsupported_ok=False,
            expected_page=24,
            expected_evidence_keywords=["shareholder", "notice"],
            expected_answer_keywords=["date"],
            forbidden_answer_keywords=[],
            notes="Known weak area: previous smoke reported unstable date answer quality.",
        ),
        GoldenCase(
            case_id="fact_effective_date_notice",
            user_request="What effective date is stated in the notice?",
            request_form="interrogative",
            expected_task_type="local_fact_qa",
            expected_answer_type="extractive",
            answerable=True,
            unsupported_ok=False,
            expected_page=24,
            expected_evidence_keywords=["notice"],
            expected_answer_keywords=["date"],
            forbidden_answer_keywords=[],
            notes="Checks date/year extraction and answer grounding.",
        ),
        GoldenCase(
            case_id="fact_financial_year_declarative",
            user_request="Find the financial year related to unclaimed dividend.",
            request_form="declarative",
            expected_task_type="local_fact_qa",
            expected_answer_type="extractive",
            answerable=True,
            unsupported_ok=False,
            expected_page=24,
            expected_evidence_keywords=["unclaimed", "dividend"],
            expected_answer_keywords=["financial year"],
            forbidden_answer_keywords=[],
            notes="Declarative form should still be treated as user_request.",
        ),
        GoldenCase(
            case_id="fact_key_dates_imperative",
            user_request="List the key dates mentioned in this notice.",
            request_form="imperative",
            expected_task_type="local_fact_qa",
            expected_answer_type="extractive",
            answerable=True,
            unsupported_ok=False,
            expected_page=24,
            expected_evidence_keywords=["notice"],
            expected_answer_keywords=["date"],
            forbidden_answer_keywords=[],
            notes="Broad date extraction through current local_fact_qa path, not structured full-scan extraction.",
        ),
        GoldenCase(
            case_id="numeric_amount_or_percentage",
            user_request="What amount or percentage is reported in the document?",
            request_form="interrogative",
            expected_task_type="local_fact_qa",
            expected_answer_type="numeric",
            answerable=True,
            unsupported_ok=False,
            expected_page=24,
            expected_evidence_keywords=["amount"],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="Numeric quality cannot be fully judged without exact gold value; manual review is expected if only generic signals pass.",
        ),
        GoldenCase(
            case_id="numeric_percentage_reported",
            user_request="Which percentage is reported in the notice?",
            request_form="interrogative",
            expected_task_type="local_fact_qa",
            expected_answer_type="numeric",
            answerable=True,
            unsupported_ok=False,
            expected_page=24,
            expected_evidence_keywords=["notice"],
            expected_answer_keywords=["%"],
            forbidden_answer_keywords=[],
            notes="Checks whether numeric/percentage values are extracted rather than only nearby prose.",
        ),
        GoldenCase(
            case_id="page_lookup_page_one_question",
            user_request="What information appears on page 1?",
            request_form="interrogative",
            expected_task_type="page_lookup",
            expected_answer_type="extractive",
            answerable=True,
            unsupported_ok=False,
            expected_page=1,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="Deterministic page location check; content needs manual inspection.",
        ),
        GoldenCase(
            case_id="page_lookup_show_page_one",
            user_request="Show the text from page 1.",
            request_form="imperative",
            expected_task_type="page_lookup",
            expected_answer_type="extractive",
            answerable=True,
            unsupported_ok=False,
            expected_page=1,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="Imperative page lookup should use get_page_text.",
        ),
        GoldenCase(
            case_id="document_statistics_page_count",
            user_request="How many pages does this document have?",
            request_form="interrogative",
            expected_task_type="document_statistics",
            expected_answer_type="numeric",
            answerable=True,
            unsupported_ok=False,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=["5"],
            forbidden_answer_keywords=[],
            notes="Accepted server status records documents.page_count = 5 for this doc_id.",
        ),
        GoldenCase(
            case_id="document_statistics_count_pages_imperative",
            user_request="Count the pages in this document.",
            request_form="imperative",
            expected_task_type="document_statistics",
            expected_answer_type="numeric",
            answerable=True,
            unsupported_ok=False,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=["5"],
            forbidden_answer_keywords=[],
            notes="Command-form deterministic statistics request.",
        ),
        GoldenCase(
            case_id="chinese_unclaimed_dividend_year",
            user_request="请找出文件中提到的未领取股息相关年份",
            request_form="extraction",
            expected_task_type="local_fact_qa",
            expected_answer_type="extractive",
            answerable=True,
            unsupported_ok=False,
            expected_page=24,
            expected_evidence_keywords=["unclaimed", "dividend"],
            expected_answer_keywords=["financial year"],
            forbidden_answer_keywords=[],
            notes="Chinese fact/extraction request over English document evidence.",
        ),
        GoldenCase(
            case_id="chinese_page_count",
            user_request="这份文件有多少页？",
            request_form="interrogative",
            expected_task_type="document_statistics",
            expected_answer_type="numeric",
            answerable=True,
            unsupported_ok=False,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=["5"],
            forbidden_answer_keywords=[],
            notes="Chinese deterministic statistics request; useful for router error attribution.",
        ),
        GoldenCase(
            case_id="ambiguous_short_date",
            user_request="What is the date?",
            request_form="ambiguous",
            expected_task_type="local_fact_qa",
            expected_answer_type="extractive",
            answerable=True,
            unsupported_ok=False,
            expected_page=24,
            expected_evidence_keywords=["notice"],
            expected_answer_keywords=["date"],
            forbidden_answer_keywords=[],
            notes="Short duplicate-prone query; automatic pass should remain conservative.",
        ),
        GoldenCase(
            case_id="ambiguous_tell_me_about_it",
            user_request="Tell me about it.",
            request_form="ambiguous",
            expected_task_type="document_summary",
            expected_answer_type="unsupported",
            answerable=False,
            unsupported_ok=True,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="Ambiguous global request should not be treated as a fully supported answer-quality pass.",
        ),
        GoldenCase(
            case_id="unanswerable_ceo_favorite_color",
            user_request="What is the CEO's favorite color?",
            request_form="interrogative",
            expected_task_type="local_fact_qa",
            expected_answer_type="abstain",
            answerable=False,
            unsupported_ok=False,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=["blue", "red", "green", "yellow"],
            notes="Unanswerable personal attribute should be refused for insufficient evidence.",
        ),
        GoldenCase(
            case_id="unanswerable_weather",
            user_request="What was the weather in Mumbai on the notice date?",
            request_form="interrogative",
            expected_task_type="local_fact_qa",
            expected_answer_type="abstain",
            answerable=False,
            unsupported_ok=False,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=["sunny", "rain", "cloudy", "temperature"],
            notes="Requires outside-world weather data; current local document QA should abstain.",
        ),
        GoldenCase(
            case_id="unanswerable_bank_account_number",
            user_request="What bank account number is given for the shareholder?",
            request_form="interrogative",
            expected_task_type="local_fact_qa",
            expected_answer_type="abstain",
            answerable=False,
            unsupported_ok=False,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="Evidence-insufficient case intended to expose hallucinated extraction.",
        ),
        GoldenCase(
            case_id="summary_boundary_main_topic",
            user_request="What is this document mainly about?",
            request_form="summary",
            expected_task_type="document_summary",
            expected_answer_type="unsupported",
            answerable=False,
            unsupported_ok=True,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="Phase 5E document_summary is not implemented; only structured limitation is acceptable.",
        ),
        GoldenCase(
            case_id="summary_boundary_key_points",
            user_request="Summarize this document and list the key points.",
            request_form="summary",
            expected_task_type="document_summary",
            expected_answer_type="unsupported",
            answerable=False,
            unsupported_ok=True,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="Summary remains an unsupported boundary, not a local_fact_qa quality pass.",
        ),
        GoldenCase(
            case_id="chinese_summary_boundary",
            user_request="请概括这份文件的主要内容",
            request_form="summary",
            expected_task_type="document_summary",
            expected_answer_type="unsupported",
            answerable=False,
            unsupported_ok=True,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="Chinese summary request should be tracked as unsupported Phase 5E boundary.",
        ),
        GoldenCase(
            case_id="table_boundary_financial_information",
            user_request="Which table contains the relevant financial information?",
            request_form="extraction",
            expected_task_type="table_lookup_or_calculation",
            expected_answer_type="unsupported",
            answerable=False,
            unsupported_ok=True,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="table_lookup remains not_started; a structured limitation is acceptable.",
        ),
        GoldenCase(
            case_id="table_boundary_highest_amount",
            user_request="Which row has the highest amount in the table?",
            request_form="interrogative",
            expected_task_type="table_lookup_or_calculation",
            expected_answer_type="unsupported",
            answerable=False,
            unsupported_ok=True,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="Table row reasoning is a boundary case, not a supported table_lookup feature.",
        ),
        GoldenCase(
            case_id="calculation_boundary_total_amount",
            user_request="Calculate the total amount mentioned for the relevant dividend item.",
            request_form="calculation",
            expected_task_type="table_lookup_or_calculation",
            expected_answer_type="unsupported",
            answerable=False,
            unsupported_ok=True,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="simple_calculation is not implemented; pass only as structured unsupported or limitation.",
        ),
        GoldenCase(
            case_id="calculation_boundary_difference",
            user_request="Calculate the difference between the two amounts mentioned in the document.",
            request_form="calculation",
            expected_task_type="table_lookup_or_calculation",
            expected_answer_type="unsupported",
            answerable=False,
            unsupported_ok=True,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="Arithmetic intent should be classified at the unsupported boundary.",
        ),
        GoldenCase(
            case_id="structured_extraction_all_dates_boundary",
            user_request="Extract all dates mentioned in the document.",
            request_form="extraction",
            expected_task_type="structured_extraction",
            expected_answer_type="unsupported",
            answerable=False,
            unsupported_ok=True,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="Full-scan extraction is not implemented as a dedicated tool in this phase.",
        ),
    ]


def _now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"phase5i_answer_quality_{stamp}_{uuid.uuid4().hex[:8]}"


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _json_default(value: Any) -> str:
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    return int(value)


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


def _read_cases_jsonl(path: Path) -> list[GoldenCase]:
    cases: list[GoldenCase] = []
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise ValueError(f"Expected JSON object at {path}:{line_number}")
            cases.append(GoldenCase.from_dict(payload))
    return cases


def _default_command_runner(command: list[str], cwd: Path, timeout_seconds: int) -> CommandResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr = exc.stderr if isinstance(exc.stderr, str) else ""
        return CommandResult(-1, stdout, f"timeout_after_{timeout_seconds}s\n{stderr}".strip())
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def _build_cli_command(
    *,
    case: GoldenCase,
    db_path: Path,
    doc_id: str,
    router_llm_env_file: Path,
    cli_output_dir: Path,
    cli_path: Path,
    dry_run: bool,
    python_executable: str,
) -> list[str]:
    command = [
        python_executable,
        str(cli_path),
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


def _router_plan(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload and isinstance(payload.get("router_plan"), dict):
        return payload["router_plan"]
    return {}


def _query_planner(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload and isinstance(payload.get("query_planner"), dict):
        return payload["query_planner"]
    return {}


def _all_warnings(payload: dict[str, Any] | None) -> list[str]:
    if payload is None:
        return []
    warnings = [str(item) for item in payload.get("warnings") or []]
    warnings.extend(str(item) for item in _router_plan(payload).get("warnings") or [])
    warnings.extend(str(item) for item in _query_planner(payload).get("warnings") or [])
    return list(dict.fromkeys(item for item in warnings if item))


def _error(payload: dict[str, Any] | None, parse_error: str = "") -> dict[str, Any]:
    if payload and isinstance(payload.get("error"), dict):
        return payload["error"]
    if parse_error:
        return {"type": parse_error, "message": "CLI stdout was not a JSON object."}
    return {}


def _answer_preview(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return ""
    return str(payload.get("answer") or "").strip()[:500]


def _citations(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if payload is None:
        return []
    citations = payload.get("citations") or []
    return [item for item in citations if isinstance(item, dict)]


def _citation_pages(citations: list[dict[str, Any]]) -> list[int]:
    pages: list[int] = []
    for citation in citations:
        try:
            pages.append(int(citation.get("page")))
        except (TypeError, ValueError):
            continue
    return pages


def _retrieved_evidence_count(payload: dict[str, Any] | None) -> int:
    if payload is None:
        return 0
    evidence_ids = payload.get("supporting_evidence_ids") or []
    return max(len(evidence_ids), len(_citations(payload)))


def _artifact_written(payload: dict[str, Any] | None) -> bool:
    if payload is None:
        return False
    artifact_dir = str(payload.get("artifact_dir") or "")
    if not artifact_dir:
        return False
    path = Path(artifact_dir)
    return path.is_dir() and (path / "result.json").is_file()


def _collect_text(value: Any, *, limit: int = 20000) -> str:
    parts: list[str] = []

    def visit(item: Any) -> None:
        if sum(len(part) for part in parts) >= limit:
            return
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return "\n".join(parts)[:limit]


def _evidence_text(payload: dict[str, Any] | None) -> str:
    if payload is None:
        return ""
    evidence_payload = {
        "citations": payload.get("citations") or [],
        "supporting_evidence_ids": payload.get("supporting_evidence_ids") or [],
        "structured_result": payload.get("structured_result") or {},
    }
    return _collect_text(evidence_payload)


def _contains_all(text: str, keywords: list[str]) -> bool | None:
    if not keywords:
        return None
    normalized = text.casefold()
    return all(keyword.casefold() in normalized for keyword in keywords)


def _contains_any(text: str, keywords: Iterable[str]) -> bool:
    normalized = text.casefold()
    return any(keyword.casefold() in normalized for keyword in keywords)


def _is_structured_unsupported(payload: dict[str, Any] | None) -> bool:
    if payload is None:
        return False
    error_type = str(_error(payload).get("type") or "")
    warnings = set(_all_warnings(payload))
    if error_type in UNSUPPORTED_ERROR_TYPES:
        return True
    if error_type and ("unsupported" in error_type or "not_implemented" in error_type):
        return True
    return bool(warnings & UNSUPPORTED_WARNING_MARKERS)


def _is_abstention(payload: dict[str, Any] | None) -> bool:
    if payload is None:
        return False
    error_type = str(_error(payload).get("type") or "")
    if "insufficient" in error_type or "not_found" in error_type:
        return True
    combined = "\n".join(
        [
            _answer_preview(payload),
            _collect_text(_error(payload)),
            "\n".join(_all_warnings(payload)),
        ]
    )
    return _contains_any(combined, ABSTENTION_MARKERS)


def _stage_for_reason(reason: str) -> str:
    if reason.startswith("task_type") or reason.startswith("router") or "task_type" in reason:
        return "router"
    if "query" in reason or "llm" in reason:
        return "query_planner"
    if "evidence" in reason:
        return "retrieval"
    if "answer" in reason or "abstention" in reason or "forbidden" in reason:
        return "answer_generation"
    if "citation" in reason or "page" in reason:
        return "citation"
    if "unsupported" in reason or "not_implemented" in reason or "boundary" in reason:
        return "unsupported_boundary"
    if "stdout" in reason or "returncode" in reason or "artifact" in reason:
        return "cli_execution"
    return "metadata"


def _manual_review_reason(case: GoldenCase, reasons: list[str], *, answer_keyword_hit: bool | None) -> str:
    if case.request_form == "ambiguous" and case.expected_answer_type not in {"unsupported", "abstain"}:
        return "ambiguous_request"
    if case.answerable and case.expected_answer_type in {"extractive", "numeric"} and not case.expected_answer_keywords:
        return "missing_exact_answer_keywords"
    if any(reason in {"answer_keyword_missing", "evidence_keyword_missing", "citation_page_mismatch"} for reason in reasons):
        return "keyword_or_citation_rule_failed"
    if case.answerable and answer_keyword_hit is None:
        return "answer_quality_not_auto_judged"
    return ""


def _evaluate_case(
    *,
    case: GoldenCase,
    payload: dict[str, Any] | None,
    parse_error: str,
    returncode: int,
) -> dict[str, Any]:
    router = _router_plan(payload)
    query_planner = _query_planner(payload)
    citations = _citations(payload)
    warnings = _all_warnings(payload)
    error = _error(payload, parse_error)
    answer = _answer_preview(payload)
    evidence = _evidence_text(payload)
    actual_task_type = str(router.get("task_type") or (payload or {}).get("task_type") or "")
    cli_task_type = str((payload or {}).get("task_type") or "")
    artifact_written = _artifact_written(payload)

    evidence_keyword_hit = _contains_all(evidence, case.expected_evidence_keywords)
    answer_keyword_hit = _contains_all(answer, case.expected_answer_keywords)
    citation_page_hit = None
    if case.expected_page is not None:
        citation_page_hit = case.expected_page in _citation_pages(citations)
    unsupported_boundary_pass = None
    if case.unsupported_ok or case.expected_answer_type == "unsupported":
        unsupported_boundary_pass = _is_structured_unsupported(payload)
    abstention_pass = None
    if case.expected_answer_type == "abstain":
        abstention_pass = _is_abstention(payload)
    forbidden_hit = _contains_any(answer, case.forbidden_answer_keywords)

    reasons: list[str] = []
    if parse_error:
        reasons.append(parse_error)
    if returncode != 0:
        reasons.append(f"nonzero_returncode:{returncode}")
    if payload is None:
        reasons.append("payload_missing")
    if payload is not None and not artifact_written:
        reasons.append("artifact_missing")
    if actual_task_type != case.expected_task_type:
        reasons.append(f"task_type_mismatch:{actual_task_type or 'unknown'}!={case.expected_task_type}")

    if case.expected_answer_type == "unsupported" or case.unsupported_ok:
        if unsupported_boundary_pass is not True:
            reasons.append("unsupported_boundary_missing")
    elif case.expected_answer_type == "abstain":
        if abstention_pass is not True:
            reasons.append("abstention_missing")
        if forbidden_hit:
            reasons.append("forbidden_answer_keyword_present")
    else:
        if payload is not None and payload.get("status") != "success":
            reasons.append(f"cli_status_{payload.get('status') or 'unknown'}")
        if case.expected_task_type == "local_fact_qa":
            if not query_planner.get("enabled"):
                reasons.append("query_planner_not_enabled")
            if not query_planner.get("final_queries"):
                reasons.append("final_queries_empty")
            if _retrieved_evidence_count(payload) <= 0:
                reasons.append("retrieved_evidence_empty")
        if evidence_keyword_hit is False:
            reasons.append("evidence_keyword_missing")
        if answer_keyword_hit is False:
            reasons.append("answer_keyword_missing")
        if citation_page_hit is False:
            reasons.append("citation_page_mismatch")
        if forbidden_hit:
            reasons.append("forbidden_answer_keyword_present")
        if not answer and case.expected_task_type != "page_lookup":
            reasons.append("answer_preview_empty")

    manual_reason = _manual_review_reason(case, reasons, answer_keyword_hit=answer_keyword_hit)
    manual_review_required = bool(manual_reason)
    if manual_review_required and not reasons:
        reasons.append("manual_review_required")

    pass_fail = "passed" if not reasons else "failed"
    failure_reason = ";".join(dict.fromkeys(reasons))
    failure_stage = _stage_for_reason(reasons[0]) if reasons else ""

    return {
        "actual_task_type": actual_task_type,
        "cli_task_type": cli_task_type,
        "router_source": str(router.get("router_source") or ""),
        "query_planner_enabled": bool(query_planner.get("enabled")),
        "query_planner_mode": str(query_planner.get("mode") or ""),
        "rule_queries": query_planner.get("rule_queries") or [],
        "llm_queries": query_planner.get("llm_queries") or [],
        "llm_unique_queries": query_planner.get("llm_unique_queries") or [],
        "llm_duplicate_queries": query_planner.get("llm_duplicate_queries") or [],
        "llm_added_unique_query_count": query_planner.get("llm_added_unique_query_count") or 0,
        "llm_status": query_planner.get("llm_status") or "",
        "llm_retry_count": query_planner.get("llm_retry_count") or 0,
        "query_sources": query_planner.get("query_sources") or {},
        "final_queries": query_planner.get("final_queries") or [],
        "tools_used": (payload or {}).get("tools_used") or [],
        "retrieved_evidence_count": _retrieved_evidence_count(payload),
        "answer_preview": answer,
        "citations": citations,
        "citation_pages": _citation_pages(citations),
        "expected_page": case.expected_page,
        "expected_evidence_keywords": case.expected_evidence_keywords,
        "expected_answer_keywords": case.expected_answer_keywords,
        "evidence_keyword_hit": evidence_keyword_hit,
        "answer_keyword_hit": answer_keyword_hit,
        "citation_page_hit": citation_page_hit,
        "unsupported_boundary_pass": unsupported_boundary_pass,
        "abstention_pass": abstention_pass,
        "manual_review_required": manual_review_required,
        "manual_review_reason": manual_reason,
        "pass_fail": pass_fail,
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
        "failure_reasons": list(dict.fromkeys(reasons)),
        "warnings": warnings,
        "error": error,
        "artifact_dir": str((payload or {}).get("artifact_dir") or ""),
        "artifact_written": artifact_written,
        "status": (payload or {}).get("status") or "",
        "returncode": returncode,
        "json_valid": payload is not None,
        "stdout_preview": "",
        "stderr_preview": "",
    }


def run_case(
    *,
    case: GoldenCase,
    db_path: Path,
    doc_id: str,
    router_llm_env_file: Path,
    cli_output_dir: Path,
    cli_path: Path,
    dry_run: bool,
    python_executable: str,
    timeout_seconds: int,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    command = _build_cli_command(
        case=case,
        db_path=db_path,
        doc_id=doc_id,
        router_llm_env_file=router_llm_env_file,
        cli_output_dir=cli_output_dir,
        cli_path=cli_path,
        dry_run=dry_run,
        python_executable=python_executable,
    )
    completed = command_runner(command, ROOT, timeout_seconds)
    payload, parse_error = _parse_stdout(completed.stdout)
    evaluated = _evaluate_case(case=case, payload=payload, parse_error=parse_error, returncode=completed.returncode)
    evaluated["stdout_preview"] = completed.stdout.strip()[:1000]
    evaluated["stderr_preview"] = completed.stderr.strip()[:1000]
    evaluated["command"] = command
    return {**case.to_dict(), **evaluated}


def _count_true(rows: list[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if row.get(key) is True)


def build_summary(
    *,
    run_id: str,
    artifact_dir: Path,
    cases: list[GoldenCase],
    results: list[dict[str, Any]],
    dry_run: bool,
) -> dict[str, Any]:
    pass_fail_counts = Counter(str(row.get("pass_fail") or "") for row in results)
    request_forms = Counter(case.request_form for case in cases)
    expected_task_types = Counter(case.expected_task_type for case in cases)
    actual_task_types = Counter(str(row.get("actual_task_type") or "unknown") for row in results)
    failure_stages = Counter(str(row.get("failure_stage") or "") for row in results if row.get("failure_stage"))
    failure_reasons = Counter(
        reason
        for row in results
        for reason in (row.get("failure_reasons") or [])
        if reason
    )
    tools = Counter(tool for row in results for tool in (row.get("tools_used") or []))
    task_type_correct_count = sum(
        1
        for case, row in zip(cases, results)
        if str(row.get("actual_task_type") or "") == case.expected_task_type
    )
    summary = {
        "command": "phase5i_answer_quality_benchmark",
        "status": "success",
        "quality_status": "passed" if pass_fail_counts.get("failed", 0) == 0 else "baseline_has_failures",
        "run_id": run_id,
        "artifact_dir": str(artifact_dir),
        "case_count": len(cases),
        "passed_count": pass_fail_counts.get("passed", 0),
        "failed_count": pass_fail_counts.get("failed", 0),
        "answerable_case_count": sum(1 for case in cases if case.answerable),
        "unsupported_case_count": sum(1 for case in cases if case.expected_answer_type == "unsupported" or case.unsupported_ok),
        "abstention_case_count": sum(1 for case in cases if case.expected_answer_type == "abstain"),
        "task_type_correct_count": task_type_correct_count,
        "task_type_accuracy": round(task_type_correct_count / len(cases), 4) if cases else 0.0,
        "evidence_keyword_hit_count": _count_true(results, "evidence_keyword_hit"),
        "answer_keyword_hit_count": _count_true(results, "answer_keyword_hit"),
        "citation_page_hit_count": _count_true(results, "citation_page_hit"),
        "unsupported_boundary_pass_count": _count_true(results, "unsupported_boundary_pass"),
        "abstention_pass_count": _count_true(results, "abstention_pass"),
        "manual_review_count": sum(1 for row in results if row.get("manual_review_required")),
        "json_valid_count": sum(1 for row in results if row.get("json_valid")),
        "artifact_write_count": sum(1 for row in results if row.get("artifact_written")),
        "dry_run_cases": len(cases) if dry_run else 0,
        "non_dry_run_cases": 0 if dry_run else len(cases),
        "request_form_distribution": dict(sorted(request_forms.items())),
        "expected_task_type_distribution": dict(sorted(expected_task_types.items())),
        "actual_task_type_distribution": dict(sorted(actual_task_types.items())),
        "tools_used_distribution": dict(sorted(tools.items())),
        "failure_stage_distribution": dict(sorted(failure_stages.items())),
        "failure_reason_distribution": dict(sorted(failure_reasons.items())),
        "used_external_api": any(_used_external_api_row(row) for row in results),
        "used_vlm": False,
        "used_training": False,
        "used_full_e2e": False,
    }
    summary["cases_path"] = str(artifact_dir / "phase5i_cases.jsonl")
    summary["results_path"] = str(artifact_dir / "phase5i_results.jsonl")
    summary["summary_path"] = str(artifact_dir / "phase5i_summary.json")
    summary["preview_path"] = str(artifact_dir / "preview.json")
    summary["manual_review_path"] = str(artifact_dir / "manual_review.md")
    return summary


def _used_external_api_row(row: dict[str, Any]) -> bool:
    if row.get("router_source") == "llm_fallback":
        return True
    return str(row.get("llm_status") or "") in {"used", "api_error", "invalid_output", "echoed_payload"}


def _write_manual_review(path: Path, results: list[dict[str, Any]]) -> None:
    review_rows = [
        row
        for row in results
        if row.get("manual_review_required") or row.get("pass_fail") == "failed"
    ]
    lines = [
        "# Phase 5I Manual Review",
        "",
        "This file lists cases where lightweight keyword/citation rules are insufficient or failed.",
        "",
    ]
    if not review_rows:
        lines.append("No manual review cases were recorded.")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return
    for row in review_rows:
        lines.extend(
            [
                f"## {row.get('case_id')}",
                "",
                f"- user_request: {row.get('user_request')}",
                f"- pass_fail: {row.get('pass_fail')}",
                f"- failure_reason: {row.get('failure_reason') or ''}",
                f"- manual_review_reason: {row.get('manual_review_reason') or ''}",
                f"- expected_answer_keywords: {json.dumps(row.get('expected_answer_keywords') or [], ensure_ascii=False)}",
                f"- expected_evidence_keywords: {json.dumps(row.get('expected_evidence_keywords') or [], ensure_ascii=False)}",
                f"- citations: {json.dumps(row.get('citations') or [], ensure_ascii=False)[:1000]}",
                f"- answer_preview: {row.get('answer_preview') or ''}",
                "",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_phase5i_benchmark(
    *,
    db_path: Path,
    doc_id: str,
    router_llm_env_file: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    cli_path: Path = DEFAULT_CLI_PATH,
    cases_jsonl: Path | None = None,
    max_cases: int | None = None,
    dry_run: bool = False,
    python_executable: str = sys.executable,
    timeout_seconds: int = 180,
    command_runner: CommandRunner = _default_command_runner,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or _now_run_id()
    artifact_dir = output_root / run_id
    cli_output_dir = artifact_dir / "cli"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    cli_output_dir.mkdir(parents=True, exist_ok=True)

    cases = _read_cases_jsonl(cases_jsonl) if cases_jsonl else default_cases()
    if max_cases is not None:
        cases = cases[: max(0, int(max_cases))]

    results = [
        run_case(
            case=case,
            db_path=db_path,
            doc_id=doc_id,
            router_llm_env_file=router_llm_env_file,
            cli_output_dir=cli_output_dir,
            cli_path=cli_path,
            dry_run=dry_run,
            python_executable=python_executable,
            timeout_seconds=timeout_seconds,
            command_runner=command_runner,
        )
        for case in cases
    ]
    summary = build_summary(run_id=run_id, artifact_dir=artifact_dir, cases=cases, results=results, dry_run=dry_run)
    preview = {
        "run_id": run_id,
        "summary": summary,
        "results": results[:5],
    }

    cases_path = artifact_dir / "phase5i_cases.jsonl"
    results_path = artifact_dir / "phase5i_results.jsonl"
    summary_path = artifact_dir / "phase5i_summary.json"
    preview_path = artifact_dir / "preview.json"
    manual_review_path = artifact_dir / "manual_review.md"
    _write_jsonl(cases_path, [case.to_dict() for case in cases])
    _write_jsonl(results_path, results)
    _write_json(summary_path, summary)
    _write_json(preview_path, preview)
    _write_manual_review(manual_review_path, results)

    return {
        **summary,
        "artifact_paths": [
            str(cases_path),
            str(results_path),
            str(summary_path),
            str(preview_path),
            str(manual_review_path),
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Phase 5I answer quality golden QA benchmark.")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--doc-id", default=DEFAULT_DOC_ID)
    parser.add_argument("--router-llm-env-file", default=".secrets/router_llm.env")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--cli-path", default=str(DEFAULT_CLI_PATH))
    parser.add_argument("--cases-jsonl")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=False)
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    summary = run_phase5i_benchmark(
        db_path=_project_path(args.db_path),
        doc_id=str(args.doc_id),
        router_llm_env_file=_project_path(args.router_llm_env_file),
        output_root=_project_path(args.output_dir),
        cli_path=_project_path(args.cli_path),
        cases_jsonl=_project_path(args.cases_jsonl) if args.cases_jsonl else None,
        max_cases=args.max_cases,
        dry_run=bool(args.dry_run),
        python_executable=str(args.python_executable),
        timeout_seconds=int(args.timeout_seconds),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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

DEFAULT_DB_PATH = ROOT / "outputs" / "docagent.db"
DEFAULT_DOC_ID = "c1fc1c5e040ec894"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "benchmark" / "phase5i_answer_quality"
DEFAULT_CLI_PATH = ROOT / "scripts" / "docagent_cli.py"
DEFAULT_QWEN_BASE_MODEL_PATH = "/root/autodl-tmp/models/Qwen3-1.7B"
DEFAULT_BGE_MODEL_PATH = "/root/autodl-tmp/models/bge-m3"
DEFAULT_RERANKER_MODEL_PATH = "/root/autodl-tmp/models/bge-reranker-v2-m3"
EVALUATION_SCOPE = "pre_llm_evidence_readiness"
FINAL_ANSWER_EVALUATION_SCOPE = "final_answer_quality_small_scenario"
SCRIPT_VERSION = "phase5i-answer-quality-benchmark-v3"

UNSUPPORTED_ERROR_TYPES = {
    "document_summary_not_implemented",
    "table_lookup_not_implemented",
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
    required_evidence_keywords: list[str] | None = None
    optional_answer_keywords: list[str] | None = None
    downstream_task_type: str = ""
    requires_downstream_answer: bool | None = None
    requires_downstream_summary: bool | None = None
    requires_downstream_calculation: bool | None = None
    requires_downstream_table_lookup: bool | None = None

    @property
    def cli_question_field(self) -> str:
        return self.user_request

    @property
    def effective_required_evidence_keywords(self) -> list[str]:
        return self.required_evidence_keywords if self.required_evidence_keywords is not None else self.expected_evidence_keywords

    @property
    def effective_optional_answer_keywords(self) -> list[str]:
        return self.optional_answer_keywords if self.optional_answer_keywords is not None else self.expected_answer_keywords

    @property
    def downstream_answer_required(self) -> bool:
        if self.requires_downstream_answer is not None:
            return self.requires_downstream_answer
        return self.answerable and self.expected_task_type == "local_fact_qa" and self.expected_answer_type in {"extractive", "numeric"}

    @property
    def downstream_summary_required(self) -> bool:
        if self.requires_downstream_summary is not None:
            return self.requires_downstream_summary
        return self.expected_task_type == "document_summary" or self.request_form == "summary"

    @property
    def downstream_calculation_required(self) -> bool:
        if self.requires_downstream_calculation is not None:
            return self.requires_downstream_calculation
        lowered = f"{self.case_id} {self.user_request} {self.request_form}".casefold()
        return "calculation" in lowered or "calculate" in lowered or "difference" in lowered

    @property
    def downstream_table_required(self) -> bool:
        if self.requires_downstream_table_lookup is not None:
            return self.requires_downstream_table_lookup
        if self.downstream_calculation_required:
            return False
        lowered = f"{self.case_id} {self.user_request}".casefold()
        return self.expected_task_type == "table_lookup_or_calculation" or "table" in lowered or "row" in lowered

    @property
    def effective_downstream_task_type(self) -> str:
        if self.downstream_task_type:
            return self.downstream_task_type
        if self.downstream_summary_required:
            return "document_summary"
        if self.downstream_calculation_required:
            return "simple_calculation"
        if self.downstream_table_required:
            return "table_lookup"
        if self.downstream_answer_required:
            return "final_answer_generation"
        if self.expected_answer_type == "abstain":
            return "insufficient_evidence_decision"
        return ""

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
            "required_evidence_keywords": self.effective_required_evidence_keywords,
            "expected_answer_keywords": self.expected_answer_keywords,
            "optional_answer_keywords": self.effective_optional_answer_keywords,
            "forbidden_answer_keywords": self.forbidden_answer_keywords,
            "downstream_task_type": self.effective_downstream_task_type,
            "requires_downstream_answer": self.downstream_answer_required,
            "requires_downstream_summary": self.downstream_summary_required,
            "requires_downstream_calculation": self.downstream_calculation_required,
            "requires_downstream_table_lookup": self.downstream_table_required,
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
            required_evidence_keywords=[str(item) for item in payload.get("required_evidence_keywords") or []]
            if "required_evidence_keywords" in payload
            else None,
            optional_answer_keywords=[str(item) for item in payload.get("optional_answer_keywords") or []]
            if "optional_answer_keywords" in payload
            else None,
            downstream_task_type=str(payload.get("downstream_task_type") or ""),
            requires_downstream_answer=_optional_bool(payload.get("requires_downstream_answer")),
            requires_downstream_summary=_optional_bool(payload.get("requires_downstream_summary")),
            requires_downstream_calculation=_optional_bool(payload.get("requires_downstream_calculation")),
            requires_downstream_table_lookup=_optional_bool(payload.get("requires_downstream_table_lookup")),
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
            expected_answer_type="extractive",
            answerable=True,
            unsupported_ok=False,
            expected_page=None,
            expected_evidence_keywords=[],
            expected_answer_keywords=[],
            forbidden_answer_keywords=[],
            notes="Deterministic full-scan date extraction should run without table lookup, calculation, VLM, or answer-generation changes.",
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


def _optional_bool(value: Any) -> bool | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return bool(value)


def _write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


def _safe_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(path: Path, *, summary: dict[str, Any], artifact_paths: list[Path]) -> None:
    files = []
    for artifact_path in artifact_paths:
        if artifact_path == path or not artifact_path.is_file():
            continue
        files.append(
            {
                "path": _safe_relpath(artifact_path),
                "byte_size": artifact_path.stat().st_size,
                "sha256": _sha256_file(artifact_path),
            }
        )
    _write_json(
        path,
        {
            "run_id": summary.get("run_id"),
            "script_version": SCRIPT_VERSION,
            "evaluation_scope": summary.get("evaluation_scope"),
            "quality_status": summary.get("quality_status"),
            "final_answer_quality_evaluated": summary.get("final_answer_quality_evaluated"),
            "formal_benchmark_acceptance": summary.get("formal_benchmark_acceptance"),
            "validation_subset_used_for_training": summary.get("validation_subset_used_for_training"),
            "used_training": summary.get("used_training"),
            "used_vlm": summary.get("used_vlm"),
            "files": files,
        },
    )


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
    full_model_path: bool,
    retriever_mode: str,
    dense_backend: str,
    dense_model_path: str,
    dense_device: str,
    dense_fp16: bool,
    build_dense_index_if_missing: bool,
    reranker_backend: str,
    reranker_model_path: str,
    reranker_device: str,
    reranker_fp16: bool,
    answer_policy: str,
    base_model_path: str,
    adapter_path: str | None,
    device: str,
    torch_dtype: str,
    max_prompt_tokens: int,
    max_new_tokens: int,
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
        "--retriever-mode",
        retriever_mode,
        "--dense-backend",
        dense_backend,
        "--dense-model-path",
        dense_model_path,
        "--dense-device",
        dense_device,
        "--reranker-backend",
        reranker_backend,
        "--reranker-model-path",
        reranker_model_path,
        "--reranker-device",
        reranker_device,
        "--output-dir",
        str(cli_output_dir),
        "--answer-policy",
        answer_policy,
        "--base-model-path",
        base_model_path,
        "--device",
        device,
        "--torch-dtype",
        torch_dtype,
        "--max-prompt-tokens",
        str(max_prompt_tokens),
        "--max-new-tokens",
        str(max_new_tokens),
    ]
    if adapter_path:
        command.extend(["--adapter-path", adapter_path])
    if full_model_path:
        command.append("--full-model-path")
    if dense_fp16:
        command.append("--dense-fp16")
    if build_dense_index_if_missing:
        command.append("--build-dense-index-if-missing")
    if reranker_fp16:
        command.append("--reranker-fp16")
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


def _router_execution(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload and isinstance(payload.get("router_execution"), dict):
        return payload["router_execution"]
    return {}


def _query_planner_execution(payload: dict[str, Any] | None) -> dict[str, Any]:
    if payload and isinstance(payload.get("query_planner_execution"), dict):
        return payload["query_planner_execution"]
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
    if reason in {"retrieved_evidence_empty"}:
        return "retrieval"
    if "evidence" in reason or "insufficient_evidence" in reason:
        return "evidence_readiness"
    if "answer_keyword" in reason or "final_answer" in reason or "manual_review" in reason:
        return "downstream_answer_not_evaluated"
    if "citation" in reason or "page" in reason:
        return "citation_metadata"
    if "unsupported" in reason or "not_implemented" in reason or "boundary" in reason:
        return "unsupported_boundary"
    if "stdout" in reason or "returncode" in reason or "artifact" in reason:
        return "cli_execution"
    return "metadata"


def _manual_review_reason(
    case: GoldenCase,
    reasons: list[str],
    *,
    answer_keyword_hit: bool | None,
    evidence_ready: bool,
    final_answer_quality_evaluated: bool,
) -> str:
    if case.downstream_answer_required and evidence_ready and not final_answer_quality_evaluated:
        return "downstream_answer_required_final_answer_not_evaluated"
    if case.request_form == "ambiguous" and case.expected_answer_type not in {"unsupported", "abstain"}:
        return "ambiguous_request"
    if case.answerable and case.expected_answer_type in {"extractive", "numeric"} and not case.effective_optional_answer_keywords:
        return "missing_exact_answer_keywords"
    if any(reason in {"evidence_keyword_missing", "citation_page_mismatch", "citation_metadata_missing"} for reason in reasons):
        return "keyword_or_citation_rule_failed"
    if case.answerable and answer_keyword_hit is None and final_answer_quality_evaluated:
        return "answer_quality_not_auto_judged"
    return ""


def _evaluate_case(
    *,
    case: GoldenCase,
    payload: dict[str, Any] | None,
    parse_error: str,
    returncode: int,
    evaluate_final_answer: bool,
    full_model_path: bool,
) -> dict[str, Any]:
    router = _router_plan(payload)
    query_planner = _query_planner(payload)
    router_execution = _router_execution(payload)
    query_planner_execution = _query_planner_execution(payload)
    citations = _citations(payload)
    warnings = _all_warnings(payload)
    error = _error(payload, parse_error)
    answer = _answer_preview(payload)
    evidence = _evidence_text(payload)
    actual_task_type = str(router.get("task_type") or (payload or {}).get("task_type") or "")
    cli_task_type = str((payload or {}).get("task_type") or "")
    artifact_written = _artifact_written(payload)

    required_evidence_keywords = case.effective_required_evidence_keywords
    optional_answer_keywords = case.effective_optional_answer_keywords
    evidence_keyword_hit = _contains_all(evidence, required_evidence_keywords)
    answer_keyword_hit = _contains_all(answer, optional_answer_keywords)
    answer_keyword_evaluated = bool(evaluate_final_answer and optional_answer_keywords)
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

    downstream_answer_required = case.downstream_answer_required
    downstream_summary_required = case.downstream_summary_required
    downstream_calculation_required = case.downstream_calculation_required
    downstream_table_required = case.downstream_table_required
    downstream_required_reason = ""
    if downstream_answer_required:
        downstream_required_reason = "final_answer_generation_required_after_evidence_package"
    elif downstream_summary_required:
        downstream_required_reason = "document_summary_module_required"
    elif downstream_calculation_required:
        downstream_required_reason = "simple_calculation_module_required"
    elif downstream_table_required:
        downstream_required_reason = "table_lookup_module_required"
    elif case.expected_answer_type == "abstain":
        downstream_required_reason = "insufficient_evidence_decision_required"

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
    if full_model_path:
        if not (payload or {}).get("full_model_path"):
            reasons.append("full_model_path_not_enabled")
        if case.expected_task_type == "local_fact_qa":
            if str(query_planner.get("llm_status") or "") != "used":
                reasons.append("llm_query_rewriter_not_used")
            if not (query_planner.get("query_sources") or {}).get("llm"):
                reasons.append("llm_query_rewriter_no_downstream_query")
            if payload is not None and payload.get("status") == "success" and not (
                payload.get("trace_run_id") or payload.get("tool_run_id")
            ):
                reasons.append("trace_run_id_missing")

    if case.expected_answer_type == "unsupported" or case.unsupported_ok:
        if unsupported_boundary_pass is not True:
            reasons.append("unsupported_boundary_missing")
    elif case.expected_answer_type == "abstain":
        if abstention_pass is not True:
            reasons.append("insufficient_evidence_signal_missing")
        if evaluate_final_answer and forbidden_hit:
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
        if answer_keyword_evaluated and answer_keyword_hit is False:
            reasons.append("answer_keyword_missing")
        if citation_page_hit is False:
            reasons.append("citation_page_mismatch")
        if evaluate_final_answer and forbidden_hit:
            reasons.append("forbidden_answer_keyword_present")

    has_evidence_package = _retrieved_evidence_count(payload) > 0 or bool(citations)
    evidence_ready = False
    evidence_packaging_status = "not_ready"
    if case.expected_answer_type == "unsupported" or case.unsupported_ok:
        evidence_ready = bool(unsupported_boundary_pass)
        evidence_packaging_status = "unsupported_boundary_ready" if evidence_ready else "unsupported_boundary_missing"
    elif case.expected_answer_type == "abstain":
        evidence_ready = bool(abstention_pass)
        evidence_packaging_status = "insufficient_evidence_signal_ready" if evidence_ready else "insufficient_evidence_signal_missing"
    elif case.expected_task_type == "local_fact_qa":
        evidence_ready = (
            payload is not None
            and payload.get("status") == "success"
            and actual_task_type == case.expected_task_type
            and bool(query_planner.get("enabled"))
            and bool(query_planner.get("final_queries"))
            and has_evidence_package
            and evidence_keyword_hit is not False
            and citation_page_hit is not False
            and bool(citations)
        )
        if evidence_ready:
            evidence_packaging_status = "ready_for_downstream_answer"
        elif not has_evidence_package:
            evidence_packaging_status = "retrieved_evidence_empty"
        elif evidence_keyword_hit is False:
            evidence_packaging_status = "evidence_keyword_missing"
        elif citation_page_hit is False or not citations:
            evidence_packaging_status = "citation_metadata_questionable"
        else:
            evidence_packaging_status = "not_ready"
    else:
        evidence_ready = payload is not None and payload.get("status") == "success" and actual_task_type == case.expected_task_type
        evidence_packaging_status = "deterministic_tool_ready" if evidence_ready else "not_ready"

    if case.answerable and case.expected_task_type == "local_fact_qa" and payload is not None and not citations:
        reasons.append("citation_metadata_missing")

    manual_reason = _manual_review_reason(
        case,
        reasons,
        answer_keyword_hit=answer_keyword_hit,
        evidence_ready=evidence_ready,
        final_answer_quality_evaluated=evaluate_final_answer,
    )
    manual_review_required = bool(manual_reason)

    pass_fail = "passed" if not reasons else "failed"
    failure_reason = ";".join(dict.fromkeys(reasons))
    failure_stage = _stage_for_reason(reasons[0]) if reasons else ""

    return {
        "evaluation_scope": _evaluation_scope(evaluate_final_answer),
        "full_model_path": bool((payload or {}).get("full_model_path", False)),
        "actual_task_type": actual_task_type,
        "cli_task_type": cli_task_type,
        "downstream_task_type": case.effective_downstream_task_type,
        "downstream_answer_required": downstream_answer_required,
        "downstream_summary_required": downstream_summary_required,
        "downstream_calculation_required": downstream_calculation_required,
        "downstream_table_required": downstream_table_required,
        "downstream_required_reason": downstream_required_reason,
        "final_answer_generation_enabled": bool(evaluate_final_answer),
        "final_answer_quality_evaluated": bool(evaluate_final_answer),
        "answer_keyword_evaluated": answer_keyword_evaluated,
        "router_source": str(router.get("router_source") or ""),
        "router_execution": router_execution,
        "used_llm_router": bool((payload or {}).get("used_llm_router", False)),
        "llm_router_status": str((payload or {}).get("llm_router_status") or router_execution.get("llm_router_status") or ""),
        "llm_router_skip_reason": str(
            (payload or {}).get("llm_router_skip_reason") or router_execution.get("llm_router_skip_reason") or ""
        ),
        "rule_confidence": router_execution.get("rule_confidence", router.get("confidence")),
        "final_task_type": str(router_execution.get("final_task_type") or actual_task_type),
        "query_planner_enabled": bool(query_planner.get("enabled")),
        "query_planner_mode": str(query_planner.get("mode") or ""),
        "query_planner_execution": query_planner_execution,
        "used_llm_query_rewriter": bool((payload or {}).get("used_llm_query_rewriter", False)),
        "llm_query_rewriter_status": str(
            (payload or {}).get("llm_query_rewriter_status")
            or query_planner_execution.get("llm_query_rewriter_status")
            or query_planner.get("llm_status")
            or ""
        ),
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
        "retrieval_candidate_count": int((payload or {}).get("retrieval_candidate_count") or _retrieved_evidence_count(payload)),
        "citation_count": int((payload or {}).get("citation_count") or len(citations)),
        "trace_run_id": str((payload or {}).get("trace_run_id") or (payload or {}).get("tool_run_id") or ""),
        "answer_policy_mode": str((payload or {}).get("answer_policy_mode") or ""),
        "used_qwen_answer_policy": bool((payload or {}).get("used_qwen_answer_policy", False)),
        "used_external_answer_api": bool((payload or {}).get("used_external_answer_api", False)),
        "answer_preview": answer,
        "citations": citations,
        "citation_pages": _citation_pages(citations),
        "expected_page": case.expected_page,
        "expected_evidence_keywords": case.expected_evidence_keywords,
        "required_evidence_keywords": required_evidence_keywords,
        "expected_answer_keywords": case.expected_answer_keywords,
        "optional_answer_keywords": optional_answer_keywords,
        "evidence_keyword_hit": evidence_keyword_hit,
        "answer_keyword_hit": answer_keyword_hit,
        "citation_page_hit": citation_page_hit,
        "unsupported_boundary_pass": unsupported_boundary_pass,
        "abstention_pass": abstention_pass,
        "evidence_ready": evidence_ready,
        "evidence_readiness_pass": pass_fail == "passed",
        "evidence_packaging_status": evidence_packaging_status,
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
    evaluate_final_answer: bool,
    full_model_path: bool,
    retriever_mode: str,
    dense_backend: str,
    dense_model_path: str,
    dense_device: str,
    dense_fp16: bool,
    build_dense_index_if_missing: bool,
    reranker_backend: str,
    reranker_model_path: str,
    reranker_device: str,
    reranker_fp16: bool,
    answer_policy: str,
    base_model_path: str,
    adapter_path: str | None,
    device: str,
    torch_dtype: str,
    max_prompt_tokens: int,
    max_new_tokens: int,
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
        full_model_path=full_model_path,
        retriever_mode=retriever_mode,
        dense_backend=dense_backend,
        dense_model_path=dense_model_path,
        dense_device=dense_device,
        dense_fp16=dense_fp16,
        build_dense_index_if_missing=build_dense_index_if_missing,
        reranker_backend=reranker_backend,
        reranker_model_path=reranker_model_path,
        reranker_device=reranker_device,
        reranker_fp16=reranker_fp16,
        answer_policy=answer_policy,
        base_model_path=base_model_path,
        adapter_path=adapter_path,
        device=device,
        torch_dtype=torch_dtype,
        max_prompt_tokens=max_prompt_tokens,
        max_new_tokens=max_new_tokens,
    )
    completed = command_runner(command, ROOT, timeout_seconds)
    payload, parse_error = _parse_stdout(completed.stdout)
    evaluated = _evaluate_case(
        case=case,
        payload=payload,
        parse_error=parse_error,
        returncode=completed.returncode,
        evaluate_final_answer=evaluate_final_answer,
        full_model_path=full_model_path,
    )
    evaluated["stdout_preview"] = completed.stdout.strip()[:1000]
    evaluated["stderr_preview"] = completed.stderr.strip()[:1000]
    evaluated["command"] = command
    return {**case.to_dict(), **evaluated}


def _count_true(rows: list[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if row.get(key) is True)


def _evaluation_scope(evaluate_final_answer: bool) -> str:
    return FINAL_ANSWER_EVALUATION_SCOPE if evaluate_final_answer else EVALUATION_SCOPE


def build_summary(
    *,
    run_id: str,
    artifact_dir: Path,
    cases: list[GoldenCase],
    results: list[dict[str, Any]],
    dry_run: bool,
    evaluate_final_answer: bool,
    full_model_path: bool,
    retriever_mode: str,
    dense_backend: str,
    dense_model_path: str,
    dense_device: str,
    dense_fp16: bool,
    build_dense_index_if_missing: bool,
    reranker_backend: str,
    reranker_model_path: str,
    reranker_device: str,
    reranker_fp16: bool,
    answer_policy: str,
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
    answer_policy_modes = Counter(str(row.get("answer_policy_mode") or "unknown") for row in results)
    llm_router_statuses = Counter(str(row.get("llm_router_status") or "unknown") for row in results)
    llm_query_statuses = Counter(str(row.get("llm_query_rewriter_status") or "unknown") for row in results)
    task_type_correct_count = sum(
        1
        for case, row in zip(cases, results)
        if str(row.get("actual_task_type") or "") == case.expected_task_type
    )
    summary = {
        "command": "phase5i_answer_quality_benchmark",
        "status": "success",
        "evaluation_scope": _evaluation_scope(evaluate_final_answer),
        "full_model_path": bool(full_model_path),
        "final_answer_generation_enabled": bool(evaluate_final_answer),
        "final_answer_quality_evaluated": bool(evaluate_final_answer),
        "evidence_readiness_status": "passed" if pass_fail_counts.get("failed", 0) == 0 else "baseline_has_failures",
        "quality_status": "passed" if pass_fail_counts.get("failed", 0) == 0 else "baseline_has_failures",
        "quality_status_semantics": "small_scenario_final_answer_quality_not_formal_benchmark"
        if evaluate_final_answer
        else "pre_llm_evidence_readiness_not_final_answer_quality",
        "answer_quality_evaluation_scope": FINAL_ANSWER_EVALUATION_SCOPE if evaluate_final_answer else "not_evaluated",
        "run_id": run_id,
        "artifact_dir": str(artifact_dir),
        "retriever_mode": retriever_mode,
        "dense_backend": dense_backend,
        "dense_model_path": dense_model_path,
        "dense_device": dense_device,
        "dense_fp16": bool(dense_fp16),
        "build_dense_index_if_missing": bool(build_dense_index_if_missing),
        "reranker_backend": reranker_backend,
        "reranker_model_path": reranker_model_path,
        "reranker_device": reranker_device,
        "reranker_fp16": bool(reranker_fp16),
        "case_count": len(cases),
        "passed_count": pass_fail_counts.get("passed", 0),
        "failed_count": pass_fail_counts.get("failed", 0),
        "answerable_case_count": sum(1 for case in cases if case.answerable),
        "unsupported_case_count": sum(1 for case in cases if case.expected_answer_type == "unsupported" or case.unsupported_ok),
        "abstention_case_count": sum(1 for case in cases if case.expected_answer_type == "abstain"),
        "downstream_llm_required_count": sum(
            1
            for row in results
            if row.get("downstream_answer_required")
            or row.get("downstream_summary_required")
            or row.get("downstream_calculation_required")
            or row.get("downstream_table_required")
        ),
        "downstream_answer_required_count": _count_true(results, "downstream_answer_required"),
        "downstream_summary_required_count": _count_true(results, "downstream_summary_required"),
        "downstream_calculation_required_count": _count_true(results, "downstream_calculation_required"),
        "downstream_table_required_count": _count_true(results, "downstream_table_required"),
        "evidence_ready_count": _count_true(results, "evidence_ready"),
        "evidence_readiness_pass_count": _count_true(results, "evidence_readiness_pass"),
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
        "used_llm_router_count": _count_true(results, "used_llm_router"),
        "used_llm_query_rewriter_count": _count_true(results, "used_llm_query_rewriter"),
        "used_qwen_answer_policy_count": _count_true(results, "used_qwen_answer_policy"),
        "trace_run_id_count": sum(1 for row in results if row.get("trace_run_id")),
        "answer_policy_mode": answer_policy,
        "dry_run_cases": len(cases) if dry_run else 0,
        "non_dry_run_cases": 0 if dry_run else len(cases),
        "request_form_distribution": dict(sorted(request_forms.items())),
        "expected_task_type_distribution": dict(sorted(expected_task_types.items())),
        "actual_task_type_distribution": dict(sorted(actual_task_types.items())),
        "tools_used_distribution": dict(sorted(tools.items())),
        "answer_policy_mode_distribution": dict(sorted(answer_policy_modes.items())),
        "llm_router_status_distribution": dict(sorted(llm_router_statuses.items())),
        "llm_query_rewriter_status_distribution": dict(sorted(llm_query_statuses.items())),
        "failure_stage_distribution": dict(sorted(failure_stages.items())),
        "failure_reason_distribution": dict(sorted(failure_reasons.items())),
        "used_external_api": any(_used_external_api_row(row) for row in results),
        "used_llm_router": any(bool(row.get("used_llm_router")) for row in results),
        "used_llm_query_rewriter": any(bool(row.get("used_llm_query_rewriter")) for row in results),
        "used_qwen_answer_policy": any(bool(row.get("used_qwen_answer_policy")) for row in results),
        "used_external_answer_api": any(bool(row.get("used_external_answer_api")) for row in results),
        "used_model_answer_generation": any(bool(row.get("used_qwen_answer_policy")) or bool(row.get("used_external_answer_api")) for row in results),
        "used_vlm": False,
        "used_training": False,
        "used_full_e2e": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "training_candidate_record_count": 0,
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


def _write_manual_review(path: Path, results: list[dict[str, Any]], *, summary: dict[str, Any] | None = None) -> None:
    summary = summary or {}
    review_rows = [
        row
        for row in results
        if row.get("manual_review_required") or row.get("pass_fail") == "failed"
    ]
    lines = [
        "# Phase 5I Manual Review",
        "",
        f"- evaluation_scope: `{summary.get('evaluation_scope') or EVALUATION_SCOPE}`",
        f"- final_answer_generation_enabled: `{str(summary.get('final_answer_generation_enabled', False)).lower()}`",
        f"- final_answer_quality_evaluated: `{str(summary.get('final_answer_quality_evaluated', False)).lower()}`",
        "",
        "This file lists evidence readiness, citation metadata, router, unsupported-boundary, and downstream-review cases.",
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
                f"- evidence_ready: {row.get('evidence_ready')}",
                f"- evidence_packaging_status: {row.get('evidence_packaging_status') or ''}",
                f"- downstream_required_reason: {row.get('downstream_required_reason') or ''}",
                f"- final_answer_quality_evaluated: {row.get('final_answer_quality_evaluated')}",
                f"- expected_answer_keywords: {json.dumps(row.get('expected_answer_keywords') or [], ensure_ascii=False)}",
                f"- expected_evidence_keywords: {json.dumps(row.get('expected_evidence_keywords') or [], ensure_ascii=False)}",
                f"- citations: {json.dumps(row.get('citations') or [], ensure_ascii=False)[:1000]}",
                f"- answer_preview: {row.get('answer_preview') or ''}",
                "",
            ]
        )
        if row.get("downstream_answer_required") and row.get("evidence_ready") and not row.get("final_answer_quality_evaluated"):
            lines.extend(
                [
                    "Evidence found; final answer generation not evaluated in Phase 5I-A.",
                    "",
                ]
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _answer_correctness(row: dict[str, Any]) -> bool | None:
    if not row.get("final_answer_quality_evaluated"):
        return None
    expected_answer_type = str(row.get("expected_answer_type") or "")
    if expected_answer_type in {"extractive", "numeric"}:
        return bool(row.get("answer_keyword_hit"))
    if expected_answer_type == "abstain":
        return bool(row.get("abstention_pass"))
    if expected_answer_type == "unsupported" or row.get("unsupported_ok"):
        return bool(row.get("unsupported_boundary_pass"))
    return None


def _prediction_row(row: dict[str, Any]) -> dict[str, Any]:
    answer_correct = _answer_correctness(row)
    return {
        "case_id": row.get("case_id"),
        "user_request": row.get("user_request"),
        "expected_task_type": row.get("expected_task_type"),
        "actual_task_type": row.get("actual_task_type"),
        "expected_answer_type": row.get("expected_answer_type"),
        "prediction_answer": row.get("answer_preview") or "",
        "answer_correct": answer_correct,
        "answer_keyword_hit": row.get("answer_keyword_hit"),
        "format_valid": bool(row.get("json_valid")),
        "citation_valid": None if row.get("expected_answer_type") in {"unsupported", "abstain"} else bool(row.get("citation_count")),
        "location_valid": row.get("citation_page_hit"),
        "citation_page_hit": row.get("citation_page_hit"),
        "citations": row.get("citations") or [],
        "evidence_ready": row.get("evidence_ready"),
        "final_answer_quality_evaluated": row.get("final_answer_quality_evaluated"),
        "pass_fail": row.get("pass_fail"),
        "failure_stage": row.get("failure_stage") or "",
        "failure_reasons": row.get("failure_reasons") or [],
    }


def _case_report_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": row.get("case_id"),
        "pass_fail": row.get("pass_fail"),
        "failure_stage": row.get("failure_stage") or "",
        "failure_reasons": row.get("failure_reasons") or [],
        "manual_review_required": bool(row.get("manual_review_required")),
        "manual_review_reason": row.get("manual_review_reason") or "",
        "evaluation_scope": row.get("evaluation_scope"),
        "downstream_task_type": row.get("downstream_task_type"),
        "evidence_packaging_status": row.get("evidence_packaging_status") or "",
        "answer_correct": _answer_correctness(row),
        "format_valid": bool(row.get("json_valid")),
        "citation_valid": None if row.get("expected_answer_type") in {"unsupported", "abstain"} else bool(row.get("citation_count")),
        "location_valid": row.get("citation_page_hit"),
        "used_llm_query_rewriter": row.get("used_llm_query_rewriter"),
        "used_qwen_answer_policy": row.get("used_qwen_answer_policy"),
        "trace_run_id": row.get("trace_run_id") or "",
    }


def _metrics_payload(summary: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any]:
    evaluated_rows = [row for row in results if row.get("final_answer_quality_evaluated")]
    answer_correct_count = sum(1 for row in evaluated_rows if _answer_correctness(row) is True)
    format_valid_count = sum(1 for row in results if row.get("json_valid"))
    citation_valid_rows = [row for row in results if row.get("expected_answer_type") not in {"unsupported", "abstain"}]
    citation_valid_count = sum(1 for row in citation_valid_rows if row.get("citation_count"))
    location_rows = [row for row in results if row.get("citation_page_hit") is not None]
    location_valid_count = sum(1 for row in location_rows if row.get("citation_page_hit") is True)
    return {
        "run_id": summary.get("run_id"),
        "evaluation_scope": summary.get("evaluation_scope"),
        "quality_status": summary.get("quality_status"),
        "quality_status_semantics": summary.get("quality_status_semantics"),
        "case_count": summary.get("case_count", 0),
        "passed_count": summary.get("passed_count", 0),
        "failed_count": summary.get("failed_count", 0),
        "final_answer_quality_evaluated": summary.get("final_answer_quality_evaluated"),
        "final_answer_evaluated_count": len(evaluated_rows),
        "answer_correct_count": answer_correct_count,
        "answer_correct_rate": round(answer_correct_count / len(evaluated_rows), 4) if evaluated_rows else None,
        "format_valid_count": format_valid_count,
        "format_valid_rate": round(format_valid_count / len(results), 4) if results else None,
        "citation_valid_count": citation_valid_count,
        "citation_valid_rate": round(citation_valid_count / len(citation_valid_rows), 4) if citation_valid_rows else None,
        "location_valid_count": location_valid_count,
        "location_valid_rate": round(location_valid_count / len(location_rows), 4) if location_rows else None,
        "failure_stage_distribution": summary.get("failure_stage_distribution", {}),
        "failure_reason_distribution": summary.get("failure_reason_distribution", {}),
        "used_qwen_answer_policy_count": summary.get("used_qwen_answer_policy_count", 0),
        "used_llm_query_rewriter_count": summary.get("used_llm_query_rewriter_count", 0),
        "used_training": summary.get("used_training", False),
        "used_vlm": summary.get("used_vlm", False),
    }


def _write_failure_analysis(path: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> None:
    failed_rows = [row for row in results if row.get("pass_fail") == "failed"]
    lines = [
        "# Phase 5I-B Failure Analysis",
        "",
        f"- run_id: `{summary.get('run_id')}`",
        f"- evaluation_scope: `{summary.get('evaluation_scope')}`",
        f"- final_answer_quality_evaluated: `{str(summary.get('final_answer_quality_evaluated')).lower()}`",
        f"- failed_count: `{len(failed_rows)}`",
        "",
        "## Failure Stage Distribution",
        "",
    ]
    for key, value in sorted((summary.get("failure_stage_distribution") or {}).items()):
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Failure Reason Distribution", ""])
    for key, value in sorted((summary.get("failure_reason_distribution") or {}).items()):
        lines.append(f"- {key}: `{value}`")
    if failed_rows:
        lines.extend(["", "## Failed Cases", ""])
        for row in failed_rows[:20]:
            lines.extend(
                [
                    f"### {row.get('case_id')}",
                    "",
                    f"- failure_stage: `{row.get('failure_stage') or ''}`",
                    f"- failure_reasons: `{json.dumps(row.get('failure_reasons') or [], ensure_ascii=False)}`",
                    f"- answer_correct: `{_answer_correctness(row)}`",
                    f"- format_valid: `{bool(row.get('json_valid'))}`",
                    f"- citation_page_hit: `{row.get('citation_page_hit')}`",
                    "",
                ]
            )
    else:
        lines.extend(["", "No failed cases were recorded."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _acceptance_report(summary: dict[str, Any], metrics: dict[str, Any], formal_paths: dict[str, Path]) -> dict[str, Any]:
    return {
        "command": "phase5i_answer_quality_benchmark_acceptance_report",
        "status": "success",
        "run_id": summary.get("run_id"),
        "evaluation_scope": summary.get("evaluation_scope"),
        "benchmark_status": "small_scenario_baseline",
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "final_answer_quality_evaluated": summary.get("final_answer_quality_evaluated"),
        "used_training": summary.get("used_training", False),
        "used_vlm": summary.get("used_vlm", False),
        "quality_status": summary.get("quality_status"),
        "metrics": metrics,
        "artifact_paths": {name: str(path) for name, path in formal_paths.items()},
        "acceptance_note": (
            "This artifact contract supports Phase 5I-B small-scenario answer-quality review. "
            "It is not a leaderboard result, not a training run, and not formal benchmark acceptance."
        ),
    }


def _write_phase5ib_artifacts(artifact_dir: Path, summary: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Path]:
    paths = {
        "metrics": artifact_dir / "metrics.json",
        "predictions": artifact_dir / "predictions.jsonl",
        "case_reports": artifact_dir / "case_reports.jsonl",
        "failure_analysis": artifact_dir / "failure_analysis.md",
        "acceptance_report": artifact_dir / "acceptance_report.json",
        "training_candidates_raw": artifact_dir / "training_candidates_raw.jsonl",
    }
    metrics = _metrics_payload(summary, results)
    _write_json(paths["metrics"], metrics)
    _write_jsonl(paths["predictions"], [_prediction_row(row) for row in results])
    _write_jsonl(paths["case_reports"], [_case_report_row(row) for row in results])
    _write_failure_analysis(paths["failure_analysis"], summary, results)
    # Validation rows are diagnostic only; this file exists to satisfy the artifact
    # contract without turning validation data into training data.
    _write_jsonl(paths["training_candidates_raw"], [])
    _write_json(paths["acceptance_report"], _acceptance_report(summary, metrics, paths))
    return paths


def _llm_planning_config_status(router_llm_env_file: Path) -> dict[str, Any]:
    from docagent.router.llm_client import load_router_llm_config

    config, warnings = load_router_llm_config(env_file=router_llm_env_file, env={})
    return {
        "configured": config is not None,
        "env_file": str(router_llm_env_file),
        "warnings": warnings,
        "model": config.model if config is not None else "",
        "base_url": config.base_url if config is not None else "",
    }


def _document_context_status(db_path: Path, doc_id: str) -> dict[str, Any]:
    if not db_path.is_file():
        return {
            "ready": False,
            "blocker_type": "db_path_not_found",
            "message": f"SQLite database not found: {db_path}",
            "db_path": str(db_path),
            "doc_id": doc_id,
        }
    if not str(doc_id or "").strip():
        return {
            "ready": False,
            "blocker_type": "doc_id_missing",
            "message": "A doc_id is required for model-backed Phase 5I-B evaluation.",
            "db_path": str(db_path),
            "doc_id": doc_id,
        }
    try:
        from docagent.storage.db import connect
        from docagent.storage.repositories import DocumentRepository

        conn = connect(db_path)
        try:
            repository = DocumentRepository(conn)
            document = repository.get_document(doc_id)
            if document is None:
                return {
                    "ready": False,
                    "blocker_type": "document_not_found",
                    "message": f"Document not found: {doc_id}",
                    "db_path": str(db_path),
                    "doc_id": doc_id,
                }
            blocks = repository.load_evidence_blocks(doc_id)
            retrievable_count = sum(1 for block in blocks if block.retrieval_text.strip())
            return {
                "ready": retrievable_count > 0,
                "blocker_type": "" if retrievable_count > 0 else "document_has_no_retrievable_evidence",
                "message": "" if retrievable_count > 0 else f"Document has no retrievable EvidenceBlocks: {doc_id}",
                "db_path": str(db_path),
                "doc_id": doc_id,
                "document": {
                    "parse_status": document.get("parse_status"),
                    "page_count": document.get("page_count"),
                    "parser_backend": document.get("parser_backend"),
                },
                "evidence_block_count": len(blocks),
                "retrievable_evidence_block_count": retrievable_count,
            }
        finally:
            conn.close()
    except Exception as exc:
        return {
            "ready": False,
            "blocker_type": "document_context_preflight_error",
            "message": str(exc),
            "db_path": str(db_path),
            "doc_id": doc_id,
        }


def _blocked_summary(
    *,
    run_id: str,
    artifact_dir: Path,
    cases: list[GoldenCase],
    router_llm_env_file: Path,
    config_status: dict[str, Any] | None = None,
    full_model_path: bool,
    answer_policy: str,
    blocker_type: str = "llm_planning_config_missing",
    blocker_message: str = "",
    quality_status_semantics: str = "full_model_path_requires_llm_planning_config",
    document_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    message = blocker_message or f"Full model path requires Router/Rewriter LLM config: {router_llm_env_file}"
    summary = {
        "command": "phase5i_answer_quality_benchmark",
        "status": "blocked",
        "evaluation_scope": EVALUATION_SCOPE,
        "full_model_path": bool(full_model_path),
        "quality_status": "blocked",
        "quality_status_semantics": quality_status_semantics,
        "answer_quality_evaluation_scope": "blocked",
        "final_answer_generation_enabled": False,
        "final_answer_quality_evaluated": False,
        "run_id": run_id,
        "artifact_dir": str(artifact_dir),
        "case_count": len(cases),
        "passed_count": 0,
        "failed_count": 0,
        "blocked_count": len(cases),
        "answer_policy_mode": answer_policy,
        "llm_planning_config": config_status or {},
        "document_context": document_context or {},
        "blocker": {
            "type": blocker_type,
            "message": message,
        },
        "used_external_api": False,
        "used_llm_router": False,
        "used_llm_query_rewriter": False,
        "used_qwen_answer_policy": False,
        "used_external_answer_api": False,
        "used_model_answer_generation": False,
        "used_vlm": False,
        "used_training": False,
        "used_full_e2e": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "training_candidate_record_count": 0,
    }
    summary["cases_path"] = str(artifact_dir / "phase5i_cases.jsonl")
    summary["results_path"] = str(artifact_dir / "phase5i_results.jsonl")
    summary["summary_path"] = str(artifact_dir / "phase5i_summary.json")
    summary["preview_path"] = str(artifact_dir / "preview.json")
    summary["manual_review_path"] = str(artifact_dir / "manual_review.md")
    return summary


def _write_blocked_run_artifacts(
    *,
    artifact_dir: Path,
    cases: list[GoldenCase],
    summary: dict[str, Any],
    manual_review_message: str,
) -> dict[str, Any]:
    preview = {"run_id": summary.get("run_id"), "summary": summary, "results": []}
    cases_path = artifact_dir / "phase5i_cases.jsonl"
    results_path = artifact_dir / "phase5i_results.jsonl"
    summary_path = artifact_dir / "phase5i_summary.json"
    preview_path = artifact_dir / "preview.json"
    manual_review_path = artifact_dir / "manual_review.md"
    manifest_path = artifact_dir / "manifest.json"
    _write_jsonl(cases_path, [case.to_dict() for case in cases])
    _write_jsonl(results_path, [])
    _write_json(preview_path, preview)
    manual_review_path.write_text("# Phase 5I Manual Review\n\n" + manual_review_message.strip() + "\n", encoding="utf-8")
    formal_paths = _write_phase5ib_artifacts(artifact_dir, summary, [])
    artifact_paths = [
        str(cases_path),
        str(results_path),
        str(summary_path),
        str(preview_path),
        str(manual_review_path),
        *[str(path) for path in formal_paths.values()],
        str(manifest_path),
    ]
    summary.update(
        {
            "phase5ib_artifact_paths": {name: str(path) for name, path in formal_paths.items()},
            "artifact_paths": artifact_paths,
        }
    )
    preview["summary"] = summary
    _write_json(summary_path, summary)
    _write_json(preview_path, preview)
    _write_json(formal_paths["acceptance_report"], _acceptance_report(summary, _metrics_payload(summary, []), formal_paths))
    _write_manifest(manifest_path, summary=summary, artifact_paths=[Path(path) for path in artifact_paths])
    return {**summary, "artifact_paths": artifact_paths}


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
    evaluate_final_answer: bool = False,
    full_model_path: bool = False,
    require_llm_planning_config: bool = False,
    retriever_mode: str = "hybrid_rerank",
    dense_backend: str = "bge",
    dense_model_path: str = DEFAULT_BGE_MODEL_PATH,
    dense_device: str = "cuda:0",
    dense_fp16: bool = False,
    build_dense_index_if_missing: bool = True,
    reranker_backend: str = "cross_encoder",
    reranker_model_path: str = DEFAULT_RERANKER_MODEL_PATH,
    reranker_device: str = "cpu",
    reranker_fp16: bool = False,
    answer_policy: str = "heuristic",
    base_model_path: str = DEFAULT_QWEN_BASE_MODEL_PATH,
    adapter_path: str | None = None,
    device: str = "cuda",
    torch_dtype: str = "bfloat16",
    max_prompt_tokens: int = 4096,
    max_new_tokens: int = 1024,
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

    if full_model_path or require_llm_planning_config:
        config_status = _llm_planning_config_status(router_llm_env_file)
        if not config_status["configured"]:
            summary = _blocked_summary(
                run_id=run_id,
                artifact_dir=artifact_dir,
                cases=cases,
                router_llm_env_file=router_llm_env_file,
                config_status=config_status,
                full_model_path=full_model_path,
                answer_policy=answer_policy,
            )
            return _write_blocked_run_artifacts(
                artifact_dir=artifact_dir,
                cases=cases,
                summary=summary,
                manual_review_message="Full model path is blocked by missing Router/Rewriter LLM config.",
            )

    if (full_model_path or evaluate_final_answer) and not dry_run:
        document_context = _document_context_status(db_path, doc_id)
        if not document_context.get("ready"):
            summary = _blocked_summary(
                run_id=run_id,
                artifact_dir=artifact_dir,
                cases=cases,
                router_llm_env_file=router_llm_env_file,
                config_status=_llm_planning_config_status(router_llm_env_file) if router_llm_env_file else {},
                full_model_path=full_model_path,
                answer_policy=answer_policy,
                blocker_type=str(document_context.get("blocker_type") or "document_context_not_ready"),
                blocker_message=str(document_context.get("message") or "Document context is not ready."),
                quality_status_semantics="model_backed_evaluation_requires_existing_document_evidence",
                document_context=document_context,
            )
            return _write_blocked_run_artifacts(
                artifact_dir=artifact_dir,
                cases=cases,
                summary=summary,
                manual_review_message=str(document_context.get("message") or "Document context is not ready."),
            )

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
            evaluate_final_answer=evaluate_final_answer,
            full_model_path=full_model_path,
            retriever_mode=retriever_mode,
            dense_backend=dense_backend,
            dense_model_path=dense_model_path,
            dense_device=dense_device,
            dense_fp16=dense_fp16,
            build_dense_index_if_missing=build_dense_index_if_missing,
            reranker_backend=reranker_backend,
            reranker_model_path=reranker_model_path,
            reranker_device=reranker_device,
            reranker_fp16=reranker_fp16,
            answer_policy=answer_policy,
            base_model_path=base_model_path,
            adapter_path=adapter_path,
            device=device,
            torch_dtype=torch_dtype,
            max_prompt_tokens=max_prompt_tokens,
            max_new_tokens=max_new_tokens,
        )
        for case in cases
    ]
    summary = build_summary(
        run_id=run_id,
        artifact_dir=artifact_dir,
        cases=cases,
        results=results,
        dry_run=dry_run,
        evaluate_final_answer=evaluate_final_answer,
        full_model_path=full_model_path,
        retriever_mode=retriever_mode,
        dense_backend=dense_backend,
        dense_model_path=dense_model_path,
        dense_device=dense_device,
        dense_fp16=dense_fp16,
        build_dense_index_if_missing=build_dense_index_if_missing,
        reranker_backend=reranker_backend,
        reranker_model_path=reranker_model_path,
        reranker_device=reranker_device,
        reranker_fp16=reranker_fp16,
        answer_policy=answer_policy,
    )
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
    manifest_path = artifact_dir / "manifest.json"
    _write_jsonl(cases_path, [case.to_dict() for case in cases])
    _write_jsonl(results_path, results)
    _write_json(preview_path, preview)
    _write_manual_review(manual_review_path, results, summary=summary)
    formal_paths = _write_phase5ib_artifacts(artifact_dir, summary, results)
    artifact_paths = [
        str(cases_path),
        str(results_path),
        str(summary_path),
        str(preview_path),
        str(manual_review_path),
        *[str(path) for path in formal_paths.values()],
        str(manifest_path),
    ]
    summary.update(
        {
            "phase5ib_artifact_paths": {name: str(path) for name, path in formal_paths.items()},
            "artifact_paths": artifact_paths,
        }
    )
    preview["summary"] = summary
    _write_json(summary_path, summary)
    _write_json(preview_path, preview)
    _write_json(formal_paths["acceptance_report"], _acceptance_report(summary, _metrics_payload(summary, results), formal_paths))
    _write_manifest(manifest_path, summary=summary, artifact_paths=[Path(path) for path in artifact_paths])

    return {
        **summary,
        "artifact_paths": artifact_paths,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase 5I evidence readiness or full model-enhanced QA path validation.")
    parser.add_argument("--run-id")
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--doc-id", default=DEFAULT_DOC_ID)
    parser.add_argument("--router-llm-env-file", default=".secrets/router_llm.env")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--cli-path", default=str(DEFAULT_CLI_PATH))
    parser.add_argument("--cases-jsonl")
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=False)
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    parser.add_argument(
        "--evaluate-final-answer",
        action="store_true",
        help="Treat answer_preview keyword checks as hard final-answer checks. Disabled by default.",
    )
    parser.add_argument("--full-model-path", dest="full_model_path", action="store_true", default=True)
    parser.add_argument("--no-full-model-path", dest="full_model_path", action="store_false")
    parser.add_argument("--require-llm-planning-config", action="store_true")
    parser.add_argument("--retriever-mode", choices=["bm25", "dense", "hybrid", "hybrid_rerank"], default="hybrid_rerank")
    parser.add_argument("--dense-backend", choices=["bge", "hash"], default="bge")
    parser.add_argument("--dense-model-path", default=DEFAULT_BGE_MODEL_PATH)
    parser.add_argument("--dense-device", default="cuda:0")
    parser.add_argument("--dense-fp16", action="store_true")
    parser.add_argument("--build-dense-index-if-missing", dest="build_dense_index_if_missing", action="store_true", default=True)
    parser.add_argument("--no-build-dense-index-if-missing", dest="build_dense_index_if_missing", action="store_false")
    parser.add_argument("--reranker-backend", choices=["cross_encoder", "keyword"], default="cross_encoder")
    parser.add_argument("--reranker-model-path", default=DEFAULT_RERANKER_MODEL_PATH)
    parser.add_argument("--reranker-device", default="cpu")
    parser.add_argument("--reranker-fp16", action="store_true")
    parser.add_argument("--answer-policy", choices=["heuristic", "base", "sft", "grpo"], default="base")
    parser.add_argument("--base-model-path", default=DEFAULT_QWEN_BASE_MODEL_PATH)
    parser.add_argument("--adapter-path")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
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
        evaluate_final_answer=bool(args.evaluate_final_answer),
        full_model_path=bool(args.full_model_path),
        require_llm_planning_config=bool(args.require_llm_planning_config or args.full_model_path),
        retriever_mode=str(args.retriever_mode),
        dense_backend=str(args.dense_backend),
        dense_model_path=str(args.dense_model_path),
        dense_device=str(args.dense_device),
        dense_fp16=bool(args.dense_fp16),
        build_dense_index_if_missing=bool(args.build_dense_index_if_missing),
        reranker_backend=str(args.reranker_backend),
        reranker_model_path=str(args.reranker_model_path),
        reranker_device=str(args.reranker_device),
        reranker_fp16=bool(args.reranker_fp16),
        answer_policy=str(args.answer_policy),
        base_model_path=str(args.base_model_path),
        adapter_path=str(args.adapter_path) if args.adapter_path else None,
        device=str(args.device),
        torch_dtype=str(args.torch_dtype),
        max_prompt_tokens=int(args.max_prompt_tokens),
        max_new_tokens=int(args.max_new_tokens),
        python_executable=str(args.python_executable),
        timeout_seconds=int(args.timeout_seconds),
        run_id=str(args.run_id) if args.run_id else None,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import shutil
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.eval.answer_quality import (
    evaluate_answer,
    evaluate_format,
    evaluate_location,
    evidence_contains_keywords,
    validate_citations,
)
from docagent.eval.failure_taxonomy import classify_failure, distribution
from docagent.eval.scenario_schema import ScenarioCase, read_scenario_jsonl, summarize_scenarios, write_scenario_snapshot
from docagent.ingestion.service import DocumentIngestionService
from docagent.models.base import AnswerPolicy, GenerationResult, HeuristicAnswerPolicy
from docagent.models.openai_compatible_answer_policy import (
    OpenAICompatibleAnswerPolicy,
    OpenAICompatibleAnswerPolicyConfig,
    masked_base_url,
)
from docagent.parser.base import ParserBackend
from docagent.parser.mineru_backend import MinerUParserBackend
from docagent.parser.text_backend import TextParserBackend
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.query_planner import plan_queries
from docagent.router.rule_router import plan_route
from docagent.schemas import EvidenceBlock
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository, TraceRepository
from docagent.tools.document_tools import count_blocks, count_images, count_pages, count_tables
from docagent.tools.local_fact_qa import local_fact_qa
from docagent.workflow.prompts import compile_answer_prompt, fallback_chat_prompt


DEFAULT_SCENARIO_PATH = ROOT / "data" / "scenario_sets" / "phase5i_b" / "phase5i_b_cases.jsonl"
DEFAULT_DB_PATH = ROOT / "outputs" / "phase5i_b_model_answer_quality" / "docagent.db"
DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "phase5i_b_model_answer_quality"
DEFAULT_DOCUMENT_ROOT = DEFAULT_OUTPUT_DIR / "documents"
AVAILABLE_TOOLS = [
    "local_fact_qa",
    "count_pages",
    "count_blocks",
    "count_tables",
    "count_images",
    "get_page_text",
    "list_pages",
    "document_summary",
]


@dataclass(frozen=True)
class PolicyBuildResult:
    policy: AnswerPolicy | None
    config: dict[str, Any]
    errors: list[str]


class RecordingAnswerPolicy:
    def __init__(self, wrapped: AnswerPolicy) -> None:
        self.wrapped = wrapped
        self.mode = getattr(wrapped, "mode", "unknown")
        self.calls: list[dict[str, Any]] = []

    def generate(
        self,
        *,
        question: str,
        evidence_blocks: list[EvidenceBlock],
        tool_results: list[dict[str, Any]] | None = None,
        answer_type: str | None = None,
        qid: str | None = None,
    ) -> GenerationResult:
        result = self.wrapped.generate(
            question=question,
            evidence_blocks=evidence_blocks,
            tool_results=tool_results,
            answer_type=answer_type,
            qid=qid,
        )
        self.calls.append(
            {
                "qid": qid or "",
                "raw_text": result.raw_text,
                "parsed": result.parsed,
                "prompt_token_count": result.prompt_token_count,
                "completion_token_count": result.completion_token_count,
                "finish_reason": result.finish_reason,
                "latency_ms": result.latency_ms,
                "metadata": result.metadata,
            }
        )
        return result

    def latest_call(self, qid: str) -> dict[str, Any]:
        for call in reversed(self.calls):
            if call.get("qid") == qid:
                return call
        return {}


class FakeScenarioAnswerPolicy:
    mode = "fake"

    def __init__(self, cases: list[ScenarioCase]) -> None:
        self.cases = {case.case_id: case for case in cases}

    def generate(
        self,
        *,
        question: str,
        evidence_blocks: list[EvidenceBlock],
        tool_results: list[dict[str, Any]] | None = None,
        answer_type: str | None = None,
        qid: str | None = None,
    ) -> GenerationResult:
        case = self.cases.get(str(qid or ""))
        answer = "Insufficient evidence in the provided document to answer." if case and case.answer_type == "refusal" else str((case.gold_answer if case else "") or "")
        block = _select_fake_block(case, evidence_blocks)
        parsed = {
            "answer": answer,
            "evidence_location": _block_location(block) if block else {},
            "evidence": _block_preview(block),
            "reason": "Fake policy output for deterministic runner tests.",
        }
        bundle = compile_answer_prompt(question=question, evidence_blocks=evidence_blocks, tool_results=tool_results, answer_type=answer_type)
        prompt_text = fallback_chat_prompt(bundle.messages)
        raw_text = json.dumps(parsed, ensure_ascii=False)
        return GenerationResult(
            raw_text=raw_text,
            parsed=parsed,
            prompt_text=prompt_text,
            prompt_token_count=len(prompt_text.split()),
            completion_token_count=len(raw_text.split()),
            finish_reason="fake",
            latency_ms=0.0,
            metadata={"policy_mode": self.mode, "qid": qid, "parse_result": {"schema_ok": True}, **bundle.metadata},
        )


class ExistingMinerUParserBackend(ParserBackend):
    backend_name = "mineru_existing"

    def __init__(self, source_dir: Path) -> None:
        self.source_dir = source_dir

    def parse(self, *, file_path: Path, doc_id: str, output_dir: Path) -> list[EvidenceBlock]:
        if output_dir.exists():
            shutil.rmtree(output_dir)
        shutil.copytree(self.source_dir, output_dir)
        return MinerUParserBackend(mode="parse_existing").parse(file_path=file_path, doc_id=doc_id, output_dir=output_dir)


def run_phase5i_b_model_answer_quality(
    *,
    scenario_path: Path = DEFAULT_SCENARIO_PATH,
    db_path: Path = DEFAULT_DB_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    document_root: Path = DEFAULT_DOCUMENT_ROOT,
    allow_external_api: bool = False,
    answer_policy_provider: str = "openai_compatible",
    answer_policy_model: str = "",
    answer_policy_env_file: Path | None = None,
    enable_query_planning: bool = False,
    query_planner_mode: str = "rule",
    max_cases: int | None = None,
    fail_on_api_error: bool = False,
    export_training_candidates: bool = True,
    run_id: str | None = None,
) -> dict[str, Any]:
    scenario_path = _project_path(scenario_path)
    db_path = _project_path(db_path)
    output_dir = _project_path(output_dir)
    document_root = _project_path(document_root)
    answer_policy_env_file = _project_path(answer_policy_env_file) if answer_policy_env_file else ROOT / ".secrets" / "answer_policy.env"
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = run_id or _now_run_id()

    cases = read_scenario_jsonl(scenario_path)
    if max_cases is not None:
        cases = cases[: max(0, int(max_cases))]
    scenario_summary = summarize_scenarios(cases)
    write_scenario_snapshot(output_dir / "scenario_snapshot.jsonl", cases)

    policy_result = _build_policy(
        provider=answer_policy_provider,
        cases=cases,
        allow_external_api=allow_external_api,
        env_file=answer_policy_env_file,
        model_override=answer_policy_model,
    )
    _write_json(output_dir / "model_config_masked.json", policy_result.config)
    if policy_result.policy is None:
        return _write_skipped_api_report(
            output_dir=output_dir,
            scenario_path=scenario_path,
            scenario_summary=scenario_summary,
            model_config=policy_result.config,
            errors=policy_result.errors,
        )

    recording_policy = RecordingAnswerPolicy(policy_result.policy)
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        trace_repository = TraceRepository(conn)
        doc_cache: dict[str, str] = {}
        predictions: list[dict[str, Any]] = []
        case_reports: list[dict[str, Any]] = []
        for case in cases:
            prediction, report = _run_case(
                case=case,
                scenario_path=scenario_path,
                repository=repository,
                trace_repository=trace_repository,
                document_root=document_root,
                doc_cache=doc_cache,
                answer_policy=recording_policy,
                case_dir=output_dir / "cli_artifacts" / case.case_id,
                enable_query_planning=enable_query_planning,
                query_planner_mode=query_planner_mode,
                provider=answer_policy_provider,
            )
            predictions.append(prediction)
            case_reports.append(report)
    finally:
        conn.close()

    metrics = _build_metrics(
        predictions=predictions,
        scenario_summary=scenario_summary,
        provider=answer_policy_provider,
        used_external_api=bool(answer_policy_provider == "openai_compatible" and allow_external_api),
    )
    training_candidates = _build_training_candidates(case_reports) if export_training_candidates else []
    _write_json(output_dir / "metrics.json", metrics)
    _write_jsonl(output_dir / "predictions.jsonl", predictions)
    _write_jsonl(output_dir / "case_reports.jsonl", case_reports)
    _write_jsonl(output_dir / "training_candidates_raw.jsonl", training_candidates)
    _write_failure_analysis(output_dir / "failure_analysis.md", metrics=metrics, case_reports=case_reports)

    status = "completed"
    if fail_on_api_error and metrics["api_error_count"]:
        status = "failed"
    acceptance_report = {
        "phase": "Phase 5I-B",
        "status": status,
        "acceptance_state": _acceptance_state(answer_policy_provider, allow_external_api, metrics),
        "run_id": run_id,
        "used_model_answer_generation": bool(answer_policy_provider == "openai_compatible" and metrics["completed_count"] > 0),
        "used_external_api": bool(answer_policy_provider == "openai_compatible" and allow_external_api),
        "used_fake_policy": answer_policy_provider == "fake",
        "used_vlm": False,
        "used_training": False,
        "used_grpo": False,
        "used_table_lookup": False,
        "used_simple_calculation": False,
        "final_answer_quality_evaluated": True,
        "scenario_path": str(scenario_path),
        "output_dir": str(output_dir),
        "metrics_path": str(output_dir / "metrics.json"),
        "predictions_path": str(output_dir / "predictions.jsonl"),
        "failure_analysis_path": str(output_dir / "failure_analysis.md"),
        "training_candidates_path": str(output_dir / "training_candidates_raw.jsonl"),
        "model_config_path": str(output_dir / "model_config_masked.json"),
        "scenario_summary": scenario_summary,
        "notes": _acceptance_notes(answer_policy_provider, allow_external_api, metrics),
    }
    _write_json(output_dir / "acceptance_report.json", acceptance_report)
    return acceptance_report


def _run_case(
    *,
    case: ScenarioCase,
    scenario_path: Path,
    repository: DocumentRepository,
    trace_repository: TraceRepository,
    document_root: Path,
    doc_cache: dict[str, str],
    answer_policy: RecordingAnswerPolicy,
    case_dir: Path,
    enable_query_planning: bool,
    query_planner_mode: str,
    provider: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    case_dir.mkdir(parents=True, exist_ok=True)
    warnings: list[str] = []
    ingestion_error = ""
    doc_id = case.doc_id
    if not doc_id:
        if case.doc_key in doc_cache:
            doc_id = doc_cache[case.doc_key]
        else:
            source_file = _resolve_case_file(case, scenario_path)
            if not source_file.is_file():
                if case.optional_fixture:
                    prediction = _skipped_prediction(case, ["skipped_missing_optional_fixture"])
                    return prediction, {"case": case.to_dict(), "prediction": prediction, "warnings": prediction["warnings"]}
                ingestion_error = f"file_not_found:{source_file}"
            if not ingestion_error:
                try:
                    parser = _parser_for_case(case, scenario_path)
                    result = DocumentIngestionService(document_root=document_root, repository=repository).ingest(
                        file_path=source_file,
                        parser_backend=parser,
                        force_parse=False,
                    )
                    doc_id = result.document.doc_id
                    doc_cache[case.doc_key] = doc_id
                except Exception as exc:
                    ingestion_error = str(exc)

    router_plan: dict[str, Any] = {}
    tool_result: dict[str, Any] = {}
    query_planner_payload: dict[str, Any] = {}
    retrieved_blocks: list[EvidenceBlock] = []
    evidence_blocks = repository.load_evidence_blocks(doc_id) if doc_id and not ingestion_error else []
    actual_task_type = ""
    if not ingestion_error:
        profile = _document_profile(repository, doc_id)
        router_plan = plan_route(
            {
                "doc_id": doc_id,
                "question": case.question,
                "available_tools": AVAILABLE_TOOLS,
                "document_profile": profile,
                "options": {"prefer_deterministic_tools": True, "max_tool_calls": 4},
            }
        )
        actual_task_type = str(router_plan.get("task_type") or "")
        if actual_task_type == "local_fact_qa":
            retriever = None
            if enable_query_planning:
                query_plan = plan_queries(
                    question=case.question,
                    task_type=actual_task_type,
                    document_profile=profile,
                    mode=query_planner_mode,
                    answer_type_hint=case.answer_type,
                )
                query_planner_payload = {"enabled": True, **query_plan.to_dict()}
                retriever = IndexedDocumentRetriever(evidence_blocks, mode="bm25", query_plan=query_plan)
            tool_result = local_fact_qa(
                {
                    "doc_id": doc_id,
                    "question": case.question,
                    "router_plan": router_plan,
                    "options": {
                        "qid": case.case_id,
                        "trace_path": str(case_dir / "trace.json"),
                        "answer_type_hint": case.answer_type,
                        "top_k": 5,
                    },
                },
                document_repository=repository,
                trace_repository=trace_repository,
                answer_policy=answer_policy,
                retriever=retriever,
            )
            by_id = {block.block_id: block for block in evidence_blocks}
            retrieved_blocks = [by_id[block_id] for block_id in tool_result.get("supporting_evidence_ids") or [] if block_id in by_id]
        else:
            tool_result = {
                "status": "error",
                "answer": "",
                "citations": [],
                "supporting_evidence_ids": [],
                "warnings": router_plan.get("warnings") or [],
                "error": {"type": "router_task_type_mismatch", "message": actual_task_type},
                "final_answer": {},
            }

    model_call = answer_policy.latest_call(case.case_id)
    final_answer = tool_result.get("final_answer") if isinstance(tool_result.get("final_answer"), dict) else {}
    predicted_answer = str(tool_result.get("answer") or final_answer.get("answer") or "")
    answer_eval = evaluate_answer(
        predicted_answer=predicted_answer,
        gold_answer=case.gold_answer,
        answer_type=case.answer_type,
        eval_method=case.eval_method,
    )
    format_eval = evaluate_format(final_answer)
    citation_eval = validate_citations(
        citations=tool_result.get("citations") if isinstance(tool_result.get("citations"), list) else [],
        final_answer=final_answer,
        evidence_blocks=evidence_blocks,
    )
    location_eval = evaluate_location(
        final_answer=final_answer,
        citations=tool_result.get("citations") if isinstance(tool_result.get("citations"), list) else [],
        gold_locations=[item.to_dict() for item in case.gold_locations],
    )
    evidence_has_gold = evidence_contains_keywords(retrieved_blocks, case.gold_evidence_text_contains)
    error_payload = tool_result.get("error") if isinstance(tool_result.get("error"), dict) else {}
    model_error = str(error_payload.get("message") or "")
    model_api_error = model_error if "OpenAI-compatible answer API" in model_error else ""
    parse_result = (model_call.get("metadata") or {}).get("parse_result") if model_call else {}
    parse_error = str(parse_result.get("error") or "") if isinstance(parse_result, dict) else ""
    unsupported = str(error_payload.get("type") or "") in {"unsupported_task", "unsupported_task_type"}
    failure_stage = classify_failure(
        status="completed" if tool_result.get("status") == "success" else "failed",
        expected_task_type=case.expected_task_type,
        actual_task_type=actual_task_type,
        ingestion_error=ingestion_error,
        model_api_error=model_api_error,
        model_output_parse_error=parse_error if model_call and not format_eval["json_valid"] else "",
        unsupported=unsupported,
        evidence_context_has_gold=evidence_has_gold,
        answer_correct=answer_eval["answer_correct"],
        format_valid=format_eval["format_valid"],
        citation_valid=citation_eval["citation_valid"],
        location_correct=location_eval["location_correct"],
        refusal_expected=case.answer_type == "refusal",
        refusal_correct=answer_eval["answer_correct"],
    )
    status = "completed" if failure_stage == "none" else "failed"
    prediction = {
        "case_id": case.case_id,
        "status": status,
        "task_type": actual_task_type,
        "question": case.question,
        "gold_answer": case.gold_answer,
        "predicted_answer": predicted_answer,
        "answer_type": case.answer_type,
        **answer_eval,
        **format_eval,
        **citation_eval,
        **location_eval,
        "evidence_context_has_gold": evidence_has_gold,
        "used_model_answer_generation": bool(provider == "openai_compatible" and model_call and not model_api_error),
        "used_fake_policy": provider == "fake",
        "failure_stage": None if failure_stage == "none" else failure_stage,
        "warnings": list(dict.fromkeys([*warnings, *(tool_result.get("warnings") or [])])),
        "api_error": model_api_error,
    }
    case_report = {
        "case": case.to_dict(),
        "prediction": prediction,
        "doc_id": doc_id,
        "router_plan": router_plan,
        "query_planner": query_planner_payload,
        "tool_result": tool_result,
        "retrieved_evidence_summary": [_block_summary(block) for block in retrieved_blocks],
        "model_io": _model_io(model_call, provider=provider),
    }
    _write_json(case_dir / "router_plan.json", router_plan)
    _write_json(case_dir / "result.json", {"prediction": prediction, "tool_result": tool_result})
    _write_json(case_dir / "summary.json", {"case_id": case.case_id, "status": status, "failure_stage": prediction["failure_stage"]})
    _write_json(case_dir / "trace.json", {"router_plan": router_plan, "query_planner": query_planner_payload, "tool_trace": tool_result.get("trace_path") or ""})
    _write_json(case_dir / "model_io.json", case_report["model_io"])
    return prediction, case_report


def _build_metrics(
    *,
    predictions: list[dict[str, Any]],
    scenario_summary: dict[str, int],
    provider: str,
    used_external_api: bool,
) -> dict[str, Any]:
    evaluated = [row for row in predictions if row.get("status") != "skipped"]
    completed = [row for row in evaluated if row.get("status") == "completed"]
    refusal_rows = [row for row in evaluated if row.get("answer_type") == "refusal"]
    return {
        "evaluation_scope": "final_answer_quality",
        "final_answer_generation_enabled": provider in {"openai_compatible", "fake", "heuristic"},
        "final_answer_quality_evaluated": True,
        "case_count": len(predictions),
        "completed_count": len(completed),
        "failed_count": sum(1 for row in predictions if row.get("status") == "failed"),
        "skipped_count": sum(1 for row in predictions if row.get("status") == "skipped"),
        "answer_accuracy": _rate(completed, "answer_correct"),
        "normalized_exact_match": _average(completed, "normalized_exact_match"),
        "average_token_f1": _average(completed, "token_f1"),
        "json_valid_rate": _rate(evaluated, "json_valid"),
        "citation_valid_rate": _rate(evaluated, "citation_valid"),
        "location_accuracy": _rate(evaluated, "location_correct"),
        "refusal_accuracy": _rate(refusal_rows, "answer_correct"),
        "router_task_type_accuracy": _router_accuracy(predictions),
        "unsupported_count": sum(1 for row in predictions if row.get("failure_stage") == "unsupported_task"),
        "api_error_count": sum(1 for row in predictions if row.get("failure_stage") == "model_api_error"),
        "failure_stage_distribution": distribution(predictions),
        "used_external_api": used_external_api,
        "used_fake_policy": provider == "fake",
        "used_model_answer_generation": any(row.get("used_model_answer_generation") for row in predictions),
        "scenario_summary": scenario_summary,
    }


def _write_skipped_api_report(
    *,
    output_dir: Path,
    scenario_path: Path,
    scenario_summary: dict[str, int],
    model_config: dict[str, Any],
    errors: list[str],
) -> dict[str, Any]:
    metrics = {
        "evaluation_scope": "final_answer_quality",
        "final_answer_generation_enabled": False,
        "final_answer_quality_evaluated": False,
        "case_count": scenario_summary["case_count"],
        "completed_count": 0,
        "failed_count": 0,
        "skipped_count": scenario_summary["case_count"],
        "answer_accuracy": 0.0,
        "normalized_exact_match": 0.0,
        "average_token_f1": 0.0,
        "json_valid_rate": 0.0,
        "citation_valid_rate": 0.0,
        "location_accuracy": 0.0,
        "refusal_accuracy": 0.0,
        "router_task_type_accuracy": 0.0,
        "unsupported_count": 0,
        "api_error_count": 0,
        "failure_stage_distribution": {},
        "used_external_api": False,
        "used_fake_policy": False,
        "used_model_answer_generation": False,
        "scenario_summary": scenario_summary,
    }
    _write_json(output_dir / "metrics.json", metrics)
    _write_jsonl(output_dir / "predictions.jsonl", [])
    _write_jsonl(output_dir / "case_reports.jsonl", [])
    _write_jsonl(output_dir / "training_candidates_raw.jsonl", [])
    _write_failure_analysis(output_dir / "failure_analysis.md", metrics=metrics, case_reports=[])
    report = {
        "phase": "Phase 5I-B",
        "status": "skipped_api_missing",
        "acceptance_state": "skipped_api_missing",
        "used_model_answer_generation": False,
        "used_external_api": False,
        "used_fake_policy": False,
        "used_vlm": False,
        "used_training": False,
        "used_grpo": False,
        "used_table_lookup": False,
        "used_simple_calculation": False,
        "final_answer_quality_evaluated": False,
        "scenario_path": str(scenario_path),
        "output_dir": str(output_dir),
        "metrics_path": str(output_dir / "metrics.json"),
        "predictions_path": str(output_dir / "predictions.jsonl"),
        "failure_analysis_path": str(output_dir / "failure_analysis.md"),
        "training_candidates_path": str(output_dir / "training_candidates_raw.jsonl"),
        "model_config_path": str(output_dir / "model_config_masked.json"),
        "scenario_summary": scenario_summary,
        "model_config_masked": model_config,
        "notes": list(dict.fromkeys(errors)),
    }
    _write_json(output_dir / "acceptance_report.json", report)
    return report


def _build_policy(
    *,
    provider: str,
    cases: list[ScenarioCase],
    allow_external_api: bool,
    env_file: Path,
    model_override: str,
) -> PolicyBuildResult:
    if provider == "fake":
        return PolicyBuildResult(
            policy=FakeScenarioAnswerPolicy(cases),
            config=_model_config(provider=provider, model="fake", used_external_api=False, base_url="", api_key_configured=False),
            errors=[],
        )
    if provider == "heuristic":
        return PolicyBuildResult(
            policy=HeuristicAnswerPolicy(),
            config=_model_config(provider=provider, model="heuristic", used_external_api=False, base_url="", api_key_configured=False),
            errors=[],
        )
    if provider != "openai_compatible":
        return PolicyBuildResult(
            policy=None,
            config=_model_config(provider=provider, model="", used_external_api=False, base_url="", api_key_configured=False),
            errors=[f"unsupported_answer_policy_provider:{provider}"],
        )
    env = _load_env_file(env_file)
    base_url = str(env.get("DOCAGENT_ANSWER_BASE_URL") or "").strip()
    api_key = str(env.get("DOCAGENT_ANSWER_API_KEY") or "").strip()
    model = str(model_override or env.get("DOCAGENT_ANSWER_MODEL") or "").strip()
    timeout = _optional_float(env.get("DOCAGENT_ANSWER_TIMEOUT_SECONDS"), 60.0)
    temperature = _optional_float(env.get("DOCAGENT_ANSWER_TEMPERATURE"), 0.0)
    config = _model_config(
        provider=provider,
        model=model,
        used_external_api=False,
        external_api_allowed=bool(allow_external_api),
        base_url=base_url,
        api_key_configured=bool(api_key),
        timeout=timeout,
        temperature=temperature,
        env_file_exists=env_file.is_file(),
    )
    errors = []
    if not allow_external_api:
        errors.append("allow_external_api_required")
    if not env_file.is_file():
        errors.append("answer_policy_env_file_missing")
    if not base_url:
        errors.append("DOCAGENT_ANSWER_BASE_URL_missing")
    if not api_key:
        errors.append("DOCAGENT_ANSWER_API_KEY_missing")
    if not model:
        errors.append("DOCAGENT_ANSWER_MODEL_missing")
    if errors:
        return PolicyBuildResult(policy=None, config=config, errors=errors)
    return PolicyBuildResult(
        policy=OpenAICompatibleAnswerPolicy(
            OpenAICompatibleAnswerPolicyConfig(
                base_url=base_url,
                api_key=api_key,
                model=model,
                timeout_seconds=timeout,
                temperature=temperature,
            )
        ),
        config=config,
        errors=[],
    )


def _model_config(
    *,
    provider: str,
    model: str,
    used_external_api: bool,
    base_url: str,
    api_key_configured: bool,
    external_api_allowed: bool = False,
    timeout: float = 0.0,
    temperature: float = 0.0,
    env_file_exists: bool = False,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "model": model,
        "used_external_api": used_external_api,
        "external_api_allowed": external_api_allowed,
        "base_url_masked": masked_base_url(base_url),
        "timeout": timeout,
        "temperature": temperature,
        "api_key_configured": api_key_configured,
        "api_key_logged": False,
        "env_file_exists": env_file_exists,
    }


def _document_profile(repository: DocumentRepository, doc_id: str) -> dict[str, Any]:
    page_result = count_pages(repository, doc_id)
    block_result = count_blocks(repository, doc_id)
    table_result = count_tables(repository, doc_id)
    image_result = count_images(repository, doc_id)
    return {
        "page_count": page_result.get("page_count") if page_result.get("status") == "success" else None,
        "block_count": block_result.get("block_count") if block_result.get("status") == "success" else None,
        "table_count": table_result.get("table_count") if table_result.get("status") == "success" else None,
        "image_count": image_result.get("image_count") if image_result.get("status") == "success" else None,
        "has_ocr": bool((block_result.get("block_count") or 0) > 0),
        "has_tables": bool((table_result.get("table_count") or 0) > 0),
        "has_images": bool((image_result.get("image_count") or 0) > 0),
    }


def _parser_for_case(case: ScenarioCase, scenario_path: Path) -> ParserBackend:
    if case.parser == "text":
        return TextParserBackend()
    if case.parser == "mineru_existing":
        return ExistingMinerUParserBackend(_resolve_path(case.mineru_output_dir, scenario_path))
    raise ValueError(f"unsupported parser: {case.parser}")


def _resolve_case_file(case: ScenarioCase, scenario_path: Path) -> Path:
    return _resolve_path(case.file, scenario_path)


def _resolve_path(value: str | Path, scenario_path: Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    root_relative = ROOT / path
    if root_relative.exists():
        return root_relative
    return scenario_path.parent / path


def _skipped_prediction(case: ScenarioCase, warnings: list[str]) -> dict[str, Any]:
    return {
        "case_id": case.case_id,
        "status": "skipped",
        "task_type": "",
        "question": case.question,
        "gold_answer": case.gold_answer,
        "predicted_answer": "",
        "answer_type": case.answer_type,
        "answer_correct": False,
        "token_f1": 0.0,
        "normalized_exact_match": 0.0,
        "citation_valid": False,
        "location_correct": False,
        "json_valid": False,
        "used_model_answer_generation": False,
        "used_fake_policy": False,
        "failure_stage": "unknown_error",
        "warnings": warnings,
    }


def _model_io(model_call: dict[str, Any], *, provider: str) -> dict[str, Any]:
    metadata = dict(model_call.get("metadata") or {})
    raw_text = str(model_call.get("raw_text") or "")
    return {
        "provider": provider,
        "called_answer_policy_generate": bool(model_call),
        "raw_model_output_preview": raw_text[:1000],
        "parsed": model_call.get("parsed") or {},
        "prompt_token_count": model_call.get("prompt_token_count"),
        "completion_token_count": model_call.get("completion_token_count"),
        "finish_reason": model_call.get("finish_reason") or "",
        "latency_ms": model_call.get("latency_ms"),
        "metadata": {key: value for key, value in metadata.items() if key not in {"raw_model_output", "canonical_output"}},
    }


def _build_training_candidates(case_reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    candidates = []
    for report in case_reports:
        prediction = report.get("prediction") or {}
        if prediction.get("status") == "completed" and prediction.get("answer_correct") is True:
            continue
        candidates.append(
            {
                "case_id": prediction.get("case_id") or "",
                "question": prediction.get("question") or "",
                "evidence_context": "\n\n".join(item.get("text_preview") or "" for item in report.get("retrieved_evidence_summary") or []),
                "tool_results": {"router_plan": report.get("router_plan") or {}},
                "gold_answer": prediction.get("gold_answer"),
                "gold_locations": (report.get("case") or {}).get("gold_locations") or [],
                "model_output": (report.get("model_io") or {}).get("parsed") or {},
                "failure_stage": prediction.get("failure_stage") or "none",
                "candidate_use": ["sft", "prompt_debug"],
                "requires_human_review": True,
            }
        )
    return candidates


def _write_failure_analysis(path: Path, *, metrics: dict[str, Any], case_reports: list[dict[str, Any]]) -> None:
    stage_counts = metrics.get("failure_stage_distribution") or {}
    lines = [
        "# Phase 5I-B Failure Analysis",
        "",
        "## 1. 总览",
        "",
        f"- case_count: {metrics.get('case_count')}",
        f"- answer_accuracy: {metrics.get('answer_accuracy')}",
        f"- json_valid_rate: {metrics.get('json_valid_rate')}",
        f"- citation_valid_rate: {metrics.get('citation_valid_rate')}",
        f"- location_accuracy: {metrics.get('location_accuracy')}",
        "",
        "## 2. 按失败阶段统计",
        "",
        "| failure_stage | count | representative_cases |",
        "|---|---:|---|",
    ]
    if stage_counts:
        for stage, count in stage_counts.items():
            representatives = [str((report.get("prediction") or {}).get("case_id")) for report in case_reports if (report.get("prediction") or {}).get("failure_stage") == stage][:5]
            lines.append(f"| {stage} | {count} | {', '.join(representatives)} |")
    else:
        lines.append("| none | 0 |  |")
    lines.extend(["", "## 3. 典型失败样本", ""])
    failures = [report for report in case_reports if (report.get("prediction") or {}).get("failure_stage")]
    if not failures:
        lines.append("No failed cases were recorded.")
    for report in failures[:10]:
        prediction = report.get("prediction") or {}
        lines.extend(
            [
                f"### {prediction.get('case_id')}",
                "",
                f"- question: {prediction.get('question')}",
                f"- gold_answer: {prediction.get('gold_answer')}",
                f"- predicted_answer: {prediction.get('predicted_answer')}",
                f"- retrieved_evidence_summary: {json.dumps(report.get('retrieved_evidence_summary') or [], ensure_ascii=False)[:1000]}",
                f"- failure_stage: {prediction.get('failure_stage')}",
                f"- likely_root_cause: {prediction.get('failure_stage')}",
                "- suggested_next_action: manual review before SFT/GRPO or prompt changes.",
                "",
            ]
        )
    lines.extend(
        [
            "## 4. 后续优化建议",
            "",
            "- retrieval: inspect retrieval_miss cases before changing retriever defaults.",
            "- evidence packing: inspect evidence_context_missing_answer and location_error cases.",
            "- prompt / output format: inspect model_output_parse_error and format_error cases.",
            "- SFT data: only promote reviewed training_candidates_raw records.",
            "- GRPO data: do not use raw candidates until human review and reward design are approved.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def _acceptance_state(provider: str, allow_external_api: bool, metrics: dict[str, Any]) -> str:
    if provider == "fake":
        return "mock_verified"
    if provider == "openai_compatible" and allow_external_api and metrics["completed_count"] >= 8 and metrics["api_error_count"] == 0:
        return "acceptance_candidate"
    return "implemented"


def _acceptance_notes(provider: str, allow_external_api: bool, metrics: dict[str, Any]) -> list[str]:
    notes = ["small_scenario_baseline_not_leaderboard"]
    if provider == "fake":
        notes.append("fake_policy_run_not_real_model_acceptance")
    if provider == "openai_compatible" and not allow_external_api:
        notes.append("external_api_disabled")
    if metrics.get("api_error_count"):
        notes.append("api_errors_present")
    return notes


def _select_fake_block(case: ScenarioCase | None, blocks: list[EvidenceBlock]) -> EvidenceBlock | None:
    if not blocks:
        return None
    if case and case.gold_locations:
        pages = {item.page for item in case.gold_locations}
        for block in blocks:
            if block.page_id in pages or block.location.page in pages:
                return block
    return blocks[0]


def _block_location(block: EvidenceBlock) -> dict[str, Any]:
    return {"page": block.location.page if block.location.page is not None else block.page_id, "block_id": block.block_id}


def _block_preview(block: EvidenceBlock | None, limit: int = 300) -> str:
    if block is None:
        return ""
    return " ".join(block.retrieval_text.split())[:limit]


def _block_summary(block: EvidenceBlock) -> dict[str, Any]:
    return {
        "block_id": block.block_id,
        "page": block.location.page if block.location.page is not None else block.page_id,
        "text_preview": _block_preview(block),
    }


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        result[key.strip()] = value.strip().strip("\"'")
    return result


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _project_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def _rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if row.get(key) is True) / len(rows), 4)


def _average(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(float(row.get(key) or 0.0) for row in rows) / len(rows), 4)


def _router_accuracy(predictions: list[dict[str, Any]]) -> float:
    evaluated = [row for row in predictions if row.get("status") != "skipped"]
    if not evaluated:
        return 0.0
    correct = sum(1 for row in evaluated if row.get("failure_stage") != "router_error")
    return round(correct / len(evaluated), 4)


def _optional_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"phase5i_b_model_answer_quality_{stamp}_{uuid.uuid4().hex[:8]}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase 5I-B model-backed final answer quality baseline.")
    parser.add_argument("--scenario-path", default=str(DEFAULT_SCENARIO_PATH))
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--document-root", default=str(DEFAULT_DOCUMENT_ROOT))
    parser.add_argument("--allow-external-api", action="store_true")
    parser.add_argument("--answer-policy-provider", required=True, choices=["heuristic", "fake", "openai_compatible"])
    parser.add_argument("--answer-policy-model", default="")
    parser.add_argument("--answer-policy-env-file", default=".secrets/answer_policy.env")
    parser.add_argument("--enable-query-planning", action="store_true")
    parser.add_argument("--query-planner-mode", default="rule", choices=["rule", "llm", "hybrid"])
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--fail-on-api-error", action="store_true")
    parser.add_argument("--export-training-candidates", dest="export_training_candidates", action="store_true", default=True)
    parser.add_argument("--no-export-training-candidates", dest="export_training_candidates", action="store_false")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_phase5i_b_model_answer_quality(
        scenario_path=Path(args.scenario_path),
        db_path=Path(args.db_path),
        output_dir=Path(args.output_dir),
        document_root=Path(args.document_root),
        allow_external_api=bool(args.allow_external_api),
        answer_policy_provider=str(args.answer_policy_provider),
        answer_policy_model=str(args.answer_policy_model or ""),
        answer_policy_env_file=Path(args.answer_policy_env_file),
        enable_query_planning=bool(args.enable_query_planning),
        query_planner_mode=str(args.query_planner_mode),
        max_cases=args.max_cases,
        fail_on_api_error=bool(args.fail_on_api_error),
        export_training_candidates=bool(args.export_training_candidates),
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    if report.get("status") == "skipped_api_missing":
        return 2
    if report.get("status") == "failed":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

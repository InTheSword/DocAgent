from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from docagent.router.llm_client import (
    OpenAICompatibleRouterClient,
    RouterLLMError,
    load_router_llm_config,
)
from docagent.router.rule_router import plan_route as plan_rule_route
from docagent.router.schemas import REQUIRED_DECISION_FIELDS, RouterDecision, RouterInput


DEFAULT_LLM_ROUTER_THRESHOLD = 0.75
DETERMINISTIC_RULE_CONFIDENCE = 0.75
LLM_TRIGGER_WARNINGS = {
    "ambiguous_question",
    "fallback_to_local_fact_qa",
    "tool_unavailable",
    "table_tool_unavailable",
    "calculation_tool_unavailable",
    "complex_query_decomposition_deferred",
}
LLM_SKIP_WARNINGS = {"visual_understanding_unsupported"}

SYSTEM_PROMPT = (
    "You are the DocAgent router planner. Return only one JSON object matching "
    "the router schema. Choose only supported task types and available tools. "
    "Do not answer the document question, do not create citations, do not ask "
    "for full document text, and keep requires_visual_understanding false."
)


def plan_route_with_optional_llm(
    payload: Mapping[str, Any],
    *,
    threshold: float = DEFAULT_LLM_ROUTER_THRESHOLD,
    env_file: Path | None = None,
    model_override: str | None = None,
    llm_client: Any | None = None,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    router_input = RouterInput.from_mapping(payload)
    rule_plan = _with_router_source(plan_rule_route(_rule_only_payload(payload)), "rule")
    if rule_plan.get("status") == "error":
        return rule_plan

    should_try = _should_try_llm(rule_plan, threshold)
    if not should_try:
        return rule_plan

    if not router_input.options.allow_external_llm_router:
        return _rule_after_llm_skip(rule_plan, "rule", ["llm_router_disabled"])

    if llm_client is None:
        config, config_warnings = load_router_llm_config(
            env_file=env_file,
            env=env,
            model_override=model_override,
        )
        if config is None:
            return _rule_after_llm_skip(
                rule_plan,
                "rule_after_llm_failure",
                config_warnings or ["llm_router_not_configured"],
                llm_router={
                    "status": "not_configured",
                    "error": {
                        "type": "llm_router_not_configured",
                        "message": "Router LLM config is incomplete; using the rule plan.",
                    },
                },
            )
        llm_client = OpenAICompatibleRouterClient(config)

    user_payload = _llm_user_payload(router_input, rule_plan)
    try:
        raw_output = llm_client.complete(system_prompt=SYSTEM_PROMPT, user_payload=user_payload)
    except RouterLLMError as exc:
        return _rule_after_llm_skip(
            rule_plan,
            "rule_after_llm_failure",
            ["llm_router_api_error"],
            llm_router={"status": "api_error", "error": {"type": "llm_router_api_error", "message": str(exc)}},
        )

    parsed = _parse_llm_json(raw_output)
    if parsed is None:
        return _rule_after_llm_skip(
            rule_plan,
            "rule_after_llm_failure",
            ["llm_router_invalid_output"],
            llm_router={
                "status": "invalid_output",
                "error": {
                    "type": "llm_router_invalid_output",
                    "message": "Router LLM did not return a valid JSON object.",
                },
            },
        )

    missing = REQUIRED_DECISION_FIELDS - parsed.keys()
    if missing:
        return _validation_failed(rule_plan, sorted(missing))

    decision = _decision_from_mapping(parsed)
    validation_errors = decision.validation_errors(router_input.available_tools)
    if validation_errors:
        return _validation_failed(rule_plan, validation_errors)

    llm_plan = decision.to_dict()
    llm_plan["router_source"] = "llm_fallback"
    llm_plan["fallback_used"] = True
    llm_plan["warnings"] = list(dict.fromkeys((llm_plan.get("warnings") or []) + ["llm_router_used"]))
    llm_plan["llm_router"] = {"status": "used"}
    return llm_plan


def _rule_only_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    data = dict(payload)
    options = dict(data.get("options") or {})
    options["allow_external_llm_router"] = False
    data["options"] = options
    return data


def _with_router_source(plan: dict[str, Any], source: str) -> dict[str, Any]:
    result = dict(plan)
    result.setdefault("router_source", source)
    return result


def _rule_after_llm_skip(
    rule_plan: dict[str, Any],
    source: str,
    warnings: list[str],
    *,
    llm_router: dict[str, Any] | None = None,
) -> dict[str, Any]:
    result = dict(rule_plan)
    result["router_source"] = source
    result["warnings"] = list(dict.fromkeys((result.get("warnings") or []) + warnings))
    if llm_router is not None:
        result["llm_router"] = llm_router
    return result


def _should_try_llm(rule_plan: Mapping[str, Any], threshold: float) -> bool:
    warnings = set(str(item) for item in rule_plan.get("warnings") or [])
    if warnings & LLM_SKIP_WARNINGS:
        return False
    task_type = str(rule_plan.get("task_type") or "")
    confidence = _float_or_default(rule_plan.get("confidence"), 0.0)
    if task_type in {"document_statistics", "page_lookup"} and confidence >= DETERMINISTIC_RULE_CONFIDENCE:
        return False
    return confidence < threshold or bool(warnings & LLM_TRIGGER_WARNINGS)


def _llm_user_payload(router_input: RouterInput, rule_plan: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "question": router_input.question,
        "available_tools": sorted(router_input.available_tools),
        "document_profile": _light_document_profile(router_input.document_profile or {}),
        "rule_plan": {
            "task_type": rule_plan.get("task_type"),
            "selected_tools": rule_plan.get("selected_tools") or [],
            "requires_retrieval": bool(rule_plan.get("requires_retrieval")),
            "requires_full_scan": bool(rule_plan.get("requires_full_scan")),
            "requires_table_tool": bool(rule_plan.get("requires_table_tool")),
            "requires_calculation": bool(rule_plan.get("requires_calculation")),
            "requires_visual_understanding": bool(rule_plan.get("requires_visual_understanding")),
            "target_evidence_types": rule_plan.get("target_evidence_types") or [],
            "query_rewrite": rule_plan.get("query_rewrite") or "",
            "confidence": _float_or_default(rule_plan.get("confidence"), 0.0),
            "reason": rule_plan.get("reason") or "",
            "fallback_used": bool(rule_plan.get("fallback_used")),
            "warnings": rule_plan.get("warnings") or [],
        },
    }


def _light_document_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "page_count",
        "block_count",
        "table_count",
        "image_count",
        "has_ocr",
        "has_tables",
        "has_images",
    }
    return {key: profile.get(key) for key in allowed if key in profile}


def _parse_llm_json(raw_output: str) -> dict[str, Any] | None:
    text = raw_output.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _decision_from_mapping(data: Mapping[str, Any]) -> RouterDecision:
    return RouterDecision(
        task_type=str(data.get("task_type") or ""),
        selected_tools=[str(item) for item in data.get("selected_tools") or []],
        requires_retrieval=bool(data.get("requires_retrieval", False)),
        requires_full_scan=bool(data.get("requires_full_scan", False)),
        requires_table_tool=bool(data.get("requires_table_tool", False)),
        requires_calculation=bool(data.get("requires_calculation", False)),
        requires_visual_understanding=bool(data.get("requires_visual_understanding", False)),
        target_evidence_types=[str(item) for item in data.get("target_evidence_types") or []],
        query_rewrite=str(data.get("query_rewrite") or ""),
        confidence=_float_or_default(data.get("confidence"), 0.0),
        reason=str(data.get("reason") or ""),
        fallback_used=bool(data.get("fallback_used", True)),
        warnings=[str(item) for item in data.get("warnings") or []],
    )


def _validation_failed(rule_plan: dict[str, Any], validation_errors: list[str]) -> dict[str, Any]:
    return _rule_after_llm_skip(
        rule_plan,
        "rule_after_llm_failure",
        ["llm_router_validation_failed", *validation_errors],
        llm_router={
            "status": "validation_failed",
            "error": {
                "type": "llm_router_validation_failed",
                "message": "Router LLM output failed schema validation; using the rule plan.",
            },
            "validation_errors": validation_errors,
        },
    )


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

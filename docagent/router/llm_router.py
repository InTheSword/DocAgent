from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from docagent.router.llm_client import (
    OpenAICompatibleRouterClient,
    RouterLLMError,
    load_router_llm_config,
)
from docagent.router.rule_router import plan_route as plan_rule_route
from docagent.router.schemas import SUPPORTED_TASK_TYPES, RouterDecision, RouterInput


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
    "You are the DocAgent router planner. Return only one JSON object with "
    "task_type, optional query_rewrite, and optional selected_tools. Do not "
    "return Markdown, explanations, chain-of-thought, citations, or answers. "
    "Do not request full document text. If you include confidence, it must be "
    "a number from 0 to 1. Never set requires_visual_understanding."
)
DEFAULT_LLM_CONFIDENCE = 0.65
RAW_RESPONSE_PREVIEW_LIMIT = 1000


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
                    "validation_errors": [],
                    "raw_response_preview": "",
                    "parsed_decision_preview": {},
                    "normalization_warnings": [],
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
            llm_router={
                "status": "api_error",
                "error": {"type": "llm_router_api_error", "message": str(exc)},
                "validation_errors": [],
                "raw_response_preview": "",
                "parsed_decision_preview": {},
                "normalization_warnings": [],
            },
        )

    parsed = _parse_llm_json(raw_output)
    if parsed is None:
        return _rule_after_llm_skip(
            rule_plan,
            "rule_after_llm_failure",
            ["llm_router_invalid_json"],
            llm_router={
                "status": "invalid_json",
                "error": {
                    "type": "llm_router_invalid_json",
                    "message": "Router LLM did not return a valid JSON object.",
                },
                "validation_errors": ["invalid_json"],
                "raw_response_preview": _safe_preview(raw_output),
                "parsed_decision_preview": {},
                "normalization_warnings": [],
            },
        )

    decision, validation_errors, normalization_warnings = _canonicalize_llm_decision(
        parsed,
        router_input=router_input,
        rule_plan=rule_plan,
    )
    validation_errors = list(dict.fromkeys(validation_errors + decision.validation_errors(router_input.available_tools)))
    if validation_errors:
        return _validation_failed(
            rule_plan,
            validation_errors,
            raw_response=raw_output,
            parsed_decision=parsed,
            normalization_warnings=normalization_warnings,
        )

    llm_plan = decision.to_dict()
    llm_plan["router_source"] = "llm_fallback"
    llm_plan["fallback_used"] = True
    llm_plan["warnings"] = list(dict.fromkeys((llm_plan.get("warnings") or []) + ["llm_router_used"]))
    llm_plan["llm_router"] = _llm_router_diag(
        status="used",
        raw_response=raw_output,
        parsed_decision=parsed,
        normalization_warnings=normalization_warnings,
    )
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
        extracted = _extract_first_json_object(text)
        if extracted is None:
            return None
        try:
            payload = json.loads(extracted)
        except json.JSONDecodeError:
            return None
    return payload if isinstance(payload, dict) else None


def _extract_first_json_object(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _canonicalize_llm_decision(
    data: Mapping[str, Any],
    *,
    router_input: RouterInput,
    rule_plan: Mapping[str, Any],
) -> tuple[RouterDecision, list[str], list[str]]:
    validation_errors: list[str] = []
    normalization_warnings: list[str] = []
    task_type = str(data.get("task_type") or "").strip()
    if task_type not in SUPPORTED_TASK_TYPES:
        validation_errors.append("unsupported_task_type")
        task_type = str(rule_plan.get("task_type") or "local_fact_qa")

    if bool(data.get("requires_visual_understanding", False)):
        validation_errors.append("visual_understanding_not_allowed")

    selected_tools, selected_warnings, selected_errors = _canonical_selected_tools(
        data.get("selected_tools"),
        task_type=task_type,
        available_tools=router_input.available_tools,
        rule_plan=rule_plan,
    )
    normalization_warnings.extend(selected_warnings)
    validation_errors.extend(selected_errors)

    confidence, confidence_warning = _normalize_confidence(data.get("confidence"), data)
    if confidence_warning:
        normalization_warnings.append(confidence_warning)

    query_rewrite = str(data.get("query_rewrite") or "").strip()
    if not query_rewrite and task_type == "local_fact_qa":
        query_rewrite = str(rule_plan.get("query_rewrite") or router_input.question).strip()

    flags = _canonical_task_flags(task_type, selected_tools, rule_plan)
    warnings = list(dict.fromkeys(normalization_warnings))
    return (
        RouterDecision(
            task_type=task_type,
            selected_tools=selected_tools,
            requires_retrieval=flags["requires_retrieval"],
            requires_full_scan=flags["requires_full_scan"],
            requires_table_tool=flags["requires_table_tool"],
            requires_calculation=flags["requires_calculation"],
            requires_visual_understanding=False,
            target_evidence_types=flags["target_evidence_types"],
            query_rewrite=query_rewrite,
            confidence=confidence,
            reason=_canonical_reason(task_type),
            fallback_used=True,
            warnings=warnings,
        ),
        list(dict.fromkeys(validation_errors)),
        list(dict.fromkeys(normalization_warnings)),
    )


def _canonical_selected_tools(
    raw_selected: Any,
    *,
    task_type: str,
    available_tools: frozenset[str],
    rule_plan: Mapping[str, Any],
) -> tuple[list[str], list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    selected = _string_list(raw_selected)
    if not selected:
        selected = _default_tools_for_task(task_type, available_tools, rule_plan)
        warnings.append("llm_router_selected_tools_inferred")
    else:
        unavailable = [tool for tool in selected if tool not in available_tools]
        if unavailable:
            fallback = _default_tools_for_task(task_type, available_tools, rule_plan)
            if fallback:
                selected = fallback
                warnings.append("llm_router_selected_tools_unavailable")
            else:
                errors.append("selected_tool_unavailable")
    if not selected:
        errors.append("selected_tools_required")
    return list(dict.fromkeys(selected)), warnings, errors


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _default_tools_for_task(
    task_type: str,
    available_tools: frozenset[str],
    rule_plan: Mapping[str, Any],
) -> list[str]:
    rule_tools = [str(tool) for tool in rule_plan.get("selected_tools") or [] if str(tool) in available_tools]
    if str(rule_plan.get("task_type") or "") == task_type and rule_tools:
        return rule_tools
    if task_type == "document_statistics":
        return [tool for tool in ["count_pages"] if tool in available_tools]
    if task_type == "page_lookup":
        for tool in ["get_page_text", "list_pages"]:
            if tool in available_tools:
                return [tool]
        return []
    if task_type == "local_fact_qa":
        return ["local_fact_qa"] if "local_fact_qa" in available_tools else []
    if task_type == "document_summary":
        if "document_summary" in available_tools:
            return ["document_summary"]
        return ["local_fact_qa"] if "local_fact_qa" in available_tools else []
    if task_type == "table_lookup_or_calculation":
        tools = [tool for tool in ["table_lookup", "simple_calculation"] if tool in available_tools]
        return tools or (["local_fact_qa"] if "local_fact_qa" in available_tools else [])
    if task_type == "structured_extraction":
        tools = [
            tool
            for tool in ["extract_all_tables", "extract_all_images", "list_sections", "document_outline"]
            if tool in available_tools
        ]
        return tools[:1] or (["local_fact_qa"] if "local_fact_qa" in available_tools else [])
    return []


def _canonical_task_flags(task_type: str, selected_tools: list[str], rule_plan: Mapping[str, Any]) -> dict[str, Any]:
    selected = set(selected_tools)
    if task_type == str(rule_plan.get("task_type") or ""):
        return {
            "requires_retrieval": bool(rule_plan.get("requires_retrieval")),
            "requires_full_scan": bool(rule_plan.get("requires_full_scan")),
            "requires_table_tool": bool(rule_plan.get("requires_table_tool")),
            "requires_calculation": bool(rule_plan.get("requires_calculation")),
            "target_evidence_types": [str(item) for item in rule_plan.get("target_evidence_types") or []],
        }
    if task_type == "document_statistics":
        return _flags(False, False, False, False, ["metadata"])
    if task_type == "page_lookup":
        return _flags(False, False, False, False, ["page", "text"])
    if task_type == "document_summary":
        return _flags("local_fact_qa" in selected, True, False, False, ["text", "table", "image"])
    if task_type == "table_lookup_or_calculation":
        return _flags("local_fact_qa" in selected, False, True, "simple_calculation" in selected, ["table", "text"])
    if task_type == "structured_extraction":
        return _flags("local_fact_qa" in selected, True, any("table" in tool for tool in selected), False, ["text"])
    return _flags(True, False, False, False, ["text", "table"])


def _flags(
    requires_retrieval: bool,
    requires_full_scan: bool,
    requires_table_tool: bool,
    requires_calculation: bool,
    target_evidence_types: list[str],
) -> dict[str, Any]:
    return {
        "requires_retrieval": requires_retrieval,
        "requires_full_scan": requires_full_scan,
        "requires_table_tool": requires_table_tool,
        "requires_calculation": requires_calculation,
        "target_evidence_types": target_evidence_types,
    }


def _canonical_reason(task_type: str) -> str:
    return f"LLM fallback selected {task_type}; system canonicalized the full router plan."


def _normalize_confidence(value: Any, data: Mapping[str, Any]) -> tuple[float, str]:
    if "confidence" not in data:
        return DEFAULT_LLM_CONFIDENCE, "llm_router_confidence_defaulted"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        value_float = float(value)
        if 0.0 <= value_float <= 1.0:
            return value_float, ""
        return DEFAULT_LLM_CONFIDENCE, "llm_router_confidence_ignored"
    text = str(value).strip().lower()
    if not text:
        return DEFAULT_LLM_CONFIDENCE, "llm_router_confidence_ignored"
    labels = {"high": 0.85, "medium": 0.65, "low": 0.35}
    if text in labels:
        return labels[text], ""
    if text.endswith("%"):
        try:
            percent = float(text[:-1].strip())
        except ValueError:
            return DEFAULT_LLM_CONFIDENCE, "llm_router_confidence_ignored"
        if 0.0 <= percent <= 100.0:
            return percent / 100.0, ""
        return DEFAULT_LLM_CONFIDENCE, "llm_router_confidence_ignored"
    try:
        value_float = float(text)
    except ValueError:
        return DEFAULT_LLM_CONFIDENCE, "llm_router_confidence_ignored"
    if 0.0 <= value_float <= 1.0:
        return value_float, ""
    return DEFAULT_LLM_CONFIDENCE, "llm_router_confidence_ignored"


def _llm_router_diag(
    *,
    status: str,
    raw_response: str,
    parsed_decision: Mapping[str, Any] | None,
    normalization_warnings: list[str],
    error: dict[str, Any] | None = None,
    validation_errors: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "error": error or {},
        "validation_errors": validation_errors or [],
        "raw_response_preview": _safe_preview(raw_response),
        "parsed_decision_preview": _preview_mapping(parsed_decision or {}),
        "normalization_warnings": list(dict.fromkeys(normalization_warnings)),
    }


def _safe_preview(value: Any) -> str:
    text = str(value)
    redactions = [
        (r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+", r"\1***"),
        (r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;]+", r"\1***"),
        (r"(?i)(token\s*[:=]\s*)[^\s,;]+", r"\1***"),
        (r"(?i)(bearer\s+)[a-z0-9._-]+", r"\1***"),
    ]
    for pattern, replacement in redactions:
        text = re.sub(pattern, replacement, text)
    return text[:RAW_RESPONSE_PREVIEW_LIMIT]


def _preview_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key in ("task_type", "query_rewrite", "selected_tools", "confidence", "intent_labels", "requires_visual_understanding"):
        if key in value:
            item = value[key]
            if isinstance(item, str):
                preview[key] = _safe_preview(item)
            elif isinstance(item, list):
                preview[key] = [_safe_preview(entry) for entry in item[:8]]
            else:
                preview[key] = item
    return preview


def _validation_failed(
    rule_plan: dict[str, Any],
    validation_errors: list[str],
    *,
    raw_response: str,
    parsed_decision: Mapping[str, Any],
    normalization_warnings: list[str],
) -> dict[str, Any]:
    return _rule_after_llm_skip(
        rule_plan,
        "rule_after_llm_failure",
        ["llm_router_validation_failed", *validation_errors],
        llm_router=_llm_router_diag(
            status="validation_failed",
            raw_response=raw_response,
            parsed_decision=parsed_decision,
            normalization_warnings=normalization_warnings,
            validation_errors=validation_errors,
            error={
                "type": "llm_router_validation_failed",
                "message": "Router LLM output failed schema validation; using the rule plan.",
            },
        ),
    )


def _float_or_default(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default

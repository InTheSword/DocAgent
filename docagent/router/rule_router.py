from __future__ import annotations

import re
from typing import Any, Mapping

from docagent.router.schemas import RouterDecision, RouterInput


DOCUMENT_STAT_TOOLS = {
    "pages": "count_pages",
    "blocks": "count_blocks",
    "tables": "count_tables",
    "images": "count_images",
}


def plan_route(payload: Mapping[str, Any]) -> dict[str, Any]:
    router_input = RouterInput.from_mapping(payload)
    input_errors = router_input.validation_errors()
    if input_errors:
        return _validation_fallback(router_input, input_errors)

    decision = _route(router_input)
    if isinstance(decision, dict):
        return decision

    validation_errors = decision.validation_errors(router_input.available_tools)
    if validation_errors:
        return _validation_fallback(router_input, validation_errors)
    return decision.to_dict()


def route_question(payload: Mapping[str, Any]) -> dict[str, Any]:
    return plan_route(payload)


def _route(router_input: RouterInput) -> RouterDecision | dict[str, Any]:
    question = router_input.question
    normalized = _normalize_for_match(question)
    warnings = _external_llm_warning(router_input)
    warnings.extend(_document_profile_warnings(router_input, normalized))
    if _is_complex_query(normalized):
        warnings.append("complex_query_decomposition_deferred")

    stat_tools = _document_statistics_tools(normalized)
    if stat_tools:
        return _document_statistics_decision(router_input, stat_tools, warnings)

    if _is_page_lookup(normalized):
        return _page_lookup_decision(router_input, normalized, warnings)

    if _is_structured_extraction(normalized):
        return _structured_extraction_decision(router_input, normalized, warnings)

    if _is_document_summary(normalized):
        return _document_summary_decision(router_input, warnings)

    if _is_visual_pixel_question(normalized):
        return _visual_boundary_decision(router_input, warnings)

    if _is_table_or_calculation(normalized):
        return _table_decision(router_input, normalized, warnings)

    if _is_ambiguous(normalized):
        return _ambiguous_fallback(router_input, warnings)

    return _local_fact_decision(router_input, warnings)


def _document_statistics_decision(
    router_input: RouterInput,
    tool_names: list[str],
    base_warnings: list[str],
) -> RouterDecision | dict[str, Any]:
    selected, missing, warnings = _select_tools(router_input, tool_names, base_warnings)
    if not selected:
        return _fallback_to_local_fact(
            router_input,
            "Matched document statistics pattern, but deterministic count tools are unavailable.",
            warnings + ["tool_unavailable"],
            confidence=0.2,
            task_type="local_fact_qa",
        )
    confidence = 0.95 if not missing else 0.82
    reason = "Matched document statistics pattern and selected deterministic count tools."
    if missing:
        reason = "Matched document statistics pattern; some requested count tools are unavailable."
    return RouterDecision(
        task_type="document_statistics",
        selected_tools=selected,
        requires_retrieval=False,
        requires_full_scan=False,
        requires_table_tool=False,
        requires_calculation=False,
        requires_visual_understanding=False,
        target_evidence_types=["metadata"],
        query_rewrite="",
        confidence=confidence,
        reason=reason,
        warnings=warnings,
    )


def _page_lookup_decision(
    router_input: RouterInput,
    normalized: str,
    base_warnings: list[str],
) -> RouterDecision | dict[str, Any]:
    desired = ["list_pages"] if _matches(normalized, r"\blist\s+(all\s+)?pages\b") else ["get_page_text"]
    selected, _missing, warnings = _select_tools(router_input, desired, base_warnings)
    if not selected:
        return _fallback_to_local_fact(
            router_input,
            "Matched page lookup pattern, but page lookup tools are unavailable.",
            warnings + ["tool_unavailable"],
            confidence=0.2,
            task_type="local_fact_qa",
        )
    page = _extract_page_number(normalized)
    reason = "Matched explicit page lookup pattern."
    if page is not None:
        reason = f"Matched explicit page lookup pattern: page {page}."
    return RouterDecision(
        task_type="page_lookup",
        selected_tools=selected,
        requires_retrieval=False,
        requires_full_scan=False,
        requires_table_tool=False,
        requires_calculation=False,
        requires_visual_understanding=False,
        target_evidence_types=["page", "text"],
        query_rewrite="",
        confidence=0.88,
        reason=reason,
        warnings=warnings,
    )


def _structured_extraction_decision(
    router_input: RouterInput,
    normalized: str,
    base_warnings: list[str],
) -> RouterDecision | dict[str, Any]:
    desired = _structured_tools(normalized)
    selected, missing, warnings = _select_tools(router_input, desired, base_warnings)
    if not selected:
        return _fallback_to_local_fact(
            router_input,
            "Matched structured extraction pattern, but full-scan extraction tools are unavailable.",
            warnings + ["tool_unavailable", "fallback_to_local_fact_qa"],
            confidence=0.52,
            task_type="structured_extraction",
            requires_full_scan=True,
            target_evidence_types=_structured_evidence_types(normalized),
        )
    requires_table_tool = any(tool in {"extract_all_tables", "table_lookup"} for tool in selected)
    return RouterDecision(
        task_type="structured_extraction",
        selected_tools=selected,
        requires_retrieval=False,
        requires_full_scan=True,
        requires_table_tool=requires_table_tool,
        requires_calculation=False,
        requires_visual_understanding=False,
        target_evidence_types=_structured_evidence_types(normalized),
        query_rewrite="",
        confidence=0.84 if not missing else 0.76,
        reason="Matched full-scan structured extraction pattern.",
        warnings=warnings,
    )


def _document_summary_decision(
    router_input: RouterInput,
    base_warnings: list[str],
) -> RouterDecision | dict[str, Any]:
    selected, _missing, warnings = _select_tools(router_input, ["document_summary"], base_warnings)
    if not selected:
        return _fallback_to_local_fact(
            router_input,
            "Matched document summary pattern, but document_summary is unavailable.",
            warnings + ["tool_unavailable", "fallback_to_local_fact_qa"],
            confidence=0.55,
            task_type="document_summary",
            requires_full_scan=True,
            target_evidence_types=["text", "table", "image"],
        )
    return RouterDecision(
        task_type="document_summary",
        selected_tools=selected,
        requires_retrieval=False,
        requires_full_scan=True,
        requires_table_tool=False,
        requires_calculation=False,
        requires_visual_understanding=False,
        target_evidence_types=["text", "table", "image"],
        query_rewrite="",
        confidence=0.82,
        reason="Matched global document summary pattern.",
        warnings=warnings,
    )


def _visual_boundary_decision(
    router_input: RouterInput,
    base_warnings: list[str],
) -> RouterDecision | dict[str, Any]:
    warnings = base_warnings + ["visual_understanding_unsupported", "fallback_to_local_fact_qa"]
    if "local_fact_qa" in router_input.available_tools:
        return RouterDecision(
            task_type="local_fact_qa",
            selected_tools=["local_fact_qa"],
            requires_retrieval=True,
            requires_full_scan=False,
            requires_table_tool=False,
            requires_calculation=False,
            requires_visual_understanding=False,
            target_evidence_types=["text", "image"],
            query_rewrite=_light_query_rewrite(router_input.question),
            confidence=0.42,
            reason="Matched visual question pattern; pixel-level visual understanding is unsupported in Phase 5.",
            fallback_used=True,
            warnings=warnings,
        )
    return _router_error(
        "visual_understanding_unsupported",
        "Pixel-level visual understanding is unsupported in Phase 5 and no OCR/caption fallback tool is available.",
        router_input,
        warnings=warnings,
    )


def _table_decision(
    router_input: RouterInput,
    normalized: str,
    base_warnings: list[str],
) -> RouterDecision | dict[str, Any]:
    needs_calculation = _requires_calculation(normalized)
    desired = ["table_lookup"]
    if needs_calculation:
        desired.append("simple_calculation")
    selected, missing, warnings = _select_tools(router_input, desired, base_warnings)
    if selected and not missing:
        return RouterDecision(
            task_type="table_lookup_or_calculation",
            selected_tools=selected,
            requires_retrieval=False,
            requires_full_scan=False,
            requires_table_tool=True,
            requires_calculation=needs_calculation,
            requires_visual_understanding=False,
            target_evidence_types=["table", "text"],
            query_rewrite=_light_query_rewrite(router_input.question),
            confidence=0.78 if needs_calculation else 0.8,
            reason="Matched table lookup or calculation pattern and required tools are available.",
            warnings=warnings,
        )

    table_warnings = warnings + ["table_tool_unavailable", "fallback_to_local_fact_qa"]
    if needs_calculation and "simple_calculation" not in router_input.available_tools:
        table_warnings.append("calculation_tool_unavailable")
    return _fallback_to_local_fact(
        router_input,
        "Matched table/calculation pattern, but table tools are unavailable; falling back to local_fact_qa.",
        table_warnings,
        confidence=0.62,
        task_type="table_lookup_or_calculation",
        requires_table_tool=True,
        requires_calculation=needs_calculation,
        target_evidence_types=["table", "text"],
    )


def _ambiguous_fallback(router_input: RouterInput, base_warnings: list[str]) -> RouterDecision | dict[str, Any]:
    return _fallback_to_local_fact(
        router_input,
        "Question is ambiguous; falling back to local_fact_qa.",
        base_warnings + ["ambiguous_question", "external_llm_router_disabled"],
        confidence=0.4,
    )


def _local_fact_decision(router_input: RouterInput, base_warnings: list[str]) -> RouterDecision | dict[str, Any]:
    if "local_fact_qa" not in router_input.available_tools:
        return _router_error(
            "tool_unavailable",
            "local_fact_qa is required for specific fact questions but is not available.",
            router_input,
            warnings=base_warnings + ["tool_unavailable"],
        )
    warnings = list(base_warnings)
    if _is_complex_query(_normalize_for_match(router_input.question)):
        warnings.append("complex_query_decomposition_deferred")
    return RouterDecision(
        task_type="local_fact_qa",
        selected_tools=["local_fact_qa"],
        requires_retrieval=True,
        requires_full_scan=False,
        requires_table_tool=False,
        requires_calculation=False,
        requires_visual_understanding=False,
        target_evidence_types=["text", "table"],
        query_rewrite=_light_query_rewrite(router_input.question),
        confidence=0.86 if "complex_query_decomposition_deferred" not in warnings else 0.68,
        reason="Defaulted to local_fact_qa for a specific fact question.",
        warnings=warnings,
    )


def _fallback_to_local_fact(
    router_input: RouterInput,
    reason: str,
    warnings: list[str],
    *,
    confidence: float,
    task_type: str = "local_fact_qa",
    requires_full_scan: bool = False,
    requires_table_tool: bool = False,
    requires_calculation: bool = False,
    target_evidence_types: list[str] | None = None,
) -> RouterDecision | dict[str, Any]:
    if "local_fact_qa" not in router_input.available_tools:
        return _router_error("tool_unavailable", reason, router_input, warnings=warnings)
    return RouterDecision(
        task_type=task_type,
        selected_tools=["local_fact_qa"],
        requires_retrieval=True,
        requires_full_scan=requires_full_scan,
        requires_table_tool=requires_table_tool,
        requires_calculation=requires_calculation,
        requires_visual_understanding=False,
        target_evidence_types=target_evidence_types or ["text", "table"],
        query_rewrite=_light_query_rewrite(router_input.question) if task_type in {"local_fact_qa", "table_lookup_or_calculation"} else "",
        confidence=confidence,
        reason=reason,
        fallback_used=True,
        warnings=warnings,
    )


def _validation_fallback(router_input: RouterInput, validation_errors: list[str]) -> dict[str, Any]:
    warnings = ["router_validation_failed", *validation_errors]
    if "local_fact_qa" in router_input.available_tools:
        return RouterDecision(
            task_type="local_fact_qa",
            selected_tools=["local_fact_qa"],
            requires_retrieval=True,
            requires_full_scan=False,
            requires_table_tool=False,
            requires_calculation=False,
            requires_visual_understanding=False,
            target_evidence_types=["text", "table"],
            query_rewrite="",
            confidence=0.2,
            reason="Router validation failed; falling back to local_fact_qa.",
            fallback_used=True,
            warnings=warnings,
        ).to_dict()
    return _router_error("router_validation_failed", "Router input or output validation failed.", router_input, warnings=warnings)


def _router_error(
    code: str,
    message: str,
    router_input: RouterInput,
    *,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": "error",
        "doc_id": router_input.doc_id,
        "task_type": "",
        "selected_tools": [],
        "requires_retrieval": False,
        "requires_full_scan": False,
        "requires_table_tool": False,
        "requires_calculation": False,
        "requires_visual_understanding": False,
        "target_evidence_types": [],
        "query_rewrite": "",
        "confidence": 0.0,
        "reason": message,
        "fallback_used": False,
        "warnings": list(dict.fromkeys(warnings or [])),
        "error": {"code": code, "message": message},
    }


def _select_tools(router_input: RouterInput, desired: list[str], warnings: list[str]) -> tuple[list[str], list[str], list[str]]:
    selected = [tool for tool in desired if tool in router_input.available_tools]
    missing = [tool for tool in desired if tool not in router_input.available_tools]
    if missing:
        warnings = warnings + ["tool_unavailable"]
    if len(selected) > router_input.options.max_tool_calls:
        selected = selected[: router_input.options.max_tool_calls]
        warnings = warnings + ["max_tool_calls_limited"]
    return selected, missing, list(dict.fromkeys(warnings))


def _document_statistics_tools(normalized: str) -> list[str]:
    tools = []
    if _matches(normalized, r"\b(how many|number of|count|page count)\b.*\bpages?\b|\bpages?\b.*\b(count|number)\b"):
        tools.append(DOCUMENT_STAT_TOOLS["pages"])
    if _matches(normalized, r"\b(how many|number of|count|table count)\b.*\btables?\b|\btables?\b.*\b(count|number)\b"):
        tools.append(DOCUMENT_STAT_TOOLS["tables"])
    if _matches(normalized, r"\b(how many|number of|count|image count|figure count)\b.*\b(images?|figures?|image regions?|figure regions?)\b|\b(images?|figures?)\b.*\b(count|number|detected)\b"):
        tools.append(DOCUMENT_STAT_TOOLS["images"])
    if _matches(normalized, r"\b(how many|number of|count)\b.*\b(ocr\s+)?blocks?\b|\bblocks?\b.*\b(count|number|stored)\b"):
        tools.append(DOCUMENT_STAT_TOOLS["blocks"])
    return list(dict.fromkeys(tools))


def _is_page_lookup(normalized: str) -> bool:
    return _matches(
        normalized,
        r"\b(page|p\.)\s*\d+\b|\b(show|display|text from|what is on|summarize)\b.*\bpage\s*\d+\b|\blist\s+(all\s+)?pages\b",
    )


def _is_structured_extraction(normalized: str) -> bool:
    return _matches(
        normalized,
        r"\b(extract|list|show)\s+all\b.*\b(tables?|figures?|images?|dates?|sections?|headings?)\b|\blist\s+(section\s+)?headings\b|\b(document\s+)?outline\b",
    )


def _is_document_summary(normalized: str) -> bool:
    return _matches(
        normalized,
        r"\b(summarize|summary|overview)\b.*\b(document|pdf|file)?\b|\bwhat is this (pdf|document) about\b|\bkey points\b",
    )


def _is_visual_pixel_question(normalized: str) -> bool:
    return _matches(
        normalized,
        r"\b(chart|graph)\b.*\b(color|trend|shown|look like|mean)\b|\bwhat is shown\b.*\b(picture|image|figure)\b|\b(picture|image|figure)\b.*\b(show|shown|depict|look like)\b",
    )


def _is_table_or_calculation(normalized: str) -> bool:
    if _matches(normalized, r"\b(row|column|highest|lowest|maximum|minimum|difference|sum|average|ratio|percent change|growth)\b"):
        return True
    if _matches(normalized, r"\b(revenue|sales|income|profit|expense|cost|value|amount|rate)\b.*\b(19|20)\d{2}\b|\b(19|20)\d{2}\b.*\b(revenue|sales|income|profit|expense|cost|value|amount|rate)\b"):
        return True
    return False


def _requires_calculation(normalized: str) -> bool:
    return _matches(
        normalized,
        r"\b(difference|sum|average|ratio|percent change|growth|increase|decrease|highest|lowest|maximum|minimum|calculate)\b",
    )


def _is_ambiguous(normalized: str) -> bool:
    return normalized in {"help", "help me", "can you help", "can you help me", "what about this", "tell me about it"}


def _is_complex_query(normalized: str) -> bool:
    intent_count = 0
    if _document_statistics_tools(normalized):
        intent_count += 1
    if _is_page_lookup(normalized):
        intent_count += 1
    if _is_structured_extraction(normalized):
        intent_count += 1
    if _is_document_summary(normalized):
        intent_count += 1
    if _is_table_or_calculation(normalized):
        intent_count += 1
    return intent_count > 1 or bool(re.search(r"\b(and then|then also|also)\b", normalized))


def _structured_tools(normalized: str) -> list[str]:
    if _matches(normalized, r"\btables?\b"):
        return ["extract_all_tables"]
    if _matches(normalized, r"\b(figures?|images?)\b"):
        return ["extract_all_images"]
    if _matches(normalized, r"\b(section\s+)?headings?\b|\bsections?\b"):
        return ["list_sections"]
    if _matches(normalized, r"\boutline\b"):
        return ["document_outline"]
    if _matches(normalized, r"\bdates?\b"):
        return ["extract_all_dates"]
    return ["structured_extract"]


def _structured_evidence_types(normalized: str) -> list[str]:
    if _matches(normalized, r"\btables?\b"):
        return ["table"]
    if _matches(normalized, r"\b(figures?|images?)\b"):
        return ["image"]
    return ["text"]


def _extract_page_number(normalized: str) -> int | None:
    match = re.search(r"\b(?:page|p\.)\s*(\d+)\b", normalized)
    if not match:
        return None
    return int(match.group(1))


def _external_llm_warning(router_input: RouterInput) -> list[str]:
    if router_input.options.allow_external_llm_router:
        return ["external_llm_router_unavailable"]
    return []


def _document_profile_warnings(router_input: RouterInput, normalized: str) -> list[str]:
    profile = router_input.document_profile
    if not profile:
        return []
    warnings = []
    needs_table = _is_table_or_calculation(normalized) or (
        _is_structured_extraction(normalized) and _matches(normalized, r"\btables?\b")
    )
    needs_image = _is_visual_pixel_question(normalized) or (
        _is_structured_extraction(normalized) and _matches(normalized, r"\b(images?|figures?)\b")
    )
    if needs_table and (profile.get("has_tables") is False or profile.get("table_count") == 0):
        warnings.append("document_profile_no_tables")
    if needs_image and (profile.get("has_images") is False or profile.get("image_count") == 0):
        warnings.append("document_profile_no_images")
    return warnings


def _light_query_rewrite(question: str) -> str:
    rewrite = question.strip()
    replacements = [
        r"^\s*(please\s+)?(can|could|would)\s+you\s+(please\s+)?",
        r"^\s*(please\s+)?help\s+me\s+",
        r"^\s*tell\s+me\s+",
        r"\b(in|from)\s+(this\s+)?(document|pdf|file)\b",
        r"\bthis\s+(document|pdf|file)\b",
    ]
    for pattern in replacements:
        rewrite = re.sub(pattern, " ", rewrite, flags=re.IGNORECASE)
    rewrite = re.sub(r"\s+", " ", rewrite).strip(" ?.")
    return rewrite or question.strip()


def _normalize_for_match(question: str) -> str:
    normalized = re.sub(r"\s+", " ", question.strip().lower())
    return normalized.strip(" ?.!。！？")


def _matches(text: str, pattern: str) -> bool:
    return re.search(pattern, text, flags=re.IGNORECASE) is not None

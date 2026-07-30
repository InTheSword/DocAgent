from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from docagent.query.schemas import QueryDecision, QueryMetadataFilter
from docagent.retrieval.metadata_filter import infer_metadata_filter
from docagent.router.llm_client import (
    OpenAICompatibleRouterClient,
    RouterLLMError,
    load_router_llm_config,
    parse_json_object,
)


INTENT_ROUTER_ROLE = "intent_router"
INTENT_ROUTER_PROMPT_VERSION = "m1-intent-router-v1"
INTENT_ROUTER_SYSTEM_PROMPT = """You are the intent_router for a PDF RAG system.
Classify only the user's retrieval intent. Never answer the question, generate search
queries, choose internal tools, request document text, or provide chain-of-thought.
Return one JSON object with exactly:
{"intent": "<allowed intent>", "confidence": <number 0..1>, "reason": "<brief reason>"}
Allowed intents: semantic_fact, navigation, table_lookup, table_analysis,
visual_lookup, complex_analysis, document_summary, no_retrieval,
clarification_required.
Use table_lookup for direct table values and table_analysis for filtering,
comparison, aggregation, ranking, or calculation over table data. Use visual_lookup
when the answer depends on a figure, image, plot, or chart. Use complex_analysis only
when multiple distinct pieces of evidence must be combined."""

_POLICY: dict[str, tuple[bool, tuple[str, ...], tuple[str, ...]]] = {
    "semantic_fact": (True, ("none", "rewrite", "expand", "preserve_terms"), ("dense", "sparse")),
    "navigation": (
        True,
        ("none", "rewrite", "preserve_terms"),
        ("metadata_filter", "dense", "sparse"),
    ),
    "table_lookup": (
        True,
        ("none", "rewrite", "preserve_terms"),
        ("table_text", "table_structured"),
    ),
    "table_analysis": (
        True,
        ("rewrite", "decompose", "preserve_terms"),
        ("table_structured", "table_text", "multi_query"),
    ),
    "visual_lookup": (
        True,
        ("none", "rewrite", "preserve_terms"),
        ("metadata_filter", "visual"),
    ),
    "complex_analysis": (
        True,
        ("none", "rewrite", "expand", "decompose", "preserve_terms"),
        ("multi_query", "dense", "sparse"),
    ),
    "document_summary": (True, ("none",), ("global_scan",)),
    "no_retrieval": (False, (), ("no_retrieval",)),
    "clarification_required": (False, ("request_clarification",), ("clarification",)),
}

_NO_RETRIEVAL_RE = re.compile(
    r"^(?:hi|hello|thanks|thank you|你好|您好|谢谢|感谢)[!！。.，,\s]*$",
    flags=re.IGNORECASE,
)
_SUMMARY_RE = re.compile(
    r"\b(?:summari[sz]e|summary|overview|main points?|entire document|whole (?:paper|document))\b|"
    r"\bwhat is (?:this|the) (?:pdf|paper|document|file)(?: mainly)? about\b|"
    r"(?:总结|概括|概述|全文|整篇|主要内容|核心内容)",
    flags=re.IGNORECASE,
)
_TABLE_RE = re.compile(r"\btable\s*\d*\b|表\s*\d*|表格", flags=re.IGNORECASE)
_TABLE_METRIC_RE = re.compile(
    r"\b(?:revenue|sales|income|profit|expense|cost|value|amount|rate)\b.*\b(?:19|20)\d{2}\b|"
    r"\b(?:19|20)\d{2}\b.*\b(?:revenue|sales|income|profit|expense|cost|value|amount|rate)\b|"
    r"(?:收入|利润|成本|费用|金额|比率|数值).*(?:19|20)\d{2}|"
    r"(?:19|20)\d{2}.*(?:收入|利润|成本|费用|金额|比率|数值)",
    flags=re.IGNORECASE,
)
_ANALYSIS_RE = re.compile(
    r"\b(?:compare|difference|rank|highest|lowest|average|sum|total|trend|correlation)\b|"
    r"(?:比较|差异|排序|最高|最低|平均|合计|总计|趋势|相关性|占比|增长率)",
    flags=re.IGNORECASE,
)
_VISUAL_RE = re.compile(
    r"\b(?:figure|fig\.?|image|picture|plot|chart)\s*\d*\b|(?:图像|图片|图表|曲线图|柱状图|饼图|图)\s*\d*",
    flags=re.IGNORECASE,
)
_COMPLEX_RE = re.compile(
    r"\b(?:why|explain.*relationship|across sections?|synthesize|causes? and effects?|compare .* and )\b|"
    r"(?:为什么|原因和影响|跨章节|综合分析|结合.*分析|对比.*并|关系是什么)",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class IntentRoutingResult:
    decision: QueryDecision
    diagnostics: dict[str, Any]


def route_query_intent(
    *,
    question: str,
    document_profile: Mapping[str, Any] | None = None,
    llm_client: Any | None = None,
    env_file: Path | None = None,
    model_override: str | None = None,
    env: Mapping[str, str] | None = None,
    use_llm: bool = True,
) -> IntentRoutingResult:
    profile = _light_document_profile(document_profile or {})
    model_id = model_override or ""
    config_warnings: list[str] = []
    if llm_client is None and use_llm:
        config, config_warnings = load_router_llm_config(
            env_file=env_file,
            env=env,
            model_override=model_override,
        )
        if config is not None:
            llm_client = OpenAICompatibleRouterClient(config)
            model_id = config.model
    elif llm_client is not None:
        model_id = str(getattr(getattr(llm_client, "config", None), "model", model_id))

    diagnostics = {
        "role": INTENT_ROUTER_ROLE,
        "prompt_version": INTENT_ROUTER_PROMPT_VERSION,
        "model_id": model_id,
        "status": "fallback",
        "validation_errors": [],
        "error": {},
    }
    if llm_client is None:
        decision = _fallback_decision(
            question,
            profile,
            warnings=[*config_warnings, "intent_router_llm_unavailable"],
        )
        return IntentRoutingResult(decision=decision, diagnostics=diagnostics)

    try:
        raw_output = llm_client.complete(
            system_prompt=INTENT_ROUTER_SYSTEM_PROMPT,
            user_payload={"question": question, "document_profile": profile},
        )
    except (RouterLLMError, RuntimeError, ValueError, TypeError) as exc:
        diagnostics["error"] = {"type": type(exc).__name__, "message": str(exc)}
        decision = _fallback_decision(question, profile, warnings=["intent_router_llm_failed"])
        return IntentRoutingResult(decision=decision, diagnostics=diagnostics)

    payload = parse_json_object(raw_output)
    try:
        if payload is None:
            raise ValueError("response_not_json_object")
        decision = _decision_from_llm(question, profile, payload)
    except (TypeError, ValueError) as exc:
        diagnostics["status"] = "validation_failed"
        diagnostics["validation_errors"] = [str(exc)]
        decision = _fallback_decision(question, profile, warnings=["intent_router_validation_failed"])
        return IntentRoutingResult(decision=decision, diagnostics=diagnostics)

    diagnostics["status"] = "used"
    return IntentRoutingResult(decision=decision, diagnostics=diagnostics)


def _decision_from_llm(
    question: str,
    profile: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> QueryDecision:
    unknown = set(payload) - {"intent", "confidence", "reason"}
    if unknown:
        raise ValueError(f"unknown intent router fields: {sorted(unknown)}")
    intent = payload.get("intent")
    confidence = payload.get("confidence")
    if not isinstance(intent, str):
        raise ValueError("intent must be a string")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence must be a number from 0 to 1")
    return _build_decision(
        question=question,
        intent=intent,
        confidence=float(confidence),
        reason=str(payload.get("reason") or ""),
        source="llm",
        profile=profile,
        warnings=[],
    )


def _fallback_decision(
    question: str,
    profile: Mapping[str, Any],
    *,
    warnings: list[str],
) -> QueryDecision:
    intent = _fallback_intent(question)
    return _build_decision(
        question=question,
        intent=intent,
        confidence=0.55 if intent == "semantic_fact" else 0.7,
        reason=f"Bounded fallback selected {intent}.",
        source="fallback",
        profile=profile,
        warnings=warnings,
    )


def _fallback_intent(question: str) -> str:
    text = " ".join(str(question or "").split())
    if not text or text in {"?", "？"}:
        return "clarification_required"
    if _NO_RETRIEVAL_RE.fullmatch(text):
        return "no_retrieval"
    if _SUMMARY_RE.search(text):
        return "document_summary"
    if _TABLE_RE.search(text) or _TABLE_METRIC_RE.search(text):
        return "table_analysis" if _ANALYSIS_RE.search(text) else "table_lookup"
    if _VISUAL_RE.search(text):
        return "visual_lookup"
    if _COMPLEX_RE.search(text):
        return "complex_analysis"
    inferred = infer_metadata_filter(text)
    if inferred.page_ids or inferred.printed_page_numbers or inferred.section_queries:
        return "navigation"
    return "semantic_fact"


def _build_decision(
    *,
    question: str,
    intent: str,
    confidence: float,
    reason: str,
    source: str,
    profile: Mapping[str, Any],
    warnings: list[str],
) -> QueryDecision:
    requires_retrieval, allowed_actions, routes = _POLICY.get(intent, (True, (), ()))
    metadata = QueryMetadataFilter.from_retrieval_filter(infer_metadata_filter(question))
    active_warnings = list(warnings)

    if intent in {"table_lookup", "table_analysis"} and profile.get("has_tables") is False:
        routes = ("dense", "sparse")
        metadata = _without_content_constraints(metadata)
        active_warnings.append("table_intent_document_has_no_tables")
    if intent == "visual_lookup" and profile.get("has_images") is False:
        routes = ("dense", "sparse")
        metadata = _without_content_constraints(metadata)
        active_warnings.append("visual_intent_document_has_no_images")

    return QueryDecision(
        original_question=question,
        intent=intent,
        confidence=confidence,
        requires_retrieval=requires_retrieval,
        allowed_actions=allowed_actions,
        retrieval_routes=routes,
        metadata_filter=metadata,
        reason=reason[:240],
        source=source,
        warnings=tuple(dict.fromkeys(active_warnings)),
    )


def _without_content_constraints(metadata: QueryMetadataFilter) -> QueryMetadataFilter:
    return QueryMetadataFilter(
        physical_pages=metadata.physical_pages,
        printed_pages=metadata.printed_pages,
        section_path=metadata.section_path,
    )


def _light_document_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {
        "page_count",
        "block_count",
        "table_count",
        "image_count",
        "has_ocr",
        "has_tables",
        "has_images",
        "dominant_language",
    }
    return {key: profile.get(key) for key in allowed if key in profile}

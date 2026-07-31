from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from docagent.query.schemas import QueryDecision, QueryPlan
from docagent.router.llm_client import (
    OpenAICompatibleRouterClient,
    RouterLLMError,
    load_router_llm_config,
    parse_json_object,
)


QUERY_TRANSFORMER_ROLE = "query_transformer"
QUERY_TRANSFORMER_PROMPT_VERSION = "m1-query-transformer-v1"
QUERY_TRANSFORMER_SYSTEM_PROMPT = """You are the query_transformer for a PDF RAG system.

## Task
Transform a query only within the supplied allowed_actions. Never answer the question, change its intent, choose tools, add unsupported facts, or provide chain-of-thought.

## Output Format
Return one JSON object with exactly:
{"actions": ["..."], "retrieval_queries": ["..."], "preserved_terms": ["..."]}

## Rules
- Allowed actions: none, rewrite, expand, decompose.
- Use 'none' when the original query is already suitable. 
- 'rewrite' returns one equivalent retrieval query. 
- 'expand' returns a few complementary formulations. 
- 'decompose' returns subqueries with distinct evidence responsibilities. 
- Preserve all entities, numbers, years, comparison directions, quoted text, method names, and explicit locations.
- Return at most 4 retrieval queries. 
- Keep the document/query language unless the document profile explicitly indicates a different dominant language."""

_QUOTED_TERM_RE = re.compile(r'"([^"]+)"|“([^”]+)”|‘([^’]+)’|\'([^\']+)\'')
_NUMBER_RE = re.compile(r"(?<!\w)\d+(?:\.\d+)?%?(?!\w)")
_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9-]{1,}\b")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z]")


@dataclass(frozen=True)
class QueryTransformationResult:
    plan: QueryPlan
    diagnostics: dict[str, Any]


def transform_query(
    *,
    decision: QueryDecision,
    document_profile: Mapping[str, Any] | None = None,
    llm_client: Any | None = None,
    env_file: Path | None = None,
    model_override: str | None = None,
    env: Mapping[str, str] | None = None,
    use_llm: bool = True,
) -> QueryTransformationResult:
    diagnostics = {
        "role": QUERY_TRANSFORMER_ROLE,
        "prompt_version": QUERY_TRANSFORMER_PROMPT_VERSION,
        "model_id": model_override or "",
        "status": "fallback",
        "validation_errors": [],
        "error": {},
    }
    if decision.intent == "no_retrieval":
        diagnostics["status"] = "short_circuited"
        return QueryTransformationResult(plan=_empty_plan(decision, actions=()), diagnostics=diagnostics)
    if decision.intent == "clarification_required":
        diagnostics["status"] = "short_circuited"
        return QueryTransformationResult(
            plan=_empty_plan(decision, actions=("request_clarification",)),
            diagnostics=diagnostics,
        )
    if decision.allowed_actions == ("none",):
        diagnostics["status"] = "not_needed"
        return QueryTransformationResult(plan=_fallback_plan(decision), diagnostics=diagnostics)

    config_warnings: list[str] = []
    if llm_client is None and use_llm:
        config, config_warnings = load_router_llm_config(
            env_file=env_file,
            env=env,
            model_override=model_override,
        )
        if config is not None:
            llm_client = OpenAICompatibleRouterClient(config)
            diagnostics["model_id"] = config.model
    elif llm_client is not None:
        diagnostics["model_id"] = str(
            getattr(getattr(llm_client, "config", None), "model", diagnostics["model_id"])
        )

    if llm_client is None:
        return QueryTransformationResult(
            plan=_fallback_plan(
                decision,
                warnings=[*config_warnings, "query_transformer_llm_unavailable"],
            ),
            diagnostics=diagnostics,
        )

    profile = _light_document_profile(document_profile or {})
    try:
        raw_output = llm_client.complete(
            system_prompt=QUERY_TRANSFORMER_SYSTEM_PROMPT,
            user_payload={
                "original_question": decision.original_question,
                "intent": decision.intent,
                "allowed_actions": list(decision.allowed_actions),
                "retrieval_routes": list(decision.retrieval_routes),
                "metadata_filter": decision.metadata_filter.to_dict(),
                "document_profile": profile,
            },
        )
    except (RouterLLMError, RuntimeError, ValueError, TypeError) as exc:
        diagnostics["error"] = {"type": type(exc).__name__, "message": str(exc)}
        return QueryTransformationResult(
            plan=_fallback_plan(decision, warnings=["query_transformer_llm_failed"]),
            diagnostics=diagnostics,
        )

    payload = parse_json_object(raw_output)
    try:
        if payload is None:
            raise ValueError("response_not_json_object")
        plan = _plan_from_llm(decision, profile, payload)
    except (TypeError, ValueError) as exc:
        diagnostics["status"] = "validation_failed"
        diagnostics["validation_errors"] = [str(exc)]
        return QueryTransformationResult(
            plan=_fallback_plan(decision, warnings=["query_transformer_validation_failed"]),
            diagnostics=diagnostics,
        )

    diagnostics["status"] = "used"
    return QueryTransformationResult(plan=plan, diagnostics=diagnostics)


def _plan_from_llm(
    decision: QueryDecision,
    profile: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> QueryPlan:
    unknown = set(payload) - {"actions", "retrieval_queries", "preserved_terms"}
    if unknown:
        raise ValueError(f"unknown query transformer fields: {sorted(unknown)}")
    actions = _string_tuple(payload.get("actions"), "actions")
    queries = _dedupe_queries(_string_tuple(payload.get("retrieval_queries"), "retrieval_queries"))
    preserved_terms = _string_tuple(payload.get("preserved_terms"), "preserved_terms")
    if not actions:
        raise ValueError("actions cannot be empty")
    if any(action not in decision.allowed_actions for action in actions):
        raise ValueError("query transformer selected an action outside allowed_actions")
    if len(queries) > 4:
        raise ValueError("retrieval_queries cannot contain more than 4 queries")
    if "none" in actions:
        if actions != ("none",) or queries != (decision.original_question,):
            raise ValueError("none must preserve the original question as the only retrieval query")
    elif not queries:
        raise ValueError("transformed actions require retrieval_queries")
    elif not any(action in {"rewrite", "expand", "decompose"} for action in actions):
        raise ValueError("transformed plan requires rewrite, expand, or decompose")

    mandatory_terms = _extract_mandatory_terms(decision.original_question)
    combined_queries = " ".join(queries).casefold()
    missing_terms = [term for term in mandatory_terms if term.casefold() not in combined_queries]
    if missing_terms:
        raise ValueError(f"retrieval queries dropped protected terms: {missing_terms}")
    invalid_preserved = [
        term
        for term in preserved_terms
        if term.casefold() not in decision.original_question.casefold()
    ]
    source_preserved = tuple(term for term in preserved_terms if term not in invalid_preserved)
    _validate_language(decision.original_question, queries, profile)

    return QueryPlan(
        original_question=decision.original_question,
        intent=decision.intent,
        actions=actions,
        retrieval_queries=queries,
        retrieval_routes=decision.retrieval_routes,
        metadata_filter=decision.metadata_filter,
        preserved_terms=tuple(dict.fromkeys((*mandatory_terms, *source_preserved))),
        transformation_source="llm",
        warnings=tuple(
            dict.fromkeys(
                (
                    *decision.warnings,
                    *(["query_transformer_ignored_non_source_preserved_terms"] if invalid_preserved else []),
                )
            )
        ),
    )


def _fallback_plan(decision: QueryDecision, warnings: list[str] | None = None) -> QueryPlan:
    return QueryPlan(
        original_question=decision.original_question,
        intent=decision.intent,
        actions=("none",),
        retrieval_queries=(decision.original_question,),
        retrieval_routes=decision.retrieval_routes,
        metadata_filter=decision.metadata_filter,
        preserved_terms=_extract_mandatory_terms(decision.original_question),
        transformation_source="fallback",
        warnings=tuple(dict.fromkeys((*decision.warnings, *(warnings or [])))),
    )


def _empty_plan(decision: QueryDecision, *, actions: tuple[str, ...]) -> QueryPlan:
    return QueryPlan(
        original_question=decision.original_question,
        intent=decision.intent,
        actions=actions,
        retrieval_queries=(),
        retrieval_routes=decision.retrieval_routes,
        metadata_filter=decision.metadata_filter,
        transformation_source="short_circuit",
        warnings=decision.warnings,
    )


def _extract_mandatory_terms(question: str) -> tuple[str, ...]:
    quoted = [
        next(group for group in match.groups() if group)
        for match in _QUOTED_TERM_RE.finditer(question)
    ]
    return tuple(dict.fromkeys((*quoted, *_NUMBER_RE.findall(question), *_ACRONYM_RE.findall(question))))


def _validate_language(
    question: str,
    queries: tuple[str, ...],
    profile: Mapping[str, Any],
) -> None:
    dominant_language = str(profile.get("dominant_language") or "").casefold()
    combined = " ".join(queries)
    if dominant_language.startswith("zh") and _CJK_RE.search(question) and not _CJK_RE.search(combined):
        raise ValueError("Chinese query was transformed without Chinese retrieval text")
    if dominant_language.startswith("en") and _LATIN_RE.search(question) and not _LATIN_RE.search(combined):
        raise ValueError("English query was transformed without English retrieval text")


def _dedupe_queries(queries: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = " ".join(query.split())
        key = normalized.casefold()
        if normalized and key not in seen:
            result.append(normalized)
            seen.add(key)
    return tuple(result)


def _string_tuple(value: Any, field_name: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{field_name} must contain non-empty strings")
    return tuple(item.strip() for item in value)


def _light_document_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    allowed = {"dominant_language", "has_tables", "has_images"}
    return {key: profile.get(key) for key in allowed if key in profile}

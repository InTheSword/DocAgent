from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from docagent.retrieval.query_fusion import fuse_queries, normalize_query
from docagent.retrieval.query_generator_llm import generate_llm_queries
from docagent.retrieval.query_generator_rule import generate_rule_queries


QUERY_PLANNER_MODES = {"rule", "llm", "hybrid"}
QUERY_ID_RE = re.compile(r"[^a-z0-9]+", flags=re.IGNORECASE)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
ASCII_WORD_RE = re.compile(r"[A-Za-z]{3,}")


@dataclass(frozen=True)
class QueryPlannerOutput:
    question: str
    rule_queries: list[str]
    llm_queries: list[str]
    final_queries: list[str]
    query_sources: dict[str, list[str]] = field(default_factory=dict)
    llm_unique_queries: list[str] = field(default_factory=list)
    llm_duplicate_queries: list[str] = field(default_factory=list)
    llm_added_unique_query_count: int = 0
    llm_retry_count: int = 0
    llm_attempts: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "hybrid"
    warnings: list[str] = field(default_factory=list)
    llm_status: str = "not_started"
    llm_error_type: str | None = None
    llm_raw_response_preview: str = ""
    llm_parsed_queries_preview: list[str] = field(default_factory=list)
    llm_normalization_warnings: list[str] = field(default_factory=list)
    error: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "rule_queries": list(self.rule_queries),
            "llm_queries": list(self.llm_queries),
            "final_queries": list(self.final_queries),
            "query_sources": {
                "rule": list((self.query_sources or {}).get("rule") or []),
                "llm": list((self.query_sources or {}).get("llm") or []),
            },
            "llm_unique_queries": list(self.llm_unique_queries),
            "llm_duplicate_queries": list(self.llm_duplicate_queries),
            "llm_added_unique_query_count": self.llm_added_unique_query_count,
            "llm_retry_count": self.llm_retry_count,
            "llm_attempts": [dict(attempt) for attempt in self.llm_attempts],
            "mode": self.mode,
            "warnings": list(dict.fromkeys(self.warnings)),
            "llm_status": self.llm_status,
            "llm_error_type": self.llm_error_type or "",
            "llm_raw_response_preview": self.llm_raw_response_preview,
            "llm_parsed_queries_preview": list(self.llm_parsed_queries_preview),
            "llm_normalization_warnings": list(dict.fromkeys(self.llm_normalization_warnings)),
            "error": dict(self.error),
        }


def plan_queries(
    *,
    question: str,
    task_type: str = "",
    document_profile: Mapping[str, Any] | None = None,
    mode: str = "hybrid",
    answer_type_hint: str | None = None,
    llm_client: Any | None = None,
    env_file: Path | None = None,
    model_override: str | None = None,
    env: Mapping[str, str] | None = None,
    limit: int = 8,
) -> QueryPlannerOutput:
    normalized_mode = mode if mode in QUERY_PLANNER_MODES else "hybrid"
    warnings: list[str] = []
    if normalized_mode != mode:
        warnings.append("query_planner_mode_defaulted")

    rule_queries = generate_rule_queries(
        question,
        task_type=task_type,
        answer_type_hint=answer_type_hint,
    )
    if not rule_queries:
        rule_queries = [question.strip()]

    llm_queries: list[str] = []
    llm_status = "skipped" if normalized_mode == "rule" else "not_started"
    llm_error_type: str | None = None
    llm_raw_response_preview = ""
    llm_parsed_queries_preview: list[str] = []
    llm_normalization_warnings: list[str] = []
    llm_retry_count = 0
    llm_attempts: list[dict[str, Any]] = []
    error: dict[str, Any] = {}

    if normalized_mode == "rule":
        final_queries = fuse_queries(rule_queries, [], limit=limit)
        query_sources = _query_sources(rule_queries, [], final_queries)
        llm_unique_queries: list[str] = []
        llm_duplicate_queries: list[str] = []
    else:
        final_queries: list[str] = []
        query_sources = {"rule": [], "llm": []}
        llm_unique_queries = []
        llm_duplicate_queries = []

    if normalized_mode in {"llm", "hybrid"}:
        llm_queries, diagnostics = generate_llm_queries(
            question=question,
            llm_client=llm_client,
            env_file=env_file,
            model_override=model_override,
            env=env,
        )
        final_queries = _fuse_for_mode(normalized_mode, rule_queries, llm_queries, limit)
        query_sources = _query_sources(rule_queries, llm_queries, final_queries)
        llm_unique_queries, llm_duplicate_queries = _llm_query_uniqueness(rule_queries, llm_queries, query_sources)
        llm_attempts.append(_llm_attempt_record(1, diagnostics, llm_unique_queries, llm_duplicate_queries))
        selected_diagnostics = diagnostics

        retry_reasons = _retry_reasons(
            question=question,
            llm_queries=llm_queries,
            llm_unique_queries=llm_unique_queries,
            diagnostics=diagnostics,
        )
        if retry_reasons:
            avoid_queries = [*rule_queries, *llm_queries] if "cross_lingual" in retry_reasons else rule_queries
            retry_queries, retry_diagnostics = generate_llm_queries(
                question=question,
                avoid_exact_queries=_avoid_exact_queries(avoid_queries, question),
                llm_client=llm_client,
                env_file=env_file,
                model_override=model_override,
                env=env,
            )
            llm_retry_count = 1
            retry_final_queries = _fuse_for_mode(normalized_mode, rule_queries, retry_queries, limit)
            retry_query_sources = _query_sources(rule_queries, retry_queries, retry_final_queries)
            retry_unique_queries, retry_duplicate_queries = _llm_query_uniqueness(
                rule_queries,
                retry_queries,
                retry_query_sources,
            )
            llm_attempts.append(
                _llm_attempt_record(2, retry_diagnostics, retry_unique_queries, retry_duplicate_queries)
            )
            if str(retry_diagnostics.get("status") or "") == "used" and retry_queries:
                llm_queries = retry_queries
                final_queries = retry_final_queries
                query_sources = retry_query_sources
                llm_unique_queries = retry_unique_queries
                llm_duplicate_queries = retry_duplicate_queries
                selected_diagnostics = retry_diagnostics
            else:
                warnings.extend(str(item) for item in retry_diagnostics.get("warnings") or [])

        llm_status = str(selected_diagnostics.get("status") or "not_started")
        warnings.extend(str(item) for item in selected_diagnostics.get("warnings") or [])
        llm_error_type = selected_diagnostics.get("llm_error_type") or None
        llm_raw_response_preview = str(selected_diagnostics.get("llm_raw_response_preview") or "")
        llm_parsed_queries_preview = [
            str(item) for item in selected_diagnostics.get("llm_parsed_queries_preview") or []
        ]
        llm_normalization_warnings = [
            str(item) for item in selected_diagnostics.get("llm_normalization_warnings") or []
        ]
        error = dict(selected_diagnostics.get("error") or {})
        if _needs_cross_lingual_retry(question, llm_queries):
            warnings.append("query_planner_llm_no_cross_lingual_query")

    if normalized_mode == "llm" and not fuse_queries([], llm_queries, limit=limit):
        warnings.append("query_planner_fallback_rule_queries")
    if llm_status == "used" and llm_queries and not llm_unique_queries:
        warnings.append("query_planner_llm_no_unique_queries")
    if not final_queries:
        final_queries = [question.strip()]
        query_sources = _query_sources(rule_queries, llm_queries, final_queries)

    return QueryPlannerOutput(
        question=question,
        rule_queries=rule_queries,
        llm_queries=llm_queries,
        final_queries=final_queries,
        query_sources=query_sources,
        llm_unique_queries=llm_unique_queries,
        llm_duplicate_queries=llm_duplicate_queries,
        llm_added_unique_query_count=len(llm_unique_queries),
        llm_retry_count=llm_retry_count,
        llm_attempts=llm_attempts,
        mode=normalized_mode,
        warnings=list(dict.fromkeys(warnings)),
        llm_status=llm_status,
        llm_error_type=llm_error_type,
        llm_raw_response_preview=llm_raw_response_preview,
        llm_parsed_queries_preview=llm_parsed_queries_preview,
        llm_normalization_warnings=llm_normalization_warnings,
        error=error,
    )


def _fuse_for_mode(mode: str, rule_queries: list[str], llm_queries: list[str], limit: int) -> list[str]:
    if mode == "llm":
        final_queries = fuse_queries([], llm_queries, limit=limit)
        return final_queries or fuse_queries(rule_queries, [], limit=limit)
    if mode == "hybrid":
        return _fuse_hybrid_queries(rule_queries, llm_queries, limit=limit)
    return fuse_queries(rule_queries, [], limit=limit)


def _retry_reasons(
    *,
    question: str,
    llm_queries: list[str],
    llm_unique_queries: list[str],
    diagnostics: Mapping[str, Any],
) -> list[str]:
    if str(diagnostics.get("status") or "") != "used" or not llm_queries:
        return []
    reasons = []
    if not llm_unique_queries:
        reasons.append("duplicate")
    if _needs_cross_lingual_retry(question, llm_queries):
        reasons.append("cross_lingual")
    return reasons


def _needs_cross_lingual_retry(question: str, llm_queries: list[str]) -> bool:
    if not CJK_RE.search(str(question or "")):
        return False
    return not any(ASCII_WORD_RE.search(str(query or "")) for query in llm_queries)


def _fuse_hybrid_queries(rule_queries: list[str], llm_queries: list[str], *, limit: int) -> list[str]:
    final_queries = fuse_queries(rule_queries, llm_queries, limit=limit)
    if not final_queries or not llm_queries:
        return final_queries
    if _query_sources(rule_queries, llm_queries, final_queries).get("llm"):
        return final_queries

    rule_keys = {_query_identity_key(query) for query in rule_queries}
    final_keys = {_query_identity_key(query) for query in final_queries}
    for llm_query in fuse_queries([], llm_queries, limit=len(llm_queries)):
        llm_key = _query_identity_key(llm_query)
        if not llm_key or llm_key in rule_keys or llm_key in final_keys:
            continue
        if len(final_queries) < limit:
            return [*final_queries, llm_query]
        return [*final_queries[:-1], llm_query]
    return final_queries


def _query_sources(rule_queries: list[str], llm_queries: list[str], final_queries: list[str]) -> dict[str, list[str]]:
    rule_keys = {_query_identity_key(query): query for query in rule_queries}
    llm_keys = {_query_identity_key(query): query for query in llm_queries}
    sources = {"rule": [], "llm": []}
    for query in final_queries:
        key = _query_identity_key(query)
        if key in rule_keys:
            sources["rule"].append(query)
        elif key in llm_keys:
            sources["llm"].append(query)
    return sources


def _llm_query_uniqueness(
    rule_queries: list[str],
    llm_queries: list[str],
    query_sources: dict[str, list[str]],
) -> tuple[list[str], list[str]]:
    rule_keys = {_query_identity_key(query) for query in rule_queries}
    llm_unique = list((query_sources or {}).get("llm") or [])
    duplicate_queries: list[str] = []
    seen_duplicates: set[str] = set()
    for query in llm_queries:
        normalized = normalize_query(query)
        key = _query_identity_key(normalized)
        if not normalized or key not in rule_keys or key in seen_duplicates:
            continue
        duplicate_queries.append(normalized)
        seen_duplicates.add(key)
    return llm_unique, duplicate_queries


def _llm_attempt_record(
    attempt: int,
    diagnostics: Mapping[str, Any],
    unique_queries: list[str],
    duplicate_queries: list[str],
) -> dict[str, Any]:
    return {
        "attempt": attempt,
        "status": str(diagnostics.get("status") or ""),
        "error_type": str(diagnostics.get("llm_error_type") or ""),
        "raw_response_preview": str(diagnostics.get("llm_raw_response_preview") or ""),
        "parsed_queries_preview": [str(item) for item in diagnostics.get("llm_parsed_queries_preview") or []],
        "duplicate_queries": list(duplicate_queries),
        "unique_queries": list(unique_queries),
        "normalization_warnings": [
            str(item) for item in diagnostics.get("llm_normalization_warnings") or []
        ],
    }


def _avoid_exact_queries(rule_queries: list[str], question: str) -> list[str]:
    return [
        normalized
        for normalized in dict.fromkeys(normalize_query(item) for item in [*rule_queries, question])
        if normalized
    ]


def _query_identity_key(query: str) -> str:
    normalized = normalize_query(query).casefold()
    return " ".join(QUERY_ID_RE.sub(" ", normalized).split())

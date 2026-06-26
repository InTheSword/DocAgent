from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from docagent.retrieval.query_fusion import fuse_queries
from docagent.retrieval.query_generator_llm import generate_llm_queries
from docagent.retrieval.query_generator_rule import generate_rule_queries


QUERY_PLANNER_MODES = {"rule", "llm", "hybrid"}


@dataclass(frozen=True)
class QueryPlannerOutput:
    question: str
    rule_queries: list[str]
    llm_queries: list[str]
    final_queries: list[str]
    query_sources: dict[str, list[str]] = field(default_factory=dict)
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
            "mode": self.mode,
            "warnings": list(dict.fromkeys(self.warnings)),
            "llm_status": self.llm_status,
            "llm_error_type": self.llm_error_type,
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
    error: dict[str, Any] = {}
    if normalized_mode in {"llm", "hybrid"}:
        llm_queries, diagnostics = generate_llm_queries(
            question=question,
            llm_client=llm_client,
            env_file=env_file,
            model_override=model_override,
            env=env,
        )
        llm_status = str(diagnostics.get("status") or "not_started")
        warnings.extend(str(item) for item in diagnostics.get("warnings") or [])
        llm_error_type = diagnostics.get("llm_error_type") or None
        llm_raw_response_preview = str(diagnostics.get("llm_raw_response_preview") or "")
        llm_parsed_queries_preview = [
            str(item) for item in diagnostics.get("llm_parsed_queries_preview") or []
        ]
        llm_normalization_warnings = [
            str(item) for item in diagnostics.get("llm_normalization_warnings") or []
        ]
        error = dict(diagnostics.get("error") or {})

    if normalized_mode == "rule":
        final_queries = fuse_queries(rule_queries, [], limit=limit)
    elif normalized_mode == "llm":
        final_queries = fuse_queries([], llm_queries, limit=limit)
        if not final_queries:
            warnings.append("query_planner_fallback_rule_queries")
            final_queries = fuse_queries(rule_queries, [], limit=limit)
    else:
        final_queries = fuse_queries(rule_queries, llm_queries, limit=limit)

    if not final_queries:
        final_queries = [question.strip()]
    query_sources = _query_sources(rule_queries, llm_queries, final_queries)

    return QueryPlannerOutput(
        question=question,
        rule_queries=rule_queries,
        llm_queries=llm_queries,
        final_queries=final_queries,
        query_sources=query_sources,
        mode=normalized_mode,
        warnings=list(dict.fromkeys(warnings)),
        llm_status=llm_status,
        llm_error_type=llm_error_type,
        llm_raw_response_preview=llm_raw_response_preview,
        llm_parsed_queries_preview=llm_parsed_queries_preview,
        llm_normalization_warnings=llm_normalization_warnings,
        error=error,
    )


def _query_sources(rule_queries: list[str], llm_queries: list[str], final_queries: list[str]) -> dict[str, list[str]]:
    rule_keys = {str(query).casefold(): query for query in rule_queries}
    llm_keys = {str(query).casefold(): query for query in llm_queries}
    sources = {"rule": [], "llm": []}
    for query in final_queries:
        key = str(query).casefold()
        if key in rule_keys:
            sources["rule"].append(query)
        elif key in llm_keys:
            sources["llm"].append(query)
    return sources

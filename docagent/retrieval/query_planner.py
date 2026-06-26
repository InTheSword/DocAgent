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
    mode: str = "hybrid"
    warnings: list[str] = field(default_factory=list)
    llm_status: str = "not_started"
    error: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "rule_queries": list(self.rule_queries),
            "llm_queries": list(self.llm_queries),
            "final_queries": list(self.final_queries),
            "mode": self.mode,
            "warnings": list(dict.fromkeys(self.warnings)),
            "llm_status": self.llm_status,
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
        document_profile=document_profile,
        answer_type_hint=answer_type_hint,
    )
    if not rule_queries:
        rule_queries = [question.strip()]

    llm_queries: list[str] = []
    llm_status = "not_started"
    error: dict[str, Any] = {}
    if normalized_mode in {"llm", "hybrid"}:
        llm_queries, diagnostics = generate_llm_queries(
            question=question,
            task_type=task_type,
            document_profile=document_profile,
            rule_queries=rule_queries,
            llm_client=llm_client,
            env_file=env_file,
            model_override=model_override,
            env=env,
        )
        llm_status = str(diagnostics.get("status") or "not_started")
        warnings.extend(str(item) for item in diagnostics.get("warnings") or [])
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

    return QueryPlannerOutput(
        question=question,
        rule_queries=rule_queries,
        llm_queries=llm_queries,
        final_queries=final_queries,
        mode=normalized_mode,
        warnings=list(dict.fromkeys(warnings)),
        llm_status=llm_status,
        error=error,
    )

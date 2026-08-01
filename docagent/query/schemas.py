from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from docagent.retrieval.base import RetrievalFilter


QUERY_INTENTS = frozenset(
    {
        "semantic_fact",
        "navigation",
        "table_lookup",
        "table_analysis",
        "visual_lookup",
        "complex_analysis",
        "document_summary",
        "no_retrieval",
        "clarification_required",
    }
)
QUERY_TASK_TYPES = frozenset(
    {
        "fact_lookup",
        "navigation",
        "analysis",
        "document_summary",
        "no_retrieval",
        "clarification",
    }
)
QUERY_EVIDENCE_TYPES = frozenset({"text", "table", "visual"})
QUERY_RETRIEVER_MODES = frozenset({"none", "bm25", "dense", "hybrid", "hybrid_rerank"})
QUERY_ACTIONS = frozenset(
    {
        "none",
        "rewrite",
        "expand",
        "decompose",
        "preserve_terms",
        "request_clarification",
    }
)
RETRIEVAL_ROUTES = frozenset(
    {
        "dense",
        "sparse",
        "metadata_filter",
        "table_text",
        "table_structured",
        "visual",
        "multi_query",
        "global_scan",
        "no_retrieval",
        "clarification",
    }
)
CONTENT_TYPES = frozenset(
    {
        "body",
        "heading",
        "table",
        "image",
        "figure",
        "chart",
        "page_header",
        "page_footer",
        "page_number",
    }
)
METADATA_FILTER_FIELDS = frozenset(
    {"physical_pages", "printed_pages", "section_path", "content_types"}
)
QUERY_DECISION_FIELDS = frozenset(
    {
        "original_question",
        "task_type",
        "evidence_types",
        "multi_step",
        "intent",
        "confidence",
        "requires_retrieval",
        "allowed_actions",
        "retrieval_routes",
        "retriever_mode",
        "metadata_filter",
        "reason",
        "source",
        "warnings",
    }
)
QUERY_PLAN_FIELDS = frozenset(
    {
        "original_question",
        "intent",
        "actions",
        "retrieval_queries",
        "retrieval_routes",
        "retriever_mode",
        "metadata_filter",
        "preserved_terms",
        "transformation_source",
        "warnings",
    }
)


@dataclass(frozen=True)
class QueryMetadataFilter:
    physical_pages: tuple[int, ...] = ()
    printed_pages: tuple[str, ...] = ()
    section_path: tuple[str, ...] = ()
    content_types: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if any(isinstance(page, bool) or not isinstance(page, int) or page < 1 for page in self.physical_pages):
            raise ValueError("physical_pages must contain positive integers")
        unknown_content_types = set(self.content_types) - CONTENT_TYPES
        if unknown_content_types:
            raise ValueError(f"unknown content_types: {sorted(unknown_content_types)}")
        for field_name in ("printed_pages", "section_path", "content_types"):
            if any(not isinstance(item, str) or not item.strip() for item in getattr(self, field_name)):
                raise ValueError(f"{field_name} must contain non-empty strings")

    @property
    def is_empty(self) -> bool:
        return not any((self.physical_pages, self.printed_pages, self.section_path, self.content_types))

    def to_dict(self) -> dict[str, list[object]]:
        return {
            key: list(values)
            for key, values in (
                ("physical_pages", self.physical_pages),
                ("printed_pages", self.printed_pages),
                ("section_path", self.section_path),
                ("content_types", self.content_types),
            )
            if values
        }

    def to_retrieval_filter(self) -> RetrievalFilter:
        block_types = tuple(
            item
            for item in self.content_types
            if item in {"table", "image"}
        )
        return RetrievalFilter(
            page_ids=self.physical_pages,
            block_types=block_types,
            content_types=self.content_types,
            printed_page_numbers=self.printed_pages,
            section_queries=self.section_path,
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> QueryMetadataFilter:
        payload = dict(value or {})
        unknown_fields = set(payload) - METADATA_FILTER_FIELDS
        if unknown_fields:
            raise ValueError(f"unknown metadata filter fields: {sorted(unknown_fields)}")
        return cls(
            physical_pages=_integer_tuple(payload.get("physical_pages")),
            printed_pages=_string_tuple(payload.get("printed_pages")),
            section_path=_string_tuple(payload.get("section_path")),
            content_types=_string_tuple(payload.get("content_types")),
        )

    @classmethod
    def from_retrieval_filter(cls, value: RetrievalFilter) -> QueryMetadataFilter:
        return cls(
            physical_pages=tuple(value.page_ids),
            printed_pages=tuple(value.printed_page_numbers),
            section_path=tuple(value.section_queries),
            content_types=tuple(value.content_types),
        )


@dataclass(frozen=True)
class QueryDecision:
    original_question: str
    intent: str
    confidence: float
    requires_retrieval: bool
    allowed_actions: tuple[str, ...]
    retrieval_routes: tuple[str, ...]
    task_type: str = "fact_lookup"
    evidence_types: tuple[str, ...] = ("text",)
    multi_step: bool = False
    retriever_mode: str = "hybrid"
    metadata_filter: QueryMetadataFilter = field(default_factory=QueryMetadataFilter)
    reason: str = ""
    source: str = "fallback"
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_question(self.original_question)
        _validate_enum(self.intent, QUERY_INTENTS, "intent")
        _validate_enum(self.task_type, QUERY_TASK_TYPES, "task type")
        _validate_enum_values(self.evidence_types, QUERY_EVIDENCE_TYPES, "evidence types")
        _validate_enum(self.retriever_mode, QUERY_RETRIEVER_MODES, "retriever mode")
        if not isinstance(self.multi_step, bool):
            raise ValueError("multi_step must be boolean")
        if isinstance(self.confidence, bool) or not isinstance(self.confidence, (int, float)):
            raise ValueError("confidence must be a number from 0 to 1")
        if not 0.0 <= float(self.confidence) <= 1.0:
            raise ValueError("confidence must be a number from 0 to 1")
        _validate_enum_values(self.allowed_actions, QUERY_ACTIONS, "actions")
        _validate_enum_values(self.retrieval_routes, RETRIEVAL_ROUTES, "retrieval routes")
        if not isinstance(self.requires_retrieval, bool):
            raise ValueError("requires_retrieval must be boolean")
        if self.intent in {"no_retrieval", "clarification_required"} and self.requires_retrieval:
            raise ValueError(f"{self.intent} cannot require retrieval")

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_question": self.original_question,
            "task_type": self.task_type,
            "evidence_types": list(self.evidence_types),
            "multi_step": self.multi_step,
            "intent": self.intent,
            "confidence": float(self.confidence),
            "requires_retrieval": self.requires_retrieval,
            "allowed_actions": list(self.allowed_actions),
            "retrieval_routes": list(self.retrieval_routes),
            "retriever_mode": self.retriever_mode,
            "metadata_filter": self.metadata_filter.to_dict(),
            "reason": self.reason,
            "source": self.source,
            "warnings": list(dict.fromkeys(self.warnings)),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> QueryDecision:
        payload = dict(value)
        _reject_unknown_fields(payload, QUERY_DECISION_FIELDS, "QueryDecision")
        return cls(
            original_question=str(payload.get("original_question") or ""),
            task_type=str(payload.get("task_type") or "fact_lookup"),
            evidence_types=_string_tuple(payload.get("evidence_types") or ["text"]),
            multi_step=payload.get("multi_step", False),
            intent=str(payload.get("intent") or ""),
            confidence=_strict_float(payload.get("confidence")),
            requires_retrieval=payload.get("requires_retrieval"),
            allowed_actions=_string_tuple(payload.get("allowed_actions")),
            retrieval_routes=_string_tuple(payload.get("retrieval_routes")),
            retriever_mode=str(payload.get("retriever_mode") or "hybrid"),
            metadata_filter=QueryMetadataFilter.from_mapping(payload.get("metadata_filter")),
            reason=str(payload.get("reason") or ""),
            source=str(payload.get("source") or "fallback"),
            warnings=_string_tuple(payload.get("warnings")),
        )


@dataclass(frozen=True)
class QueryPlan:
    original_question: str
    intent: str
    actions: tuple[str, ...]
    retrieval_queries: tuple[str, ...]
    retrieval_routes: tuple[str, ...]
    retriever_mode: str = "hybrid"
    metadata_filter: QueryMetadataFilter = field(default_factory=QueryMetadataFilter)
    preserved_terms: tuple[str, ...] = ()
    transformation_source: str = "fallback"
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _validate_question(self.original_question)
        _validate_enum(self.intent, QUERY_INTENTS, "intent")
        _validate_enum_values(self.actions, QUERY_ACTIONS, "actions")
        _validate_enum_values(self.retrieval_routes, RETRIEVAL_ROUTES, "retrieval routes")
        _validate_enum(self.retriever_mode, QUERY_RETRIEVER_MODES, "retriever mode")
        if len(self.retrieval_queries) > 4:
            raise ValueError("retrieval_queries cannot contain more than 4 queries")
        if any(not isinstance(query, str) or not query.strip() for query in self.retrieval_queries):
            raise ValueError("retrieval_queries must contain non-empty strings")
        if "none" in self.actions and self.actions != ("none",):
            raise ValueError("none cannot be combined with another query action")
        if self.intent in {"no_retrieval", "clarification_required"} and self.retrieval_queries:
            raise ValueError(f"{self.intent} cannot contain retrieval queries")
        if self.actions == ("none",) and self.retrieval_queries != (self.original_question,):
            raise ValueError("none must preserve the original question as the only retrieval query")

    @property
    def final_queries(self) -> list[str]:
        """Compatibility view for the existing multi-query retriever."""

        return list(self.retrieval_queries)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_question": self.original_question,
            "intent": self.intent,
            "actions": list(self.actions),
            "retrieval_queries": list(self.retrieval_queries),
            "retrieval_routes": list(self.retrieval_routes),
            "retriever_mode": self.retriever_mode,
            "metadata_filter": self.metadata_filter.to_dict(),
            "preserved_terms": list(self.preserved_terms),
            "transformation_source": self.transformation_source,
            "warnings": list(dict.fromkeys(self.warnings)),
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> QueryPlan:
        payload = dict(value)
        _reject_unknown_fields(payload, QUERY_PLAN_FIELDS, "QueryPlan")
        return cls(
            original_question=str(payload.get("original_question") or ""),
            intent=str(payload.get("intent") or ""),
            actions=_string_tuple(payload.get("actions")),
            retrieval_queries=_string_tuple(payload.get("retrieval_queries")),
            retrieval_routes=_string_tuple(payload.get("retrieval_routes")),
            retriever_mode=str(payload.get("retriever_mode") or "hybrid"),
            metadata_filter=QueryMetadataFilter.from_mapping(payload.get("metadata_filter")),
            preserved_terms=_string_tuple(payload.get("preserved_terms")),
            transformation_source=str(payload.get("transformation_source") or "fallback"),
            warnings=_string_tuple(payload.get("warnings")),
        )


def _validate_question(value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("original_question must be a non-empty string")


def _validate_enum(value: str, allowed: frozenset[str], label: str) -> None:
    if value not in allowed:
        raise ValueError(f"unknown {label}: {value}")


def _validate_enum_values(values: tuple[str, ...], allowed: frozenset[str], label: str) -> None:
    unknown = set(values) - allowed
    if unknown:
        raise ValueError(f"unknown {label}: {sorted(unknown)}")


def _reject_unknown_fields(payload: Mapping[str, Any], allowed: frozenset[str], label: str) -> None:
    unknown = set(payload) - allowed
    if unknown:
        raise ValueError(f"unknown {label} fields: {sorted(unknown)}")


def _strict_float(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("confidence must be a number from 0 to 1")
    return float(value)


def _string_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected a list of strings")
    return tuple(str(item).strip() for item in value)


def _integer_tuple(value: Any) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected a list of integers")
    if any(isinstance(item, bool) or not isinstance(item, int) for item in value):
        raise ValueError("expected a list of integers")
    return tuple(value)

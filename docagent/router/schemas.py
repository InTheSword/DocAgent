from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


SUPPORTED_TASK_TYPES = {
    "local_fact_qa",
    "table_lookup_or_calculation",
    "document_statistics",
    "page_lookup",
    "structured_extraction",
    "document_summary",
}

REQUIRED_DECISION_FIELDS = {
    "task_type",
    "selected_tools",
    "requires_retrieval",
    "requires_full_scan",
    "requires_table_tool",
    "requires_calculation",
    "requires_visual_understanding",
    "target_evidence_types",
    "query_rewrite",
    "confidence",
    "reason",
    "fallback_used",
    "warnings",
}


@dataclass(frozen=True)
class RouterOptions:
    allow_external_llm_router: bool = False
    prefer_deterministic_tools: bool = True
    max_tool_calls: int = 4

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "RouterOptions":
        if not data:
            return cls()
        max_tool_calls = data.get("max_tool_calls", 4)
        try:
            max_tool_calls_int = int(max_tool_calls)
        except (TypeError, ValueError):
            max_tool_calls_int = 4
        return cls(
            allow_external_llm_router=bool(data.get("allow_external_llm_router", False)),
            prefer_deterministic_tools=bool(data.get("prefer_deterministic_tools", True)),
            max_tool_calls=max(1, max_tool_calls_int),
        )


@dataclass(frozen=True)
class RouterInput:
    doc_id: str
    question: str
    available_tools: frozenset[str]
    document_profile: dict[str, Any] | None = None
    options: RouterOptions = field(default_factory=RouterOptions)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "RouterInput":
        doc_id = str(data.get("doc_id") or "").strip()
        question = str(data.get("question") or "").strip()
        available = data.get("available_tools") or []
        if isinstance(available, str):
            available_tools = frozenset({available})
        else:
            available_tools = frozenset(str(tool) for tool in available)
        profile = data.get("document_profile")
        if profile is not None and not isinstance(profile, dict):
            profile = None
        return cls(
            doc_id=doc_id,
            question=question,
            available_tools=available_tools,
            document_profile=profile,
            options=RouterOptions.from_mapping(data.get("options")),
        )

    def validation_errors(self) -> list[str]:
        errors = []
        if not self.doc_id:
            errors.append("doc_id_required")
        if not self.question:
            errors.append("question_required")
        if not self.available_tools:
            errors.append("available_tools_required")
        return errors


@dataclass(frozen=True)
class RouterDecision:
    task_type: str
    selected_tools: list[str]
    requires_retrieval: bool
    requires_full_scan: bool
    requires_table_tool: bool
    requires_calculation: bool
    requires_visual_understanding: bool
    target_evidence_types: list[str]
    query_rewrite: str
    confidence: float
    reason: str
    fallback_used: bool = False
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type,
            "selected_tools": list(self.selected_tools),
            "requires_retrieval": self.requires_retrieval,
            "requires_full_scan": self.requires_full_scan,
            "requires_table_tool": self.requires_table_tool,
            "requires_calculation": self.requires_calculation,
            "requires_visual_understanding": self.requires_visual_understanding,
            "target_evidence_types": list(self.target_evidence_types),
            "query_rewrite": self.query_rewrite,
            "confidence": float(self.confidence),
            "reason": self.reason,
            "fallback_used": self.fallback_used,
            "warnings": list(dict.fromkeys(self.warnings)),
        }

    def validation_errors(self, available_tools: set[str] | frozenset[str]) -> list[str]:
        result = self.to_dict()
        errors = []
        missing = REQUIRED_DECISION_FIELDS - result.keys()
        if missing:
            errors.append("missing_output_fields")
        if self.task_type not in SUPPORTED_TASK_TYPES:
            errors.append("unsupported_task_type")
        if not self.selected_tools:
            errors.append("selected_tools_required")
        unavailable = [tool for tool in self.selected_tools if tool not in available_tools]
        if unavailable:
            errors.append("selected_tool_unavailable")
        if self.requires_visual_understanding:
            errors.append("visual_understanding_not_allowed")
        if not 0.0 <= float(self.confidence) <= 1.0:
            errors.append("confidence_out_of_range")
        if not self.reason:
            errors.append("reason_required")
        return errors

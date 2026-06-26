"""Rule-first routing for Phase 5 planning."""

from docagent.router.rule_router import plan_route, route_question
from docagent.router.llm_router import plan_route_with_optional_llm
from docagent.router.schemas import (
    RouterDecision,
    RouterInput,
    RouterOptions,
    SUPPORTED_TASK_TYPES,
)

__all__ = [
    "RouterDecision",
    "RouterInput",
    "RouterOptions",
    "SUPPORTED_TASK_TYPES",
    "plan_route",
    "plan_route_with_optional_llm",
    "route_question",
]

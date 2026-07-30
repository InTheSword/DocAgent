from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from docagent.query.intent_router import IntentRoutingResult, route_query_intent
from docagent.query.query_transformer import QueryTransformationResult, transform_query
from docagent.query.schemas import QueryDecision, QueryPlan


@dataclass(frozen=True)
class QueryPipelineOutput:
    decision: QueryDecision
    plan: QueryPlan
    trace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_decision": self.decision.to_dict(),
            "query_plan": self.plan.to_dict(),
            "trace": dict(self.trace),
        }


def run_query_pipeline(
    *,
    question: str,
    document_profile: Mapping[str, Any] | None = None,
    llm_client: Any | None = None,
    env_file: Path | None = None,
    model_override: str | None = None,
    env: Mapping[str, str] | None = None,
    use_llm: bool = True,
) -> QueryPipelineOutput:
    routing: IntentRoutingResult = route_query_intent(
        question=question,
        document_profile=document_profile,
        llm_client=llm_client,
        env_file=env_file,
        model_override=model_override,
        env=env,
        use_llm=use_llm,
    )
    transformation: QueryTransformationResult = transform_query(
        decision=routing.decision,
        document_profile=document_profile,
        llm_client=llm_client,
        env_file=env_file,
        model_override=model_override,
        env=env,
        use_llm=use_llm,
    )
    if transformation.plan.original_question != question:
        raise ValueError("query pipeline changed the original question")
    return QueryPipelineOutput(
        decision=routing.decision,
        plan=transformation.plan,
        trace={
            "intent_router": routing.diagnostics,
            "query_transformer": transformation.diagnostics,
            "static_decomposition": "decompose" in transformation.plan.actions,
        },
    )

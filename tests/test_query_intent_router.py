from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from docagent.query.intent_router import route_query_intent
from docagent.query.schemas import QueryDecision, QueryMetadataFilter, QueryPlan


def test_query_contracts_preserve_original_question_and_map_metadata_filter() -> None:
    question = "第 3 页的 Table 2 报告了什么？"
    metadata = QueryMetadataFilter(
        physical_pages=(3,),
        section_path=("2.1",),
        content_types=("table",),
    )
    decision = QueryDecision(
        original_question=question,
        intent="table_lookup",
        confidence=0.92,
        requires_retrieval=True,
        allowed_actions=("none", "rewrite", "preserve_terms"),
        retrieval_routes=("metadata_filter", "table_text", "table_structured"),
        metadata_filter=metadata,
        source="llm",
    )
    plan = QueryPlan(
        original_question=decision.original_question,
        intent=decision.intent,
        actions=("rewrite", "preserve_terms"),
        retrieval_queries=("第 3 页 Table 2 报告结果",),
        retrieval_routes=decision.retrieval_routes,
        metadata_filter=decision.metadata_filter,
        preserved_terms=("3", "Table 2"),
        transformation_source="llm",
    )

    assert decision.to_dict()["original_question"] == question
    assert plan.to_dict()["original_question"] == question
    assert plan.final_queries == ["第 3 页 Table 2 报告结果"]
    retrieval_filter = plan.metadata_filter.to_retrieval_filter()
    assert retrieval_filter.page_ids == (3,)
    assert retrieval_filter.block_types == ("table",)
    assert retrieval_filter.section_queries == ("2.1",)


@pytest.mark.parametrize(
    ("constructor", "message"),
    [
        (
            lambda: QueryDecision(
                original_question="question",
                intent="custom_intent",
                confidence=0.5,
                requires_retrieval=True,
                allowed_actions=("none",),
                retrieval_routes=("dense",),
            ),
            "unknown intent",
        ),
        (
            lambda: QueryPlan(
                original_question="question",
                intent="semantic_fact",
                actions=("invent",),
                retrieval_queries=("question",),
                retrieval_routes=("dense",),
            ),
            "unknown actions",
        ),
        (
            lambda: QueryPlan(
                original_question="question",
                intent="semantic_fact",
                actions=("none",),
                retrieval_queries=("question",),
                retrieval_routes=("custom_route",),
            ),
            "unknown retrieval routes",
        ),
        (
            lambda: QueryMetadataFilter.from_mapping({"page": [1]}),
            "unknown metadata filter fields",
        ),
    ],
)
def test_query_contracts_reject_unknown_values(constructor, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        constructor()


def test_query_plan_limits_queries_and_none_action_is_exact() -> None:
    with pytest.raises(ValueError, match="more than 4"):
        QueryPlan(
            original_question="question",
            intent="complex_analysis",
            actions=("decompose",),
            retrieval_queries=("q1", "q2", "q3", "q4", "q5"),
            retrieval_routes=("multi_query", "dense", "sparse"),
        )

    with pytest.raises(ValueError, match="preserve the original question"):
        QueryPlan(
            original_question="question",
            intent="semantic_fact",
            actions=("none",),
            retrieval_queries=("rewritten question",),
            retrieval_routes=("dense", "sparse"),
        )


class FakeLLMClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.config = SimpleNamespace(model="qwen3.7-max-2026-05-17")
        self.calls: list[dict[str, object]] = []

    def complete(self, *, system_prompt: str, user_payload: dict[str, object]) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_payload": user_payload})
        return json.dumps(self.payload, ensure_ascii=False)


@pytest.mark.parametrize(
    "intent",
    [
        "semantic_fact",
        "navigation",
        "table_lookup",
        "table_analysis",
        "visual_lookup",
        "complex_analysis",
        "document_summary",
        "no_retrieval",
        "clarification_required",
    ],
)
def test_llm_intent_router_supports_all_frozen_intents(intent: str) -> None:
    fake = FakeLLMClient({"intent": intent, "confidence": 0.81, "reason": "brief"})

    result = route_query_intent(
        question="What information is needed?",
        document_profile={"has_tables": True, "has_images": True},
        llm_client=fake,
    )

    assert result.decision.intent == intent
    assert result.decision.source == "llm"
    assert result.diagnostics == {
        "role": "intent_router",
        "prompt_version": "m1-intent-router-v1",
        "model_id": "qwen3.7-max-2026-05-17",
        "status": "used",
        "validation_errors": [],
        "error": {},
    }
    assert "retrieval_queries" not in fake.calls[0]["user_payload"]
    assert "document text" not in fake.calls[0]["user_payload"]


def test_intent_router_falls_back_on_invalid_output() -> None:
    fake = FakeLLMClient({"intent": "made_up", "confidence": 1.5, "reason": "invalid"})

    result = route_query_intent(
        question="What method does the paper propose?",
        document_profile={},
        llm_client=fake,
    )

    assert result.decision.intent == "semantic_fact"
    assert result.decision.source == "fallback"
    assert result.diagnostics["status"] == "validation_failed"
    assert "intent_router_validation_failed" in result.decision.warnings


def test_table_and_visual_profile_mismatch_remove_impossible_constraints() -> None:
    table_result = route_query_intent(
        question="What is shown in Table 2?",
        document_profile={"has_tables": False, "has_images": True},
        llm_client=FakeLLMClient({"intent": "table_lookup", "confidence": 0.9, "reason": "table"}),
    )
    visual_result = route_query_intent(
        question="What is shown in Figure 2?",
        document_profile={"has_tables": True, "has_images": False},
        llm_client=FakeLLMClient({"intent": "visual_lookup", "confidence": 0.9, "reason": "visual"}),
    )

    assert table_result.decision.retrieval_routes == ("dense", "sparse")
    assert table_result.decision.metadata_filter.content_types == ()
    assert "table_intent_document_has_no_tables" in table_result.decision.warnings
    assert visual_result.decision.retrieval_routes == ("dense", "sparse")
    assert visual_result.decision.metadata_filter.content_types == ()
    assert "visual_intent_document_has_no_images" in visual_result.decision.warnings


def test_fallback_does_not_treat_generic_comparison_as_table_analysis() -> None:
    result = route_query_intent(
        question="Compare the proposed method and the baseline and explain their differences.",
        document_profile={"has_tables": True},
        use_llm=False,
    )

    assert result.decision.intent == "complex_analysis"

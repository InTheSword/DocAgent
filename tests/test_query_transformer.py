from __future__ import annotations

import json
from types import SimpleNamespace

from docagent.query.query_transformer import transform_query
from docagent.query.schemas import QueryDecision


class FakeLLMClient:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload
        self.config = SimpleNamespace(model="qwen3.7-max-2026-05-17")
        self.calls: list[dict[str, object]] = []

    def complete(self, *, system_prompt: str, user_payload: dict[str, object]) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_payload": user_payload})
        return json.dumps(self.payload, ensure_ascii=False)


class SequencedLLMClient(FakeLLMClient):
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        super().__init__({})
        self.payloads = list(payloads)

    def complete(self, *, system_prompt: str, user_payload: dict[str, object]) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_payload": user_payload})
        return json.dumps(self.payloads.pop(0), ensure_ascii=False)


def _decision(question: str, *, intent: str = "semantic_fact") -> QueryDecision:
    return QueryDecision(
        original_question=question,
        intent=intent,
        confidence=0.9,
        requires_retrieval=True,
        allowed_actions=("none", "rewrite", "expand", "decompose"),
        retrieval_routes=("multi_query", "dense", "sparse"),
        task_type="analysis" if intent == "complex_analysis" else "fact_lookup",
        multi_step=intent == "complex_analysis",
        retriever_mode="hybrid_rerank" if intent == "complex_analysis" else "hybrid",
        source="llm",
    )


def test_transformer_can_keep_simple_question_unchanged() -> None:
    question = "What method is proposed?"
    fake = FakeLLMClient(
        {"strategy": "none", "retrieval_queries": [question]}
    )

    result = transform_query(decision=_decision(question), llm_client=fake)

    assert result.plan.original_question == question
    assert result.plan.retrieval_queries == (question,)
    assert result.plan.actions == ("none",)
    assert result.plan.transformation_source == "llm"
    assert result.diagnostics["role"] == "query_transformer"


def test_transformer_preserves_numbers_acronyms_and_query_language() -> None:
    question = "比较 2021 年 GDP 与 2022 年 GDP 的变化。"
    fake = FakeLLMClient(
        {
            "strategy": "decompose",
            "retrieval_queries": [
                "2021 年 GDP 数值",
                "2022 年 GDP 数值及变化",
            ],
        }
    )

    result = transform_query(
        decision=_decision(question, intent="complex_analysis"),
        document_profile={"dominant_language": "zh"},
        llm_client=fake,
    )

    assert result.plan.actions == ("decompose",)
    assert result.plan.retrieval_queries == ("2021 年 GDP 数值", "2022 年 GDP 数值及变化")
    assert set(result.plan.preserved_terms) == {"2021", "2022", "GDP"}


def test_transformer_rejects_dropped_protected_terms_and_falls_back() -> None:
    question = "Compare GDP in 2021 and 2022."
    fake = FakeLLMClient(
        {
            "strategy": "rewrite",
            "retrieval_queries": ["Compare gross domestic product across the two years"],
        }
    )

    result = transform_query(
        decision=_decision(question, intent="complex_analysis"),
        document_profile={"dominant_language": "en"},
        llm_client=fake,
    )

    assert result.plan.retrieval_queries == (question,)
    assert result.plan.transformation_source == "fallback"
    assert "query_transformer_validation_failed" in result.plan.warnings
    assert result.diagnostics["status"] == "validation_failed"


def test_transformer_rejects_model_generated_preserved_terms_as_extra_output() -> None:
    question = "Compare Sections 3 and 4."
    fake = FakeLLMClient(
        {
            "strategy": "decompose",
            "retrieval_queries": ["Section 3 findings", "Section 4 findings"],
            "preserved_terms": ["3", "4", "section comparison"],
        }
    )

    result = transform_query(
        decision=_decision(question, intent="complex_analysis"),
        document_profile={"dominant_language": "en"},
        llm_client=fake,
    )

    assert result.plan.transformation_source == "fallback"
    assert result.plan.retrieval_queries == (question,)
    assert result.diagnostics["attempt_count"] == 2
    assert "query_transformer_validation_failed" in result.plan.warnings


def test_transformer_retries_once_when_strategy_is_outside_runtime_allowlist() -> None:
    question = "What method is proposed?"
    decision = QueryDecision(
        original_question=question,
        intent="semantic_fact",
        confidence=0.0,
        requires_retrieval=True,
        allowed_actions=("none", "rewrite", "preserve_terms"),
        retrieval_routes=("dense", "sparse"),
        source="llm",
    )
    fake = SequencedLLMClient(
        [
            {"strategy": "decompose", "retrieval_queries": ["method", "proposal"]},
            {"strategy": "rewrite", "retrieval_queries": ["proposed method"]},
        ]
    )

    result = transform_query(decision=decision, llm_client=fake)

    assert result.plan.actions == ("rewrite",)
    assert result.plan.retrieval_queries == ("proposed method",)
    assert result.diagnostics["status"] == "used_after_retry"
    assert result.diagnostics["attempt_count"] == 2
    assert fake.calls[0]["user_payload"]["allowed_strategies"] == ["none", "rewrite"]
    assert "preserved_terms" not in fake.calls[0]["user_payload"]


def test_no_retrieval_and_clarification_short_circuit_without_llm() -> None:
    no_retrieval = QueryDecision(
        original_question="Thanks",
        intent="no_retrieval",
        confidence=0.9,
        requires_retrieval=False,
        allowed_actions=(),
        retrieval_routes=("no_retrieval",),
    )
    clarification = QueryDecision(
        original_question="Which one?",
        intent="clarification_required",
        confidence=0.7,
        requires_retrieval=False,
        allowed_actions=("request_clarification",),
        retrieval_routes=("clarification",),
    )
    fake = FakeLLMClient({})

    no_result = transform_query(decision=no_retrieval, llm_client=fake)
    clarification_result = transform_query(decision=clarification, llm_client=fake)

    assert no_result.plan.retrieval_queries == ()
    assert clarification_result.plan.retrieval_queries == ()
    assert clarification_result.plan.actions == ("request_clarification",)
    assert fake.calls == []

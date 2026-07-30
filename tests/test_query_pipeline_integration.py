from __future__ import annotations

import json
from types import SimpleNamespace

from docagent.query.pipeline import run_query_pipeline
from docagent.query.schemas import QueryMetadataFilter, QueryPlan
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.schemas import Chunk


class SequencedLLMClient:
    def __init__(self, payloads: list[dict[str, object]]) -> None:
        self.payloads = list(payloads)
        self.config = SimpleNamespace(model="qwen3.7-max-2026-05-17")
        self.system_prompts: list[str] = []

    def complete(self, *, system_prompt: str, user_payload: dict[str, object]) -> str:
        self.system_prompts.append(system_prompt)
        return json.dumps(self.payloads.pop(0), ensure_ascii=False)


def test_query_pipeline_separates_original_question_from_retrieval_queries() -> None:
    question = "Why do Sections 3 and 4 report different results?"
    fake = SequencedLLMClient(
        [
            {"intent": "complex_analysis", "confidence": 0.91, "reason": "multi-evidence"},
            {
                "actions": ["decompose", "preserve_terms"],
                "retrieval_queries": [
                    "Section 3 reported results",
                    "Section 4 reported results",
                    "reasons for different results in Sections 3 and 4",
                ],
                "preserved_terms": ["3", "4"],
            },
        ]
    )

    output = run_query_pipeline(
        question=question,
        document_profile={"dominant_language": "en", "has_tables": True, "has_images": True},
        llm_client=fake,
    )

    assert output.decision.original_question == question
    assert output.plan.original_question == question
    assert output.plan.retrieval_queries[0] != question
    assert output.trace["static_decomposition"] is True
    assert len(fake.system_prompts) == 2
    assert fake.system_prompts[0] != fake.system_prompts[1]


def test_canonical_query_plan_drives_multi_query_and_metadata_prefilter() -> None:
    plan = QueryPlan(
        original_question="What does Section 2 say?",
        intent="navigation",
        actions=("rewrite",),
        retrieval_queries=("Section 2 target finding", "target finding"),
        retrieval_routes=("metadata_filter", "dense", "sparse"),
        metadata_filter=QueryMetadataFilter(physical_pages=(2,)),
        transformation_source="llm",
    )
    retriever = IndexedDocumentRetriever(
        [
            Chunk(doc_id="doc1", block_id="p1", block_type="text", page_id=1, text="target finding"),
            Chunk(doc_id="doc1", block_id="p2", block_type="text", page_id=2, text="Section 2 target finding"),
        ],
        mode="bm25",
        query_plan=plan,
        filters=plan.metadata_filter.to_retrieval_filter(),
        query_intent=plan.intent,
    )

    result = retriever.retrieve(doc_id="doc1", question=plan.original_question, top_k=2)

    assert [candidate.block.block_id for candidate in result.candidates] == ["p2"]
    assert result.metadata["pre_filter_block_count"] == 2
    assert result.metadata["post_filter_block_count"] == 1
    assert result.metadata["metadata_filter"] == {"page_ids": [2]}
    assert result.metadata["query_intent"] == "navigation"
    assert result.rewritten_query == "Section 2 target finding | target finding"

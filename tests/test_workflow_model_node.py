from __future__ import annotations

from typing import Any

from docagent.models.base import GenerationResult
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.workflow.graph import run_qa_workflow


class FakePolicy:
    mode = "fake"

    def generate(self, **kwargs: Any) -> GenerationResult:
        return GenerationResult(
            raw_text='{"answer": "March 12, 2020", "evidence_location": {"block_id": "b1"}, "evidence": "Date: March 12, 2020", "reason": "supported"}',
            parsed={
                "answer": "March 12, 2020",
                "evidence_location": {"block_id": "b1"},
                "evidence": "Date: March 12, 2020",
                "reason": "supported",
            },
            prompt_text="prompt",
            prompt_token_count=1,
            completion_token_count=10,
            finish_reason="stop",
            latency_ms=2.0,
            metadata={"parse_result": {"raw_json_ok": True, "schema_ok": True}},
        )


class CandidateSchemaPolicy:
    mode = "candidate_fake"

    def generate(self, **kwargs: Any) -> GenerationResult:
        parsed = {
            "answer": "March 12, 2020",
            "reasoning_summary": "The invoice date is stated in the selected text block.",
            "citation_block_ids": ["missing_block", "b1"],
            "evidence_used": [
                {"block_id": "missing_block", "text_preview": "not in the evidence pack"},
                {"block_id": "b1", "text_preview": "Date: March 12, 2020"},
            ],
        }
        return GenerationResult(
            raw_text='{"answer": "March 12, 2020", "reasoning_summary": "..."}',
            parsed=parsed,
            prompt_text="prompt",
            prompt_token_count=1,
            completion_token_count=10,
            finish_reason="stop",
            latency_ms=2.0,
            metadata={"parse_result": {"raw_json_ok": True, "schema_ok": True}},
        )


class ToolAwarePolicy:
    mode = "tool_aware_fake"

    def generate(self, **kwargs: Any) -> GenerationResult:
        tool_result = (kwargs.get("tool_results") or [])[0]
        citation = tool_result["citations"][0]
        parsed = {
            "answer": tool_result["answer"],
            "reasoning_summary": "The table tool selected the cited table cell.",
            "citation_block_ids": [citation["block_id"]],
            "evidence_used": [{"block_id": citation["block_id"], "text_preview": citation["text_preview"]}],
        }
        return GenerationResult(
            raw_text='{"answer": "2019: 10"}',
            parsed=parsed,
            prompt_text="prompt",
            prompt_token_count=1,
            completion_token_count=10,
            finish_reason="stop",
            latency_ms=2.0,
            metadata={"parse_result": {"raw_json_ok": True, "schema_ok": True}},
        )


class ToolAnswerWrongCitationPolicy:
    mode = "tool_wrong_citation_fake"

    def generate(self, **kwargs: Any) -> GenerationResult:
        tool_result = (kwargs.get("tool_results") or [])[0]
        retrieved_block = kwargs["evidence_blocks"][0]
        parsed = {
            "answer": tool_result["answer"],
            "reasoning_summary": "The table tool selected the value, but the model cited the retrieved text.",
            "citation_block_ids": [retrieved_block.block_id],
            "evidence_used": [{"block_id": retrieved_block.block_id, "text_preview": retrieved_block.retrieval_text}],
        }
        return GenerationResult(
            raw_text='{"answer": "2019: 10"}',
            parsed=parsed,
            prompt_text="prompt",
            prompt_token_count=1,
            completion_token_count=10,
            finish_reason="stop",
            latency_ms=2.0,
            metadata={"parse_result": {"raw_json_ok": True, "schema_ok": True}},
        )


class V3RefPolicy:
    mode = "v3_fake"

    def generate(self, **kwargs: Any) -> GenerationResult:
        parsed = {
            "answer": "March 12, 2020",
            "supporting_refs": ["E1"],
            "support_status": "supported",
            "reasoning_summary": "E1 states the date.",
        }
        return GenerationResult(
            raw_text='{"answer": "March 12, 2020"}',
            parsed=parsed,
            prompt_text="prompt",
            prompt_token_count=1,
            completion_token_count=10,
            finish_reason="stop",
            latency_ms=2.0,
            metadata={
                "parse_result": {"raw_json_ok": True, "schema_ok": True},
                "evidence_ref_map": {"E1": {"source_kind": "evidence_block", "block_id": "b1"}},
            },
        )


def _blocks() -> list[EvidenceBlock]:
    return [
        EvidenceBlock(
            doc_id="doc1",
            page_id=1,
            block_id="b1",
            block_type="text",
            text="Date: March 12, 2020",
            location=EvidenceLocation(page=1, block_id="b1"),
        )
    ]


def _blocks_with_table() -> list[EvidenceBlock]:
    return [
        EvidenceBlock(
            doc_id="doc1",
            page_id=1,
            block_id="text",
            block_type="text",
            text="The annual report contains a table of yearly values.",
            location=EvidenceLocation(page=1, block_id="text"),
        ),
        EvidenceBlock(
            doc_id="doc1",
            page_id=2,
            block_id="table",
            block_type="table",
            table_html="<table><tr><td>Year</td><td>Value</td></tr><tr><td>2019</td><td>10</td></tr></table>",
            location=EvidenceLocation(page=2, block_id="table", table_id="table"),
        ),
    ]


def test_workflow_uses_injected_answer_policy() -> None:
    state = run_qa_workflow(
        qid="q1",
        question="What is the date?",
        blocks=_blocks(),
        answer_policy=FakePolicy(),
        answer_type_hint="extractive",
    )

    assert state.final_answer["answer"] == "March 12, 2020"
    assert state.generation_metadata["policy_mode"] == "fake"
    assert state.parse_result["schema_ok"] is True
    assert "generate_answer" in [item["step"] for item in state.trace]


def test_workflow_maps_model_output_v3_refs_to_citations() -> None:
    state = run_qa_workflow(
        qid="q1",
        question="What is the date?",
        blocks=_blocks(),
        answer_policy=V3RefPolicy(),
        answer_type_hint="extractive",
        preserve_input_order=True,
    )

    assert state.final_answer["answer"] == "March 12, 2020"
    assert state.final_answer["supporting_refs"] == ["E1"]
    assert state.final_answer["citation_block_ids"] == ["b1"]
    assert state.final_answer["evidence_location"]["block_id"] == "b1"
    assert state.generation_metadata["evidence_ref_map"]["E1"]["block_id"] == "b1"


def test_workflow_can_preserve_input_evidence_order() -> None:
    blocks = [
        EvidenceBlock(
            doc_id="doc1",
            page_id=1,
            block_id="first",
            block_type="text",
            text="unrelated text",
            location=EvidenceLocation(page=1, block_id="first"),
        ),
        EvidenceBlock(
            doc_id="doc1",
            page_id=2,
            block_id="second",
            block_type="text",
            text="date date date March 12 2020",
            location=EvidenceLocation(page=2, block_id="second"),
        ),
    ]

    state = run_qa_workflow(
        qid="q1",
        question="What is the date?",
        blocks=blocks,
        answer_policy=FakePolicy(),
        answer_type_hint="extractive",
        preserve_input_order=True,
    )

    assert [block.block_id for block in state.retrieved_blocks] == ["first", "second"]
    assert state.trace[0]["preserve_input_order"] is True


def test_workflow_accepts_candidate_schema_and_filters_citations() -> None:
    state = run_qa_workflow(
        qid="q1",
        question="What is the date?",
        blocks=_blocks(),
        answer_policy=CandidateSchemaPolicy(),
        answer_type_hint="extractive",
    )

    assert state.status == "completed"
    assert state.final_answer["answer"] == "March 12, 2020"
    assert state.final_answer["reasoning_summary"] == "The invoice date is stated in the selected text block."
    assert state.final_answer["citation_block_ids"] == ["b1"]
    assert state.final_answer["citation_validation"]["invalid_block_ids"] == ["missing_block"]
    assert state.format_check["success"] is True
    assert state.location_check["success"] is True


def test_workflow_passes_tool_results_to_answer_policy() -> None:
    tool_result = {
        "status": "success",
        "tool": "table_lookup_or_calculation",
        "answer": "2019: 10",
        "citations": [{"block_id": "b1", "text_preview": "2019 10"}],
    }

    state = run_qa_workflow(
        qid="q1",
        question="What is the 2019 value?",
        blocks=_blocks(),
        answer_policy=ToolAwarePolicy(),
        answer_type_hint="numeric",
        preserve_input_order=True,
        tool_results=[tool_result],
    )

    assert state.final_answer["answer"] == "2019: 10"
    assert state.final_answer["citation_block_ids"] == ["b1"]
    assert state.table_results == [tool_result]
    trace_by_step = {item["step"]: item for item in state.trace}
    assert trace_by_step["build_evidence_context"]["tool_result_count"] == 1
    assert trace_by_step["generate_answer"]["tool_result_count"] == 1


def test_workflow_allows_tool_citation_outside_retrieved_top_k() -> None:
    tool_result = {
        "status": "success",
        "tool": "table_lookup_or_calculation",
        "answer": "2019: 10",
        "citations": [{"block_id": "table", "text_preview": "2019 10"}],
    }

    state = run_qa_workflow(
        qid="q1",
        question="What is the 2019 value?",
        blocks=_blocks_with_table(),
        answer_policy=ToolAwarePolicy(),
        answer_type_hint="numeric",
        top_k=1,
        preserve_input_order=True,
        tool_results=[tool_result],
    )

    assert [block.block_id for block in state.retrieved_blocks] == ["text"]
    assert state.final_answer["citation_block_ids"] == ["table"]
    assert state.final_answer["evidence_location"]["block_id"] == "table"
    assert state.final_answer["citation_validation"]["preferred_block_ids"] == ["table"]
    assert state.final_answer["citation_validation"]["missing_preferred_block_ids"] == []
    assert state.location_check["success"] is True
    assert state.generation_metadata["citation_allowlist_block_ids"] == ["text", "table"]


def test_workflow_prefers_tool_citation_when_model_cites_retrieved_text() -> None:
    tool_result = {
        "status": "success",
        "tool": "table_lookup_or_calculation",
        "answer": "2019: 10",
        "citations": [{"block_id": "table", "text_preview": "2019 10"}],
    }

    state = run_qa_workflow(
        qid="q1",
        question="What is the 2019 value?",
        blocks=_blocks_with_table(),
        answer_policy=ToolAnswerWrongCitationPolicy(),
        answer_type_hint="numeric",
        top_k=1,
        preserve_input_order=True,
        tool_results=[tool_result],
    )

    assert state.final_answer["citation_block_ids"] == ["table", "text"]
    assert state.final_answer["evidence_location"]["block_id"] == "table"
    assert state.final_answer["citation_validation"]["added_preferred_block_ids"] == ["table"]
    assert state.final_answer["citation_validation"]["requested_block_ids"] == ["text"]
    assert state.location_check["success"] is True

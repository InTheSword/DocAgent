from __future__ import annotations

from typing import Any

from docagent.models.base import GenerationResult
from docagent.retrieval.base import RetrievalCandidate, RetrievalResult
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.workflow.graph import _recovery_windows, run_qa_workflow


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


class RecoverOnSecondWindowPolicy:
    mode = "recovery_fake"

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def generate(self, **kwargs: Any) -> GenerationResult:
        block_ids = [block.block_id for block in kwargs["evidence_blocks"]]
        self.calls.append(block_ids)
        first_block = kwargs["evidence_blocks"][0]
        if len(self.calls) == 1:
            parsed = {
                "answer": "Insufficient evidence.",
                "supporting_refs": [],
                "support_status": "insufficient",
                "reasoning_summary": "No provided evidence supports the answer.",
            }
        else:
            parsed = {
                "answer": "Recovered answer",
                "supporting_refs": ["E1"],
                "support_status": "supported",
                "reasoning_summary": "E1 supports the answer.",
            }
        return GenerationResult(
            raw_text='{"answer": "..."}',
            parsed=parsed,
            prompt_text="prompt",
            prompt_token_count=1,
            completion_token_count=10,
            finish_reason="stop",
            latency_ms=2.0,
            metadata={
                "parse_result": {"raw_json_ok": True, "schema_ok": True},
                "evidence_ref_map": {"E1": {"source_kind": "evidence_block", "block_id": first_block.block_id}},
            },
        )


class RankedFakeRetriever:
    def __init__(self, blocks: list[EvidenceBlock]) -> None:
        self.blocks = blocks
        self.top_k_calls: list[int] = []

    def retrieve(self, *, doc_id: str | None, question: str, top_k: int, answer_type_hint: str | None = None) -> RetrievalResult:
        self.top_k_calls.append(top_k)
        return RetrievalResult(
            rewritten_query=question,
            candidates=[RetrievalCandidate(block=block) for block in self.blocks[:top_k]],
            metadata={"retriever_mode": "fake"},
        )


class AlwaysInsufficientPolicy:
    mode = "insufficient_fake"

    def generate(self, **kwargs: Any) -> GenerationResult:
        return GenerationResult(
            raw_text='{"answer": "Insufficient evidence."}',
            parsed={
                "answer": "Insufficient evidence.",
                "supporting_refs": [],
                "support_status": "insufficient",
                "reasoning_summary": "No provided evidence supports the answer.",
            },
            prompt_text="prompt",
            prompt_token_count=1,
            completion_token_count=10,
            finish_reason="stop",
            latency_ms=2.0,
            metadata={"parse_result": {"raw_json_ok": True, "schema_ok": True}, "evidence_ref_map": {}},
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


def test_recovery_windows_replace_context_without_expanding_prompt() -> None:
    assert _recovery_windows(20, 40) == [(0, 20), (10, 30), (20, 40)]


def test_workflow_recovery_uses_rank_window_after_insufficient_answer() -> None:
    blocks = [
        EvidenceBlock(
            doc_id="doc1",
            page_id=index,
            block_id=f"b{index}",
            block_type="text",
            text=f"Evidence block {index}",
            location=EvidenceLocation(page=index, block_id=f"b{index}"),
        )
        for index in range(1, 41)
    ]
    policy = RecoverOnSecondWindowPolicy()
    retriever = RankedFakeRetriever(blocks)

    state = run_qa_workflow(
        qid="q1",
        question="What is the answer?",
        blocks=blocks,
        answer_policy=policy,
        answer_type_hint="extractive",
        top_k=20,
        retriever=retriever,
        enable_evidence_recovery=True,
    )

    assert retriever.top_k_calls == [20, 40]
    assert policy.calls[0] == [f"b{index}" for index in range(1, 21)]
    assert policy.calls[1] == [f"b{index}" for index in range(11, 31)]
    assert all(len(call) <= 20 for call in policy.calls)
    assert state.final_answer["answer"] == "Recovered answer"
    assert state.final_answer["citation_block_ids"] == ["b11"]
    assert state.evidence_recovery["status"] == "recovered"
    assert state.evidence_recovery["selected_attempt_index"] == 1


def test_workflow_recovery_exhaustion_preserves_insufficient_without_fake_citations() -> None:
    blocks = [
        EvidenceBlock(
            doc_id="doc1",
            page_id=index,
            block_id=f"b{index}",
            block_type="text",
            text=f"Evidence block {index}",
            location=EvidenceLocation(page=index, block_id=f"b{index}"),
        )
        for index in range(1, 16)
    ]

    state = run_qa_workflow(
        qid="q1",
        question="What is the answer?",
        blocks=blocks,
        answer_policy=AlwaysInsufficientPolicy(),
        top_k=5,
        retriever=RankedFakeRetriever(blocks),
        enable_evidence_recovery=True,
    )

    assert state.final_answer["support_status"] == "insufficient"
    assert state.final_answer["citation_block_ids"] == []
    assert state.final_answer["citations"] == []
    assert state.evidence_recovery["status"] == "exhausted"


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


def test_workflow_passes_visual_observation_to_answer_policy() -> None:
    image_block = EvidenceBlock(
        doc_id="doc1",
        block_id="image",
        block_type="image",
        text="",
        page_id=1,
        image_path="images/chart.png",
        location=EvidenceLocation(page=1, block_id="image"),
        metadata={"visual_content_status": "resource_only", "requires_visual_understanding": True},
    )

    def fake_visual_reviewer(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "status": "success",
            "tool": "visual_review",
            "answer": "FY2020 reaches 45%.",
            "reasoning_summary": "The visual observation reads the chart label.",
            "citations": [{"block_id": "image", "text_preview": "FY2020 reaches 45%."}],
            "structured_result": {"used_vlm": True},
        }

    state = run_qa_workflow(
        qid="q_visual",
        question="What does the chart show for FY2020?",
        blocks=[image_block],
        answer_policy=ToolAwarePolicy(),
        answer_type_hint="visual",
        preserve_input_order=True,
        visual_review_mode="force",
        visual_reviewer=fake_visual_reviewer,
    )

    assert state.visual_results[0]["structured_result"]["used_vlm"] is True
    assert state.final_answer["answer"] == "FY2020 reaches 45%."
    assert state.final_answer["citation_block_ids"] == ["image"]
    trace_by_step = {item["step"]: item for item in state.trace}
    assert trace_by_step["visual_review"]["used_vlm"] is True
    assert trace_by_step["generate_answer"]["tool_result_count"] == 1


def test_workflow_does_not_pass_skipped_visual_observation_to_answer_policy() -> None:
    image_block = EvidenceBlock(
        doc_id="doc1",
        block_id="image",
        block_type="image",
        text="Existing caption only.",
        page_id=1,
        image_path="images/chart.png",
        location=EvidenceLocation(page=1, block_id="image"),
    )

    class NoToolPolicy:
        mode = "no_tool_fake"

        def generate(self, **kwargs: Any) -> GenerationResult:
            assert kwargs.get("tool_results") == []
            parsed = {
                "answer": "Existing caption only.",
                "reasoning_summary": "The image block already contains usable text.",
                "citation_block_ids": ["image"],
                "evidence_used": [{"block_id": "image", "text_preview": "Existing caption only."}],
            }
            return GenerationResult(
                raw_text='{"answer": "Existing caption only."}',
                parsed=parsed,
                prompt_text="prompt",
                prompt_token_count=1,
                completion_token_count=10,
                finish_reason="stop",
                latency_ms=2.0,
                metadata={"parse_result": {"raw_json_ok": True, "schema_ok": True}},
            )

    def skipped_visual_reviewer(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"status": "skipped", "structured_result": {"skip_reason": "visual_review_disabled", "used_vlm": False}}

    state = run_qa_workflow(
        qid="q_visual_skipped",
        question="What does the image show?",
        blocks=[image_block],
        answer_policy=NoToolPolicy(),
        answer_type_hint="visual",
        preserve_input_order=True,
        visual_review_mode="off",
        visual_reviewer=skipped_visual_reviewer,
    )

    assert state.visual_results[0]["status"] == "skipped"
    trace_by_step = {item["step"]: item for item in state.trace}
    assert trace_by_step["visual_review"]["status"] == "skipped"
    assert trace_by_step["generate_answer"]["tool_result_count"] == 0

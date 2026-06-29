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

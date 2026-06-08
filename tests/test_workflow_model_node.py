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

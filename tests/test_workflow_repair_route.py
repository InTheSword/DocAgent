from __future__ import annotations

from typing import Any

from docagent.models.base import GenerationResult
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.workflow.graph import run_qa_workflow


class BadLocationPolicy:
    mode = "fake"

    def generate(self, **kwargs: Any) -> GenerationResult:
        parsed = {
            "answer": "March 12, 2020",
            "evidence_location": {"block_id": "wrong"},
            "evidence": "Date: March 12, 2020",
            "reason": "supported",
        }
        return GenerationResult(
            raw_text="{}",
            parsed=parsed,
            prompt_text="prompt",
            prompt_token_count=1,
            completion_token_count=1,
            finish_reason="stop",
            latency_ms=1.0,
            metadata={"parse_result": {"raw_json_ok": True, "schema_ok": True}},
        )


def test_workflow_repairs_location_once() -> None:
    block = EvidenceBlock(
        doc_id="doc1",
        page_id=1,
        block_id="b1",
        block_type="text",
        text="Date: March 12, 2020",
        location=EvidenceLocation(page=1, block_id="b1"),
    )

    state = run_qa_workflow(
        qid="q1",
        question="What is the date?",
        blocks=[block],
        answer_policy=BadLocationPolicy(),
        answer_type_hint="extractive",
    )

    assert state.repair_attempted is True
    assert state.final_answer["evidence_location"]["block_id"] == "b1"
    assert state.location_check["success"] is True
    assert [item["step"] for item in state.trace].count("answer_repair") == 1

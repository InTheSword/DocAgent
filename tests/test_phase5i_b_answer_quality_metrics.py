from __future__ import annotations

from docagent.eval.answer_quality import evaluate_answer, evaluate_format, evaluate_location, validate_citations
from docagent.eval.failure_taxonomy import classify_failure
from docagent.schemas import EvidenceBlock, EvidenceLocation


def _block(page: int = 1, block_id: str = "b1") -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="doc1",
        page_id=page,
        block_id=block_id,
        block_type="text",
        text="The report was published by Northstar Research Institute.",
        location=EvidenceLocation(page=page, block_id=block_id),
    )


def test_answer_quality_exact_contains_and_token_f1() -> None:
    result = evaluate_answer(
        predicted_answer="It was published by Northstar Research Institute.",
        gold_answer="Northstar Research Institute",
        answer_type="extractive",
        eval_method="normalized_exact_or_contains",
    )

    assert result["answer_correct"] is True
    assert result["contains_match"] is True
    assert result["token_f1"] > 0


def test_refusal_answer_quality() -> None:
    result = evaluate_answer(
        predicted_answer="Insufficient evidence in the provided document to answer.",
        gold_answer=None,
        answer_type="refusal",
        eval_method="refusal_expected",
    )

    assert result["answer_correct"] is True
    assert result["is_refusal"] is True


def test_format_citation_and_location_checks() -> None:
    block = _block()
    final_answer = {
        "answer": "Northstar Research Institute",
        "evidence_location": {"page": 1, "block_id": "b1"},
        "evidence": "published by Northstar Research Institute",
        "reason": "The evidence names the publisher.",
    }
    citations = [{"page": 1, "block_id": "b1"}]

    assert evaluate_format(final_answer)["format_valid"] is True
    assert validate_citations(citations=citations, final_answer=final_answer, evidence_blocks=[block])["citation_valid"] is True
    assert evaluate_location(final_answer=final_answer, citations=citations, gold_locations=[{"page": 1}])["location_correct"] is True


def test_failure_taxonomy_prioritizes_router_and_generation() -> None:
    assert (
        classify_failure(
            status="failed",
            expected_task_type="local_fact_qa",
            actual_task_type="document_summary",
            answer_correct=False,
            format_valid=True,
            citation_valid=True,
            location_correct=True,
        )
        == "router_error"
    )
    assert (
        classify_failure(
            status="failed",
            expected_task_type="local_fact_qa",
            actual_task_type="local_fact_qa",
            answer_correct=False,
            format_valid=True,
            citation_valid=True,
            location_correct=True,
        )
        == "generation_error"
    )

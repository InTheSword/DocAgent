from __future__ import annotations

from docagent.rewards.combined import docqa_v3_reward
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.workflow.answer_contract import validate_model_output_v3
from docagent.workflow.output_adapter import canonicalize_output, render_user_answer_text


def _block(block_id: str = "b1") -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="doc1",
        block_id=block_id,
        block_type="text",
        text="The invoice date is March 12, 2020.",
        page_id=2,
        location=EvidenceLocation(page=2, block_id=block_id, bbox=[0, 1, 2, 3]),
    )


def test_model_output_v3_schema_accepts_supported_and_insufficient() -> None:
    ok, error = validate_model_output_v3(
        {
            "answer": "March 12, 2020",
            "supporting_refs": ["E1"],
            "support_status": "supported",
            "reasoning_summary": "E1 states the invoice date.",
        },
        allowed_refs={"E1"},
    )
    assert ok is True
    assert error is None

    ok, error = validate_model_output_v3(
        {
            "answer": "Insufficient evidence.",
            "supporting_refs": [],
            "support_status": "insufficient",
            "reasoning_summary": "No candidate gives the requested date.",
        },
        allowed_refs={"E1"},
    )
    assert ok is True
    assert error is None


def test_model_output_v3_rejects_bad_ref_status_combinations() -> None:
    ok, error = validate_model_output_v3(
        {
            "answer": "March 12, 2020",
            "supporting_refs": [],
            "support_status": "supported",
            "reasoning_summary": "No ref.",
        },
        allowed_refs={"E1"},
    )
    assert ok is False
    assert "requires at least one" in str(error)

    ok, error = validate_model_output_v3(
        {
            "answer": "Insufficient evidence.",
            "supporting_refs": ["E1"],
            "support_status": "insufficient",
            "reasoning_summary": "Ref should not be present.",
        },
        allowed_refs={"E1"},
    )
    assert ok is False
    assert "must not include" in str(error)

    ok, error = validate_model_output_v3(
        {
            "answer": "March 12, 2020",
            "supporting_refs": ["E9"],
            "support_status": "supported",
            "reasoning_summary": "Invalid ref.",
        },
        allowed_refs={"E1"},
    )
    assert ok is False
    assert "invalid supporting_refs" in str(error)


def test_canonicalize_v3_maps_supporting_refs_to_internal_citations() -> None:
    block = _block()
    output = canonicalize_output(
        {
            "answer": "March 12, 2020",
            "supporting_refs": ["E1"],
            "support_status": "supported",
            "reasoning_summary": "E1 states the invoice date.",
        },
        [block],
    )

    assert output["citation_block_ids"] == ["b1"]
    assert output["evidence_location"]["block_id"] == "b1"
    assert output["citations"][0]["doc_id"] == "doc1"
    assert output["citation_validation"]["valid_supporting_refs"] == ["E1"]


def test_canonicalize_v3_uses_derived_refs_for_calculation_observation() -> None:
    block = _block("table1")
    output = canonicalize_output(
        {
            "answer": "-1161.33",
            "supporting_refs": ["E2"],
            "support_status": "supported",
            "reasoning_summary": "E2 gives the calculation result.",
        },
        [block],
        evidence_ref_map={
            "E1": {"block_id": "table1", "source_kind": "evidence_block"},
            "E2": {
                "source_kind": "calculation_result",
                "derived_from_refs": ["E1"],
                "preview": "Calculation result: (-2235 + -6986 + 5737) / 3 = -1161.33",
            },
        },
    )

    assert output["citation_block_ids"] == ["table1"]
    assert output["supporting_refs"] == ["E2"]
    assert output["citation_validation"]["unmapped_supporting_refs"] == []


def test_canonicalize_v3_insufficient_does_not_emit_fake_citations() -> None:
    output = canonicalize_output(
        {
            "answer": "Insufficient evidence.",
            "supporting_refs": [],
            "support_status": "insufficient",
            "reasoning_summary": "No evidence candidate contains the answer.",
        },
        [_block()],
    )

    assert output["citation_block_ids"] == []
    assert output["citations"] == []
    assert output["evidence_used"] == []


def test_render_user_answer_text_hides_internal_ids_and_paths() -> None:
    output = canonicalize_output(
        {
            "answer": "March 12, 2020",
            "supporting_refs": ["E1"],
            "support_status": "supported",
            "reasoning_summary": "E1 states the invoice date.",
        },
        [_block()],
    )

    rendered = render_user_answer_text(output)

    assert "March 12, 2020" in rendered
    assert "Page 2" in rendered
    assert "block_id" not in rendered
    assert "doc1" not in rendered
    assert "image_path" not in rendered
    assert "trace_path" not in rendered


def test_docqa_v3_reward_scores_answer_refs_and_insufficient() -> None:
    supported = {
        "answer": "March 12, 2020",
        "supporting_refs": ["E1"],
        "support_status": "supported",
        "reasoning_summary": "E1 states the invoice date.",
    }
    insufficient = {
        "answer": "Insufficient evidence.",
        "supporting_refs": [],
        "support_status": "insufficient",
        "reasoning_summary": "No candidate contains the answer.",
    }

    assert docqa_v3_reward(supported, "March 12, 2020", positive_refs=["E1"]) == 1.0
    assert docqa_v3_reward({**supported, "supporting_refs": ["E9"]}, "March 12, 2020", positive_refs=["E1"]) < 0.7
    assert docqa_v3_reward(insufficient, "", positive_refs=[], insufficient_expected=True) == 1.0

from __future__ import annotations

from docagent.retrieval.evidence_packing import (
    EvidenceCandidateBuilder,
    TopPageCandidate,
    candidate_artifact_has_gold_leakage,
    parse_question_hints,
    summarize_candidate_packing,
)
from docagent.schemas import EvidenceBlock, EvidenceLocation


def _block(
    block_id: str,
    text: str = "",
    *,
    block_type: str = "text",
    page: int = 1,
    order: int = 1,
    table_html: str | None = None,
    image_path: str | None = None,
    visual_summary: str | None = None,
    bbox: list[float] | None = None,
    metadata: dict[str, object] | None = None,
) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="internal_doc",
        block_id=block_id,
        block_type=block_type,
        text=text,
        page_id=page,
        table_html=table_html,
        image_path=image_path,
        visual_summary=visual_summary,
        location=EvidenceLocation(page=page, block_id=block_id, bbox=bbox or [0, order * 20, 100, order * 20 + 10]),
        metadata={"reading_order": order, **(metadata or {})},
    )


def _top_page(*block_ids: str, page_id: str = "page_1", rank: int = 1) -> TopPageCandidate:
    return TopPageCandidate(
        page=1,
        page_aggregate_id=page_id,
        retrieval_rank=rank,
        retrieval_score=1.0 / rank,
        child_block_ids=list(block_ids),
    )


def test_parse_question_hints_detects_required_types() -> None:
    numeric = parse_question_hints("What percentage index share rate is shown for age 21-25?")
    date = parse_question_hints("When is the signature date 12/31/2020?")
    heading = parse_question_hints("What is the heading title of this page?")
    source = parse_question_hints("What source is cited in the footer?")

    assert numeric.answer_type_hint == "numeric"
    assert {"percentage", "index", "share", "rate"}.issubset(set(numeric.field_hints))
    assert "21-25" in numeric.numeric_tokens
    assert date.answer_type_hint == "date"
    assert "12/31/2020" in date.date_tokens
    assert heading.answer_type_hint == "heading"
    assert "heading" in heading.field_hints
    assert source.answer_type_hint == "source"
    assert "source" in source.field_hints


def test_candidate_builder_prioritizes_index_percentage_source_and_heading() -> None:
    blocks = {
        "heading": _block(
            "heading",
            "Risk Factors",
            order=1,
            bbox=[0, 10, 400, 40],
            metadata={"reading_order": 1, "text_level": 1},
        ),
        "index": _block("index", "Index (31) segment share rate", order=2),
        "percentage": _block("percentage", "Revenue growth was 2.5%", block_type="table", table_html="<table>2.5%</table>", order=3),
        "source": _block(
            "source",
            "Source: company filings",
            order=4,
            metadata={"reading_order": 4, "is_boilerplate": True, "exclude_from_retrieval": True, "raw_mineru_type": "footer"},
        ),
    }
    builder = EvidenceCandidateBuilder(max_candidate_spans=2, max_candidate_spans_per_page=2, neighbor_window=0)
    top_pages = [_top_page(*blocks)]

    index_packet = builder.build(qid="q1", doc_id="doc", question="What index share rate is shown?", top_pages=top_pages, child_lookup=blocks)
    percentage_packet = builder.build(qid="q2", doc_id="doc", question="What percentage is shown?", top_pages=top_pages, child_lookup=blocks)
    source_packet = builder.build(qid="q3", doc_id="doc", question="What source is cited in the footer?", top_pages=top_pages, child_lookup=blocks)
    heading_packet = builder.build(qid="q4", doc_id="doc", question="What heading title is shown?", top_pages=top_pages, child_lookup=blocks)

    assert index_packet["candidate_spans"][0]["primary_block_id"] == "index"
    assert percentage_packet["candidate_spans"][0]["primary_block_id"] == "percentage"
    assert source_packet["candidate_spans"][0]["primary_block_id"] == "source"
    assert heading_packet["candidate_spans"][0]["primary_block_id"] == "heading"


def test_phase4d_b1_table_index_enhancement_is_disabled_by_default() -> None:
    blocks = {
        "header": _block("header", "Segment Share Rate Index", order=1, metadata={"raw_mineru_type": "table_header"}),
        "row": _block("row", "Share of Segment: 4.1% (241)", order=2, metadata={"raw_mineru_type": "table_row"}),
        "neighbor": _block("neighbor", "Previous segment share: 0.9% (53)", order=3, metadata={"raw_mineru_type": "table_row"}),
        "noise": _block("noise", "Company overview without table values", order=4),
    }
    builder = EvidenceCandidateBuilder(
        max_candidate_spans=2,
        max_candidate_spans_per_page=2,
        neighbor_window=0,
        max_candidate_blocks=4,
    )
    packet = builder.build(
        qid="q_table",
        doc_id="doc",
        question="What is the index of the segment share rate?",
        top_pages=[_top_page("header", "row", "neighbor", "noise")],
        child_lookup=blocks,
    )
    metrics = summarize_candidate_packing([packet])

    assert packet["packing_stats"]["table_index_enhancement_enabled"] is False
    assert metrics["table_index_enhancement_enabled"] is False
    assert packet["question_hints"]["table_index_hint"] is True
    assert all(span["score_breakdown"]["table_index_bonus"] == 0.0 for span in packet["candidate_spans"])
    assert all(len(span["block_ids"]) == 1 for span in packet["candidate_spans"])


def test_phase4d_b1_table_index_scoring_context_and_diagnostics_when_enabled() -> None:
    hints = parse_question_hints("What is the index of the segment share rate?")

    assert hints.answer_type_hint == "numeric"
    assert hints.to_dict()["table_index_hint"] is True
    assert {"index", "segment", "share", "rate"}.issubset(set(hints.field_hints))

    blocks = {
        "header": _block("header", "Segment Share Rate Index", order=1, metadata={"raw_mineru_type": "table_header"}),
        "row": _block("row", "Share of Segment: 4.1% (241)", order=2, metadata={"raw_mineru_type": "table_row"}),
        "neighbor": _block("neighbor", "Previous segment share: 0.9% (53)", order=3, metadata={"raw_mineru_type": "table_row"}),
        "noise": _block("noise", "Company overview without table values", order=4),
    }
    builder = EvidenceCandidateBuilder(
        max_candidate_spans=2,
        max_candidate_spans_per_page=2,
        neighbor_window=0,
        max_candidate_blocks=4,
        enable_table_index_packing=True,
    )
    packet = builder.build(
        qid="q_table",
        doc_id="doc",
        question="What is the index of the segment share rate?",
        top_pages=[_top_page("header", "row", "neighbor", "noise")],
        child_lookup=blocks,
    )
    first = packet["candidate_spans"][0]
    metrics = summarize_candidate_packing(
        [packet],
        gold_page_aggregate_ids={"q_table": "page_1"},
        gold_answers_by_qid={"q_table": ["241"]},
    )

    assert first["primary_block_id"] == "row"
    assert packet["packing_stats"]["table_index_enhancement_enabled"] is True
    assert metrics["table_index_enhancement_enabled"] is True
    assert first["table_index_candidate"] is True
    assert first["table_index_field_value_pattern"] is True
    assert first["table_index_parenthesized_index"] is True
    assert first["score_breakdown"]["table_index_bonus"] > 0.0
    assert first["block_ids"] == ["header", "row", "neighbor"]
    assert "Share of Segment: 4.1% (241)" in first["text"]
    assert packet["packing_stats"]["table_index_candidate_span_count"] >= 1
    assert packet["packing_stats"]["table_index_top_span_contains_field_value_rate"] == 1.0
    assert packet["packing_stats"]["table_index_neighbor_context_added_count"] >= 1
    assert packet["packing_stats"]["table_index_parenthesized_index_span_count"] >= 1
    assert metrics["table_index_candidate_span_count"] >= 1
    assert metrics["table_index_candidate_span_answer_coverage"] == 1.0
    assert metrics["table_index_top_span_contains_field_value_rate"] == 1.0
    assert metrics["table_index_neighbor_context_added_count"] >= 1
    assert metrics["table_index_parenthesized_index_span_count"] >= 1
    assert metrics["no_gold_leakage"] is True


def test_phase4d_b1_non_table_question_keeps_table_index_inactive() -> None:
    blocks = {
        "name": _block("name", "Company: Acme Corporation", order=1),
        "row": _block("row", "Share of Segment: 4.1% (241)", order=2, metadata={"raw_mineru_type": "table_row"}),
    }
    builder = EvidenceCandidateBuilder(max_candidate_spans=2, neighbor_window=0)
    packet = builder.build(
        qid="q_text",
        doc_id="doc",
        question="What is the company name?",
        top_pages=[_top_page("name", "row")],
        child_lookup=blocks,
    )

    assert packet["question_hints"]["table_index_hint"] is False
    assert packet["packing_stats"]["table_index_enhancement_enabled"] is False
    assert packet["candidate_spans"][0]["primary_block_id"] == "name"
    assert packet["candidate_spans"][0]["table_index_candidate"] is False
    assert packet["packing_stats"]["table_index_candidate_span_count"] == 0


def test_neighbor_expansion_limits_fallback_and_paths_are_safe() -> None:
    blocks = {
        "before": _block("before", "Context before", order=1),
        "primary": _block("primary", "Index (31) segment share rate", order=2),
        "after": _block("after", "Context after", order=3),
        "image": _block("image", block_type="image", image_path=r"C:\private\chart.png", visual_summary="Chart shows 45% share", order=4),
    }
    builder = EvidenceCandidateBuilder(
        max_candidate_spans=2,
        max_candidate_spans_per_page=2,
        neighbor_window=1,
        max_candidate_blocks=3,
    )
    packet = builder.build(
        qid="q1",
        doc_id="doc",
        question="What index share rate is shown?",
        top_pages=[_top_page("before", "primary", "after", "image")],
        child_lookup=blocks,
    )

    first = packet["candidate_spans"][0]
    assert first["block_ids"] == ["before", "primary", "after"]
    assert packet["packing_stats"]["candidate_block_count"] == 3
    assert packet["packing_stats"]["dropped_block_count"] == 1
    assert "\\" not in str(first.get("image_path") or "")
    assert not str(first.get("image_path") or "").startswith("C:")


def test_image_table_fallback_metrics_and_no_gold_leakage() -> None:
    blocks = {
        "image": _block("image", block_type="image", image_path="images/chart.png", visual_summary="Chart shows 45% share", order=1),
        "table": _block("table", "Table row", block_type="table", table_html="<table><tr><td>45%</td></tr></table>", order=2),
    }
    builder = EvidenceCandidateBuilder(max_candidate_spans=2, neighbor_window=0)
    packet = builder.build(
        qid="q1",
        doc_id="doc",
        question="What percentage is shown in the chart?",
        top_pages=[_top_page("image", "table")],
        child_lookup=blocks,
    )
    metrics = summarize_candidate_packing([packet], gold_page_aggregate_ids={"q1": "page_1"})

    assert packet["candidate_spans"]
    assert any(span["block_types"] == ["image"] for span in packet["candidate_spans"])
    assert any("table" in span["block_types"] for span in packet["candidate_spans"])
    assert metrics["sample_count"] == 1
    assert metrics["table_index_enhancement_enabled"] is False
    assert metrics["gold_page_in_candidate_pages_rate"] == 1.0
    assert metrics["gold_page_has_candidate_span_rate"] == 1.0
    assert metrics["no_gold_leakage"] is True
    assert candidate_artifact_has_gold_leakage({"gold_page_id": "page_1"}) is True
    assert packet["candidate_spans"][0].get("image_path") != r"C:\private\chart.png"

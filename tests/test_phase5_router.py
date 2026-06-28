from __future__ import annotations

import json

import pytest

from docagent.router import plan_route
from docagent.router.schemas import REQUIRED_DECISION_FIELDS, SUPPORTED_TASK_TYPES


FULL_TOOLS = [
    "local_fact_qa",
    "count_pages",
    "count_blocks",
    "count_tables",
    "count_images",
    "get_page_text",
    "list_pages",
    "extract_all_tables",
    "extract_all_images",
    "list_sections",
    "document_outline",
    "extract_all_dates",
    "document_summary",
    "table_lookup",
    "simple_calculation",
]

P0_TOOLS = [
    "local_fact_qa",
    "count_pages",
    "count_blocks",
    "count_tables",
    "count_images",
    "get_page_text",
    "list_pages",
]


def _route(question: str, tools: list[str] | None = None, **extra):
    payload = {
        "doc_id": "doc1",
        "question": question,
        "available_tools": FULL_TOOLS if tools is None else tools,
        **extra,
    }
    return plan_route(payload)


@pytest.mark.parametrize(
    ("question", "task_type", "selected_tools"),
    [
        ("How many pages are in this document?", "document_statistics", ["count_pages"]),
        ("Count the tables in this PDF.", "document_statistics", ["count_tables"]),
        ("How many image or figure regions are detected?", "document_statistics", ["count_images"]),
        ("How many OCR blocks are stored?", "document_statistics", ["count_blocks"]),
        ("How many pages, tables, and images are in this document?", "document_statistics", ["count_pages", "count_tables", "count_images"]),
        ("Show the text on page 3.", "page_lookup", ["get_page_text"]),
        ("What is on page 5?", "page_lookup", ["get_page_text"]),
        ("List all pages in the document.", "page_lookup", ["list_pages"]),
        ("Summarize page 2.", "page_lookup", ["get_page_text"]),
        ("Extract all tables.", "structured_extraction", ["extract_all_tables"]),
        ("List all figures.", "structured_extraction", ["extract_all_images"]),
        ("List all section headings.", "structured_extraction", ["list_sections"]),
        ("Give the document outline.", "structured_extraction", ["document_outline"]),
        ("Extract all dates mentioned in the document.", "structured_extraction", ["extract_all_dates"]),
        ("Summarize this document.", "document_summary", ["document_summary"]),
        ("What is this PDF about?", "document_summary", ["document_summary"]),
        ("What is this document mainly about?", "document_summary", ["document_summary"]),
        ("Give me the key points.", "document_summary", ["document_summary"]),
        ("请概括这份文件的主要内容", "document_summary", ["document_summary"]),
        ("What is the invoice date?", "local_fact_qa", ["local_fact_qa"]),
        ("Which organization issued the report?", "local_fact_qa", ["local_fact_qa"]),
        ("What is the total amount due?", "local_fact_qa", ["local_fact_qa"]),
        ("What was revenue in 2020?", "table_lookup_or_calculation", ["table_lookup"]),
        ("What is the difference between 2020 and 2021 revenue?", "table_lookup_or_calculation", ["table_lookup", "simple_calculation"]),
        ("Which row has the highest amount?", "table_lookup_or_calculation", ["table_lookup", "simple_calculation"]),
        ("What is the sum of 2020 and 2021 values?", "table_lookup_or_calculation", ["table_lookup", "simple_calculation"]),
        ("What was the tax rate in 2021?", "table_lookup_or_calculation", ["table_lookup"]),
        ("List all images.", "structured_extraction", ["extract_all_images"]),
        ("Count document blocks.", "document_statistics", ["count_blocks"]),
        ("Page count?", "document_statistics", ["count_pages"]),
        ("Show page 10.", "page_lookup", ["get_page_text"]),
        ("Give me a document overview.", "document_summary", ["document_summary"]),
    ],
)
def test_router_fixed_contract_examples(question: str, task_type: str, selected_tools: list[str]) -> None:
    result = _route(question)

    assert result["task_type"] == task_type
    assert result["selected_tools"] == selected_tools
    assert result["requires_visual_understanding"] is False
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["reason"]
    assert REQUIRED_DECISION_FIELDS.issubset(result.keys())
    assert result["task_type"] in SUPPORTED_TASK_TYPES
    assert set(result["selected_tools"]).issubset(FULL_TOOLS)
    json.dumps(result)


def test_document_statistics_uses_deterministic_tools_not_retrieval() -> None:
    result = _route("How many tables are detected?")

    assert result["task_type"] == "document_statistics"
    assert result["selected_tools"] == ["count_tables"]
    assert result["requires_retrieval"] is False
    assert result["query_rewrite"] == ""


def test_page_lookup_has_empty_query_rewrite() -> None:
    result = _route("Show the text from page 4.")

    assert result["task_type"] == "page_lookup"
    assert result["query_rewrite"] == ""
    assert result["reason"] == "Matched explicit page lookup pattern: page 4."


def test_structured_extraction_requires_full_scan() -> None:
    result = _route("Extract all tables.")

    assert result["task_type"] == "structured_extraction"
    assert result["requires_full_scan"] is True
    assert result["requires_table_tool"] is True
    assert result["target_evidence_types"] == ["table"]


def test_document_summary_requires_full_scan_without_retrieval() -> None:
    result = _route("Summarize this PDF.")

    assert result["task_type"] == "document_summary"
    assert result["requires_full_scan"] is True
    assert result["requires_retrieval"] is False
    assert result["query_rewrite"] == ""


def test_table_tool_unavailable_falls_back_to_local_fact_qa() -> None:
    result = _route("What is the difference between 2020 and 2021 revenue?", tools=P0_TOOLS)

    assert result["task_type"] == "table_lookup_or_calculation"
    assert result["selected_tools"] == ["local_fact_qa"]
    assert result["requires_retrieval"] is True
    assert result["requires_table_tool"] is True
    assert result["requires_calculation"] is True
    assert result["fallback_used"] is True
    assert "table_tool_unavailable" in result["warnings"]
    assert "calculation_tool_unavailable" in result["warnings"]
    assert "fallback_to_local_fact_qa" in result["warnings"]


def test_visual_pixel_question_falls_back_to_ocr_caption_local_fact() -> None:
    result = _route("What does the chart color mean?", tools=P0_TOOLS)

    assert result["task_type"] == "local_fact_qa"
    assert result["selected_tools"] == ["local_fact_qa"]
    assert result["requires_visual_understanding"] is False
    assert result["fallback_used"] is True
    assert "visual_understanding_unsupported" in result["warnings"]


def test_visual_pixel_question_without_local_fact_returns_error() -> None:
    result = _route("What is shown in the picture?", tools=["count_pages"])

    assert result["status"] == "error"
    assert result["error"]["code"] == "visual_understanding_unsupported"
    assert result["requires_visual_understanding"] is False
    assert result["selected_tools"] == []


def test_ambiguous_question_falls_back_with_low_confidence() -> None:
    result = _route("Can you help me?", tools=P0_TOOLS)

    assert result["task_type"] == "local_fact_qa"
    assert result["selected_tools"] == ["local_fact_qa"]
    assert result["fallback_used"] is True
    assert result["confidence"] < 0.55
    assert "ambiguous_question" in result["warnings"]
    assert "external_llm_router_disabled" in result["warnings"]


def test_missing_count_tool_uses_structured_fallback() -> None:
    result = _route("How many pages are in this document?", tools=["local_fact_qa"])

    assert result["task_type"] == "local_fact_qa"
    assert result["selected_tools"] == ["local_fact_qa"]
    assert result["fallback_used"] is True
    assert result["confidence"] == 0.2
    assert "tool_unavailable" in result["warnings"]


def test_no_available_tools_returns_router_error() -> None:
    result = _route("What is the invoice date?", tools=[])

    assert result["status"] == "error"
    assert result["error"]["code"] == "router_validation_failed"
    assert result["selected_tools"] == []


def test_selected_tools_are_validated_against_available_tools() -> None:
    result = _route("Count the tables in this PDF.", tools=["local_fact_qa", "count_pages"])

    assert result["selected_tools"] == ["local_fact_qa"]
    assert set(result["selected_tools"]).issubset({"local_fact_qa", "count_pages"})
    assert "tool_unavailable" in result["warnings"]


def test_query_rewrite_lightly_normalizes_local_fact_question() -> None:
    result = _route("Can you please tell me the invoice date in this PDF?")

    assert result["task_type"] == "local_fact_qa"
    assert result["query_rewrite"] == "the invoice date"


def test_query_rewrite_lightly_normalizes_table_question() -> None:
    result = _route("Please help me find the revenue in 2020 in this document.")

    assert result["task_type"] == "table_lookup_or_calculation"
    assert result["query_rewrite"] == "find the revenue in 2020"


def test_external_llm_option_returns_warning_without_api_call() -> None:
    result = _route("What is the invoice date?", options={"allow_external_llm_router": True})

    assert result["task_type"] == "local_fact_qa"
    assert "external_llm_router_unavailable" in result["warnings"]


def test_max_tool_calls_limits_selected_tools() -> None:
    result = _route(
        "How many pages, tables, images, and blocks are stored?",
        options={"max_tool_calls": 2},
    )

    assert result["task_type"] == "document_statistics"
    assert result["selected_tools"] == ["count_pages", "count_tables"]
    assert "max_tool_calls_limited" in result["warnings"]


def test_complex_query_decomposition_is_deferred() -> None:
    result = _route("What is the invoice date and then also summarize this document?")

    assert result["task_type"] == "document_summary"
    assert result["requires_visual_understanding"] is False
    assert result["query_rewrite"] == ""
    assert "complex_query_decomposition_deferred" in result["warnings"]


def test_complex_local_fact_query_warns_when_no_better_rule_matches() -> None:
    result = _route("What is the invoice date and also who approved it?")

    assert result["task_type"] == "local_fact_qa"
    assert "complex_query_decomposition_deferred" in result["warnings"]


def test_document_summary_unavailable_falls_back_without_generating_summary() -> None:
    result = _route("Summarize this document.", tools=P0_TOOLS)

    assert result["task_type"] == "document_summary"
    assert result["selected_tools"] == ["local_fact_qa"]
    assert result["fallback_used"] is True
    assert "tool_unavailable" in result["warnings"]


def test_structured_dates_tool_unavailable_falls_back() -> None:
    result = _route("Extract all dates mentioned in the document.", tools=P0_TOOLS)

    assert result["task_type"] == "structured_extraction"
    assert result["selected_tools"] == ["local_fact_qa"]
    assert result["requires_full_scan"] is True
    assert "fallback_to_local_fact_qa" in result["warnings"]


def test_document_profile_participates_in_planning_warnings() -> None:
    result = _route(
        "What was revenue in 2020?",
        document_profile={"has_tables": False, "table_count": 0},
    )

    assert result["task_type"] == "table_lookup_or_calculation"
    assert "document_profile_no_tables" in result["warnings"]

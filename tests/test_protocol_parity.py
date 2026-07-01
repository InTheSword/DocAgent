from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docagent.models.base import GenerationResult
from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.workflow.graph import run_qa_workflow
from docagent.workflow.output_adapter import canonicalize_output
from docagent.workflow.prompts import (
    PROMPT_VERSION,
    build_evidence_context,
    compile_answer_prompt,
    format_evidence_blocks,
)
from scripts.build_grpo_dataset import build_grpo_record
from scripts.build_sft_dataset import build_sft_record


class FakePolicy:
    mode = "fake"

    def generate(self, **kwargs: Any) -> GenerationResult:
        bundle = compile_answer_prompt(
            question=kwargs["question"],
            evidence_blocks=kwargs["evidence_blocks"],
            answer_type=kwargs.get("answer_type"),
        )
        parsed = {
            "answer": "March 12, 2020",
            "evidence_location": {"block_id": "b1"},
            "evidence": "Date: March 12, 2020",
            "reason": "The cited block contains the date.",
        }
        return GenerationResult(
            raw_text=json.dumps(parsed),
            parsed=parsed,
            prompt_text="prompt",
            prompt_token_count=12,
            completion_token_count=8,
            finish_reason="stop",
            latency_ms=1.0,
            metadata={"parse_result": {"raw_json_ok": True, "schema_ok": True}, **bundle.metadata},
        )


def _block(block_id: str, text: str, *, block_type: str = "text", page: int = 1, raw_type: str | None = None) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="doc1",
        page_id=page,
        block_id=block_id,
        block_type=block_type,
        text=text if block_type != "table" else "",
        table_html=text if block_type == "table" else None,
        visual_summary=text if block_type == "image" else None,
        location=EvidenceLocation(page=page, block_id=block_id, bbox=[0, 1, 2, 3]),
        metadata={"raw_mineru_type": raw_type} if raw_type else {},
    )


def _sample() -> DocAgentSample:
    return DocAgentSample(
        qid="q1",
        source="fixture",
        doc_id="doc1",
        question="What is the invoice date?",
        answer="March 12, 2020",
        answer_type="extractive",
        evidence=[
            _block("b1", "Invoice Date: March 12, 2020"),
            _block("b2", "Total: $42.00", block_type="table"),
        ],
        metadata={"gold_block_ids": ["b1"]},
    )


def test_sft_grpo_and_runtime_share_prompt_compiler() -> None:
    sample = _sample()
    expected = compile_answer_prompt(
        question=sample.question,
        evidence_blocks=sample.evidence,
        answer_type=sample.answer_type,
        max_chars_per_block=300,
        answer="March 12, 2020",
        gold_block_id="b1",
    )

    sft = build_sft_record(sample, max_evidence_blocks=5, max_block_chars=300, gold_first=False)
    grpo = build_grpo_record(sample, max_evidence_blocks=5, max_block_chars=300, gold_first=False)
    target = json.loads(sft["messages"][-1]["content"])

    assert sft["messages"][:2] == expected.messages
    assert grpo["messages"] == expected.messages
    assert sft["prompt_version"] == PROMPT_VERSION
    assert grpo["prompt_version"] == PROMPT_VERSION
    assert sft["evidence_context_hash"] == expected.evidence_context["evidence_context_hash"]
    assert "citation_block_ids" in expected.messages[1]["content"]
    assert "evidence_location" not in expected.messages[1]["content"]
    assert target["citation_block_ids"] == ["b1"]
    assert target["evidence_used"][0]["block_id"] == "b1"
    assert "reasoning_summary" in target


def test_context_hash_is_stable_and_order_sensitive() -> None:
    blocks = [_block("b1", "alpha"), _block("b2", "beta")]
    first = build_evidence_context(question="Q?", evidence_blocks=blocks)
    second = build_evidence_context(question="Q?", evidence_blocks=blocks)
    reversed_context = build_evidence_context(question="Q?", evidence_blocks=list(reversed(blocks)))

    assert first["evidence_context_hash"] == second["evidence_context_hash"]
    assert first["evidence_context_hash"] != reversed_context["evidence_context_hash"]
    assert first["selected_block_ids"] == ["b1", "b2"]


def test_context_serializes_text_table_chart_location_and_truncation() -> None:
    blocks = [
        _block("text", "alpha " * 20),
        _block("table", "<table><tr><td>42</td></tr></table>", block_type="table"),
        _block("chart", "chart says 9.9", block_type="image", raw_type="chart"),
        EvidenceBlock(
            doc_id="doc1",
            block_id="boiler",
            block_type="text",
            text="boilerplate",
            location=EvidenceLocation(block_id="boiler"),
            metadata={"is_boilerplate": True},
        ),
    ]

    context = build_evidence_context(question="Q?", evidence_blocks=blocks, token_budget=60, max_chars_per_block=50)

    assert context["truncation_applied"] is True
    assert "boiler" in context["dropped_block_ids"]
    assert context["evidence"][0]["block_type"] == "text"
    assert context["evidence"][0]["location"]["bbox"] == [0, 1, 2, 3]
    assert format_evidence_blocks(blocks[:1], max_chars_per_block=20).startswith("[TEXT | block_id=text")


def test_canonical_output_adapter_adds_doc_id_page_and_bbox() -> None:
    block = _block("b1", "Invoice Date: March 12, 2020")
    canonical = canonicalize_output(
        {"answer": "March 12, 2020", "evidence_location": {"block_id": "b1"}, "evidence": "Date", "reason": "cited"},
        [block],
    )

    assert canonical["evidence_location"]["doc_id"] == "doc1"
    assert canonical["evidence_location"]["page"] == 1
    assert canonical["evidence_location"]["bbox"] == [0, 1, 2, 3]


def test_canonical_output_adapter_filters_candidate_citations_to_allowlist() -> None:
    block = _block("b1", "Invoice Date: March 12, 2020")
    canonical = canonicalize_output(
        {
            "answer": "March 12, 2020",
            "reasoning_summary": "The selected block gives the invoice date.",
            "citation_block_ids": ["missing", "b1"],
            "evidence_used": [
                {"block_id": "missing", "text_preview": "not in evidence pack"},
                {"block_id": "b1", "text_preview": "Invoice Date: March 12, 2020"},
            ],
        },
        [block],
    )

    assert canonical["evidence_location"]["block_id"] == "b1"
    assert canonical["citation_block_ids"] == ["b1"]
    assert [item["block_id"] for item in canonical["citations"]] == ["b1"]
    assert [item["block_id"] for item in canonical["evidence_used"]] == ["b1"]
    assert canonical["citation_validation"]["invalid_block_ids"] == ["missing"]


def test_canonical_output_preserves_table_and_image_resource_fields() -> None:
    table = EvidenceBlock(
        doc_id="doc1",
        block_id="table1",
        block_type="table",
        text="Budget Estimate $100,000",
        table_html="<table><tr><td>Budget Estimate</td><td>$100,000</td></tr></table>",
        image_path="https://mineru.example/table.png",
        page_id=1,
        location=EvidenceLocation(page=1, block_id="table1"),
        metadata={"table_caption": ["Budget table"]},
    )
    image = EvidenceBlock(
        doc_id="doc1",
        block_id="image1",
        block_type="image",
        text="Revenue chart caption",
        image_path="images/chart.png",
        page_id=2,
        location=EvidenceLocation(page=2, block_id="image1"),
        metadata={"image_caption": "Revenue chart"},
    )

    canonical = canonicalize_output(
        {
            "answer": "Budget Estimate is $100,000.",
            "reasoning_summary": "The table and chart evidence identify the budget estimate.",
            "citation_block_ids": ["table1", "image1"],
            "evidence_used": [{"block_id": "table1"}, {"block_id": "image1"}],
        },
        [table, image],
    )

    assert canonical["citations"][0]["table_caption"] == "Budget table"
    assert canonical["citations"][0]["image_path"] == "https://mineru.example/table.png"
    assert canonical["citations"][1]["image_caption"] == "Revenue chart"
    assert canonical["citations"][1]["image_path"] == "images/chart.png"
    assert canonical["evidence_used"][0]["table_caption"] == "Budget table"
    assert canonical["evidence_used"][0]["image_path"] == "https://mineru.example/table.png"
    assert canonical["evidence_used"][1]["image_caption"] == "Revenue chart"
    assert canonical["evidence_used"][1]["image_path"] == "images/chart.png"


def test_workflow_trace_records_unified_protocol(tmp_path: Path) -> None:
    state = run_qa_workflow(
        qid="q1",
        question="What is the invoice date?",
        blocks=[_block("b1", "Invoice Date: March 12, 2020")],
        answer_policy=FakePolicy(),
        preserve_input_order=True,
    )

    trace_by_step = {item["step"]: item for item in state.trace}
    generation = trace_by_step["generate_answer"]
    finalize = trace_by_step["finalize"]

    assert trace_by_step["build_evidence_context"]["evidence_context_hash"]
    assert generation["prompt_version"] == PROMPT_VERSION
    assert generation["selected_block_ids"] == ["b1"]
    assert generation["raw_model_output"].startswith("{")
    assert generation["canonical_output"]["evidence_location"]["doc_id"] == "doc1"
    assert finalize["canonical_output"] == state.final_answer

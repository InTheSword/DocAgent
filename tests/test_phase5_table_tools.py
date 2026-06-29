from __future__ import annotations

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.tools.table_tools import table_lookup_or_calculation
from scripts.run_final_eval_subset import InMemoryDocumentRepository


def _sample_with_table(question: str) -> DocAgentSample:
    doc_id = "table_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id="table_doc_table",
        block_type="table",
        text=(
            "| Metric | 2019 | 2018 |\n"
            "| --- | --- | --- |\n"
            "| Net decrease in cash and cash equivalents | (472.7) | (361.2) |\n"
            "| Weighted-average common shares outstanding | 46,552 | 44,120 |"
        ),
        table_html=(
            "<table>"
            "<tr><th>Metric</th><th>2019</th><th>2018</th></tr>"
            "<tr><td>Net decrease in cash and cash equivalents</td><td>(472.7)</td><td>(361.2)</td></tr>"
            "<tr><td>Weighted-average common shares outstanding</td><td>46,552</td><td>44,120</td></tr>"
            "</table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id="table_doc_table", table_id="table_doc_table"),
    )
    return DocAgentSample(
        qid="table_q",
        source="fixture",
        doc_id=doc_id,
        question=question,
        answer=[],
        answer_type="extractive",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def test_table_lookup_does_not_infer_calculation_from_decrease_row_label() -> None:
    sample = _sample_with_table("What was the Net decrease in cash and cash equivalents in 2019?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup"],
    )

    assert result["status"] == "success"
    assert result["tools_used"] == ["table_lookup"]
    assert result["structured_result"]["operation"] == "table_lookup"
    assert "(472.7)" in result["answer"]


def test_table_lookup_does_not_infer_calculation_from_weighted_average_row_label() -> None:
    sample = _sample_with_table("What was the Weighted-average common shares outstanding in 2019?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup"],
    )

    assert result["status"] == "success"
    assert result["tools_used"] == ["table_lookup"]
    assert result["structured_result"]["operation"] == "table_lookup"
    assert "46,552" in result["answer"]


def test_table_calculation_still_runs_when_simple_calculation_is_selected() -> None:
    sample = _sample_with_table("What is the difference between 2018 and 2019 net decrease in cash?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup", "simple_calculation"],
    )

    assert result["status"] == "success"
    assert result["tools_used"] == ["table_lookup", "simple_calculation"]
    assert result["structured_result"]["operation"] == "simple_calculation"

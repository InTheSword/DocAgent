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


def _sample_with_multirow_header(question: str) -> DocAgentSample:
    doc_id = "multirow_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id="multirow_doc_table",
        block_type="table",
        text=(
            "| | Year ended March 31 | |\n"
            "| | 2019 | 2018 |\n"
            "| | $000 | $000 |\n"
            "| Net cash used for financing activities | $(42,056) | $(9,982) |\n"
            "| Underlying EBITDA | 85,123 | 62,575 |"
        ),
        table_html=(
            "<table>"
            "<tr><th></th><th>Year ended March 31</th><th></th></tr>"
            "<tr><td></td><td>2019</td><td>2018</td></tr>"
            "<tr><td></td><td>$000</td><td>$000</td></tr>"
            "<tr><td>Net cash used for financing activities</td><td>$(42,056)</td><td>$(9,982)</td></tr>"
            "<tr><td>Underlying EBITDA</td><td>85,123</td><td>62,575</td></tr>"
            "</table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id="multirow_doc_table", table_id="multirow_doc_table"),
    )
    return DocAgentSample(
        qid="multirow_q",
        source="fixture",
        doc_id=doc_id,
        question=question,
        answer=[],
        answer_type="extractive",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _sample_with_transfers_table(question: str) -> DocAgentSample:
    doc_id = "transfers_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id="transfers_doc_table",
        block_type="table",
        text=(
            "| | 2019 | 2018 |\n"
            "| Transfers (Note (b)) | (1,421) | (78,816) |\n"
            "| At end of the year | 135,936 | 97,877 |"
        ),
        table_html=(
            "<table>"
            "<tr><th></th><th>2019</th><th>2018</th></tr>"
            "<tr><td></td><td>RMB Million</td><td>RMB Million</td></tr>"
            "<tr><td>Transfers (Note (b))</td><td>(1,421)</td><td>(78,816)</td></tr>"
            "<tr><td>At end of the year</td><td>135,936</td><td>97,877</td></tr>"
            "</table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id="transfers_doc_table", table_id="transfers_doc_table"),
    )
    return DocAgentSample(
        qid="transfers_q",
        source="fixture",
        doc_id=doc_id,
        question=question,
        answer=[],
        answer_type="numeric",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _sample_with_activity_table(question: str) -> DocAgentSample:
    doc_id = "activity_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id="activity_doc_table",
        block_type="table",
        text=(
            "| | Number of Shares | Weighted Average Grant Date Fair Value |\n"
            "| Nonvested at January 1, 2017 | 98 | $23.52 |\n"
            "| Granted | 132 | 19.74 |\n"
            "| Vested | (43) | 20.44 |\n"
            "| Nonvested at December 30, 2018 | 183 | 17.22 |\n"
            "| Granted | 353 | 10.77 |\n"
            "| Vested | (118) | 14.48 |"
        ),
        table_html=(
            "<table>"
            "<tr><th></th><th></th><th>RSUs & PRSUs Outstanding</th></tr>"
            "<tr><td></td><td>Number of Shares</td><td>Weighted Average Grant Date Fair Value</td></tr>"
            "<tr><td></td><td>(in thousands)</td><td></td></tr>"
            "<tr><td>Nonvested at January 1, 2017</td><td>98</td><td>$23.52</td></tr>"
            "<tr><td>Granted</td><td>132</td><td>19.74</td></tr>"
            "<tr><td>Vested</td><td>(43)</td><td>20.44</td></tr>"
            "<tr><td>Nonvested at December 30, 2018</td><td>183</td><td>17.22</td></tr>"
            "<tr><td>Granted</td><td>353</td><td>10.77</td></tr>"
            "<tr><td>Vested</td><td>(118)</td><td>14.48</td></tr>"
            "</table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id="activity_doc_table", table_id="activity_doc_table"),
    )
    return DocAgentSample(
        qid="activity_q",
        source="fixture",
        doc_id=doc_id,
        question=question,
        answer=[],
        answer_type="extractive",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _sample_with_high_low_table(question: str) -> DocAgentSample:
    doc_id = "high_low_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id="high_low_doc_table",
        block_type="table",
        text=(
            "| | September 29, | July 7, |\n"
            "| | 2019 | 2019 |\n"
            "| High | $91.30 | $87.84 |\n"
            "| Low | $70.77 | $75.80 |"
        ),
        table_html=(
            "<table>"
            "<tr><th></th><th>September 29,</th><th>July 7,</th></tr>"
            "<tr><td></td><td>2019</td><td>2019</td></tr>"
            "<tr><td>High</td><td>$91.30</td><td>$87.84</td></tr>"
            "<tr><td>Low</td><td>$70.77</td><td>$75.80</td></tr>"
            "</table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id="high_low_doc_table", table_id="high_low_doc_table"),
    )
    return DocAgentSample(
        qid="high_low_q",
        source="fixture",
        doc_id=doc_id,
        question=question,
        answer=[],
        answer_type="numeric",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _sample_with_section_row_table(question: str) -> DocAgentSample:
    doc_id = "section_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id="section_doc_table",
        block_type="table",
        text=(
            "| Fiscal Years Ended March 31 | 2019 | 2018 | 2017 |\n"
            "| Weighted-average common shares outstanding: | | | |\n"
            "| Basic | 57,840 | 52,798 | 46,552 |"
        ),
        table_html=(
            "<table>"
            "<tr><th>Fiscal Years Ended March 31</th><th>2019</th><th>2018</th><th>2017</th></tr>"
            "<tr><td>Weighted-average common shares outstanding:</td><td></td><td></td><td></td></tr>"
            "<tr><td>Basic</td><td>57,840</td><td>52,798</td><td>46,552</td></tr>"
            "</table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id="section_doc_table", table_id="section_doc_table"),
    )
    return DocAgentSample(
        qid="section_q",
        source="fixture",
        doc_id=doc_id,
        question=question,
        answer=[],
        answer_type="extractive",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _sample_with_year_values_table(question: str) -> DocAgentSample:
    doc_id = "year_values_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id="year_values_doc_table",
        block_type="table",
        text=(
            "| | 2019 | 2018 | 2017 |\n"
            "| Nonvested shares | 6,148 | 5,974 | 4,800 |\n"
            "| Research, development and engineering | 126 | 67 | 31 |\n"
            "| Special termination benefits charge | 6 | 15 | 0 |\n"
            "| Operating income (loss) | $ (2,235) | $ (6,986) | $ 5,737 |"
        ),
        table_html=(
            "<table>"
            "<tr><th></th><th>2019</th><th>2018</th><th>2017</th></tr>"
            "<tr><td>Nonvested shares</td><td>6,148</td><td>5,974</td><td>4,800</td></tr>"
            "<tr><td>Research, development and engineering</td><td>126</td><td>67</td><td>31</td></tr>"
            "<tr><td>Special termination benefits charge</td><td>6</td><td>15</td><td>0</td></tr>"
            "<tr><td>Operating income (loss)</td><td>$ (2,235)</td><td>$ (6,986)</td><td>$ 5,737</td></tr>"
            "</table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id="year_values_doc_table", table_id="year_values_doc_table"),
    )
    return DocAgentSample(
        qid="year_values_q",
        source="fixture",
        doc_id=doc_id,
        question=question,
        answer=[],
        answer_type="numeric",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _sample_with_contract_obligations_table(question: str) -> DocAgentSample:
    doc_id = "contract_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id="contract_doc_table",
        block_type="table",
        text=(
            "| | Payments due by Period (In thousands) | | |\n"
            "| Contractual Obligations | Less Than 1 Year | 2-5 Years | Total |\n"
            "| Operating Lease Obligations: | $773 | $2,055 | $2,828 |"
        ),
        table_html=(
            "<table>"
            "<tr><th></th><th></th><th>Payments due by Period (In thousands)</th><th></th></tr>"
            "<tr><td>Contractual Obligations</td><td>Less Than 1 Year</td><td>2-5 Years</td><td>Total</td></tr>"
            "<tr><td>Operating Lease Obligations:</td><td>$773</td><td>$2,055</td><td>$2,828</td></tr>"
            "</table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id="contract_doc_table", table_id="contract_doc_table"),
    )
    return DocAgentSample(
        qid="contract_q",
        source="fixture",
        doc_id=doc_id,
        question=question,
        answer=[],
        answer_type="extractive",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _sample_with_quarter_table(question: str) -> DocAgentSample:
    doc_id = "quarter_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id="quarter_doc_table",
        block_type="table",
        text=(
            "| | First Quarter | Second Quarter | Third Quarter | Fiscal 2019 Fourth Quarter | Total |\n"
            "| Gross margin | 40.3% | 41.5% | 40.1% | 39.7% | 40.4% |"
        ),
        table_html=(
            "<table>"
            "<tr><th></th><th>First Quarter</th><th>Second Quarter</th><th>Third Quarter</th><th>Fiscal 2019 Fourth Quarter</th><th>Total</th></tr>"
            "<tr><td>Gross margin</td><td>40.3%</td><td>41.5%</td><td>40.1%</td><td>39.7%</td><td>40.4%</td></tr>"
            "</table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id="quarter_doc_table", table_id="quarter_doc_table"),
    )
    return DocAgentSample(
        qid="quarter_q",
        source="fixture",
        doc_id=doc_id,
        question=question,
        answer=[],
        answer_type="extractive",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _sample_with_reported_table(question: str) -> DocAgentSample:
    doc_id = "reported_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id="reported_doc_table",
        block_type="table",
        text=(
            "| (In millions) | As Reported | Balances Without Adoption of New Standard | Effect of Change |\n"
            "| Accounts receivable, net | $708 | $657 | $51 |"
        ),
        table_html=(
            "<table>"
            "<tr><th>(In millions)</th><th>As Reported</th><th>As of March 29, 2019 Balances Without Adoption of New Standard</th><th>Effect of Change</th></tr>"
            "<tr><td>Accounts receivable, net</td><td>$708</td><td>$657</td><td>$51</td></tr>"
            "</table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id="reported_doc_table", table_id="reported_doc_table"),
    )
    return DocAgentSample(
        qid="reported_q",
        source="fixture",
        doc_id=doc_id,
        question=question,
        answer=[],
        answer_type="extractive",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _sample_with_officers_table(question: str) -> DocAgentSample:
    doc_id = "officers_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id="officers_doc_table",
        block_type="table",
        text=(
            "| Name | Age | Title |\n"
            "| Andrew R. Kaiser | 51 | Chief Financial Officer |"
        ),
        table_html=(
            "<table>"
            "<tr><th>Name</th><th>Age</th><th>Title</th></tr>"
            "<tr><td>Andrew R. Kaiser</td><td>51</td><td>Chief Financial Officer</td></tr>"
            "</table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id="officers_doc_table", table_id="officers_doc_table"),
    )
    return DocAgentSample(
        qid="officers_q",
        source="fixture",
        doc_id=doc_id,
        question=question,
        answer=[],
        answer_type="extractive",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _sample_with_intangible_assets_table(question: str) -> DocAgentSample:
    doc_id = "intangible_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id="intangible_doc_table",
        block_type="table",
        text=(
            "| | Weighted-Average Useful Lives (in years) | Fair Value Amount |\n"
            "| Purchased technology | 4.2 | $232 |\n"
            "| Customer relationships and customer lists | 7.0 | 215 |\n"
            "| Other intangible assets | 2.0 | 20 |\n"
            "| Total intangible assets acquired | | 492 |"
        ),
        table_html=(
            "<table>"
            "<tr><th></th><th>Weighted-Average Useful Lives (in years)</th><th>Fair Value Amount</th></tr>"
            "<tr><td>Purchased technology</td><td>4.2</td><td>$232</td></tr>"
            "<tr><td>Customer relationships and customer lists</td><td>7.0</td><td>215</td></tr>"
            "<tr><td>Other intangible assets</td><td>2.0</td><td>20</td></tr>"
            "<tr><td>Total intangible assets acquired</td><td></td><td>492</td></tr>"
            "</table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id="intangible_doc_table", table_id="intangible_doc_table"),
    )
    return DocAgentSample(
        qid="intangible_q",
        source="fixture",
        doc_id=doc_id,
        question=question,
        answer=[],
        answer_type="numeric",
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


def test_table_lookup_uses_year_from_multirow_header() -> None:
    sample = _sample_with_multirow_header("How much net cash was used for financing activities in 2018?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "table_lookup"
    assert "$(9,982)" in result["answer"]


def test_table_lookup_understands_fiscal_year_shorthand() -> None:
    sample = _sample_with_multirow_header("What was the underlying EBITDA in FY19?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "table_lookup"
    assert "85,123" in result["answer"]
    assert "$85.1 million" in result["answer"]


def test_table_lookup_can_return_year_labels_from_header() -> None:
    sample = _sample_with_table("In which years was weighted-average common shares outstanding calculated?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "table_lookup"
    assert "2019" in result["answer"]
    assert "2018" in result["answer"]


def test_simple_calculation_prefers_direct_row_label_over_year_end_words() -> None:
    sample = _sample_with_transfers_table("How much is the change in transfers between 2018 year end and 2019 year end?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup", "simple_calculation"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "simple_calculation"
    assert "77395" in result["answer"]


def test_simple_calculation_averages_repeated_activity_rows() -> None:
    sample = _sample_with_activity_table(
        "What is the average number of nonvested shares granted on January 1, 2017 and between December 30, 2018 and December 29, 2019?"
    )

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup", "simple_calculation"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "simple_calculation"
    assert "242.5" in result["answer"]


def test_table_lookup_returns_respective_repeated_activity_values() -> None:
    sample = _sample_with_activity_table(
        "What is the respective number of nonvested shares vested on January 1, 2017 and between December 30, 2018 and December 29, 2019?"
    )

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "table_lookup"
    assert "(43)" in result["answer"]
    assert "(118)" in result["answer"]


def test_simple_calculation_uses_question_date_for_high_low_difference() -> None:
    sample = _sample_with_high_low_table("What is the difference between the high and low price in September 29, 2019?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup", "simple_calculation"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "simple_calculation"
    assert "20.53" in result["answer"]


def test_table_lookup_uses_section_row_context_for_child_label() -> None:
    sample = _sample_with_section_row_table("What was the basic Weighted-average common shares outstanding in 2017?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "table_lookup"
    assert "46,552" in result["answer"]


def test_simple_calculation_sums_total_values_across_years() -> None:
    sample = _sample_with_year_values_table("What is the total number of nonvested shares as of December 31, 2019 and 2018?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup", "simple_calculation"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "simple_calculation"
    assert result["structured_result"]["calculation"]["operation"] == "sum"
    assert "12122" in result["answer"]


def test_simple_calculation_sums_total_charge_across_years() -> None:
    sample = _sample_with_year_values_table("What is the total special termination benefits charge in 2018 and 2019?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup", "simple_calculation"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "simple_calculation"
    assert result["structured_result"]["calculation"]["operation"] == "sum"
    assert "21" in result["answer"]


def test_simple_calculation_detects_percentage_increase_wording() -> None:
    sample = _sample_with_year_values_table(
        "What is the percentage increase / (decrease) of Research, development and engineering from 2018 to 2019?"
    )

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup", "simple_calculation"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "simple_calculation"
    assert result["structured_result"]["calculation"]["operation"] == "percentage_change"
    assert "88.0597%" in result["answer"]


def test_simple_calculation_averages_same_row_across_three_years_with_currency_parentheses() -> None:
    sample = _sample_with_year_values_table("What is the average operating income (loss) across 2017, 2018 and 2019?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup", "simple_calculation"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "simple_calculation"
    assert result["structured_result"]["calculation"]["operation"] == "average"
    assert "-1161.3333" in result["answer"]


def test_simple_calculation_computes_row_value_as_percentage_of_total() -> None:
    sample = _sample_with_intangible_assets_table(
        "What was fair value amount of Other intangible assets as a percentage of total intangible assets acquired?"
    )

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup", "simple_calculation"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "simple_calculation"
    assert result["structured_result"]["calculation"]["operation"] == "percentage_of_total"
    assert "4.065%" in result["answer"]


def test_table_lookup_returns_respective_values_from_requested_period_columns() -> None:
    sample = _sample_with_contract_obligations_table(
        "What are the respective values of operating lease obligations that are less than one year and between 2-5 years?"
    )

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "table_lookup"
    assert "$773" in result["answer"]
    assert "$2,055" in result["answer"]
    assert "$2,828" not in result["answer"]


def test_table_lookup_prefers_requested_quarter_over_fiscal_year_group_header() -> None:
    sample = _sample_with_quarter_table("What was the gross margin in the fiscal 2019 second quarter?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "table_lookup"
    assert "41.5%" in result["answer"]
    assert "39.7%" not in result["answer"]


def test_table_lookup_prefers_as_reported_column_over_date_context_column() -> None:
    sample = _sample_with_reported_table("What is the Accounts receivable, net as reported as of March 29, 2019?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "table_lookup"
    assert "$708" in result["answer"]
    assert "$657" not in result["answer"]


def test_table_lookup_returns_name_for_who_question_in_people_table() -> None:
    sample = _sample_with_officers_table("Who is the company's Chief Financial Officer?")

    result = table_lookup_or_calculation(
        InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
        sample.doc_id,
        sample.question,
        selected_tools=["table_lookup"],
    )

    assert result["status"] == "success"
    assert result["structured_result"]["operation"] == "table_lookup"
    assert "Andrew R. Kaiser" in result["answer"]
    assert "51" not in result["answer"]

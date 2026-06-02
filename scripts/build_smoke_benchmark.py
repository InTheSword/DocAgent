from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import write_jsonl


def build_samples() -> list[DocAgentSample]:
    invoice_block = EvidenceBlock(
        doc_id="smoke_invoice",
        page_id=1,
        block_id="smoke_invoice_p1_b1",
        block_type="text",
        text="Invoice No: INV-2020-0312\nInvoice Date: March 12, 2020",
        location=EvidenceLocation(page=1, block_id="smoke_invoice_p1_b1"),
    )
    table_block = EvidenceBlock(
        doc_id="smoke_report",
        page_id=2,
        block_id="smoke_report_p2_table",
        block_type="table",
        text="| Year | Revenue |\n| --- | --- |\n| 2019 | 1000 |\n| 2020 | 1280 |",
        location=EvidenceLocation(page=2, block_id="smoke_report_p2_table", table_id="revenue_table"),
    )
    image_block = EvidenceBlock(
        doc_id="smoke_info",
        page_id=1,
        block_id="smoke_info_p1_img",
        block_type="image",
        text="A bar chart compares yearly revenue. The highest bar is 2020.",
        visual_summary="The chart shows 2020 has the highest revenue.",
        location=EvidenceLocation(page=1, block_id="smoke_info_p1_img", image_id="chart_1"),
    )
    return [
        DocAgentSample(
            qid="smoke_invoice_date",
            source="smoke",
            doc_id="smoke_invoice",
            question="What is the invoice date?",
            answer="March 12, 2020",
            answer_type="extractive",
            evidence=[invoice_block],
            split="dev",
        ),
        DocAgentSample(
            qid="smoke_revenue_2020",
            source="smoke",
            doc_id="smoke_report",
            question="What was the revenue in 2020?",
            answer="1280",
            answer_type="numeric",
            evidence=[table_block],
            split="dev",
        ),
        DocAgentSample(
            qid="smoke_highest_year",
            source="smoke",
            doc_id="smoke_info",
            question="Which year has the highest revenue in the chart?",
            answer="2020",
            answer_type="visual",
            evidence=[image_block],
            split="dev",
        ),
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="data/benchmark/smoke_eval.jsonl")
    args = parser.parse_args()
    samples = build_samples()
    write_jsonl(ROOT / args.output, [sample.to_dict() for sample in samples])
    print(f"wrote {len(samples)} samples to {args.output}")


if __name__ == "__main__":
    main()


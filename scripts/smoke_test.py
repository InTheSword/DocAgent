from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.retrieval_metrics import mrr_at_k, recall_at_k
from docagent.rewards.combined import docqa_reward
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect, save_evidence_blocks, save_qa_state
from docagent.workflow.graph import run_qa_workflow


def build_blocks() -> list[EvidenceBlock]:
    return [
        EvidenceBlock(
            doc_id="demo_doc",
            page_id=1,
            block_id="demo_doc_p1_b1",
            block_type="text",
            text="Invoice No: INV-2020-0312\nInvoice Date: March 12, 2020",
            location=EvidenceLocation(page=1, block_id="demo_doc_p1_b1"),
        ),
        EvidenceBlock(
            doc_id="demo_doc",
            page_id=2,
            block_id="demo_doc_p2_table",
            block_type="table",
            text="| Year | Revenue |\n| --- | --- |\n| 2019 | 1000 |\n| 2020 | 1280 |",
            location=EvidenceLocation(page=2, block_id="demo_doc_p2_table", table_id="revenue_table"),
        ),
        EvidenceBlock(
            doc_id="demo_doc",
            page_id=3,
            block_id="demo_doc_p3_img",
            block_type="image",
            text="A bar chart compares yearly revenue. The highest bar is 2020.",
            visual_summary="The chart shows 2020 has the highest revenue.",
            location=EvidenceLocation(page=3, block_id="demo_doc_p3_img", image_id="chart_1"),
        ),
    ]


def main() -> None:
    blocks = build_blocks()
    state = run_qa_workflow(
        qid="smoke_001",
        question="What is the invoice date?",
        blocks=blocks,
        top_k=2,
        answer_type_hint="extractive",
    )
    ranking = [block.block_id for block in state.retrieved_blocks]
    recall = recall_at_k([ranking], [{"demo_doc_p1_b1"}], k=2)
    mrr = mrr_at_k([ranking], [{"demo_doc_p1_b1"}], k=2)
    reward = docqa_reward(
        state.final_answer,
        gold_answer="March 12, 2020",
        gold_location={"page": 1, "block_id": "demo_doc_p1_b1"},
        answer_type="extractive",
    )
    conn = connect(ROOT / "outputs" / "traces" / "smoke.sqlite")
    save_evidence_blocks(conn, blocks)
    save_qa_state(conn, state)
    result = {
        "final_answer": state.final_answer,
        "ranking": ranking,
        "recall_at_2": recall,
        "mrr_at_2": mrr,
        "reward": reward,
        "trace_steps": [item["step"] for item in state.trace],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    assert recall == 1.0
    assert mrr == 1.0
    assert reward > 0.5


if __name__ == "__main__":
    main()


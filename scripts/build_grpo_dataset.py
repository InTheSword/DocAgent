from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from docagent.schemas import DocAgentSample
from docagent.utils.jsonl import read_jsonl, write_jsonl
from build_sft_dataset import (
    SYSTEM_PROMPT,
    build_location_target,
    format_evidence,
    normalize_answer,
    ordered_evidence_blocks,
    select_gold_block,
)


def load_samples(path: Path) -> list[DocAgentSample]:
    return [DocAgentSample.from_dict(record) for record in read_jsonl(path)]


def build_grpo_record(sample: DocAgentSample, max_evidence_blocks: int, max_block_chars: int) -> dict[str, Any]:
    gold_block = select_gold_block(sample)
    gold_location = build_location_target(gold_block) if gold_block else {}
    gold_answer = normalize_answer(sample.answer)
    gold_block_id = gold_block.block_id if gold_block else None
    evidence_blocks = ordered_evidence_blocks(sample)[:max_evidence_blocks]
    output_schema = json.dumps(
        {
            "answer": "short answer string copied or normalized from evidence",
            "evidence_location": {"page": 1, "block_id": "candidate_block_id"},
            "evidence": "minimal supporting span, compact row, or calculation inputs",
            "reason": "one sentence explaining why the evidence supports the answer",
        },
        ensure_ascii=False,
    )
    user_content = (
        "## Task\n"
        "Answer the question from the evidence candidates and cite the exact supporting location.\n\n"
        "## Question\n"
        f"{sample.question}\n\n"
        "## Answer Type\n"
        f"{sample.answer_type}\n\n"
        "## Evidence Candidates\n"
        f"{format_evidence(evidence_blocks, max_block_chars=max_block_chars, answer=gold_answer, gold_block_id=gold_block_id)}\n\n"
        "## Output Contract\n"
        f"Return JSON matching this schema: {output_schema}\n"
        "Rules:\n"
        "- answer must be concise and grounded in the evidence.\n"
        "- evidence_location must be a JSON object copied from one evidence header.\n"
        "- evidence must be the shortest sufficient supporting span or compact table row, no more than 300 characters.\n"
        "- reason must explain the answer-source relation in one sentence."
    )
    return {
        "id": sample.qid,
        "source": sample.source,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "gold_answer": gold_answer,
        "gold_location": gold_location,
        "answer_type": sample.answer_type,
        "reward_schema": ["format_reward", "answer_reward", "location_reward"],
        "metadata": {
            "doc_id": sample.doc_id,
            "gold_block_id": gold_block.block_id if gold_block else None,
            "scale": sample.metadata.get("scale"),
            "derivation": sample.metadata.get("derivation"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="data/benchmark/grpo_train.jsonl")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-evidence-blocks", type=int, default=5)
    parser.add_argument("--max-block-chars", type=int, default=1200)
    args = parser.parse_args()

    samples = [
        sample
        for sample in load_samples(ROOT / args.input)
        if sample.verifiable and sample.answer_type in {"extractive", "numeric", "boolean", "choice", "visual"}
    ]
    if args.offset:
        samples = samples[args.offset :]
    if args.limit is not None:
        samples = samples[: args.limit]
    records = [
        build_grpo_record(sample, max_evidence_blocks=args.max_evidence_blocks, max_block_chars=args.max_block_chars)
        for sample in samples
    ]
    write_jsonl(ROOT / args.output, records)
    print(
        json.dumps(
            {
                "input": args.input,
                "output": args.output,
                "num_records": len(records),
                "answer_types": _count_answer_types(records),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _count_answer_types(records: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        answer_type = str(record["answer_type"])
        counts[answer_type] = counts.get(answer_type, 0) + 1
    return counts


if __name__ == "__main__":
    main()

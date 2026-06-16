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
from docagent.workflow.prompts import compile_answer_prompt
from build_sft_dataset import (
    build_location_target,
    normalize_answer,
    ordered_evidence_blocks,
    select_gold_block,
)


def load_samples(path: Path) -> list[DocAgentSample]:
    return [DocAgentSample.from_dict(record) for record in read_jsonl(path)]


def build_grpo_record(
    sample: DocAgentSample,
    max_evidence_blocks: int,
    max_block_chars: int,
    gold_first: bool,
) -> dict[str, Any]:
    gold_block = select_gold_block(sample)
    gold_location = build_location_target(gold_block) if gold_block else {}
    gold_answer = normalize_answer(sample.answer)
    gold_block_id = gold_block.block_id if gold_block else None
    evidence_blocks = ordered_evidence_blocks(sample, gold_first=gold_first)[:max_evidence_blocks]
    bundle = compile_answer_prompt(
        question=sample.question,
        evidence_blocks=evidence_blocks,
        answer_type=sample.answer_type,
        append_no_think=False,
        max_chars_per_block=max_block_chars,
        answer=gold_answer,
        gold_block_id=gold_block_id,
    )
    return {
        "id": sample.qid,
        "source": sample.source,
        "messages": bundle.messages,
        "gold_answer": gold_answer,
        "gold_location": gold_location,
        "answer_type": sample.answer_type,
        "reward_schema": ["format_reward", "answer_reward", "location_reward"],
        "prompt_version": bundle.prompt_version,
        "evidence_context_hash": bundle.evidence_context["evidence_context_hash"],
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
    parser.add_argument("--preserve-evidence-order", action="store_true")
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
        build_grpo_record(
            sample,
            max_evidence_blocks=args.max_evidence_blocks,
            max_block_chars=args.max_block_chars,
            gold_first=not args.preserve_evidence_order,
        )
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

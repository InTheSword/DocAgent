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
    select_gold_block,
)


def load_samples(path: Path) -> list[DocAgentSample]:
    return [DocAgentSample.from_dict(record) for record in read_jsonl(path)]


def build_grpo_record(sample: DocAgentSample) -> dict[str, Any]:
    gold_block = select_gold_block(sample)
    gold_location = build_location_target(gold_block) if gold_block else {}
    user_content = (
        f"Question:\n{sample.question}\n\n"
        f"Answer type: {sample.answer_type}\n\n"
        f"Evidence:\n{format_evidence(sample.evidence)}\n\n"
        "Required output: only one JSON object with answer, evidence_location, evidence, reason. "
        "evidence_location must be an object copied from an evidence header."
    )
    return {
        "id": sample.qid,
        "source": sample.source,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "gold_answer": normalize_answer(sample.answer),
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
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    samples = [
        sample
        for sample in load_samples(ROOT / args.input)
        if sample.verifiable and sample.answer_type in {"extractive", "numeric", "boolean", "choice", "visual"}
    ]
    if args.limit is not None:
        samples = samples[: args.limit]
    records = [build_grpo_record(sample) for sample in samples]
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

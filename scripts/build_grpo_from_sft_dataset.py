from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.answer_contract import primary_location_from_output


def assistant_target(record: dict[str, Any]) -> dict[str, Any]:
    messages = record.get("messages") or []
    if not messages or messages[-1].get("role") != "assistant":
        raise ValueError(f"missing assistant target for record {record.get('id')}")
    parsed = json.loads(messages[-1].get("content") or "{}")
    if not isinstance(parsed, dict):
        raise ValueError(f"assistant target is not an object for record {record.get('id')}")
    return parsed


def infer_answer_type(messages: list[dict[str, Any]]) -> str:
    for message in messages:
        if message.get("role") != "user":
            continue
        match = re.search(
            r"(?:Answer type:|## Answer Type\s*)\s*([A-Za-z_-]+)",
            str(message.get("content") or ""),
            re.IGNORECASE,
        )
        if match:
            return match.group(1)
    return "extractive"


def convert_record(record: dict[str, Any]) -> dict[str, Any]:
    messages = record.get("messages") or []
    target = assistant_target(record)
    prompt_messages = [dict(message) for message in messages if message.get("role") != "assistant"]
    return {
        "id": record.get("id"),
        "source": record.get("source"),
        "messages": prompt_messages,
        "gold_answer": target.get("answer", ""),
        "gold_location": primary_location_from_output(target),
        "answer_type": infer_answer_type(prompt_messages),
        "reward_schema": ["format_reward", "answer_reward", "location_reward"],
        "metadata": {
            "source_dataset": "sft",
            "source_record_id": record.get("id"),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    records = read_jsonl(ROOT / args.input)
    if args.limit is not None:
        records = records[: args.limit]
    converted = [convert_record(record) for record in records]
    write_jsonl(ROOT / args.output, converted)
    print(
        json.dumps(
            {
                "input": args.input,
                "output": args.output,
                "num_records": len(converted),
                "sources": sorted({str(record.get("source")) for record in converted}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

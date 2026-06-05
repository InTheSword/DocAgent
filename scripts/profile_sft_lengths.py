from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl


def percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    index = min(int((len(values) - 1) * ratio), len(values) - 1)
    return sorted(values)[index]


def render_messages(tokenizer: Any, messages: list[dict[str, Any]]) -> str:
    try:
        return tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=False)
    except Exception:
        return "\n".join(f"{message.get('role', '')}: {message.get('content', '')}" for message in messages)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--model", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--thresholds", default="1024,2048,3072,4096")
    args = parser.parse_args()

    from transformers import AutoTokenizer

    records = read_jsonl(ROOT / args.input)
    if args.limit is not None:
        records = records[: args.limit]
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True, trust_remote_code=True)

    lengths = []
    for record in records:
        messages = record.get("messages") or []
        text = render_messages(tokenizer, messages)
        lengths.append(len(tokenizer(text, add_special_tokens=False)["input_ids"]))

    thresholds = [int(item) for item in args.thresholds.split(",") if item.strip()]
    summary = {
        "input": args.input,
        "model": args.model,
        "num_records": len(lengths),
        "token_length": {
            "min": min(lengths) if lengths else 0,
            "mean": statistics.mean(lengths) if lengths else 0,
            "p50": percentile(lengths, 0.50),
            "p90": percentile(lengths, 0.90),
            "p95": percentile(lengths, 0.95),
            "p99": percentile(lengths, 0.99),
            "max": max(lengths) if lengths else 0,
        },
        "over_threshold_counts": {str(threshold): sum(length > threshold for length in lengths) for threshold in thresholds},
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

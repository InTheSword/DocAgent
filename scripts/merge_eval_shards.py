from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "num_samples": 0,
            "json_pass_rate": 0.0,
            "schema_pass_rate": 0.0,
            "thinking_rate": 0.0,
            "answer_em": 0.0,
            "answer_f1": 0.0,
            "answer_score": 0.0,
            "location_accuracy": 0.0,
            "mean_reward": 0.0,
        }
    n = len(rows)
    return {
        "num_samples": n,
        "json_pass_rate": sum(row["metrics"]["json_ok"] for row in rows) / n,
        "schema_pass_rate": sum(row["metrics"]["schema_ok"] for row in rows) / n,
        "thinking_rate": sum(row["metrics"]["has_thinking"] for row in rows) / n,
        "answer_em": sum(row["metrics"]["answer_em"] for row in rows) / n,
        "answer_f1": sum(row["metrics"]["answer_f1"] for row in rows) / n,
        "answer_score": sum(row["metrics"].get("answer_score", 0.0) for row in rows) / n,
        "location_accuracy": sum(row["metrics"]["location_ok"] for row in rows) / n,
        "mean_reward": sum(row["metrics"]["reward"] for row in rows) / n,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", nargs="+", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--adapter", required=True)
    parser.add_argument("--input-name", required=True)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for input_name in args.inputs:
        rows.extend(read_jsonl(ROOT / input_name))

    rows.sort(key=lambda row: str(row.get("id", "")))
    write_jsonl(ROOT / args.output, rows)

    summary = {
        "model": args.model,
        "adapter": args.adapter,
        "input": args.input_name,
        "output": args.output,
        **summarize(rows),
    }
    summary_path = ROOT / args.summary_output
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

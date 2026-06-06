from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.eval_sft_checkpoint import evaluate_prediction, summarize


def recompute_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    recomputed: list[dict[str, Any]] = []
    for record in records:
        row = dict(record)
        previous_metrics = row.get("metrics") or {}
        prediction = row.get("prediction")
        metrics = evaluate_prediction(
            prediction if isinstance(prediction, dict) else None,
            row.get("gold") or {},
            str(row.get("answer_type") or "extractive"),
        )
        metrics["has_thinking"] = bool(previous_metrics.get("has_thinking", False))
        row["metrics"] = metrics
        recomputed.append(row)
    return recomputed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-output", required=True)
    parser.add_argument("--summary-template", default=None)
    args = parser.parse_args()

    rows = recompute_records(read_jsonl(ROOT / args.input))
    write_jsonl(ROOT / args.output, rows)

    summary: dict[str, Any] = {}
    if args.summary_template:
        template_path = ROOT / args.summary_template
        if template_path.is_file():
            summary.update(json.loads(template_path.read_text(encoding="utf-8")))
    summary["output"] = args.output
    summary.update(summarize(rows))

    summary_path = ROOT / args.summary_output
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

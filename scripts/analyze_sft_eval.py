from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl
from docagent.workflow.answer_contract import primary_location_from_output


def as_location_type(value: Any) -> str:
    if isinstance(value, dict):
        return "object"
    if value is None:
        return "missing"
    return type(value).__name__


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_answer_type: dict[str, Counter[str]] = defaultdict(Counter)
    location_types: Counter[str] = Counter()
    failure_counts: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in records:
        metrics = record.get("metrics") or {}
        answer_type = str(record.get("answer_type") or "unknown")
        prediction = record.get("prediction") or {}
        pred_location = primary_location_from_output(prediction)
        gold_location = primary_location_from_output((record.get("gold") or {}))
        location_types[as_location_type(pred_location)] += 1

        for key in ("json_ok", "schema_ok", "answer_em", "location_ok"):
            ok = bool(metrics.get(key))
            by_answer_type[answer_type][f"{key}:{ok}"] += 1
            if not ok:
                failure_counts[key] += 1
                if len(examples[key]) < 3:
                    examples[key].append(
                        {
                            "id": record.get("id"),
                            "answer_type": answer_type,
                            "gold_answer": (record.get("gold") or {}).get("answer"),
                            "pred_answer": prediction.get("answer"),
                            "gold_location": gold_location,
                            "pred_location": pred_location,
                            "generated": record.get("generated", "")[:800],
                        }
                    )

    return {
        "num_records": len(records),
        "location_value_types": dict(location_types),
        "failure_counts": dict(failure_counts),
        "by_answer_type": {key: dict(value) for key, value in by_answer_type.items()},
        "examples": examples,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    records = read_jsonl(ROOT / args.input)
    report = summarize(records)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

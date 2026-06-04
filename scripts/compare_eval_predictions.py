from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl


def score(record: dict[str, Any]) -> float:
    metrics = record.get("metrics") or {}
    return float(metrics.get("reward", 0.0))


def answer_ok(record: dict[str, Any]) -> bool:
    metrics = record.get("metrics") or {}
    return bool(metrics.get("answer_em"))


def compact_record(record: dict[str, Any], baseline_record: dict[str, Any] | None = None) -> dict[str, Any]:
    prediction = record.get("prediction") or {}
    gold = record.get("gold") or {}
    result = {
        "id": record.get("id"),
        "answer_type": record.get("answer_type"),
        "gold_answer": gold.get("answer"),
        "pred_answer": prediction.get("answer"),
        "reward": score(record),
        "answer_em": answer_ok(record),
    }
    if baseline_record is not None:
        baseline_prediction = baseline_record.get("prediction") or {}
        result["baseline_pred_answer"] = baseline_prediction.get("answer")
        result["baseline_reward"] = score(baseline_record)
        result["baseline_answer_em"] = answer_ok(baseline_record)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", required=True)
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--max-examples", type=int, default=5)
    args = parser.parse_args()

    baseline_rows = {str(row.get("id")): row for row in read_jsonl(ROOT / args.baseline)}
    candidate_rows = {str(row.get("id")): row for row in read_jsonl(ROOT / args.candidate)}
    common_ids = sorted(set(baseline_rows) & set(candidate_rows))

    improved: list[dict[str, Any]] = []
    regressed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    for row_id in common_ids:
        baseline = baseline_rows[row_id]
        candidate = candidate_rows[row_id]
        baseline_score = score(baseline)
        candidate_score = score(candidate)
        if candidate_score > baseline_score:
            improved.append(compact_record(candidate, baseline))
        elif candidate_score < baseline_score:
            regressed.append(compact_record(candidate, baseline))
        if (candidate.get("prediction") or {}).get("answer") != (baseline.get("prediction") or {}).get("answer"):
            changed.append(compact_record(candidate, baseline))

    report = {
        "baseline": args.baseline,
        "candidate": args.candidate,
        "num_common": len(common_ids),
        "reward_delta_sum": sum(score(candidate_rows[row_id]) - score(baseline_rows[row_id]) for row_id in common_ids),
        "improved_count": len(improved),
        "regressed_count": len(regressed),
        "changed_answer_count": len(changed),
        "improved_examples": improved[: args.max_examples],
        "regressed_examples": regressed[: args.max_examples],
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

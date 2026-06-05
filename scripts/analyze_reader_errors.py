from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl


def normalize_text(text: Any) -> str:
    text = str(text or "").lower().strip()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff.%+-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def compact_text(text: Any) -> str:
    return re.sub(r"[^a-z0-9\u4e00-\u9fff.%+-]+", "", str(text or "").lower())


def user_content(record: dict[str, Any] | None) -> str:
    if not record:
        return ""
    return "\n".join(
        str(message.get("content") or "")
        for message in record.get("messages", [])
        if message.get("role") == "user"
    )


def extract_question(content: str) -> str:
    match = re.search(r"## Question\n(.*?)\n\n## Answer Type", content, flags=re.S)
    return match.group(1).strip() if match else ""


def question_buckets(question: str, gold_answer: Any) -> list[str]:
    lowered = question.lower()
    buckets: list[str] = []
    if re.search(r"\b(full form|stand for|abbreviation|acronym)\b", lowered):
        buckets.append("abbreviation")
    if re.search(r"\b(table|row|column|list|item|first|heading)\b", lowered):
        buckets.append("table_or_list")
    if re.search(r"\b(date|time|day|month|year|when)\b", lowered):
        buckets.append("date_or_time")
    if re.search(r"\b(amount|value|expense|expenses|cost|price|total|how much|how many|number|mg|percent)\b", lowered):
        buckets.append("numeric")
    if re.search(r"\b(who|whom|whose|name|person)\b", lowered):
        buckets.append("person")
    if re.search(r"\b(title|heading|form)\b", lowered):
        buckets.append("title_or_form")
    if "page number" in lowered:
        buckets.append("page_number")
    if not buckets:
        gold_text = str(gold_answer or "")
        if re.search(r"\d", gold_text):
            buckets.append("numeric")
        else:
            buckets.append("other")
    return buckets


def f1_bucket(value: float) -> str:
    if value == 0:
        return "f1=0"
    if value < 0.5:
        return "0<f1<0.5"
    if value < 0.9:
        return "0.5<=f1<0.9"
    return "f1>=0.9"


def compact_example(record: dict[str, Any], dataset_record: dict[str, Any] | None) -> dict[str, Any]:
    prediction = record.get("prediction") or {}
    gold = record.get("gold") or {}
    content = user_content(dataset_record)
    return {
        "id": record.get("id"),
        "question": extract_question(content),
        "gold_answer": gold.get("answer"),
        "pred_answer": prediction.get("answer"),
        "answer_f1": (record.get("metrics") or {}).get("answer_f1"),
        "gold_location": gold.get("evidence_location"),
        "pred_location": prediction.get("evidence_location"),
        "pred_evidence": str(prediction.get("evidence") or "")[:300],
    }


def summarize(
    eval_records: list[dict[str, Any]],
    dataset_records: dict[str, dict[str, Any]],
    max_examples: int,
) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    f1_counts: Counter[str] = Counter()
    question_type_counts: Counter[str] = Counter()
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for record in eval_records:
        metrics = record.get("metrics") or {}
        prediction = record.get("prediction") or {}
        gold = record.get("gold") or {}
        row_id = str(record.get("id"))
        dataset_record = dataset_records.get(row_id)
        content = user_content(dataset_record)
        question = extract_question(content)
        gold_answer = gold.get("answer")
        pred_answer = prediction.get("answer")

        if not metrics.get("schema_ok"):
            counters["schema_bad"] += 1
            continue
        if metrics.get("answer_em") and metrics.get("location_ok"):
            counters["answer_ok_location_ok"] += 1
            continue
        if metrics.get("answer_em") and not metrics.get("location_ok"):
            counters["answer_ok_location_bad"] += 1
            continue
        if not metrics.get("answer_em") and not metrics.get("location_ok"):
            counters["answer_bad_location_bad"] += 1
            continue

        counters["answer_bad_location_ok"] += 1
        f1_counts[f1_bucket(float(metrics.get("answer_f1", 0.0)))] += 1
        counters["gold_in_prompt"] += bool(normalize_text(gold_answer) and normalize_text(gold_answer) in normalize_text(content))
        counters["pred_in_prompt"] += bool(normalize_text(pred_answer) and normalize_text(pred_answer) in normalize_text(content))
        counters["compact_equal"] += compact_text(gold_answer) == compact_text(pred_answer)
        for bucket in question_buckets(question, gold_answer):
            question_type_counts[bucket] += 1
            if len(examples[bucket]) < max_examples:
                examples[bucket].append(compact_example(record, dataset_record))

    return {
        "num_records": len(eval_records),
        "outcome_counts": dict(counters),
        "answer_bad_location_ok_f1": dict(f1_counts),
        "answer_bad_location_ok_question_types": dict(question_type_counts),
        "examples": dict(examples),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--max-examples", type=int, default=5)
    args = parser.parse_args()

    eval_records = read_jsonl(ROOT / args.eval)
    dataset_records = {str(record.get("id")): record for record in read_jsonl(ROOT / args.dataset)}
    report = summarize(eval_records, dataset_records, args.max_examples)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.output:
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

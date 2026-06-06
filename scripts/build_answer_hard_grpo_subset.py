from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.analyze_reader_errors import (
    compact_text,
    extract_question,
    f1_bucket,
    question_buckets,
    user_content,
)
from scripts.build_grpo_from_sft_dataset import convert_record


def numeric_like(text: Any) -> bool:
    return bool(re.search(r"\d", str(text or "")))


def answer_issue_type(gold_answer: Any, pred_answer: Any, answer_f1: float) -> str:
    gold_compact = compact_text(gold_answer)
    pred_compact = compact_text(pred_answer)
    gold_tokens = str(gold_answer or "").split()
    pred_tokens = str(pred_answer or "").split()
    if numeric_like(gold_answer) and numeric_like(pred_answer) and gold_compact != pred_compact:
        return "numeric_mismatch"
    if gold_compact and gold_compact in pred_compact and len(pred_tokens) > len(gold_tokens):
        return "over_extracted"
    if pred_compact and pred_compact in gold_compact and len(pred_tokens) < len(gold_tokens):
        return "under_extracted"
    if answer_f1 == 0:
        return "no_overlap"
    if answer_f1 >= 0.8:
        return "near_miss"
    return "partial_overlap"


def is_answer_hard(eval_record: dict[str, Any], max_answer_f1: float) -> bool:
    metrics = eval_record.get("metrics") or {}
    return (
        bool(metrics.get("schema_ok"))
        and bool(metrics.get("location_ok"))
        and not bool(metrics.get("answer_em"))
        and float(metrics.get("answer_f1", 0.0)) <= max_answer_f1
    )


def hard_case_metadata(eval_record: dict[str, Any], grpo_record: dict[str, Any]) -> dict[str, Any]:
    metrics = eval_record.get("metrics") or {}
    gold = eval_record.get("gold") or {}
    prediction = eval_record.get("prediction") or {}
    answer_f1 = float(metrics.get("answer_f1", 0.0))
    question = extract_question(user_content(grpo_record))
    buckets = question_buckets(question, gold.get("answer"))
    return {
        "source_eval_id": eval_record.get("id"),
        "answer_f1": answer_f1,
        "f1_bucket": f1_bucket(answer_f1),
        "question_types": buckets,
        "issue_type": answer_issue_type(gold.get("answer"), prediction.get("answer"), answer_f1),
        "pred_answer": prediction.get("answer"),
    }


def build_subset(
    eval_records: list[dict[str, Any]],
    grpo_records: list[dict[str, Any]],
    sft_records: list[dict[str, Any]] | None,
    limit: int | None,
    max_answer_f1: float,
    max_per_question_type: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grpo_by_id = {str(record.get("id")): record for record in grpo_records}
    sft_by_id = {str(record.get("id")): record for record in sft_records or []}
    candidates: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    missing_ids: list[str] = []
    source_counts: Counter[str] = Counter()

    for eval_record in eval_records:
        if not is_answer_hard(eval_record, max_answer_f1=max_answer_f1):
            continue
        row_id = str(eval_record.get("id"))
        grpo_record = grpo_by_id.get(row_id)
        if grpo_record is None:
            sft_record = sft_by_id.get(row_id)
            if sft_record is None:
                missing_ids.append(row_id)
                continue
            grpo_record = convert_record(sft_record)
            source_counts["sft_converted"] += 1
        else:
            source_counts["grpo"] += 1
        metadata = hard_case_metadata(eval_record, grpo_record)
        candidates.append((eval_record, grpo_record, metadata))

    candidates.sort(key=lambda item: (item[2]["answer_f1"], str(item[1].get("id"))))
    selected: list[dict[str, Any]] = []
    question_type_counts: Counter[str] = Counter()
    skipped_by_question_cap = 0

    for _, grpo_record, hard_metadata in candidates:
        primary_type = hard_metadata["question_types"][0] if hard_metadata["question_types"] else "other"
        if max_per_question_type > 0 and question_type_counts[primary_type] >= max_per_question_type:
            skipped_by_question_cap += 1
            continue
        output_record = dict(grpo_record)
        metadata = dict(output_record.get("metadata") or {})
        metadata["hard_case"] = hard_metadata
        output_record["metadata"] = metadata
        selected.append(output_record)
        question_type_counts[primary_type] += 1
        if limit is not None and len(selected) >= limit:
            break

    f1_counts: Counter[str] = Counter()
    issue_counts: Counter[str] = Counter()
    all_question_type_counts: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []
    for eval_record, grpo_record, metadata in candidates:
        f1_counts[metadata["f1_bucket"]] += 1
        issue_counts[metadata["issue_type"]] += 1
        for bucket in metadata["question_types"]:
            all_question_type_counts[bucket] += 1
        if len(examples) < 10:
            gold = eval_record.get("gold") or {}
            prediction = eval_record.get("prediction") or {}
            examples.append(
                {
                    "id": eval_record.get("id"),
                    "question": extract_question(user_content(grpo_record)),
                    "gold_answer": gold.get("answer"),
                    "pred_answer": prediction.get("answer"),
                    "answer_f1": metadata["answer_f1"],
                    "issue_type": metadata["issue_type"],
                    "question_types": metadata["question_types"],
                }
            )

    report = {
        "num_eval_records": len(eval_records),
        "num_grpo_records": len(grpo_records),
        "num_sft_records": len(sft_records or []),
        "num_answer_hard_candidates": len(candidates),
        "num_selected": len(selected),
        "max_answer_f1": max_answer_f1,
        "max_per_question_type": max_per_question_type,
        "skipped_missing_grpo": len(missing_ids),
        "skipped_by_question_cap": skipped_by_question_cap,
        "candidate_source_counts": dict(source_counts),
        "candidate_f1_buckets": dict(f1_counts),
        "candidate_issue_types": dict(issue_counts),
        "candidate_question_types": dict(all_question_type_counts),
        "selected_question_types": dict(question_type_counts),
        "missing_grpo_ids": missing_ids[:20],
        "examples": examples,
    }
    return selected, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", required=True)
    parser.add_argument("--grpo", required=True)
    parser.add_argument("--sft", default=None)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report-output", default=None)
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--max-answer-f1", type=float, default=0.999)
    parser.add_argument("--max-per-question-type", type=int, default=0)
    args = parser.parse_args()

    eval_records = read_jsonl(ROOT / args.eval)
    grpo_records = read_jsonl(ROOT / args.grpo)
    sft_records = read_jsonl(ROOT / args.sft) if args.sft else None
    selected, report = build_subset(
        eval_records,
        grpo_records,
        sft_records,
        limit=args.limit,
        max_answer_f1=args.max_answer_f1,
        max_per_question_type=args.max_per_question_type,
    )
    write_jsonl(ROOT / args.output, selected)
    report = {
        "eval": args.eval,
        "grpo": args.grpo,
        "sft": args.sft,
        "output": args.output,
        **report,
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.report_output:
        output = ROOT / args.report_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

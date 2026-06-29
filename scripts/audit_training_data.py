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

from docagent.eval.answer_metrics import normalize_text
from docagent.utils.jsonl import read_jsonl
from docagent.workflow.answer_contract import primary_location_from_output


def get_messages(record: dict[str, Any]) -> list[dict[str, Any]]:
    messages = record.get("messages")
    return messages if isinstance(messages, list) else []


def get_user_content(record: dict[str, Any]) -> str:
    for message in get_messages(record):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def infer_answer_type(record: dict[str, Any]) -> str:
    answer_type = record.get("answer_type")
    if answer_type:
        return str(answer_type)
    match = re.search(r"(?:Answer type:|## Answer Type\s*)\s*([A-Za-z_-]+)", get_user_content(record), re.IGNORECASE)
    if match:
        return match.group(1)
    return "unknown"


def get_assistant_target(record: dict[str, Any]) -> dict[str, Any] | None:
    messages = get_messages(record)
    if not messages or messages[-1].get("role") != "assistant":
        return None
    try:
        parsed = json.loads(messages[-1].get("content") or "{}")
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def get_target(record: dict[str, Any]) -> tuple[dict[str, Any], str]:
    assistant = get_assistant_target(record)
    if assistant is not None:
        return assistant, "assistant"
    return {
        "answer": record.get("gold_answer"),
        "evidence_location": record.get("gold_location"),
        "evidence": "",
    }, "gold"


def location_ids(location: Any) -> list[str]:
    if not isinstance(location, dict):
        return []
    ids = []
    for key in ("block_id", "table_id", "image_id", "page_id"):
        value = location.get(key)
        if value is not None:
            ids.append(str(value))
    return ids


def target_evidence_text(target: dict[str, Any]) -> str:
    legacy = str(target.get("evidence") or "")
    if legacy:
        return legacy
    evidence_used = target.get("evidence_used")
    if isinstance(evidence_used, list):
        previews = [
            str(item.get("text_preview") or "")
            for item in evidence_used
            if isinstance(item, dict) and str(item.get("text_preview") or "").strip()
        ]
        return " ".join(previews)
    if isinstance(evidence_used, str):
        return evidence_used
    return ""


def answer_in_text(answer: Any, text: Any) -> bool:
    answer_norm = normalize_text(str(answer or ""))
    text_norm = normalize_text(str(text or ""))
    return bool(answer_norm and answer_norm in text_norm)


def is_midword_truncated(text: str, max_chars: int) -> bool:
    if len(text) < max_chars:
        return False
    return bool(text and text[-1].isalnum())


def audit_record(record: dict[str, Any], max_evidence_chars: int) -> list[str]:
    issues: list[str] = []
    user_content = get_user_content(record)
    target, target_source = get_target(record)

    if target_source == "assistant" and get_assistant_target(record) is None:
        issues.append("assistant_target_invalid_json")

    location = primary_location_from_output(target)
    if not isinstance(location, dict):
        issues.append("location_not_object")
    else:
        ids = location_ids(location)
        if ids and not any(item in user_content for item in ids):
            issues.append("location_not_in_prompt")

    evidence = target_evidence_text(target)
    if target_source == "assistant":
        if len(evidence) > max_evidence_chars:
            issues.append("evidence_too_long")
        if is_midword_truncated(evidence, max_evidence_chars):
            issues.append("evidence_may_be_midword_truncated")

    answer_type = infer_answer_type(record)
    answer = target.get("answer")
    if target_source == "assistant" and answer_type == "extractive" and evidence:
        if not answer_in_text(answer, evidence):
            issues.append("extractive_answer_not_in_target_evidence")

    if not user_content:
        issues.append("missing_user_prompt")

    return issues


def summarize(records: list[dict[str, Any]], max_evidence_chars: int) -> dict[str, Any]:
    issue_counts: Counter[str] = Counter()
    by_answer_type: dict[str, Counter[str]] = defaultdict(Counter)
    examples: dict[str, list[dict[str, Any]]] = defaultdict(list)
    clean = 0

    for record in records:
        issues = audit_record(record, max_evidence_chars)
        answer_type = infer_answer_type(record)
        if not issues:
            clean += 1
            by_answer_type[answer_type]["clean"] += 1
            continue
        for issue in issues:
            issue_counts[issue] += 1
            by_answer_type[answer_type][issue] += 1
            if len(examples[issue]) < 3:
                target, target_source = get_target(record)
                examples[issue].append(
                    {
                        "id": record.get("id"),
                        "answer_type": answer_type,
                        "target_source": target_source,
                        "answer": target.get("answer"),
                        "location": primary_location_from_output(target),
                        "evidence": target_evidence_text(target)[:500],
                    }
                )

    total = len(records)
    return {
        "num_records": total,
        "clean_records": clean,
        "clean_rate": clean / total if total else 0.0,
        "issue_counts": dict(issue_counts),
        "by_answer_type": {key: dict(value) for key, value in by_answer_type.items()},
        "examples": examples,
    }


def compact_report(report: dict[str, Any]) -> dict[str, Any]:
    return {
        "num_records": report["num_records"],
        "clean_records": report["clean_records"],
        "clean_rate": report["clean_rate"],
        "issue_counts": report["issue_counts"],
        "by_answer_type": report["by_answer_type"],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--max-evidence-chars", type=int, default=300)
    parser.add_argument("--print-mode", choices=["full", "summary", "none"], default="full")
    args = parser.parse_args()

    records = read_jsonl(ROOT / args.input)
    report = summarize(records, args.max_evidence_chars)
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.print_mode == "full":
        print(text)
    elif args.print_mode == "summary":
        print(json.dumps(compact_report(report), ensure_ascii=False, indent=2))
    if args.output:
        output = ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()

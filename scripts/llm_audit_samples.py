from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.schemas import DocAgentSample
from docagent.utils.jsonl import read_jsonl, write_jsonl


SYSTEM_PROMPT = (
    "You are a strict data quality auditor for a document QA training dataset. "
    "Judge whether the answer is directly supported by the provided evidence. "
    "Return only valid JSON."
)


def compact_sample(sample: DocAgentSample, max_evidence_chars: int) -> dict[str, Any]:
    return {
        "qid": sample.qid,
        "source": sample.source,
        "doc_id": sample.doc_id,
        "question": sample.question,
        "answer": sample.answer,
        "answer_type": sample.answer_type,
        "evidence_blocks": [
            {
                "block_id": block.block_id,
                "block_type": block.block_type,
                "location": block.location.to_dict(),
                "text": block.retrieval_text[:max_evidence_chars],
            }
            for block in sample.evidence
        ],
    }


def build_user_prompt(sample: DocAgentSample, max_evidence_chars: int) -> str:
    payload = compact_sample(sample, max_evidence_chars)
    schema = {
        "verdict": "keep | repair | drop",
        "confidence": "0.0-1.0",
        "answer": "corrected answer if repair, otherwise original answer",
        "answer_type": "extractive | numeric | visual | boolean | choice | refusal | summary",
        "gold_block_ids": ["supporting block id list"],
        "evidence": "short supporting span copied from evidence, <=300 chars",
        "issues": ["short issue tags"],
        "reason": "one short sentence",
    }
    return (
        "Audit this DocAgent training sample.\n\n"
        "Rules:\n"
        "1. keep only if the answer is directly supported by evidence.\n"
        "2. repair only if a corrected answer and supporting block can be inferred from evidence.\n"
        "3. drop if evidence is missing, OCR is unusable, the question needs unseen visual content, "
        "or the answer cannot be verified.\n"
        "4. For numeric answers, normalize commas, units, and percentages when clearly equivalent.\n"
        "5. Do not invent missing evidence.\n\n"
        f"Required JSON schema:\n{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"Sample:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


def build_task(sample: DocAgentSample, max_evidence_chars: int) -> dict[str, Any]:
    return {
        "id": sample.qid,
        "source": sample.source,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(sample, max_evidence_chars)},
        ],
        "sample": sample.to_dict(),
    }


def parse_json_object(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def call_openai_compatible(messages: list[dict[str, str]], model: str, base_url: str, api_key: str, timeout: int) -> str:
    url = base_url.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "response_format": {"type": "json_object"},
        },
        ensure_ascii=False,
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str(payload["choices"][0]["message"]["content"])


def apply_decision(sample_data: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any] | None:
    verdict = str(decision.get("verdict") or "").lower()
    if verdict == "drop":
        return None
    sample = DocAgentSample.from_dict(sample_data)
    repaired = sample.to_dict()
    if verdict == "repair":
        answer = decision.get("answer")
        answer_type = decision.get("answer_type")
        gold_block_ids = decision.get("gold_block_ids")
        if answer:
            repaired["answer"] = answer
        if answer_type:
            repaired["answer_type"] = answer_type
        if isinstance(gold_block_ids, list):
            repaired.setdefault("metadata", {})["gold_block_ids"] = [str(item) for item in gold_block_ids]
    repaired.setdefault("metadata", {})["llm_audit"] = {
        "verdict": verdict or "unknown",
        "confidence": decision.get("confidence"),
        "issues": decision.get("issues") or [],
        "reason": decision.get("reason") or "",
        "evidence": decision.get("evidence") or "",
    }
    return repaired


def summarize(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    issues: dict[str, int] = {}
    for item in decisions:
        verdict = str((item.get("decision") or {}).get("verdict") or "unknown").lower()
        counts[verdict] = counts.get(verdict, 0) + 1
        for issue in (item.get("decision") or {}).get("issues") or []:
            key = str(issue)
            issues[key] = issues.get(key, 0) + 1
    return {"num_decisions": len(decisions), "verdict_counts": counts, "issue_counts": issues}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--tasks-output", required=True)
    parser.add_argument("--audited-output", default=None)
    parser.add_argument("--decisions-output", default=None)
    parser.add_argument("--report-output", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-evidence-chars", type=int, default=1800)
    parser.add_argument("--mode", choices=["export", "api"], default="export")
    parser.add_argument("--model", default=os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"))
    parser.add_argument("--base-url", default=os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1"))
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY"))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--sleep", type=float, default=0.0)
    args = parser.parse_args()

    rows = read_jsonl(ROOT / args.input)
    if args.limit is not None:
        rows = rows[: args.limit]
    samples = [DocAgentSample.from_dict(row) for row in rows]
    tasks = [build_task(sample, args.max_evidence_chars) for sample in samples]
    write_jsonl(ROOT / args.tasks_output, tasks)

    if args.mode == "export":
        print(
            json.dumps(
                {
                    "mode": "export",
                    "input": args.input,
                    "tasks_output": args.tasks_output,
                    "num_tasks": len(tasks),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return

    if not args.api_key:
        raise ValueError("OPENAI_API_KEY or --api-key is required for --mode api")

    decisions = []
    audited = []
    for task in tasks:
        try:
            content = call_openai_compatible(task["messages"], args.model, args.base_url, args.api_key, args.timeout)
            decision = parse_json_object(content) or {"verdict": "drop", "issues": ["invalid_llm_json"], "reason": content[:300]}
        except (urllib.error.URLError, TimeoutError, KeyError, json.JSONDecodeError) as exc:
            decision = {"verdict": "drop", "issues": ["api_error"], "reason": str(exc)}
        decisions.append({"id": task["id"], "source": task["source"], "decision": decision})
        repaired = apply_decision(task["sample"], decision)
        if repaired is not None:
            audited.append(repaired)
        if args.sleep:
            time.sleep(args.sleep)

    if args.decisions_output:
        write_jsonl(ROOT / args.decisions_output, decisions)
    if args.audited_output:
        write_jsonl(ROOT / args.audited_output, audited)
    report = {
        "mode": "api",
        "input": args.input,
        "tasks_output": args.tasks_output,
        "audited_output": args.audited_output,
        "decisions_output": args.decisions_output,
        "num_input": len(samples),
        "num_audited": len(audited),
        **summarize(decisions),
    }
    if args.report_output:
        output = ROOT / args.report_output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

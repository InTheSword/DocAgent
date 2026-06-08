from __future__ import annotations

import json
import re
from typing import Any

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation


QUESTION_RE = re.compile(r"## Question\s*\n(?P<value>.*?)(?:\n\n##|\Z)", re.DOTALL)
ANSWER_TYPE_RE = re.compile(r"## Answer Type\s*\n(?P<value>[A-Za-z_-]+)")
EVIDENCE_RE = re.compile(
    r"\[(?P<block_type>[A-Z_]+)\s+\|\s*(?P<header>.*?)location=(?P<location>\{.*?\})\]\n(?P<text>.*?)(?=\n\n\[[A-Z_]+\s+\||\n\n## Output Contract|\Z)",
    re.DOTALL,
)


def user_content(record: dict[str, Any]) -> str:
    for message in record.get("messages") or []:
        if message.get("role") == "user":
            return str(message.get("content") or "")
    return ""


def assistant_target(record: dict[str, Any]) -> dict[str, Any] | None:
    messages = record.get("messages") or []
    if messages and messages[-1].get("role") == "assistant":
        try:
            parsed = json.loads(messages[-1].get("content") or "{}")
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    if "gold_answer" in record:
        return {
            "answer": record.get("gold_answer"),
            "evidence_location": record.get("gold_location") or {},
        }
    return None


def extract_question(content: str) -> str:
    match = QUESTION_RE.search(content)
    return match.group("value").strip() if match else ""


def extract_answer_type(content: str) -> str:
    match = ANSWER_TYPE_RE.search(content)
    return match.group("value").strip() if match else "extractive"


def _header_value(header: str, key: str) -> str | None:
    match = re.search(rf"{re.escape(key)}=([^|]+)", header)
    return match.group(1).strip() if match else None


def evidence_blocks_from_prompt(content: str, fallback_doc_id: str = "") -> list[EvidenceBlock]:
    blocks: list[EvidenceBlock] = []
    for index, match in enumerate(EVIDENCE_RE.finditer(content), start=1):
        header = match.group("header")
        block_type = match.group("block_type").lower()
        block_id = (_header_value(header, "block_id") or f"prompt_block_{index}").strip()
        doc_id = (_header_value(header, "doc_id") or fallback_doc_id or "prompt_doc").strip()
        try:
            location_data = json.loads(match.group("location"))
        except json.JSONDecodeError:
            location_data = {"block_id": block_id}
        location_data.setdefault("block_id", block_id)
        page = location_data.get("page")
        blocks.append(
            EvidenceBlock(
                doc_id=doc_id,
                page_id=page if isinstance(page, int) else None,
                block_id=block_id,
                block_type=block_type if block_type in {"text", "table", "image", "figure", "visual_summary", "page"} else "text",
                text=match.group("text").strip(),
                location=EvidenceLocation.from_dict(location_data),
            )
        )
    return blocks


def workflow_input_from_record(record: dict[str, Any]) -> dict[str, Any]:
    if "evidence" in record and "question" in record:
        sample = DocAgentSample.from_dict(record)
        return {
            "qid": sample.qid,
            "doc_id": sample.doc_id,
            "question": sample.question,
            "answer_type": sample.answer_type,
            "blocks": sample.evidence,
            "gold": {"answer": sample.answer, "evidence_location": sample.evidence[0].location.to_dict() if sample.evidence else {}},
        }

    content = user_content(record)
    qid = str(record.get("id") or record.get("qid") or "")
    question = extract_question(content)
    answer_type = extract_answer_type(content)
    blocks = evidence_blocks_from_prompt(content, fallback_doc_id=str(record.get("doc_id") or ""))
    return {
        "qid": qid,
        "doc_id": blocks[0].doc_id if blocks else str(record.get("doc_id") or ""),
        "question": question,
        "answer_type": answer_type,
        "blocks": blocks,
        "gold": assistant_target(record),
    }

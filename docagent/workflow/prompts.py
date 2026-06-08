from __future__ import annotations

import json
import re
from typing import Any

from docagent.schemas import EvidenceBlock


SYSTEM_PROMPT = (
    "You are DocAgent, a document question-answering assistant. "
    "Use only the provided evidence candidates and tool results. "
    "Return exactly one valid JSON object. "
    "Do not output markdown, analysis, chain-of-thought, or <think> tags. "
    "If evidence is insufficient, return an explicit refusal answer."
)

EXTRACTION_RULES_TEXT = (
    "- Use only evidence text from the candidates; do not use outside knowledge or common expansions.\n"
    "- Match the exact question intent before selecting an answer span.\n"
    "- For tables, lists, and key-value blocks, first match the relevant row, column, label, or relation, then copy the value.\n"
    "- Do not answer with a neighboring entity, label, heading, total, or abbreviation unless the question asks for it."
)

OUTPUT_SCHEMA = {
    "answer": "short answer string copied or normalized from evidence",
    "evidence_location": {"page": 1, "block_id": "candidate_block_id"},
    "evidence": "minimal supporting span, compact row, or calculation inputs",
    "reason": "one sentence explaining why the evidence supports the answer",
}


def smart_truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    prefix = text[:limit]
    split_at = max(prefix.rfind(" "), prefix.rfind(";"), prefix.rfind(","))
    if split_at >= int(limit * 0.5):
        prefix = prefix[:split_at]
    return prefix.rstrip(" ,;:-")


def build_location_target(block: EvidenceBlock) -> dict[str, Any]:
    location = block.location.to_dict()
    location["block_id"] = block.block_id
    return location


def format_evidence_blocks(
    blocks: list[EvidenceBlock],
    *,
    max_chars_per_block: int = 1200,
    max_total_chars: int | None = 5000,
) -> str:
    parts: list[str] = []
    total_chars = 0
    for index, block in enumerate(blocks, start=1):
        location = build_location_target(block)
        header = (
            f"[{block.block_type.upper()} | evidence_index={index} | "
            f"doc_id={block.doc_id} | block_id={block.block_id} | "
            f"location={json.dumps(location, ensure_ascii=False)}]"
        )
        body = smart_truncate(block.retrieval_text, max_chars_per_block)
        item = f"{header}\n{body}"
        if max_total_chars is not None and total_chars + len(item) > max_total_chars:
            remaining = max_total_chars - total_chars
            if remaining <= len(header) + 20:
                break
            body = smart_truncate(body, remaining - len(header) - 1)
            item = f"{header}\n{body}"
        parts.append(item)
        total_chars += len(item)
    return "\n\n".join(parts)


def build_answer_messages(
    *,
    question: str,
    evidence_blocks: list[EvidenceBlock],
    tool_results: list[dict[str, Any]] | None = None,
    answer_type: str | None = None,
    append_no_think: bool = True,
    max_chars_per_block: int = 1200,
    max_total_chars: int | None = 5000,
) -> list[dict[str, str]]:
    output_schema = json.dumps(OUTPUT_SCHEMA, ensure_ascii=False)
    tool_text = json.dumps(tool_results or [], ensure_ascii=False, indent=2)
    user_content = (
        "## Task\n"
        "Answer the question from the evidence candidates and cite the exact supporting location.\n\n"
        "## Question\n"
        f"{question}\n\n"
        "## Answer Type\n"
        f"{answer_type or 'extractive'}\n\n"
        "## Evidence Candidates\n"
        f"{format_evidence_blocks(evidence_blocks, max_chars_per_block=max_chars_per_block, max_total_chars=max_total_chars)}\n\n"
        "## Tool Results\n"
        f"{tool_text}\n\n"
        "## Output Contract\n"
        f"Return JSON matching this schema: {output_schema}\n"
        "Rules:\n"
        f"{EXTRACTION_RULES_TEXT}\n"
        "- answer must be concise and grounded in the evidence.\n"
        "- evidence_location must be a JSON object copied from one evidence header.\n"
        "- evidence must be the shortest sufficient supporting span or compact table row, no more than 300 characters.\n"
        "- reason must explain the answer-source relation in one sentence."
    )
    if append_no_think:
        user_content = (
            f"{user_content}\n\n/no_think\n"
            "Return only one valid JSON object. Start with { and end with }."
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def fallback_chat_prompt(messages: list[dict[str, str]]) -> str:
    parts = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)

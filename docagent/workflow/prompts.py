from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from docagent.schemas import EvidenceBlock


PROMPT_VERSION = "docagent_answer_v1"
DEFAULT_TASK_TYPE = "local_fact_qa"

SYSTEM_PROMPT = (
    "You are DocAgent, a document question-answering assistant. "
    "Use only the provided evidence candidates. Return exactly one valid JSON object. "
    "Do not include markdown, chain-of-thought, analysis text, or <think> tags."
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


@dataclass(frozen=True)
class PromptBundle:
    messages: list[dict[str, str]]
    prompt_version: str
    task_type: str
    evidence_context: dict[str, Any]

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "prompt_version": self.prompt_version,
            "task_type": self.task_type,
            "selected_block_ids": self.evidence_context["selected_block_ids"],
            "dropped_block_ids": self.evidence_context["dropped_block_ids"],
            "evidence_context_hash": self.evidence_context["evidence_context_hash"],
            "truncation_applied": self.evidence_context["truncation_applied"],
            "evidence_count": len(self.evidence_context["evidence"]),
        }


def sha256_json(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def smart_truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    prefix = text[:limit]
    split_at = max(prefix.rfind(" "), prefix.rfind(";"), prefix.rfind(","))
    if split_at >= int(limit * 0.5):
        prefix = prefix[:split_at]
    return prefix.rstrip(" ,;:-")


def contains_answer(text: str, answer: str) -> bool:
    if not answer:
        return False
    compact = re.sub(r"\s+", " ", text).strip().lower()
    target = re.sub(r"\s+", " ", answer).strip().lower()
    return bool(target and target in compact)


def find_answer_span(text: str, answer: str) -> tuple[int, int] | None:
    answer = str(answer or "").strip()
    if not answer:
        return None
    direct = re.search(re.escape(answer), text, flags=re.IGNORECASE)
    if direct:
        return direct.start(), direct.end()
    answer_tokens = re.findall(r"[A-Za-z0-9\u4e00-\u9fff.%+-]+", answer.lower())
    if not answer_tokens:
        return None
    tokens: list[tuple[str, int, int]] = []
    for match in re.finditer(r"[A-Za-z0-9\u4e00-\u9fff.%+-]+", text):
        tokens.append((match.group(0).lower(), match.start(), match.end()))
    window = len(answer_tokens)
    for start_idx in range(0, len(tokens) - window + 1):
        if [item[0] for item in tokens[start_idx : start_idx + window]] == answer_tokens:
            return tokens[start_idx][1], tokens[start_idx + window - 1][2]
    return None


def centered_evidence_window(text: str, answer: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    span = find_answer_span(compact, answer)
    if span is None:
        return smart_truncate(compact, limit)
    start, end = span
    answer_len = max(end - start, 1)
    side_budget = max((limit - answer_len) // 2, 0)
    left = max(start - side_budget, 0)
    right = min(end + side_budget, len(compact))
    if right - left < limit:
        if left == 0:
            right = min(limit, len(compact))
        elif right == len(compact):
            left = max(0, len(compact) - limit)
    return compact[left:right].strip(" ,;:-")


def build_location_target(block: EvidenceBlock) -> dict[str, Any]:
    location = block.location.to_dict()
    location["block_id"] = block.block_id
    return location


def _context_location(block: EvidenceBlock) -> dict[str, Any]:
    location = block.location.to_dict()
    return {
        "page": location.get("page", block.page_id),
        "bbox": location.get("bbox"),
        "block_id": block.block_id,
        "table_id": location.get("table_id"),
        "image_id": location.get("image_id"),
        "sheet": location.get("sheet"),
        "cell_range": location.get("cell_range"),
        "slide": location.get("slide"),
        "section": location.get("section") or block.metadata.get("section_title"),
    }


def _context_block_type(block: EvidenceBlock) -> str:
    raw_type = str(block.metadata.get("raw_mineru_type") or "").lower()
    if raw_type == "chart":
        return "chart"
    return block.block_type


def _block_content(
    block: EvidenceBlock,
    *,
    max_chars: int,
    answer: str = "",
    gold_block_id: str | None = None,
) -> tuple[str, bool]:
    text = block.retrieval_text.strip()
    if gold_block_id and block.block_id == gold_block_id and answer and contains_answer(text, answer):
        content = centered_evidence_window(text, answer, max_chars)
    else:
        content = smart_truncate(text, max_chars)
    return content, len(content) < len(re.sub(r"\s+", " ", text).strip())


def build_evidence_context(
    *,
    question: str,
    evidence_blocks: list[EvidenceBlock],
    task_type: str = DEFAULT_TASK_TYPE,
    token_budget: int | None = None,
    max_chars_per_block: int = 1200,
    answer: str = "",
    gold_block_id: str | None = None,
) -> dict[str, Any]:
    evidence: list[dict[str, Any]] = []
    selected: list[str] = []
    dropped: list[str] = []
    total_chars = 0
    truncation_applied = False
    for rank, block in enumerate(evidence_blocks, start=1):
        if block.metadata.get("is_boilerplate") or block.metadata.get("exclude_from_retrieval"):
            dropped.append(block.block_id)
            continue
        raw_text = block.retrieval_text.strip()
        if not raw_text:
            dropped.append(block.block_id)
            continue
        remaining = None if token_budget is None else token_budget - total_chars
        if remaining is not None and remaining <= 0:
            dropped.append(block.block_id)
            truncation_applied = True
            continue
        limit = max_chars_per_block if remaining is None else min(max_chars_per_block, max(remaining, 0))
        content, block_truncated = _block_content(
            block,
            max_chars=limit,
            answer=answer,
            gold_block_id=gold_block_id,
        )
        if not content:
            dropped.append(block.block_id)
            continue
        truncation_applied = truncation_applied or block_truncated
        selected.append(block.block_id)
        total_chars += len(content)
        evidence.append(
            {
                "rank": rank,
                "doc_id": block.doc_id,
                "block_id": block.block_id,
                "block_type": _context_block_type(block),
                "location": _context_location(block),
                "content": content,
            }
        )
    payload = {
        "task_type": task_type,
        "question": question,
        "evidence": evidence,
    }
    return {
        **payload,
        "selected_block_ids": selected,
        "dropped_block_ids": dropped,
        "truncation_applied": truncation_applied,
        "evidence_context_hash": sha256_json(payload),
    }


def format_evidence_blocks(
    blocks: list[EvidenceBlock],
    *,
    max_chars_per_block: int = 1200,
    max_total_chars: int | None = None,
    answer: str = "",
    gold_block_id: str | None = None,
) -> str:
    context = build_evidence_context(
        question="",
        evidence_blocks=blocks,
        token_budget=max_total_chars,
        max_chars_per_block=max_chars_per_block,
        answer=answer,
        gold_block_id=gold_block_id,
    )
    parts: list[str] = []
    by_id = {block.block_id: block for block in blocks}
    for item in context["evidence"]:
        block = by_id[item["block_id"]]
        location_text = json.dumps(build_location_target(block), ensure_ascii=False)
        header = f"[{block.block_type.upper()} | block_id={block.block_id} | location={location_text}]"
        parts.append(f"{header}\n{item['content']}")
    return "\n\n".join(parts)


def compile_answer_prompt(
    *,
    question: str,
    evidence_blocks: list[EvidenceBlock],
    tool_results: list[dict[str, Any]] | None = None,
    answer_type: str | None = None,
    task_type: str = DEFAULT_TASK_TYPE,
    append_no_think: bool = False,
    max_chars_per_block: int = 1200,
    max_total_chars: int | None = None,
    answer: str = "",
    gold_block_id: str | None = None,
) -> PromptBundle:
    output_schema = json.dumps(OUTPUT_SCHEMA, ensure_ascii=False)
    context = build_evidence_context(
        question=question,
        evidence_blocks=evidence_blocks,
        task_type=task_type,
        token_budget=max_total_chars,
        max_chars_per_block=max_chars_per_block,
        answer=answer,
        gold_block_id=gold_block_id,
    )
    evidence_text = format_evidence_blocks(
        evidence_blocks,
        max_chars_per_block=max_chars_per_block,
        max_total_chars=max_total_chars,
        answer=answer,
        gold_block_id=gold_block_id,
    )
    tool_section = ""
    if tool_results:
        tool_text = json.dumps(tool_results, ensure_ascii=False, indent=2)
        tool_section = f"\n\n## Tool Results\n{tool_text}"
    user_content = (
        "## Task\n"
        "Answer the question from the evidence candidates and cite the exact supporting location.\n\n"
        "## Question\n"
        f"{question}\n\n"
        "## Answer Type\n"
        f"{answer_type or 'extractive'}\n\n"
        "## Evidence Candidates\n"
        f"{evidence_text}"
        f"{tool_section}\n\n"
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
    return PromptBundle(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        prompt_version=PROMPT_VERSION,
        task_type=task_type,
        evidence_context=context,
    )


def build_answer_messages(
    *,
    question: str,
    evidence_blocks: list[EvidenceBlock],
    tool_results: list[dict[str, Any]] | None = None,
    answer_type: str | None = None,
    append_no_think: bool = True,
    max_chars_per_block: int = 1200,
    max_total_chars: int | None = None,
) -> list[dict[str, str]]:
    return compile_answer_prompt(
        question=question,
        evidence_blocks=evidence_blocks,
        tool_results=tool_results,
        answer_type=answer_type,
        append_no_think=append_no_think,
        max_chars_per_block=max_chars_per_block,
        max_total_chars=max_total_chars,
    ).messages


def fallback_chat_prompt(messages: list[dict[str, str]]) -> str:
    parts = []
    for message in messages:
        role = message.get("role", "user")
        content = message.get("content", "")
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)

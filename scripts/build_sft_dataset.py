from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.eval.answer_metrics import normalize_text
from docagent.schemas import DocAgentSample, EvidenceBlock
from docagent.utils.jsonl import read_jsonl, write_jsonl


TARGET_EVIDENCE_CHARS = 300

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


def load_samples(path: Path) -> list[DocAgentSample]:
    return [DocAgentSample.from_dict(record) for record in read_jsonl(path)]


def select_gold_block(sample: DocAgentSample) -> EvidenceBlock | None:
    gold_ids = sample.metadata.get("gold_block_ids") or []
    if gold_ids:
        for block in sample.evidence:
            if block.block_id in gold_ids:
                return block
    return sample.evidence[0] if sample.evidence else None


def ordered_evidence_blocks(sample: DocAgentSample, gold_first: bool = True) -> list[EvidenceBlock]:
    if not gold_first:
        return list(sample.evidence)
    gold_block = select_gold_block(sample)
    if gold_block is None:
        return list(sample.evidence)
    return [gold_block] + [block for block in sample.evidence if block.block_id != gold_block.block_id]


def build_location_target(block: EvidenceBlock) -> dict[str, Any]:
    location = block.location.to_dict()
    location["block_id"] = block.block_id
    return location


def format_block_text(block: EvidenceBlock, max_chars: int, answer: str = "") -> str:
    text = block.retrieval_text.strip()
    if answer and contains_answer(text, answer):
        return centered_evidence_window(text, answer, max_chars)
    return smart_truncate(text, max_chars)


def format_evidence(
    blocks: list[EvidenceBlock],
    max_block_chars: int = 1200,
    answer: str = "",
    gold_block_id: str | None = None,
) -> str:
    parts = []
    for block in blocks:
        location = build_location_target(block)
        location_text = json.dumps(location, ensure_ascii=False)
        block_answer = answer if gold_block_id and block.block_id == gold_block_id else ""
        evidence_text = format_block_text(block, max_block_chars, block_answer)
        parts.append(
            f"[{block.block_type.upper()} | block_id={block.block_id} | location={location_text}]\n"
            f"{evidence_text}"
        )
    return "\n\n".join(parts)


def normalize_answer(answer: str | list[str]) -> str:
    if isinstance(answer, list):
        return ", ".join(str(item) for item in answer if str(item).strip())
    return str(answer)


def smart_truncate(text: str, limit: int = TARGET_EVIDENCE_CHARS) -> str:
    text = re.sub(r"\s+", " ", text).strip()
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
    text_norm = normalize_text(text)
    answer_norm = normalize_text(answer)
    return bool(answer_norm and answer_norm in text_norm)


def find_answer_span(text: str, answer: str) -> tuple[int, int] | None:
    answer = str(answer or "").strip()
    if not answer:
        return None

    direct = re.search(re.escape(answer), text, flags=re.IGNORECASE)
    if direct:
        return direct.start(), direct.end()

    answer_tokens = normalize_text(answer).split()
    if not answer_tokens:
        return None

    tokens: list[tuple[str, int, int]] = []
    for match in re.finditer(r"[A-Za-z0-9\u4e00-\u9fff.%+-]+", text):
        token = normalize_text(match.group(0))
        if token:
            tokens.append((token, match.start(), match.end()))

    window = len(answer_tokens)
    for start_idx in range(0, len(tokens) - window + 1):
        if [item[0] for item in tokens[start_idx : start_idx + window]] == answer_tokens:
            return tokens[start_idx][1], tokens[start_idx + window - 1][2]
    return None


def centered_evidence_window(text: str, answer: str, limit: int = TARGET_EVIDENCE_CHARS) -> str:
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

    if left > 0:
        next_space = compact.find(" ", left)
        if 0 <= next_space < start:
            left = next_space + 1
    if right < len(compact):
        prev_space = compact.rfind(" ", end, right)
        if prev_space > end:
            right = prev_space

    return compact[left:right].strip(" ,;:-")


def extract_target_evidence(block: EvidenceBlock, answer: str) -> str:
    text = block.retrieval_text.strip()
    if not text:
        return ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if block.block_type == "table":
        for line in lines:
            if contains_answer(line, answer):
                return centered_evidence_window(line, answer)

    segments = [
        segment.strip()
        for segment in re.split(r"(?<=[.!?])\s+|\n+", text)
        if segment.strip()
    ]
    for segment in segments:
        if contains_answer(segment, answer):
            return centered_evidence_window(segment, answer)

    return smart_truncate(text)


def build_reason(sample: DocAgentSample, block: EvidenceBlock | None, evidence: str) -> str:
    if block is None:
        return "No supporting evidence block is available."

    page = block.location.page if block.location.page is not None else block.page_id
    source = sample.source
    if source == "mp_docvqa":
        page_text = f"page {page}" if page is not None else "the cited page"
        return f"The answer is supported by official OCR on {page_text} in block {block.block_id}."

    derivation = sample.metadata.get("derivation")
    if sample.answer_type == "numeric" and derivation:
        return f"The numeric answer follows the dataset derivation from block {block.block_id}: {derivation}."

    if block.block_type == "table":
        return f"The answer is copied or calculated from the cited table block {block.block_id}."

    if evidence:
        return f"The answer is copied from the cited text block {block.block_id}."
    return f"The answer is supported by the cited evidence block {block.block_id}."


def build_assistant_target(sample: DocAgentSample) -> dict[str, Any]:
    gold_block = select_gold_block(sample)
    answer = normalize_answer(sample.answer)
    location = build_location_target(gold_block) if gold_block else {}
    evidence = extract_target_evidence(gold_block, answer) if gold_block else ""
    return {
        "answer": answer,
        "evidence_location": location,
        "evidence": evidence,
        "reason": build_reason(sample, gold_block, evidence),
    }


def build_sft_record(
    sample: DocAgentSample,
    max_evidence_blocks: int,
    max_block_chars: int,
    gold_first: bool,
) -> dict[str, Any]:
    output_schema = json.dumps(OUTPUT_SCHEMA, ensure_ascii=False)
    answer = normalize_answer(sample.answer)
    gold_block = select_gold_block(sample)
    gold_block_id = gold_block.block_id if gold_block else None
    evidence_blocks = ordered_evidence_blocks(sample, gold_first=gold_first)[:max_evidence_blocks]
    user_content = (
        "## Task\n"
        "Answer the question from the evidence candidates and cite the exact supporting location.\n\n"
        "## Question\n"
        f"{sample.question}\n\n"
        "## Answer Type\n"
        f"{sample.answer_type}\n\n"
        "## Evidence Candidates\n"
        f"{format_evidence(evidence_blocks, max_block_chars=max_block_chars, answer=answer, gold_block_id=gold_block_id)}\n\n"
        "## Output Contract\n"
        f"Return JSON matching this schema: {output_schema}\n"
        "Rules:\n"
        f"{EXTRACTION_RULES_TEXT}\n"
        "- answer must be concise and grounded in the evidence.\n"
        "- evidence_location must be a JSON object copied from one evidence header.\n"
        "- evidence must be the shortest sufficient supporting span or compact table row, no more than 300 characters.\n"
        "- reason must explain the answer-source relation in one sentence."
    )
    return {
        "id": sample.qid,
        "source": sample.source,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {
                "role": "assistant",
                "content": json.dumps(build_assistant_target(sample), ensure_ascii=False),
            },
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", default="data/benchmark/train_sft.jsonl")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--max-evidence-blocks", type=int, default=5)
    parser.add_argument("--max-block-chars", type=int, default=1200)
    parser.add_argument("--preserve-evidence-order", action="store_true")
    args = parser.parse_args()

    samples = [sample for sample in load_samples(ROOT / args.input) if sample.verifiable]
    if args.offset:
        samples = samples[args.offset :]
    if args.limit is not None:
        samples = samples[: args.limit]
    records = [
        build_sft_record(
            sample,
            max_evidence_blocks=args.max_evidence_blocks,
            max_block_chars=args.max_block_chars,
            gold_first=not args.preserve_evidence_order,
        )
        for sample in samples
    ]
    write_jsonl(ROOT / args.output, records)
    print(
        json.dumps(
            {
                "input": args.input,
                "output": args.output,
                "num_records": len(records),
                "sources": sorted({record["source"] for record in records}),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

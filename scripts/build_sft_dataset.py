from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.schemas import DocAgentSample, EvidenceBlock
from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.prompts import (
    EXTRACTION_RULES_TEXT,
    centered_evidence_window,
    compile_answer_prompt,
    contains_answer,
    smart_truncate,
)


TARGET_EVIDENCE_CHARS = 300


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


def normalize_answer(answer: str | list[str]) -> str:
    if isinstance(answer, list):
        return ", ".join(str(item) for item in answer if str(item).strip())
    return str(answer)


def extract_target_evidence(block: EvidenceBlock, answer: str) -> str:
    text = block.retrieval_text.strip()
    if not text:
        return ""

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if block.block_type == "table":
        for line in lines:
            if contains_answer(line, answer):
                return centered_evidence_window(line, answer, TARGET_EVIDENCE_CHARS)

    segments = [
        segment.strip()
        for segment in re.split(r"(?<=[.!?])\s+|\n+", text)
        if segment.strip()
    ]
    for segment in segments:
        if contains_answer(segment, answer):
            return centered_evidence_window(segment, answer, TARGET_EVIDENCE_CHARS)

    return smart_truncate(text, TARGET_EVIDENCE_CHARS)


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
    evidence = extract_target_evidence(gold_block, answer) if gold_block else ""
    evidence_used = []
    if gold_block is not None:
        evidence_used.append(
            {
                key: value
                for key, value in {
                    "doc_id": gold_block.doc_id,
                    "page": gold_block.location.page if gold_block.location.page is not None else gold_block.page_id,
                    "block_id": gold_block.block_id,
                    "block_type": gold_block.block_type,
                    "text_preview": evidence,
                }.items()
                if value not in {None, ""}
            }
        )
    return {
        "answer": answer,
        "reasoning_summary": build_reason(sample, gold_block, evidence),
        "citation_block_ids": [gold_block.block_id] if gold_block else [],
        "evidence_used": evidence_used,
    }


def build_sft_record(
    sample: DocAgentSample,
    max_evidence_blocks: int,
    max_block_chars: int,
    gold_first: bool,
) -> dict[str, Any]:
    answer = normalize_answer(sample.answer)
    gold_block = select_gold_block(sample)
    gold_block_id = gold_block.block_id if gold_block else None
    evidence_blocks = ordered_evidence_blocks(sample, gold_first=gold_first)[:max_evidence_blocks]
    bundle = compile_answer_prompt(
        question=sample.question,
        evidence_blocks=evidence_blocks,
        answer_type=sample.answer_type,
        append_no_think=False,
        max_chars_per_block=max_block_chars,
        answer=answer,
        gold_block_id=gold_block_id,
    )
    return {
        "id": sample.qid,
        "source": sample.source,
        "messages": [
            *bundle.messages,
            {
                "role": "assistant",
                "content": json.dumps(build_assistant_target(sample), ensure_ascii=False),
            },
        ],
        "prompt_version": bundle.prompt_version,
        "evidence_context_hash": bundle.evidence_context["evidence_context_hash"],
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

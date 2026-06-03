from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.schemas import DocAgentSample, EvidenceBlock
from docagent.utils.jsonl import read_jsonl, write_jsonl


TARGET_EVIDENCE_CHARS = 300

SYSTEM_PROMPT = (
    "You are a document QA assistant. Answer only from the provided evidence. "
    "Return only valid JSON with answer, evidence_location, evidence, and reason. "
    "The evidence_location field must be a JSON object, not a string. "
    "Keep evidence concise and copy only the supporting span or compact table row. "
    "Do not include analysis, chain-of-thought, markdown, or <think> tags."
)


def load_samples(path: Path) -> list[DocAgentSample]:
    return [DocAgentSample.from_dict(record) for record in read_jsonl(path)]


def select_gold_block(sample: DocAgentSample) -> EvidenceBlock | None:
    gold_ids = sample.metadata.get("gold_block_ids") or []
    if gold_ids:
        for block in sample.evidence:
            if block.block_id in gold_ids:
                return block
    return sample.evidence[0] if sample.evidence else None


def ordered_evidence_blocks(sample: DocAgentSample) -> list[EvidenceBlock]:
    gold_block = select_gold_block(sample)
    if gold_block is None:
        return list(sample.evidence)
    return [gold_block] + [block for block in sample.evidence if block.block_id != gold_block.block_id]


def build_location_target(block: EvidenceBlock) -> dict[str, Any]:
    location = block.location.to_dict()
    location["block_id"] = block.block_id
    return location


def format_evidence(blocks: list[EvidenceBlock]) -> str:
    parts = []
    for block in blocks:
        location = build_location_target(block)
        location_text = json.dumps(location, ensure_ascii=False)
        evidence_text = block.retrieval_text[:2500]
        parts.append(
            f"[{block.block_type.upper()} | block_id={block.block_id} | location={location_text}]\n"
            f"{evidence_text}"
        )
    return "\n\n".join(parts)


def normalize_answer(answer: str | list[str]) -> str:
    if isinstance(answer, list):
        return str(answer[0]) if answer else ""
    return str(answer)


def build_assistant_target(sample: DocAgentSample) -> dict[str, Any]:
    gold_block = select_gold_block(sample)
    location = build_location_target(gold_block) if gold_block else {}
    evidence = gold_block.retrieval_text[:TARGET_EVIDENCE_CHARS] if gold_block else ""
    return {
        "answer": normalize_answer(sample.answer),
        "evidence_location": location,
        "evidence": evidence,
        "reason": "The answer is supported by the cited evidence block.",
    }


def build_sft_record(sample: DocAgentSample) -> dict[str, Any]:
    user_content = (
        f"Question:\n{sample.question}\n\n"
        f"Answer type: {sample.answer_type}\n\n"
        f"Evidence:\n{format_evidence(ordered_evidence_blocks(sample))}\n\n"
        "Required output: only one JSON object with answer, evidence_location, evidence, reason. "
        "evidence_location must be an object copied from an evidence header, for example "
        "{\"block_id\": \"...\"}. evidence must be concise and no more than 300 characters."
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
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    samples = [sample for sample in load_samples(ROOT / args.input) if sample.verifiable]
    if args.limit is not None:
        samples = samples[: args.limit]
    records = [build_sft_record(sample) for sample in samples]
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

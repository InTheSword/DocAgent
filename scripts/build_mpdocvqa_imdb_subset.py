from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import write_jsonl


def parse_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                parsed = ast.literal_eval(stripped)
            except (SyntaxError, ValueError):
                return [value]
            if isinstance(parsed, (list, tuple)):
                return list(parsed)
        return [value]
    return [value]


def first_text(value: Any) -> str:
    values = parse_list(value)
    for item in values:
        text = str(item).strip()
        if text:
            return text
    return ""


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def load_imdb_records(path: Path) -> list[dict[str, Any]]:
    import numpy as np

    array = np.load(path, allow_pickle=True)
    records = []
    for item in array[1:]:
        if hasattr(item, "item"):
            item = item.item()
        if isinstance(item, dict):
            records.append(item)
    return records


def image_path_for(page_id: str, image_root: Path | None) -> str | None:
    if image_root is None:
        return None
    candidates = [
        image_root / f"{page_id}.jpg",
        image_root / f"{page_id}.jpeg",
        image_root / f"{page_id}.png",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    return None


def ocr_page_text(record: dict[str, Any], page_index: int) -> str:
    pages = parse_list(record.get("ocr_tokens"))
    if not pages:
        return ""
    page_tokens = pages[page_index] if page_index < len(pages) else pages[0]
    tokens = [str(token).strip() for token in parse_list(page_tokens)]
    return " ".join(token for token in tokens if token)


def convert_record(record: dict[str, Any], split: str, image_root: Path | None) -> DocAgentSample | None:
    qid = str(record.get("question_id") or record.get("questionId") or "").strip()
    question = str(record.get("question") or "").strip()
    doc_id = str(record.get("image_id") or (record.get("extra_info") or {}).get("ucsf_doc_id") or qid).strip()
    answer = first_text(record.get("valid_answers") or record.get("answers"))
    image_names = [str(item) for item in parse_list(record.get("image_name")) if str(item).strip()]
    answer_page_idx = safe_int(record.get("answer_page_idx")) or 0
    answer_page = safe_int(record.get("answer_page"))
    if not qid or not question or not answer or not image_names:
        return None

    evidence_blocks: list[EvidenceBlock] = []
    for page_index, page_id in enumerate(image_names):
        text = ocr_page_text(record, page_index)
        page_number = answer_page if page_index == answer_page_idx else None
        block_id = f"{page_id}_official_ocr"
        evidence_blocks.append(
            EvidenceBlock(
                doc_id=doc_id,
                page_id=page_number,
                block_id=block_id,
                block_type="text",
                text=text,
                image_path=image_path_for(page_id, image_root),
                location=EvidenceLocation(page=page_number, block_id=block_id),
                metadata={
                    "source_record": "mp_docvqa_imdb",
                    "parser_backend": "official_imdb_ocr",
                    "page_id": page_id,
                    "answer_page_idx": answer_page_idx,
                    "is_answer_page": page_index == answer_page_idx,
                    "ocr_token_count": len(text.split()),
                },
            )
        )

    gold_block_id = evidence_blocks[min(answer_page_idx, len(evidence_blocks) - 1)].block_id
    return DocAgentSample(
        qid=qid,
        source="mp_docvqa",
        doc_id=doc_id,
        question=question,
        answer=answer,
        answer_type="extractive",
        evidence=evidence_blocks,
        verifiable=True,
        split=split,
        metadata={
            "gold_block_ids": [gold_block_id],
            "answer_page": answer_page,
            "answer_page_idx": answer_page_idx,
            "image_names": image_names,
            "imdb_doc_pages": record.get("imdb_doc_pages"),
            "total_doc_pages": record.get("total_doc_pages"),
            "ocr_backend": "official_imdb",
        },
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--imdb", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--split", default="train")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--image-root", default=None)
    parser.add_argument("--min-ocr-tokens", type=int, default=5)
    args = parser.parse_args()

    imdb_path = Path(args.imdb)
    image_root = Path(args.image_root) if args.image_root else None
    records = load_imdb_records(imdb_path)
    samples: list[DocAgentSample] = []
    skipped = 0
    for record in records:
        sample = convert_record(record, args.split, image_root)
        if sample is None:
            skipped += 1
            continue
        token_count = sum(len(block.text.split()) for block in sample.evidence)
        if token_count < args.min_ocr_tokens:
            skipped += 1
            continue
        samples.append(sample)
        if len(samples) >= args.limit:
            break

    write_jsonl(ROOT / args.output, [sample.to_dict() for sample in samples])
    summary = {
        "imdb": str(imdb_path),
        "output": args.output,
        "num_imdb_records": len(records),
        "num_samples": len(samples),
        "skipped": skipped,
        "image_root": str(image_root) if image_root else None,
        "samples_with_existing_image": sum(
            any(block.image_path for block in sample.evidence) for sample in samples
        ),
        "total_ocr_tokens": sum(
            len(block.text.split()) for sample in samples for block in sample.evidence
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

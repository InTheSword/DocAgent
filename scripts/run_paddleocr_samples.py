from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import read_jsonl, write_jsonl


def flatten_ocr_result(result: Any) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []

    def visit(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, dict):
            text = item.get("text") or item.get("transcription")
            score = item.get("score") or item.get("confidence")
            bbox = item.get("bbox") or item.get("points")
            if text:
                lines.append({"text": str(text), "score": score, "bbox": bbox})
                return
            for value in item.values():
                visit(value)
            return
        if isinstance(item, (list, tuple)):
            if len(item) >= 2 and isinstance(item[1], (list, tuple)) and item[1]:
                text = item[1][0]
                score = item[1][1] if len(item[1]) > 1 else None
                if isinstance(text, str):
                    lines.append({"text": text, "score": score, "bbox": item[0]})
                    return
            for value in item:
                visit(value)

    visit(result)
    return lines


def ocr_image(ocr: Any, image_path: str) -> tuple[str, list[dict[str, Any]]]:
    result = ocr.ocr(image_path)
    lines = flatten_ocr_result(result)
    text = "\n".join(line["text"] for line in lines if line.get("text")).strip()
    return text, lines


def mean_score(lines: list[dict[str, Any]]) -> float | None:
    scores = []
    for line in lines:
        score = line.get("score")
        if isinstance(score, (int, float)):
            scores.append(float(score))
    return sum(scores) / len(scores) if scores else None


def create_paddleocr(lang: str) -> Any:
    from paddleocr import PaddleOCR

    candidates = [
        {"lang": lang, "use_textline_orientation": True},
        {"lang": lang, "use_angle_cls": True},
        {"lang": lang},
    ]
    errors = []
    for kwargs in candidates:
        try:
            return PaddleOCR(**kwargs)
        except (TypeError, ValueError) as exc:
            errors.append(f"{kwargs}: {exc}")
    raise RuntimeError("failed to initialize PaddleOCR: " + " | ".join(errors))


def convert_sample(sample: DocAgentSample, ocr: Any, min_chars: int) -> tuple[DocAgentSample, dict[str, Any]]:
    new_blocks: list[EvidenceBlock] = []
    report = {
        "qid": sample.qid,
        "doc_id": sample.doc_id,
        "image_blocks": 0,
        "ocr_blocks": 0,
        "ocr_chars": 0,
        "mean_score": None,
        "status": "no_image",
    }
    all_scores = []

    for block in sample.evidence:
        new_blocks.append(block)
        if not block.image_path:
            continue
        report["image_blocks"] += 1
        image_path = Path(block.image_path)
        if not image_path.is_file():
            report["status"] = "missing_image"
            continue
        text, lines = ocr_image(ocr, str(image_path))
        score = mean_score(lines)
        if score is not None:
            all_scores.append(score)
        report["ocr_chars"] += len(text)
        if len(text) < min_chars:
            report["status"] = "ocr_too_short"
            continue
        ocr_block = EvidenceBlock(
            doc_id=block.doc_id,
            page_id=block.page_id,
            block_id=f"{block.block_id}_ocr",
            block_type="text",
            text=text,
            image_path=block.image_path,
            location=EvidenceLocation(page=block.location.page, block_id=f"{block.block_id}_ocr"),
            metadata={
                "source_record": block.metadata.get("source_record"),
                "ocr_engine": "paddleocr",
                "ocr_line_count": len(lines),
                "ocr_mean_score": score,
                "parent_block_id": block.block_id,
            },
        )
        new_blocks.append(ocr_block)
        report["ocr_blocks"] += 1
        report["status"] = "ok"

    metadata = dict(sample.metadata)
    metadata["needs_ocr"] = report["ocr_blocks"] == 0
    metadata["needs_llm_audit"] = True
    metadata["ocr_engine"] = "paddleocr"
    if all_scores:
        report["mean_score"] = sum(all_scores) / len(all_scores)
        metadata["ocr_mean_score"] = report["mean_score"]

    converted = DocAgentSample(
        qid=sample.qid,
        source=sample.source,
        doc_id=sample.doc_id,
        question=sample.question,
        answer=sample.answer,
        answer_type=sample.answer_type,
        evidence=new_blocks,
        verifiable=sample.verifiable,
        split=sample.split,
        metadata=metadata,
    )
    return converted, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report-output", required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--lang", default="en")
    parser.add_argument("--min-chars", type=int, default=20)
    args = parser.parse_args()

    records = read_jsonl(ROOT / args.input)
    if args.limit is not None:
        records = records[: args.limit]
    samples = [DocAgentSample.from_dict(record) for record in records]
    ocr = create_paddleocr(args.lang)

    converted = []
    reports = []
    for sample in samples:
        converted_sample, report = convert_sample(sample, ocr, args.min_chars)
        converted.append(converted_sample.to_dict())
        reports.append(report)

    write_jsonl(ROOT / args.output, converted)
    report = {
        "input": args.input,
        "output": args.output,
        "num_samples": len(converted),
        "status_counts": {
            status: sum(item["status"] == status for item in reports)
            for status in sorted({item["status"] for item in reports})
        },
        "total_ocr_blocks": sum(item["ocr_blocks"] for item in reports),
        "total_ocr_chars": sum(item["ocr_chars"] for item in reports),
        "details": reports,
    }
    report_path = ROOT / args.report_output
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key != "details"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

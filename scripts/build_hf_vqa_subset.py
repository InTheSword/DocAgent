from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.parser.parse_infographicvqa import convert_infographic_record
from docagent.parser.parse_mpdocvqa import convert_mpdocvqa_record
from docagent.schemas import DocAgentSample
from docagent.utils.jsonl import write_jsonl


def is_image_like(value: Any) -> bool:
    return hasattr(value, "save") and hasattr(value, "size")


def serializable_value(value: Any, sample_id: str, key: str, image_dir: Path | None) -> Any:
    if isinstance(value, dict) and isinstance(value.get("src"), str):
        return value
    if is_image_like(value):
        if image_dir is None:
            return None
        image_dir.mkdir(parents=True, exist_ok=True)
        path = image_dir / f"{sample_id}_{key}.jpg"
        if not path.exists():
            value.convert("RGB").save(path, quality=90)
        return str(path)
    if isinstance(value, bytes):
        return None
    if isinstance(value, list):
        return [serializable_value(item, sample_id, key, image_dir) for item in value]
    if isinstance(value, dict):
        return {str(k): serializable_value(v, sample_id, str(k), image_dir) for k, v in value.items()}
    return value


def normalize_hf_row(row: dict[str, Any], image_dir: Path | None) -> dict[str, Any]:
    sample_id = str(row.get("questionId") or row.get("sample_id") or row.get("id") or len(str(row)))
    normalized = {
        str(key): serializable_value(value, sample_id, str(key), image_dir) for key, value in row.items()
    }
    image_path = normalized.get("image_path")
    if not image_path:
        for key, value in normalized.items():
            if key.startswith("image") and isinstance(value, str):
                image_path = value
                break
            if key.startswith("image") and isinstance(value, dict) and isinstance(value.get("src"), str):
                image_path = value["src"]
                break
    if image_path:
        normalized["image_path"] = image_path
    return normalized


def convert_record(source: str, record: dict[str, Any], split: str) -> DocAgentSample:
    if source == "mp_docvqa":
        return convert_mpdocvqa_record(record, split=split)
    if source == "infographicvqa":
        return convert_infographic_record(record, split=split)
    raise ValueError(f"unsupported source: {source}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["mp_docvqa", "infographicvqa"], required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--split", default="train")
    parser.add_argument("--output", required=True)
    parser.add_argument("--image-output-dir", default=None)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--streaming", action="store_true")
    parser.add_argument("--allow-image-only", action="store_true")
    args = parser.parse_args()

    from datasets import load_dataset

    image_dir = Path(args.image_output_dir) if args.image_output_dir else None
    if image_dir is not None and not image_dir.is_absolute():
        image_dir = ROOT / image_dir

    dataset = load_dataset(args.dataset, name=args.name, split=args.split, streaming=args.streaming)
    samples: list[DocAgentSample] = []
    skipped = 0
    raw_seen = 0
    for row in dataset:
        raw_seen += 1
        record = normalize_hf_row(row, image_dir)
        try:
            sample = convert_record(args.source, record, split=args.split)
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        has_text = bool(sample.evidence and sample.evidence[0].retrieval_text)
        has_image = bool(sample.evidence and sample.evidence[0].image_path)
        if sample.verifiable and sample.evidence and (has_text or (args.allow_image_only and has_image)):
            samples.append(sample)
        else:
            skipped += 1
        if len(samples) >= args.limit:
            break

    write_jsonl(ROOT / args.output, [sample.to_dict() for sample in samples])
    print(
        json.dumps(
            {
                "source": args.source,
                "dataset": args.dataset,
                "name": args.name,
                "split": args.split,
                "output": args.output,
                "image_output_dir": str(image_dir) if image_dir else None,
                "raw_seen": raw_seen,
                "num_samples": len(samples),
                "skipped": skipped,
                "needs_ocr": sum(bool(sample.metadata.get("needs_ocr")) for sample in samples),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

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


def load_any_records(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.suffix.lower() == ".jsonl":
        records = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    records.append(json.loads(line))
        return records

    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        raise ValueError(f"expected JSON list or object in {path}")

    for key in ("data", "questions", "annotations", "records", "train", "val", "validation", "test"):
        value = data.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    raise ValueError(f"cannot find record list in {path}; expected one of data/questions/annotations/records")


def convert_record(source: str, record: dict[str, Any], split: str) -> DocAgentSample:
    if source == "mp_docvqa":
        return convert_mpdocvqa_record(record, split=split)
    if source == "infographicvqa":
        return convert_infographic_record(record, split=split)
    raise ValueError(f"unsupported source: {source}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", choices=["mp_docvqa", "infographicvqa"], required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--split", default="train")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()

    raw_path = Path(args.input)
    if not raw_path.is_absolute():
        raw_path = ROOT / raw_path
    records = load_any_records(raw_path)

    samples: list[DocAgentSample] = []
    skipped = 0
    for record in records:
        try:
            sample = convert_record(args.source, record, split=args.split)
        except (KeyError, TypeError, ValueError):
            skipped += 1
            continue
        if sample.verifiable and sample.evidence and sample.evidence[0].retrieval_text:
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
                "input": str(raw_path),
                "output": args.output,
                "split": args.split,
                "num_raw_records": len(records),
                "num_samples": len(samples),
                "skipped": skipped,
                "answer_types": {kind: sum(sample.answer_type == kind for sample in samples) for kind in sorted({sample.answer_type for sample in samples})},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

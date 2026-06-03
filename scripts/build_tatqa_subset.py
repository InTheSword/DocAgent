from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.request import urlretrieve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.parser.parse_tatqa import convert_tatqa_question
from docagent.schemas import DocAgentSample
from docagent.utils.jsonl import write_jsonl


HF_RAW_BASE = "https://huggingface.co/datasets/next-tat/TAT-QA/raw/main"
FILES = {
    "train": "tatqa_dataset_train.json",
    "dev": "tatqa_dataset_dev.json",
    "test": "tatqa_dataset_test_gold.json",
}


def resolve_raw_path(split: str, raw_dir: Path, allow_download: bool) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    filename = FILES[split]
    output = raw_dir / filename
    if output.exists() and output.stat().st_size > 0:
        return output
    if not allow_download:
        raise FileNotFoundError(
            f"Missing local TAT-QA file: {output}\n"
            f"Download {filename} manually to {raw_dir}, or rerun with --allow-download."
        )
    url = f"{HF_RAW_BASE}/{filename}"
    print(f"downloading {url} -> {output}")
    urlretrieve(url, output)
    return output


def load_records(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"expected list in {path}")
    return data


def build_subset(records: list[dict], split: str, limit: int) -> list[DocAgentSample]:
    samples: list[DocAgentSample] = []
    for context in records:
        for question in context.get("questions", []):
            sample = convert_tatqa_question(context, question, split=split)
            if sample.verifiable and sample.answer_type in {"extractive", "numeric"}:
                samples.append(sample)
            if len(samples) >= limit:
                return samples
    return samples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=sorted(FILES), default="dev")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--raw-dir", default="data/raw/tatqa")
    parser.add_argument("--output", default=None)
    parser.add_argument("--allow-download", action="store_true")
    args = parser.parse_args()

    raw_path = resolve_raw_path(args.split, ROOT / args.raw_dir, args.allow_download)
    records = load_records(raw_path)
    samples = build_subset(records, split=args.split, limit=args.limit)
    output = args.output or f"data/benchmark/tatqa_{args.split}_subset.jsonl"
    write_jsonl(ROOT / output, [sample.to_dict() for sample in samples])
    answer_types: dict[str, int] = {}
    answer_from: dict[str, int] = {}
    for sample in samples:
        answer_types[sample.answer_type] = answer_types.get(sample.answer_type, 0) + 1
        source = str(sample.metadata.get("answer_from"))
        answer_from[source] = answer_from.get(source, 0) + 1
    print(
        json.dumps(
            {
                "raw_path": str(raw_path),
                "output": output,
                "num_contexts": len(records),
                "num_samples": len(samples),
                "answer_types": answer_types,
                "answer_from": answer_from,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

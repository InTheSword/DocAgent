from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.schemas import DocAgentSample
from docagent.utils.jsonl import read_jsonl, write_jsonl


def load_samples(path: Path) -> list[DocAgentSample]:
    return [DocAgentSample.from_dict(record) for record in read_jsonl(path)]


def update_split(sample: DocAgentSample, split: str) -> dict[str, Any]:
    record = sample.to_dict()
    record["split"] = split
    return record


def summarize(samples: list[DocAgentSample]) -> dict[str, Any]:
    return {
        "num_samples": len(samples),
        "num_docs": len({sample.doc_id for sample in samples}),
        "source_counts": dict(Counter(sample.source for sample in samples)),
        "answer_type_counts": dict(Counter(sample.answer_type for sample in samples)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--dev-ratio", type=float, default=0.1)
    args = parser.parse_args()

    if not 0 < args.train_ratio < 1:
        raise ValueError("--train-ratio must be between 0 and 1")
    if not 0 <= args.dev_ratio < 1:
        raise ValueError("--dev-ratio must be between 0 and 1")
    if args.train_ratio + args.dev_ratio >= 1:
        raise ValueError("--train-ratio + --dev-ratio must be less than 1")

    samples = load_samples(ROOT / args.input)
    by_doc: dict[str, list[DocAgentSample]] = defaultdict(list)
    for sample in samples:
        by_doc[sample.doc_id].append(sample)

    doc_ids = list(by_doc)
    random.Random(args.seed).shuffle(doc_ids)
    train_end = int(len(doc_ids) * args.train_ratio)
    dev_end = train_end + int(len(doc_ids) * args.dev_ratio)
    split_docs = {
        "train": set(doc_ids[:train_end]),
        "dev": set(doc_ids[train_end:dev_end]),
        "test": set(doc_ids[dev_end:]),
    }

    splits: dict[str, list[DocAgentSample]] = {name: [] for name in split_docs}
    for split, docs in split_docs.items():
        for doc_id in docs:
            splits[split].extend(by_doc[doc_id])
        splits[split].sort(key=lambda item: item.qid)

    output_dir = ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    for split, split_samples in splits.items():
        write_jsonl(output_dir / f"{split}.jsonl", [update_split(sample, split) for sample in split_samples])

    leakage = {
        "train_dev": sorted(split_docs["train"] & split_docs["dev"]),
        "train_test": sorted(split_docs["train"] & split_docs["test"]),
        "dev_test": sorted(split_docs["dev"] & split_docs["test"]),
    }
    report = {
        "input": args.input,
        "output_dir": args.output_dir,
        "seed": args.seed,
        "ratios": {"train": args.train_ratio, "dev": args.dev_ratio, "test": 1 - args.train_ratio - args.dev_ratio},
        "total": summarize(samples),
        "splits": {split: summarize(split_samples) for split, split_samples in splits.items()},
        "doc_leakage": leakage,
    }
    (output_dir / "split_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

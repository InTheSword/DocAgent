from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.schemas import DocAgentSample
from docagent.utils.jsonl import read_jsonl, write_jsonl


def load_samples(path_text: str, limit: int | None) -> list[dict]:
    path = ROOT / path_text
    rows = read_jsonl(path)
    samples = [DocAgentSample.from_dict(row).to_dict() for row in rows]
    return samples[:limit] if limit is not None else samples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", action="append", required=True, help="path[:limit], repeatable")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    mixed: list[dict] = []
    source_counts: dict[str, int] = {}
    for spec in args.input:
        path_text, _, limit_text = spec.partition(":")
        limit = int(limit_text) if limit_text else None
        samples = load_samples(path_text, limit)
        mixed.extend(samples)
        for sample in samples:
            source = str(sample.get("source"))
            source_counts[source] = source_counts.get(source, 0) + 1

    write_jsonl(ROOT / args.output, mixed)
    print(
        json.dumps(
            {
                "output": args.output,
                "num_samples": len(mixed),
                "source_counts": source_counts,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

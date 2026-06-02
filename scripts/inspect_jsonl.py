from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--head", type=int, default=1)
    args = parser.parse_args()

    records = read_jsonl(ROOT / args.input)
    print(json.dumps({"input": args.input, "num_records": len(records)}, ensure_ascii=False, indent=2))
    for record in records[: args.head]:
        print(json.dumps(record, ensure_ascii=False, indent=2)[:4000])


if __name__ == "__main__":
    main()


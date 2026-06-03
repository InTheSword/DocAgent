from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from audit_training_data import audit_record
from docagent.utils.jsonl import read_jsonl, write_jsonl


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--clean-output", required=True)
    parser.add_argument("--dirty-output", required=True)
    parser.add_argument("--max-evidence-chars", type=int, default=300)
    args = parser.parse_args()

    records = read_jsonl(ROOT / args.input)
    clean_records = []
    dirty_records = []
    for record in records:
        issues = audit_record(record, args.max_evidence_chars)
        if issues:
            dirty = dict(record)
            dirty["audit_issues"] = issues
            dirty_records.append(dirty)
        else:
            clean_records.append(record)

    write_jsonl(ROOT / args.clean_output, clean_records)
    write_jsonl(ROOT / args.dirty_output, dirty_records)
    summary = {
        "input": args.input,
        "clean_output": args.clean_output,
        "dirty_output": args.dirty_output,
        "num_records": len(records),
        "clean_records": len(clean_records),
        "dirty_records": len(dirty_records),
        "clean_rate": len(clean_records) / len(records) if records else 0.0,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

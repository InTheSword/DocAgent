from __future__ import annotations

import argparse
import json
from typing import Any


def compact(value: Any, max_text: int) -> Any:
    if hasattr(value, "size") and hasattr(value, "mode"):
        return {"pil_image": True, "size": list(value.size), "mode": value.mode}
    if isinstance(value, str):
        return value[:max_text]
    if isinstance(value, list):
        return [compact(item, max_text) for item in value[:3]]
    if isinstance(value, dict):
        return {str(key): compact(item, max_text) for key, item in list(value.items())[:8]}
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--split", default="train")
    parser.add_argument("--rows", type=int, default=1)
    parser.add_argument("--max-text", type=int, default=500)
    args = parser.parse_args()

    from datasets import load_dataset

    dataset = load_dataset(args.dataset, name=args.name, split=args.split)
    rows = []
    for index, row in enumerate(dataset):
        if index >= args.rows:
            break
        rows.append({str(key): compact(value, args.max_text) for key, value in row.items()})
    print(
        json.dumps(
            {
                "dataset": args.dataset,
                "name": args.name,
                "split": args.split,
                "num_rows": len(rows),
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

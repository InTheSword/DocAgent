from __future__ import annotations

import argparse
import json
from typing import Any


def compact_value(value: Any, max_text: int) -> Any:
    if isinstance(value, str):
        return value[:max_text]
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, list):
        return [compact_value(item, max_text) for item in value[:3]]
    if isinstance(value, dict):
        return {str(key): compact_value(item, max_text) for key, item in list(value.items())[:8]}
    if hasattr(value, "size") and hasattr(value, "mode"):
        return {"image_size": list(value.size), "image_mode": value.mode}
    return value


def value_type(value: Any) -> str:
    if hasattr(value, "size") and hasattr(value, "mode"):
        return "PIL.Image"
    return type(value).__name__


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--name", default=None)
    parser.add_argument("--split", default="train")
    parser.add_argument("--streaming", action="store_true")
    parser.add_argument("--num-samples", type=int, default=2)
    parser.add_argument("--max-text", type=int, default=300)
    args = parser.parse_args()

    from datasets import load_dataset

    dataset = load_dataset(args.dataset, name=args.name, split=args.split, streaming=args.streaming)
    rows = []
    for index, row in enumerate(dataset):
        if index >= args.num_samples:
            break
        rows.append(row)

    field_types: dict[str, str] = {}
    for row in rows:
        for key, value in row.items():
            field_types.setdefault(str(key), value_type(value))

    preview = [
        {str(key): compact_value(value, args.max_text) for key, value in row.items()}
        for row in rows
    ]
    print(
        json.dumps(
            {
                "dataset": args.dataset,
                "name": args.name,
                "split": args.split,
                "streaming": args.streaming,
                "num_preview_rows": len(rows),
                "field_types": field_types,
                "preview": preview,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

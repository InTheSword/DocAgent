from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from typing import Any


def compact(value: Any, max_text: int) -> Any:
    if isinstance(value, str):
        return value[:max_text]
    if isinstance(value, list):
        return [compact(item, max_text) for item in value[:3]]
    if isinstance(value, dict):
        return {str(key): compact(item, max_text) for key, item in list(value.items())[:8]}
    return value


def request_json(path: str, params: dict[str, str], timeout: int) -> dict[str, Any]:
    query = urllib.parse.urlencode(params)
    url = f"https://datasets-server.huggingface.co/{path}?{query}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--config", default="default")
    parser.add_argument("--split", default=None)
    parser.add_argument("--rows", type=int, default=2)
    parser.add_argument("--max-text", type=int, default=300)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    splits = request_json("splits", {"dataset": args.dataset}, args.timeout)
    available = [
        {"config": item.get("config"), "split": item.get("split"), "num_examples": item.get("num_examples")}
        for item in splits.get("splits", [])
    ]
    split = args.split
    config = args.config
    if split is None:
        if not available:
            raise ValueError(f"no splits returned for {args.dataset}")
        config = str(available[0]["config"])
        split = str(available[0]["split"])
    elif not any(item.get("config") == config and item.get("split") == split for item in available):
        raise ValueError(
            f"requested config/split not available: {config}/{split}. "
            f"Available: {available}"
        )

    first_rows = request_json(
        "first-rows",
        {"dataset": args.dataset, "config": config, "split": split},
        args.timeout,
    )
    rows = []
    for item in first_rows.get("rows", [])[: args.rows]:
        row = item.get("row", item)
        rows.append({str(key): compact(value, args.max_text) for key, value in row.items()})

    features = first_rows.get("features") or []
    print(
        json.dumps(
            {
                "dataset": args.dataset,
                "requested_config": config,
                "requested_split": split,
                "available_splits": available,
                "features": features,
                "num_preview_rows": len(rows),
                "preview": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

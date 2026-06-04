from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--contains", default="")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    repo = urllib.parse.quote(args.dataset, safe="")
    url = f"https://huggingface.co/api/datasets/{repo}/tree/main?recursive=1"
    with urllib.request.urlopen(url, timeout=args.timeout) as response:
        entries = json.loads(response.read().decode("utf-8"))
    files = []
    needle = args.contains.lower()
    for entry in entries:
        path = str(entry.get("path") or "")
        if entry.get("type") != "file":
            continue
        if needle and needle not in path.lower():
            continue
        files.append(
            {
                "path": path,
                "size": entry.get("size"),
                "oid": entry.get("oid"),
            }
        )
        if len(files) >= args.limit:
            break
    print(
        json.dumps(
            {
                "dataset": args.dataset,
                "contains": args.contains,
                "num_files": len(files),
                "files": files,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

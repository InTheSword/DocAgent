from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.storage.db import connect
from docagent.storage.repositories import TraceRepository


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite-path", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    repo = TraceRepository(connect(ROOT / args.sqlite_path))
    payload = {"run": repo.get_run(args.run_id), "traces": repo.list_traces(args.run_id)}
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

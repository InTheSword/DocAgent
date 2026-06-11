from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doc-id")
    parser.add_argument("--sqlite-path", default="outputs/docagent.db")
    parser.add_argument("--show-blocks", action="store_true")
    parser.add_argument("--show-index", action="store_true")
    args = parser.parse_args()

    conn = connect(ROOT / args.sqlite_path)
    repository = DocumentRepository(conn)
    if not args.doc_id:
        print(json.dumps({"documents": repository.list_documents()}, ensure_ascii=False, indent=2))
        return

    document = repository.get_document(args.doc_id)
    if document is None:
        raise SystemExit(f"document not found: {args.doc_id}")
    payload: dict[str, object] = {"document": document}
    if args.show_blocks:
        blocks = repository.load_evidence_blocks(args.doc_id, include_page_blocks=True)
        payload["blocks"] = [block.to_dict() for block in blocks]
    if args.show_index:
        payload["indexes"] = repository.list_indexes(args.doc_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


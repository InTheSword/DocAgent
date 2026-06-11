from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.schemas import EvidenceBlock
from docagent.utils.jsonl import read_jsonl
from scripts.workflow_record_utils import workflow_input_from_record


def _page(block: EvidenceBlock, fallback: int) -> int:
    if block.page_id is not None:
        return int(block.page_id)
    if block.location.page is not None:
        return int(block.location.page)
    return fallback


def _content_item(block: EvidenceBlock, index: int) -> dict[str, Any]:
    page = _page(block, index - 1)
    item: dict[str, Any] = {
        "type": "table" if block.block_type == "table" else "image" if block.block_type in {"image", "figure"} else "text",
        "page_idx": page,
        "text": block.text or block.visual_summary or "",
        "bbox": block.location.bbox,
        "source_block_id": block.block_id,
        "metadata": {
            **block.metadata,
            "source_doc_id": block.doc_id,
            "source_block_id": block.block_id,
            "source_page_id": block.page_id,
        },
    }
    if block.table_html:
        item["table_body"] = block.table_html
        item["table_html"] = block.table_html
    if block.image_path:
        item["image_path"] = block.image_path
    return {key: value for key, value in item.items() if value is not None}


def _choose_source_file(item: dict[str, Any], output_dir: Path) -> str:
    for block in item["blocks"]:
        if block.image_path and Path(block.image_path).is_file():
            source = Path(block.image_path)
            target = output_dir / "source" / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            return str(target)
    source = output_dir / "source" / f"{item['qid']}.txt"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text(
        "\n\n".join(block.retrieval_text for block in item["blocks"] if block.retrieval_text),
        encoding="utf-8",
    )
    return str(source)


def select_record(records: list[dict[str, Any]], *, qid: str | None, index: int) -> dict[str, Any]:
    if qid is None:
        return records[index]
    for record in records:
        record_id = str(record.get("qid") or record.get("id") or record.get("question_id") or "")
        if record_id == qid:
            return record
    raise ValueError(f"qid not found: {qid}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--qid")
    parser.add_argument("--index", type=int, default=0)
    args = parser.parse_args()

    records = read_jsonl(ROOT / args.input)
    record = select_record(records, qid=args.qid, index=args.index)
    item = workflow_input_from_record(record)
    output_dir = ROOT / args.output_dir
    mineru_dir = output_dir / "mineru"
    mineru_dir.mkdir(parents=True, exist_ok=True)
    content = [_content_item(block, index) for index, block in enumerate(item["blocks"], start=1)]
    content_path = mineru_dir / "sample_content_list.json"
    content_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
    source_file = _choose_source_file(item, output_dir)
    summary = {
        "input": args.input,
        "qid": item["qid"],
        "doc_id": item["doc_id"],
        "question": item["question"],
        "answer_type": item["answer_type"],
        "gold": item.get("gold"),
        "source_file": source_file,
        "mineru_output_dir": str(mineru_dir),
        "content_list": str(content_path),
        "num_blocks": len(item["blocks"]),
        "block_ids": [block.block_id for block in item["blocks"]],
    }
    (output_dir / "fixture_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

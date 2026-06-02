from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from docagent.schemas import EvidenceBlock, EvidenceLocation


def run_mineru(input_path: str | Path, output_dir: str | Path, command: str = "mineru") -> Path:
    if shutil.which(command) is None:
        raise RuntimeError(f"{command} is not installed or not on PATH")
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([command, "-p", str(input_path), "-o", str(output_dir)], check=True)
    return output_dir


def content_list_to_blocks(doc_id: str, content_list_path: str | Path) -> list[EvidenceBlock]:
    path = Path(content_list_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    blocks: list[EvidenceBlock] = []
    for idx, item in enumerate(data):
        block_type = item.get("type", "text")
        if block_type in {"chart", "figure"}:
            block_type = "image"
        if block_type not in {"text", "table", "image"}:
            continue
        page = item.get("page_idx")
        block_id = f"{doc_id}_p{page if page is not None else 0}_b{idx}"
        blocks.append(
            EvidenceBlock(
                doc_id=doc_id,
                page_id=page,
                block_id=block_id,
                block_type=block_type,
                text=item.get("text") or item.get("content") or "",
                table_html=item.get("table_body"),
                image_path=item.get("image_path"),
                location=EvidenceLocation(page=page, block_id=block_id, bbox=item.get("bbox")),
                metadata={"parser": "mineru"},
            )
        )
    return blocks


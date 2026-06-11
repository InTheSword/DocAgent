from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from docagent.schemas import EvidenceBlock, EvidenceLocation


TEXT_TYPES = {"text", "title", "paragraph", "list"}
TABLE_TYPES = {"table"}
IMAGE_TYPES = {"image", "figure", "chart"}


def _clean_text(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _page(item: dict[str, Any]) -> int:
    value = item.get("page_idx", item.get("page", item.get("page_id", 0)))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _bbox(item: dict[str, Any]) -> list[float] | None:
    value = item.get("bbox")
    if not isinstance(value, list) or not value:
        return None
    result: list[float] = []
    for item_value in value[:4]:
        try:
            result.append(float(item_value))
        except (TypeError, ValueError):
            return None
    return result if len(result) == 4 else None


def _block_type(item: dict[str, Any]) -> str | None:
    raw_type = str(item.get("type", item.get("block_type", "text"))).lower()
    if raw_type in TEXT_TYPES:
        return "text"
    if raw_type in TABLE_TYPES:
        return "table"
    if raw_type in IMAGE_TYPES:
        return "image"
    return None


def _item_text(item: dict[str, Any], block_type: str) -> str:
    if block_type == "table":
        return _clean_text(
            item.get("table_text")
            or item.get("table_caption")
            or item.get("caption")
            or item.get("text")
            or item.get("content")
            or item.get("table_body")
        )
    if block_type == "image":
        return _clean_text(
            item.get("caption")
            or item.get("image_caption")
            or item.get("nearby_text")
            or item.get("text")
            or item.get("content")
        )
    return _clean_text(item.get("text") or item.get("content"))


def _table_html(item: dict[str, Any]) -> str | None:
    value = item.get("table_html") or item.get("table_body")
    return str(value) if value else None


def _image_path(item: dict[str, Any]) -> str | None:
    value = item.get("image_path") or item.get("img_path")
    return str(value) if value else None


def _make_block(doc_id: str, item: dict[str, Any], index: int) -> EvidenceBlock | None:
    block_type = _block_type(item)
    if block_type is None:
        return None
    page = _page(item)
    text = _item_text(item, block_type)
    table_html = _table_html(item) if block_type == "table" else None
    image_path = _image_path(item) if block_type == "image" else None
    if not text and not table_html and not image_path:
        return None

    block_id = f"{doc_id}_p{page:03d}_b{index:04d}"
    bbox = _bbox(item)
    metadata = {
        "parser": "mineru",
        "reading_order": index,
    }
    for key in ("section_title", "caption", "row_count", "column_count"):
        if key in item:
            metadata[key] = item[key]
    return EvidenceBlock(
        doc_id=doc_id,
        page_id=page,
        block_id=block_id,
        block_type=block_type,
        text=text,
        table_html=table_html,
        image_path=image_path,
        location=EvidenceLocation(page=page, block_id=block_id, bbox=bbox),
        metadata=metadata,
    )


def _split_large_block(block: EvidenceBlock, max_chars: int) -> list[EvidenceBlock]:
    if len(block.text) <= max_chars or block.block_type != "text":
        return [block]
    parts = [part.strip() for part in re.split(r"(?<=[。.!?])\s+|\n+", block.text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for part in parts or [block.text]:
        if current and len(current) + 1 + len(part) > max_chars:
            chunks.append(current)
            current = part
        else:
            current = f"{current} {part}".strip()
    if current:
        chunks.append(current)
    if len(chunks) <= 1:
        return [block]
    result: list[EvidenceBlock] = []
    for idx, text in enumerate(chunks, start=1):
        child_id = f"{block.block_id}_s{idx:03d}"
        result.append(
            EvidenceBlock(
                doc_id=block.doc_id,
                page_id=block.page_id,
                block_id=child_id,
                block_type=block.block_type,
                text=text,
                location=EvidenceLocation(page=block.page_id, block_id=child_id, bbox=block.location.bbox),
                metadata={**block.metadata, "parent_block_id": block.block_id},
            )
        )
    return result


def normalize_blocks(
    blocks: list[EvidenceBlock],
    *,
    merge_small_chars: int = 100,
    merge_max_chars: int = 1000,
    split_max_chars: int = 1200,
) -> list[EvidenceBlock]:
    merged: list[EvidenceBlock] = []
    pending: EvidenceBlock | None = None

    def flush_pending() -> None:
        nonlocal pending
        if pending is not None:
            merged.append(pending)
            pending = None

    for block in blocks:
        can_merge = (
            block.block_type == "text"
            and len(block.text) < merge_small_chars
            and pending is not None
            and pending.block_type == "text"
            and pending.page_id == block.page_id
            and len(pending.text) + 1 + len(block.text) <= merge_max_chars
        )
        if can_merge:
            pending.text = f"{pending.text}\n{block.text}".strip()
            pending.metadata.setdefault("merged_block_ids", [pending.block_id])
            pending.metadata["merged_block_ids"].append(block.block_id)
            continue
        flush_pending()
        pending = block
    flush_pending()

    normalized: list[EvidenceBlock] = []
    for block in merged:
        normalized.extend(_split_large_block(block, split_max_chars))
    return normalized


def build_page_blocks(doc_id: str, blocks: list[EvidenceBlock]) -> list[EvidenceBlock]:
    by_page: dict[int, list[EvidenceBlock]] = {}
    for block in blocks:
        if block.page_id is not None and block.block_type != "page":
            by_page.setdefault(block.page_id, []).append(block)
    pages: list[EvidenceBlock] = []
    for page, page_blocks in sorted(by_page.items()):
        page_blocks.sort(key=lambda item: int(item.metadata.get("reading_order", 0)))
        block_id = f"{doc_id}_p{page:03d}_page"
        text = "\n".join(block.retrieval_text for block in page_blocks if block.retrieval_text)
        pages.append(
            EvidenceBlock(
                doc_id=doc_id,
                page_id=page,
                block_id=block_id,
                block_type="page",
                text=text,
                location=EvidenceLocation(page=page, block_id=block_id),
                metadata={"parser": "mineru", "child_block_ids": [block.block_id for block in page_blocks]},
            )
        )
    return pages


def content_list_to_blocks(
    *,
    doc_id: str,
    content_list_path: str | Path,
    normalize: bool = True,
) -> list[EvidenceBlock]:
    path = Path(content_list_path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("content_list") or data.get("blocks") or []
    if not isinstance(data, list):
        raise ValueError("MinerU content list must be a list or a dict with content_list/blocks")
    blocks = [_make_block(doc_id, item, index) for index, item in enumerate(data, start=1) if isinstance(item, dict)]
    result = [block for block in blocks if block is not None]
    return normalize_blocks(result) if normalize else result


def find_content_list(output_dir: str | Path) -> Path:
    root = Path(output_dir)
    candidates = sorted(root.rglob("*content_list*.json"))
    if candidates:
        return candidates[0]
    candidates = sorted(root.rglob("*middle*.json"))
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"no MinerU content_list or middle JSON found under {root}")

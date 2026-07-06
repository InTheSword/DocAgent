from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from docagent.schemas import EvidenceBlock, EvidenceLocation


TEXT_TYPES = {"text", "title", "paragraph", "list"}
TABLE_TYPES = {"table"}
IMAGE_TYPES = {"image", "figure", "chart"}
BOILERPLATE_TYPES = {"header", "footer", "page_number"}
KNOWN_RAW_TYPES = TEXT_TYPES | TABLE_TYPES | IMAGE_TYPES | BOILERPLATE_TYPES
TEXTISH_KEYS = (
    "text",
    "content",
    "value",
    "table_text",
    "table_caption",
    "table_footnote",
    "caption",
    "image_caption",
    "chart_caption",
    "chart_footnote",
    "nearby_text",
)
VISUAL_SUMMARY_KEYS = (
    "visual_summary",
    "image_summary",
    "figure_summary",
    "chart_summary",
    "alt_text",
)
NESTED_TEXT_KEYS = ("spans", "lines", "children", "blocks", "items", "cells", "rows")
RESOURCE_PATH_KEYS = (
    "image_path",
    "img_path",
    "image_url",
    "img_url",
    "table_image_path",
    "table_img_path",
    "table_image_url",
    "table_img_url",
)
URL_RE = re.compile(r"^https?://", re.IGNORECASE)


def _clean_text(value: object) -> str:
    if isinstance(value, list):
        parts = [_clean_text(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        parts = [_clean_text(value[key]) for key in TEXTISH_KEYS if key in value]
        if not any(parts):
            parts = [_clean_text(value[key]) for key in NESTED_TEXT_KEYS if key in value]
        if not any(parts):
            parts = [_clean_text(item) for item in value.values()]
        return " ".join(part for part in parts if part).strip()
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_page_number_like(text: str) -> bool:
    normalized = _clean_text(text).casefold()
    normalized = normalized.strip(" -–—|·•")
    if not normalized:
        return True
    return bool(
        re.fullmatch(
            r"(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?",
            normalized,
        )
        or re.fullmatch(r"[ivxlcdm]{1,8}", normalized)
    )


def _has_substantive_signal(text: str) -> bool:
    normalized = _clean_text(text)
    if not normalized:
        return False
    if re.search(r"[$€£¥%]|\d[\d,]*(?:\.\d+)?", normalized):
        return True
    tokens = re.findall(r"[A-Za-z0-9]+", normalized)
    return len(tokens) >= 6


def _is_boilerplate(raw_type: str, text: str) -> bool:
    if raw_type not in BOILERPLATE_TYPES:
        return False
    if _is_page_number_like(text):
        return True
    return not _has_substantive_signal(text)


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    return _clean_text(re.sub(r"<[^>]+>", " ", value))


def _page_idx(item: dict[str, Any]) -> int | None:
    value = item.get("page_idx")
    if value is None:
        value = item.get("page")
    if value is None:
        value = item.get("page_id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _docagent_page(item: dict[str, Any]) -> int | None:
    page_idx = _page_idx(item)
    return page_idx + 1 if page_idx is not None else None


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


def _raw_type(item: dict[str, Any]) -> str:
    return str(item.get("type", item.get("block_type", "text"))).lower()


def _block_type(raw_type: str) -> str:
    if raw_type in TABLE_TYPES:
        return "table"
    if raw_type in IMAGE_TYPES:
        return "image"
    return "text"


def _as_list(value: object) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _table_html(item: dict[str, Any]) -> str | None:
    value = item.get("table_html") or item.get("table_body")
    return str(value) if value else None


def _caption_text(item: dict[str, Any], *keys: str) -> str:
    parts: list[str] = []
    for key in keys:
        parts.extend(_clean_text(value) for value in _as_list(item.get(key)))
    return _unique_text_parts(*parts)


def _unique_text_parts(*parts: str) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        cleaned = _clean_text(part)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return "\n".join(result).strip()


def _item_text(item: dict[str, Any], raw_type: str, block_type: str) -> str:
    if block_type == "table":
        caption = _caption_text(item, "table_caption")
        footnote = _caption_text(item, "table_footnote")
        body_text = _unique_text_parts(
            _clean_text(item.get("table_text")),
            _clean_text(item.get("text")),
            _clean_text(item.get("content")),
            _strip_html(_table_html(item)),
        )
        return _unique_text_parts(caption, body_text, footnote)
    if raw_type == "chart":
        caption = _caption_text(item, "chart_caption")
        footnote = _caption_text(item, "chart_footnote")
        content = _unique_text_parts(
            _visual_summary(item),
            _clean_text(item.get("nearby_text")),
            _clean_text(item.get("text")),
            _clean_text(item.get("content")),
        )
        return _unique_text_parts(caption, content, footnote)
    if block_type == "image":
        return _unique_text_parts(
            _visual_summary(item),
            _caption_text(item, "caption", "image_caption"),
            _clean_text(item.get("nearby_text")),
            _clean_text(item.get("text")),
            _clean_text(item.get("content")),
        )
    return _unique_text_parts(_clean_text(item.get("text")), _clean_text(item.get("content")))


def _visual_summary(item: dict[str, Any]) -> str:
    return _caption_text(item, *VISUAL_SUMMARY_KEYS)


def _visual_content_metadata(
    item: dict[str, Any],
    *,
    block_type: str,
    image_path: str | None,
    visual_summary: str,
) -> dict[str, Any]:
    if block_type != "image":
        return {}
    sources: list[str] = []
    if visual_summary:
        sources.append("visual_summary")
    if _caption_text(item, "caption", "image_caption", "chart_caption"):
        sources.append("caption")
    if _clean_text(item.get("nearby_text")):
        sources.append("nearby_text")
    if _unique_text_parts(_clean_text(item.get("text")), _clean_text(item.get("content"))):
        sources.append("ocr_text")

    if visual_summary:
        status = "vlm_summarized"
    elif any(source in {"nearby_text", "ocr_text"} for source in sources):
        status = "ocr_or_nearby_text"
    elif "caption" in sources:
        status = "caption_only"
    elif image_path:
        status = "resource_only"
    else:
        status = "empty"
    return {
        "visual_content_status": status,
        "visual_text_sources": sources,
        "requires_visual_understanding": bool(image_path) and status in {"resource_only", "caption_only"},
    }


def _resource_path(item: dict[str, Any]) -> tuple[str | None, str | None]:
    for key in RESOURCE_PATH_KEYS:
        value = item.get(key)
        if value:
            return str(value), key
    return None, None


def _default_document_dir(content_list_path: Path) -> Path:
    return content_list_path.parent.parent if content_list_path.parent.name == "mineru" else content_list_path.parent


def _relative_posix(path: Path, document_dir: Path) -> str:
    try:
        return path.resolve().relative_to(document_dir.resolve()).as_posix()
    except ValueError:
        return path.name if path.is_absolute() else path.as_posix()


def _is_url(value: str) -> bool:
    return bool(URL_RE.match(value.strip()))


def _resolve_resource_path(raw_path: str | None, root: Path, document_dir: Path) -> tuple[str | None, bool | None, bool]:
    if not raw_path:
        return None, None, False
    if _is_url(raw_path):
        return raw_path.strip(), None, True
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    return _relative_posix(path, document_dir), path.is_file(), False


def _layout_metadata(content_list_path: Path, document_dir: Path) -> dict[str, Any]:
    layout_path = content_list_path.parent / "layout.json"
    if not layout_path.exists():
        return {}
    try:
        data = json.loads(layout_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"layout_path": _relative_posix(layout_path, document_dir), "layout_readable": False}
    return {
        "layout_path": _relative_posix(layout_path, document_dir),
        "layout_readable": True,
        "mineru_backend": data.get("_backend"),
        "mineru_version": data.get("_version_name"),
        "mineru_ocr_enable": data.get("_ocr_enable"),
        "mineru_vlm_ocr_enable": data.get("_vlm_ocr_enable"),
        "layout_page_count": len(data.get("pdf_info") or []),
    }


def _make_block(
    *,
    doc_id: str,
    item: dict[str, Any],
    index: int,
    content_list_path: Path,
    resource_root: Path,
    document_dir: Path,
    provenance: dict[str, Any],
) -> EvidenceBlock | None:
    raw_type = _raw_type(item)
    block_type = _block_type(raw_type)
    page = _docagent_page(item)
    mineru_page_idx = _page_idx(item)
    text = _item_text(item, raw_type, block_type)
    visual_summary = _visual_summary(item) if block_type == "image" else ""
    boilerplate = _is_boilerplate(raw_type, text)
    table_html = _table_html(item) if block_type == "table" else None
    raw_image_path, raw_resource_key = _resource_path(item)
    resource_path, resource_exists, resource_is_remote = _resolve_resource_path(raw_image_path, resource_root, document_dir)
    image_path = resource_path if block_type == "image" else None
    if block_type == "table" and raw_image_path:
        image_path = resource_path
    if not text and not table_html and not image_path and not boilerplate:
        return None

    safe_page = page if page is not None else 0
    block_id = f"{doc_id}_p{safe_page:03d}_b{index:04d}"
    metadata: dict[str, Any] = {
        "parser": "mineru",
        "reading_order": index,
        "raw_item_index": index,
        "raw_mineru_type": raw_type,
        "raw_boilerplate_type": raw_type in BOILERPLATE_TYPES,
        "is_boilerplate": boilerplate,
        "exclude_from_retrieval": boilerplate,
        "mineru_provenance": provenance,
    }
    if raw_type not in KNOWN_RAW_TYPES:
        metadata["unknown_raw_type"] = True
    if mineru_page_idx is not None:
        metadata["mineru_page_idx"] = mineru_page_idx
    if "text_level" in item:
        metadata["text_level"] = item["text_level"]
    for key in (
        "table_caption",
        "table_footnote",
        "caption",
        "image_caption",
        "chart_caption",
        "chart_footnote",
        "nearby_text",
        "sub_type",
    ):
        if key in item:
            metadata[key] = item[key]
    if table_html is not None:
        metadata["table_body"] = table_html
    if raw_image_path is not None:
        metadata["img_path"] = raw_image_path
        if raw_resource_key is not None:
            metadata["resource_key"] = raw_resource_key
        metadata["resource_exists"] = resource_exists
        metadata["resource_is_remote"] = resource_is_remote
    if visual_summary:
        metadata["visual_summary"] = visual_summary
    metadata.update(
        _visual_content_metadata(
            item,
            block_type=block_type,
            image_path=image_path,
            visual_summary=visual_summary,
        )
    )

    return EvidenceBlock(
        doc_id=doc_id,
        page_id=page,
        block_id=block_id,
        block_type=block_type,
        text=text,
        table_html=table_html,
        image_path=image_path,
        visual_summary=visual_summary or None,
        location=EvidenceLocation(page=page, block_id=block_id, bbox=_bbox(item)),
        metadata=metadata,
    )


def _link_neighbors(blocks: list[EvidenceBlock]) -> None:
    for index, block in enumerate(blocks):
        if index > 0:
            block.metadata["previous_block_id"] = blocks[index - 1].block_id
        if index + 1 < len(blocks):
            block.metadata["next_block_id"] = blocks[index + 1].block_id


def _split_large_block(block: EvidenceBlock, max_chars: int) -> list[EvidenceBlock]:
    if len(block.text) <= max_chars or block.block_type != "text" or block.metadata.get("is_boilerplate"):
        return [block]
    parts = [part.strip() for part in re.split(r"(?<=[。?!?])\s+|\n+", block.text) if part.strip()]
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
            and not block.metadata.get("is_boilerplate")
            and len(block.text) < merge_small_chars
            and pending is not None
            and pending.block_type == "text"
            and not pending.metadata.get("is_boilerplate")
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
    _link_neighbors(normalized)
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
                metadata={
                    "parser": "mineru",
                    "child_block_ids": [block.block_id for block in page_blocks],
                    "excluded_child_block_ids": [
                        block.block_id for block in page_blocks if block.metadata.get("exclude_from_retrieval")
                    ],
                },
            )
        )
    return pages


def raw_content_list_stats(content_list_path: str | Path) -> dict[str, Any]:
    path = Path(content_list_path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("content_list") or data.get("blocks") or []
    if not isinstance(data, list):
        raise ValueError("MinerU content list must be a list or a dict with content_list/blocks")
    pages = {_page_idx(item) for item in data if isinstance(item, dict) and _page_idx(item) is not None}
    types = Counter(_raw_type(item) for item in data if isinstance(item, dict))
    return {
        "root_type": "list",
        "raw_block_count": len(data),
        "content_list_pages": len(pages),
        "raw_type_distribution": dict(sorted(types.items())),
        "missing_page_count": sum(1 for item in data if not isinstance(item, dict) or _page_idx(item) is None),
        "missing_or_invalid_bbox_count": sum(1 for item in data if not isinstance(item, dict) or _bbox(item) is None),
    }


def content_list_to_blocks(
    *,
    doc_id: str,
    content_list_path: str | Path,
    normalize: bool = False,
    resource_root: str | Path | None = None,
    document_dir: str | Path | None = None,
) -> list[EvidenceBlock]:
    path = Path(content_list_path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("content_list") or data.get("blocks") or []
    if not isinstance(data, list):
        raise ValueError("MinerU content list must be a list or a dict with content_list/blocks")
    resource_base = Path(resource_root) if resource_root is not None else path.parent
    document_base = Path(document_dir) if document_dir is not None else _default_document_dir(path)
    provenance = _layout_metadata(path, document_base)
    provenance["content_list_file"] = _relative_posix(path, document_base)
    blocks = [
        _make_block(
            doc_id=doc_id,
            item=item,
            index=index,
            content_list_path=path,
            resource_root=resource_base,
            document_dir=document_base,
            provenance=provenance,
        )
        for index, item in enumerate(data, start=1)
        if isinstance(item, dict)
    ]
    result = [block for block in blocks if block is not None]
    result = normalize_blocks(result) if normalize else result
    _link_neighbors(result)
    return result


def find_content_list(output_dir: str | Path) -> Path:
    root = Path(output_dir)
    ordinary_candidates = [
        path
        for path in sorted(root.rglob("*content_list.json"))
        if not path.name.endswith("_content_list_v2.json") and path.name != "content_list_v2.json"
    ]
    if len(ordinary_candidates) > 1:
        names = ", ".join(str(path) for path in ordinary_candidates)
        raise ValueError(f"multiple ordinary MinerU content-list files found under {root}: {names}")

    if ordinary_candidates:
        return ordinary_candidates[0]

    v2_candidates = [
        path
        for path in sorted(root.rglob("*content_list_v2.json"))
        if path.name.endswith("_content_list_v2.json") or path.name == "content_list_v2.json"
    ]
    if not v2_candidates:
        raise FileNotFoundError(f"no MinerU content-list file found under {root}")
    if len(v2_candidates) > 1:
        names = ", ".join(str(path) for path in v2_candidates)
        raise ValueError(f"multiple MinerU content-list v2 files found under {root}: {names}")
    return v2_candidates[0]

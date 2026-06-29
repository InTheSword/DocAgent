from __future__ import annotations

import re
from collections import Counter
from typing import Any

from docagent.schemas import EvidenceBlock
from docagent.storage.repositories import DocumentRepository


DEFAULT_ITEM_LIMIT = 50
PREVIEW_CHARS = 180

DATE_PATTERNS = [
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"),
    re.compile(r"\b\d{4}[/-]\d{2}\b"),
    re.compile(r"\b\d{4}\s*[-/]\s*\d{2}\b"),
    re.compile(
        r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
        r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
        r"\s+\d{1,2},?\s+\d{4}\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:19|20)\d{2}\b"),
]


def structured_extract(
    repository: DocumentRepository,
    doc_id: str,
    *,
    selected_tools: list[str] | None = None,
    question: str = "",
    limit: int = DEFAULT_ITEM_LIMIT,
) -> dict[str, Any]:
    document = repository.get_document(doc_id)
    if document is None:
        return _error("document_not_found", "Document was not found.", doc_id=doc_id)

    tools = selected_tools or ["structured_extract"]
    blocks = repository.load_evidence_blocks(doc_id)
    items: list[dict[str, Any]] = []
    warnings: list[str] = []

    if "extract_all_dates" in tools:
        items.extend(_date_items(blocks, limit=max(0, limit - len(items))))
    if "extract_all_tables" in tools:
        items.extend(_block_items(blocks, {"table"}, "table", limit=max(0, limit - len(items))))
    if "extract_all_images" in tools:
        items.extend(_block_items(blocks, {"image", "figure"}, "image", limit=max(0, limit - len(items))))
    if "list_sections" in tools or "document_outline" in tools:
        section_items = _section_items(blocks, limit=max(0, limit - len(items)))
        items.extend(section_items)
        if not section_items:
            warnings.append("section_metadata_not_found")
    if not items and "structured_extract" in tools:
        items.extend(_generic_items(blocks, limit=limit))

    if not items:
        warnings.append("no_structured_items_found")

    counts = Counter(str(item.get("type") or "") for item in items)
    return {
        "status": "success",
        "tool": "structured_extraction",
        "doc_id": doc_id,
        "question": question,
        "selected_tools": tools,
        "item_count": len(items),
        "counts_by_type": dict(sorted(counts.items())),
        "items": items,
        "citations": [_citation_from_item(item) for item in items[:10] if item.get("block_id")],
        "warnings": warnings,
    }


def _date_items(blocks: list[EvidenceBlock], *, limit: int) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    items: list[dict[str, Any]] = []
    for block in blocks:
        text = block.retrieval_text
        if not text:
            continue
        for pattern in DATE_PATTERNS:
            for match in pattern.finditer(text):
                value = " ".join(match.group(0).split())
                key = (value.casefold(), block.block_id)
                if key in seen:
                    continue
                seen.add(key)
                items.append(_item(block, item_type="date", value=value, text=text))
                if len(items) >= limit:
                    return items
    return items


def _block_items(blocks: list[EvidenceBlock], block_types: set[str], item_type: str, *, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in blocks:
        if block.block_type not in block_types:
            continue
        value = block.metadata.get("raw_mineru_type") or block.block_type
        items.append(_item(block, item_type=item_type, value=str(value), text=block.retrieval_text))
        if len(items) >= limit:
            return items
    return items


def _section_items(blocks: list[EvidenceBlock], *, limit: int) -> list[dict[str, Any]]:
    seen: set[str] = set()
    items: list[dict[str, Any]] = []
    for block in blocks:
        section_values = []
        section_title = block.metadata.get("section_title")
        if section_title:
            section_values.append(str(section_title))
        section_path = block.metadata.get("section_path")
        if isinstance(section_path, list):
            section_values.extend(str(item) for item in section_path if str(item).strip())
        raw_type = str(block.metadata.get("raw_mineru_type") or "").casefold()
        if raw_type in {"title", "heading", "section_header"} and block.text:
            section_values.append(block.text)
        for value in section_values:
            normalized = " ".join(value.split())
            if not normalized or normalized.casefold() in seen:
                continue
            seen.add(normalized.casefold())
            items.append(_item(block, item_type="section", value=normalized, text=block.retrieval_text or block.text))
            if len(items) >= limit:
                return items
    return items


def _generic_items(blocks: list[EvidenceBlock], *, limit: int) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for block in blocks:
        if not block.retrieval_text:
            continue
        items.append(_item(block, item_type=block.block_type, value=block.block_type, text=block.retrieval_text))
        if len(items) >= limit:
            return items
    return items


def _item(block: EvidenceBlock, *, item_type: str, value: str, text: str) -> dict[str, Any]:
    return {
        "type": item_type,
        "value": value,
        "doc_id": block.doc_id,
        "page": _block_page(block),
        "block_id": block.block_id,
        "block_type": block.block_type,
        "text_preview": _preview(text),
    }


def _citation_from_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": item.get("doc_id"),
        "page": item.get("page"),
        "block_id": item.get("block_id"),
        "block_type": item.get("block_type"),
        "text_preview": item.get("text_preview") or "",
    }


def _block_page(block: EvidenceBlock) -> int | None:
    if block.page_id is not None:
        return int(block.page_id)
    if block.location.page is not None:
        return int(block.location.page)
    return None


def _preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    return " ".join((text or "").split())[:limit]


def _error(code: str, message: str, **details: Any) -> dict[str, Any]:
    error = {"code": code, "message": message}
    error.update(details)
    return {"status": "error", "tool": "structured_extraction", "error": error}

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from docagent.schemas import EvidenceBlock
from docagent.storage.repositories import DocumentRepository


DEFAULT_PAGE_PREVIEW_CHARS = 300
DEFAULT_LIST_PREVIEW_CHARS = 160


def count_pages(repository: DocumentRepository, doc_id: str) -> dict[str, Any]:
    document = repository.get_document(doc_id)
    if document is None:
        return _error("count_pages", doc_id, "document_not_found", "Document was not found.")

    page_count = document.get("page_count")
    if page_count is not None:
        return {
            "status": "success",
            "tool": "count_pages",
            "doc_id": doc_id,
            "page_count": int(page_count),
            "source": "documents.page_count",
        }

    blocks = repository.load_evidence_blocks(doc_id, include_page_blocks=True)
    page_blocks = [block for block in blocks if block.block_type == "page" and _block_page(block) is not None]
    if page_blocks:
        return {
            "status": "success",
            "tool": "count_pages",
            "doc_id": doc_id,
            "page_count": len({_block_page(block) for block in page_blocks}),
            "source": "evidence_blocks.page_blocks",
        }

    pages = _available_pages(blocks)
    return {
        "status": "success",
        "tool": "count_pages",
        "doc_id": doc_id,
        "page_count": len(pages),
        "source": "evidence_blocks.page_ids",
    }


def count_blocks(repository: DocumentRepository, doc_id: str) -> dict[str, Any]:
    document = repository.get_document(doc_id)
    if document is None:
        return _error("count_blocks", doc_id, "document_not_found", "Document was not found.")

    blocks = repository.load_evidence_blocks(doc_id)
    by_type = Counter(block.block_type for block in blocks)
    return {
        "status": "success",
        "tool": "count_blocks",
        "doc_id": doc_id,
        "block_count": len(blocks),
        "by_block_type": dict(sorted(by_type.items())),
        "source": "evidence_blocks",
        "includes_page_blocks": False,
    }


def count_tables(repository: DocumentRepository, doc_id: str) -> dict[str, Any]:
    document = repository.get_document(doc_id)
    if document is None:
        return _error("count_tables", doc_id, "document_not_found", "Document was not found.")

    tables = [block for block in repository.load_evidence_blocks(doc_id) if block.block_type == "table"]
    return {
        "status": "success",
        "tool": "count_tables",
        "doc_id": doc_id,
        "table_count": len(tables),
        "table_html_count": sum(1 for block in tables if block.table_html),
        "tables": [_block_summary(block) for block in tables],
        "source": "evidence_blocks.block_type",
    }


def count_images(repository: DocumentRepository, doc_id: str) -> dict[str, Any]:
    document = repository.get_document(doc_id)
    if document is None:
        return _error("count_images", doc_id, "document_not_found", "Document was not found.")

    image_blocks = [
        block
        for block in repository.load_evidence_blocks(doc_id)
        if block.block_type in {"image", "figure"}
    ]
    by_raw_type = Counter(str(block.metadata.get("raw_mineru_type") or block.block_type) for block in image_blocks)
    return {
        "status": "success",
        "tool": "count_images",
        "doc_id": doc_id,
        "image_count": len(image_blocks),
        "chart_count": by_raw_type.get("chart", 0),
        "by_raw_type": dict(sorted(by_raw_type.items())),
        "images": [_block_summary(block) for block in image_blocks],
        "source": "evidence_blocks.block_type",
    }


def get_page_text(
    repository: DocumentRepository,
    doc_id: str,
    page: int,
    *,
    text_preview_chars: int = DEFAULT_PAGE_PREVIEW_CHARS,
) -> dict[str, Any]:
    document = repository.get_document(doc_id)
    if document is None:
        return _error("get_page_text", doc_id, "document_not_found", "Document was not found.")
    if page < 1:
        return _error("get_page_text", doc_id, "invalid_page", "Page must be a 1-based positive integer.", page=page)

    page_infos = _page_infos(repository.load_evidence_blocks(doc_id, include_page_blocks=True))
    if page not in page_infos:
        return _error(
            "get_page_text",
            doc_id,
            "page_not_found",
            "Page was not found for this document.",
            page=page,
            available_pages=sorted(page_infos),
        )

    info = page_infos[page]
    preview = _preview(info["text"], text_preview_chars)
    return {
        "status": "success",
        "tool": "get_page_text",
        "doc_id": doc_id,
        "page": page,
        "text": info["text"],
        "text_preview": preview["text_preview"],
        "text_preview_chars": text_preview_chars,
        "truncated": preview["truncated"],
        "block_ids": info["block_ids"],
        "page_block_id": info["page_block_id"],
        "child_block_ids": info["child_block_ids"],
        "source": info["source"],
    }


def list_pages(
    repository: DocumentRepository,
    doc_id: str,
    *,
    text_preview_chars: int = DEFAULT_LIST_PREVIEW_CHARS,
) -> dict[str, Any]:
    document = repository.get_document(doc_id)
    if document is None:
        return _error("list_pages", doc_id, "document_not_found", "Document was not found.")

    page_infos = _page_infos(repository.load_evidence_blocks(doc_id, include_page_blocks=True))
    pages = []
    for page in sorted(page_infos):
        info = page_infos[page]
        preview = _preview(info["text"], text_preview_chars)
        pages.append(
            {
                "page": page,
                "block_count": info["block_count"],
                "page_block_id": info["page_block_id"],
                "text_preview": preview["text_preview"],
                "text_preview_chars": text_preview_chars,
                "truncated": preview["truncated"],
                "source": info["source"],
            }
        )

    return {
        "status": "success",
        "tool": "list_pages",
        "doc_id": doc_id,
        "page_count": len(pages),
        "pages": pages,
        "source": "evidence_blocks",
    }


def _error(tool: str, doc_id: str, code: str, message: str, **details: Any) -> dict[str, Any]:
    error = {"code": code, "message": message}
    error.update(details)
    return {"status": "error", "tool": tool, "doc_id": doc_id, "error": error}


def _block_page(block: EvidenceBlock) -> int | None:
    if block.page_id is not None:
        return int(block.page_id)
    if block.location.page is not None:
        return int(block.location.page)
    return None


def _available_pages(blocks: list[EvidenceBlock]) -> list[int]:
    return sorted({page for block in blocks if (page := _block_page(block)) is not None})


def _page_infos(blocks: list[EvidenceBlock]) -> dict[int, dict[str, Any]]:
    children_by_page: dict[int, list[EvidenceBlock]] = defaultdict(list)
    page_blocks: dict[int, EvidenceBlock] = {}

    for block in blocks:
        page = _block_page(block)
        if page is None:
            continue
        if block.block_type == "page":
            page_blocks[page] = block
        else:
            children_by_page[page].append(block)

    pages = sorted(set(page_blocks) | set(children_by_page))
    infos: dict[int, dict[str, Any]] = {}
    for page in pages:
        page_block = page_blocks.get(page)
        children = children_by_page.get(page, [])
        if page_block is not None and page_block.text:
            text = page_block.text
            source = "page_block"
            block_ids = [page_block.block_id]
        else:
            text = "\n".join(block.retrieval_text for block in children if block.retrieval_text).strip()
            source = "child_blocks"
            block_ids = [block.block_id for block in children]

        metadata_child_ids = []
        if page_block is not None:
            metadata_child_ids = [str(item) for item in page_block.metadata.get("child_block_ids", [])]
        child_block_ids = metadata_child_ids or [block.block_id for block in children]

        infos[page] = {
            "text": text,
            "block_ids": block_ids,
            "child_block_ids": child_block_ids,
            "block_count": len(children) if children else len(child_block_ids),
            "page_block_id": page_block.block_id if page_block is not None else None,
            "source": source,
        }
    return infos


def _preview(text: str, limit: int) -> dict[str, Any]:
    normalized = " ".join((text or "").split())
    if limit < 0:
        limit = 0
    return {
        "text_preview": normalized[:limit],
        "truncated": len(normalized) > limit,
    }


def _block_summary(block: EvidenceBlock) -> dict[str, Any]:
    page = _block_page(block)
    return {
        "block_id": block.block_id,
        "page": page,
        "block_type": block.block_type,
        "raw_mineru_type": block.metadata.get("raw_mineru_type"),
    }

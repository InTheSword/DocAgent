from __future__ import annotations

import re
from typing import Any

from docagent.storage.repositories import DocumentRepository


STRATEGY = "extractive_page_preview_v1"
MIN_TEXT_CHARS = 12


def summarize_document(
    repository: DocumentRepository,
    doc_id: str,
    *,
    question: str | None = None,
    page_range: list[int] | None = None,
    max_pages: int = 8,
    max_blocks_per_page: int = 4,
    max_key_points: int = 8,
    max_chars_per_point: int = 240,
    max_answer_chars: int = 2500,
) -> dict[str, Any]:
    """Build a deterministic, evidence-grounded document summary."""

    document = _load_document(repository, doc_id)
    if document is None:
        return _error_result(
            doc_id=doc_id,
            status="error",
            code="document_not_found_or_unreadable",
            message="Unable to summarize the document because it could not be loaded.",
            answer="Unable to summarize the document because it could not be loaded.",
            blocks_loaded=0,
        )

    try:
        blocks = list(repository.load_evidence_blocks(doc_id))
    except Exception as exc:
        return _error_result(
            doc_id=doc_id,
            status="error",
            code="document_not_found_or_unreadable",
            message=str(exc),
            answer="Unable to summarize the document because it could not be loaded.",
            blocks_loaded=0,
        )

    if not blocks:
        return _error_result(
            doc_id=doc_id,
            status="error",
            code="no_evidence_blocks",
            message="No evidence blocks were found for this document.",
            answer="Unable to summarize the document because no evidence blocks were found.",
            blocks_loaded=0,
        )

    warnings: list[str] = []
    normalized = _normalize_blocks(blocks, warnings)
    if not normalized:
        return _error_result(
            doc_id=doc_id,
            status="unsupported",
            code="no_textual_evidence_for_summary",
            message="The document has evidence blocks but no textual content suitable for extractive summary.",
            answer="Unable to summarize the document because no textual evidence was found.",
            blocks_loaded=len(blocks),
            warnings=warnings,
        )

    requested_pages = page_range or _parse_page_range(question or "")
    grouped = _group_by_page(normalized)
    selected, pages_considered, truncated = _select_blocks(
        grouped,
        page_range=requested_pages,
        max_pages=max(1, int(max_pages)),
        max_blocks_per_page=max(1, int(max_blocks_per_page)),
    )
    if truncated:
        warnings.append("summary_truncated_by_max_pages")
    if requested_pages and not selected:
        warnings.append("requested_summary_pages_not_found")

    if not selected:
        return _error_result(
            doc_id=doc_id,
            status="unsupported",
            code="no_textual_evidence_for_summary",
            message="The requested summary scope has no textual evidence suitable for extractive summary.",
            answer="Unable to summarize the requested scope because no textual evidence was found.",
            blocks_loaded=len(blocks),
            warnings=warnings,
        )

    title_candidates = _select_title_candidates(selected)
    key_points = _build_key_points(
        selected,
        max_key_points=max(1, int(max_key_points)),
        max_chars_per_point=max(1, int(max_chars_per_point)),
    )
    page_summaries = _build_page_summaries(selected, max_chars_per_point=max(1, int(max_chars_per_point)))
    citations = _dedupe_citations(
        [citation for point in key_points for citation in point["citations"]]
        + [citation for page in page_summaries for citation in page["citations"]]
    )

    valid_block_ids = {str(_get_field(block, "block_id", "")) for block in blocks if _get_field(block, "block_id", "")}
    citations, citation_warnings = _validate_citations(citations, valid_block_ids, _page_count(document))
    warnings.extend(citation_warnings)

    summary = {
        "strategy": STRATEGY,
        "scope": {
            "doc_id": doc_id,
            "page_count": _page_count(document),
            "pages_considered": pages_considered,
            "blocks_loaded": len(blocks),
            "blocks_considered": len(selected),
            "max_pages": max_pages,
            "max_blocks_per_page": max_blocks_per_page,
            "max_key_points": max_key_points,
        },
        "title_candidates": title_candidates,
        "key_points": key_points,
        "page_summaries": page_summaries,
    }
    trace = _trace(
        blocks_loaded=len(blocks),
        blocks_considered=len(selected),
        pages_considered=pages_considered,
        warnings_count=len(list(dict.fromkeys(warnings))),
    )
    return {
        "task_type": "document_summary",
        "status": "completed",
        "doc_id": doc_id,
        "answer": _build_answer(question or "", key_points, max_answer_chars=max(1, int(max_answer_chars))),
        "summary": summary,
        "citations": citations,
        "supporting_evidence_ids": [citation["block_id"] for citation in citations if citation.get("block_id")],
        "warnings": list(dict.fromkeys(warnings)),
        "trace": trace,
        "error": {},
    }


def _load_document(repository: DocumentRepository, doc_id: str) -> dict[str, Any] | None:
    get_document = getattr(repository, "get_document", None)
    if get_document is None:
        return {}
    try:
        document = get_document(doc_id)
    except Exception:
        return None
    return document


def _normalize_blocks(blocks: list[Any], warnings: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    missing_page = False
    for index, block in enumerate(blocks):
        block_id = str(_get_field(block, "block_id", "") or "")
        if not block_id:
            continue
        text = _clean_text(_block_text(block))
        if not text:
            continue
        if len(text) < MIN_TEXT_CHARS and not _is_heading_like(text):
            continue
        dedupe_key = text.casefold()[:160]
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        page = _block_page(block)
        if page is None:
            missing_page = True
        item = {
            "doc_id": str(_get_field(block, "doc_id", "") or ""),
            "page": page,
            "block_id": block_id,
            "block_type": str(_get_field(block, "block_type", "") or "text"),
            "text": text,
            "source_order": index,
        }
        item["score"] = _score_item(item)
        items.append(item)
    if missing_page:
        warnings.append("missing_page_metadata")
    return items


def _block_text(block: Any) -> str:
    text = str(_get_field(block, "text", "") or "")
    if text.strip():
        return text
    visual_summary = str(_get_field(block, "visual_summary", "") or "")
    if visual_summary.strip():
        return visual_summary
    table_html = str(_get_field(block, "table_html", "") or "")
    if table_html.strip():
        return re.sub(r"<[^>]+>", " ", table_html)
    return ""


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _group_by_page(items: list[dict[str, Any]]) -> dict[int | None, list[dict[str, Any]]]:
    grouped: dict[int | None, list[dict[str, Any]]] = {}
    for item in items:
        grouped.setdefault(item.get("page"), []).append(item)
    for page_items in grouped.values():
        page_items.sort(key=lambda item: int(item["source_order"]))
    return grouped


def _select_blocks(
    grouped: dict[int | None, list[dict[str, Any]]],
    *,
    page_range: list[int] | None,
    max_pages: int,
    max_blocks_per_page: int,
) -> tuple[list[dict[str, Any]], list[int | None], bool]:
    pages = _ordered_pages(grouped)
    if page_range:
        requested = {int(page) for page in page_range if int(page) > 0}
        pages = [page for page in pages if page in requested]
    pages_considered = pages[:max_pages]
    selected: list[dict[str, Any]] = []
    for page in pages_considered:
        candidates = sorted(grouped.get(page, []), key=lambda item: (-float(item["score"]), int(item["source_order"])))
        chosen = candidates[:max_blocks_per_page]
        selected.extend(sorted(chosen, key=lambda item: int(item["source_order"])))
    selected.sort(key=lambda item: (_page_sort_key(item.get("page")), int(item["source_order"])))
    return selected, pages_considered, len(pages) > len(pages_considered)


def _ordered_pages(grouped: dict[int | None, list[dict[str, Any]]]) -> list[int | None]:
    return sorted(grouped, key=_page_sort_key)


def _select_title_candidates(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pages = [page for page in _ordered_pages(_group_by_page(selected)) if page is not None][:2]
    candidates = []
    for item in selected:
        if item.get("page") not in pages:
            continue
        text = str(item.get("text") or "")
        if not _is_heading_like(text):
            continue
        candidates.append({"text": _truncate(text, 160), "page": item.get("page"), "block_id": item.get("block_id")})
    return candidates[:3]


def _build_key_points(
    selected: list[dict[str, Any]],
    *,
    max_key_points: int,
    max_chars_per_point: int,
) -> list[dict[str, Any]]:
    key_points = []
    for item in selected[:max_key_points]:
        key_points.append({"text": _truncate(str(item["text"]), max_chars_per_point), "citations": [_make_citation(item)]})
    return key_points


def _build_page_summaries(
    selected: list[dict[str, Any]],
    *,
    max_chars_per_point: int,
) -> list[dict[str, Any]]:
    grouped = _group_by_page(selected)
    page_summaries = []
    for page in _ordered_pages(grouped):
        items = grouped[page]
        preview = _truncate(" ".join(str(item["text"]) for item in items[:2]), max_chars_per_point * 2)
        page_summaries.append(
            {
                "page": page,
                "summary": preview,
                "citations": [_make_citation(item) for item in items[:2]],
            }
        )
    return page_summaries


def _make_citation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": item.get("doc_id") or "",
        "page": item.get("page"),
        "block_id": item.get("block_id") or "",
        "block_type": item.get("block_type") or "",
        "text_preview": _truncate(str(item.get("text") or ""), 180),
    }


def _dedupe_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    seen: set[str] = set()
    for citation in citations:
        key = str(citation.get("block_id") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(citation)
    return result


def _validate_citations(
    citations: list[dict[str, Any]],
    valid_block_ids: set[str],
    page_count: int | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    valid: list[dict[str, Any]] = []
    for citation in citations:
        block_id = str(citation.get("block_id") or "")
        if block_id not in valid_block_ids:
            warnings.append("invalid_summary_citation_block_id")
            continue
        page = citation.get("page")
        if page_count is not None and page is not None:
            try:
                if int(page) > page_count:
                    warnings.append("summary_citation_page_exceeds_document_page_count")
            except (TypeError, ValueError):
                warnings.append("invalid_summary_citation_page")
        valid.append(citation)
    return valid, list(dict.fromkeys(warnings))


def _score_item(item: dict[str, Any]) -> float:
    text = str(item.get("text") or "")
    length_score = min(len(text) / 400.0, 1.0)
    heading_bonus = 0.3 if _is_heading_like(text) else 0.0
    page = item.get("page")
    early_page_bonus = 0.1 if page in {1, 2} else 0.0
    informative_bonus = 0.1 if _has_informative_keyword(text) else 0.0
    boilerplate_penalty = 0.25 if _looks_like_boilerplate(text) else 0.0
    return length_score + heading_bonus + early_page_bonus + informative_bonus - boilerplate_penalty


def _is_heading_like(text: str) -> bool:
    stripped = text.strip()
    if len(stripped) < 4 or len(stripped) > 100:
        return False
    if stripped.endswith((".", "。", "?", "？", "!", "！", ";", "；")):
        return False
    return True


def _has_informative_keyword(text: str) -> bool:
    normalized = text.casefold()
    keywords = {
        "abstract",
        "background",
        "conclusion",
        "findings",
        "overview",
        "purpose",
        "report",
        "result",
        "summary",
        "背景",
        "报告",
        "结果",
        "结论",
        "目的",
        "主要",
        "摘要",
    }
    return any(keyword in normalized for keyword in keywords)


def _looks_like_boilerplate(text: str) -> bool:
    normalized = text.casefold()
    return any(
        marker in normalized
        for marker in (
            "all rights reserved",
            "confidential",
            "page ",
            "copyright",
            "www.",
            "http://",
            "https://",
        )
    )


def _build_answer(question: str, key_points: list[dict[str, Any]], *, max_answer_chars: int) -> str:
    heading = "文档摘要：" if _is_cjk(question) else "Document summary:"
    lines = [heading]
    for point in key_points:
        text = str(point.get("text") or "").strip()
        if text:
            lines.append(f"- {text}")
    return _truncate("\n".join(lines), max_answer_chars)


def _is_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text or "")


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3].rstrip() + "..."


def _parse_page_range(question: str) -> list[int] | None:
    matches = re.findall(r"\b(?:page|p\.)\s*(\d+)\b", question, flags=re.IGNORECASE)
    matches.extend(re.findall(r"第\s*(\d+)\s*页", question))
    pages = [int(item) for item in matches if int(item) > 0]
    return list(dict.fromkeys(pages)) or None


def _block_page(block: Any) -> int | None:
    location = _get_field(block, "location", None)
    page = _get_field(location, "page", None)
    if page is None:
        page = _get_field(block, "page_id", None)
    metadata = _get_field(block, "metadata", {}) or {}
    if page is None:
        page = _get_field(metadata, "page", None)
    try:
        return int(page) if page is not None else None
    except (TypeError, ValueError):
        return None


def _page_count(document: dict[str, Any] | Any | None) -> int | None:
    if not document:
        return None
    page_count = _get_field(document, "page_count", None)
    try:
        return int(page_count) if page_count is not None else None
    except (TypeError, ValueError):
        return None


def _page_sort_key(page: int | None) -> tuple[int, int]:
    if page is None:
        return (1, 0)
    return (0, int(page))


def _get_field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _trace(
    *,
    blocks_loaded: int,
    blocks_considered: int,
    pages_considered: list[int | None],
    warnings_count: int,
) -> dict[str, Any]:
    return {
        "tool": "document_summary",
        "strategy": STRATEGY,
        "used_llm": False,
        "used_vlm": False,
        "used_training": False,
        "blocks_loaded": blocks_loaded,
        "blocks_considered": blocks_considered,
        "pages_considered": pages_considered,
        "warnings_count": warnings_count,
    }


def _error_result(
    *,
    doc_id: str,
    status: str,
    code: str,
    message: str,
    answer: str,
    blocks_loaded: int,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    warnings = list(dict.fromkeys(warnings or []))
    return {
        "task_type": "document_summary",
        "status": status,
        "doc_id": doc_id,
        "answer": answer,
        "summary": None,
        "citations": [],
        "supporting_evidence_ids": [],
        "warnings": warnings,
        "trace": _trace(blocks_loaded=blocks_loaded, blocks_considered=0, pages_considered=[], warnings_count=len(warnings)),
        "error": {"code": code, "message": message},
    }

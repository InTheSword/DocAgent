from __future__ import annotations

import re

from docagent.retrieval.base import RetrievalFilter


PRINTED_PAGE_RE = re.compile(
    r"\b(?:printed|labelled|labeled)\s+page\s+([A-Za-z0-9-]+)\b|(?:印刷|标注)页码\s*[:：]?\s*([A-Za-z0-9一二三四五六七八九十-]+)",
    flags=re.IGNORECASE,
)
DOCUMENT_PAGE_RE = re.compile(r"\bpage\s*(\d+)\b|第\s*(\d+)\s*页", flags=re.IGNORECASE)
DOCUMENT_PAGE_RANGE_RE = re.compile(
    r"\bpages?\s*(\d+)\s*(?:-|–|—|to)\s*(\d+)\b|第\s*(\d+)\s*(?:-|–|—|至|到)\s*(\d+)\s*页",
    flags=re.IGNORECASE,
)
SECTION_NUMBER_RE = re.compile(
    r"\b(?:section|chapter)\s+(\d+(?:\.\d+)*)\b|第\s*(\d+(?:\.\d+)*)\s*(?:节|章)",
    flags=re.IGNORECASE,
)
TABLE_RE = re.compile(
    r"\btable\s*\d+\b|\btable\s+(?:chunk|block|result)s?\b|\bresults?\s+table\b|表\s*\d+\b|表格(?:块|片段)?",
    flags=re.IGNORECASE,
)
CHART_RE = re.compile(r"\bchart\s+(?:chunk|block)s?\b|图表(?:块|片段)?", flags=re.IGNORECASE)
FIGURE_RE = re.compile(
    r"\b(?:figure|fig\.?|image|picture)\s*\d+\b|\b(?:figure|image|picture)\s+(?:chunk|block)s?\b|"
    r"(?:图|图片|图像)\s*\d+\b|(?:图片|图像)(?:块|片段)",
    flags=re.IGNORECASE,
)
VISUAL_BLOCK_RE = re.compile(r"\bvisual\s+(?:chunk|block)s?\b|视觉(?:块|片段)", flags=re.IGNORECASE)
DOCUMENT_TITLE_RE = re.compile(
    r"\b(?:paper|document)\s+title\b|论文标题|文档标题",
    flags=re.IGNORECASE,
)
SECTION_TITLE_RE = re.compile(
    r"\b(?:section|chapter)\s+title\b|章节标题",
    flags=re.IGNORECASE,
)
HEADER_RE = re.compile(r"\bpage\s+header\b|页眉", flags=re.IGNORECASE)
FOOTER_RE = re.compile(r"\bpage\s+footer\b|页脚", flags=re.IGNORECASE)
PAGE_NUMBER_RE = re.compile(r"\bpage\s+number\s+(?:chunk|block)\b|页码(?:块|片段)", flags=re.IGNORECASE)
BODY_RE = re.compile(r"\bbody\s+text\b|正文(?:块|片段)?", flags=re.IGNORECASE)


def infer_metadata_filter(question: str) -> RetrievalFilter:
    """Infer only explicit navigation constraints; semantic terms stay unfiltered."""

    text = " ".join(str(question or "").split())
    printed_pages = _matches(PRINTED_PAGE_RE, text)
    text_without_printed = PRINTED_PAGE_RE.sub(" ", text)
    page_ids_set = {int(value) for value in _matches(DOCUMENT_PAGE_RE, text_without_printed)}
    for match in DOCUMENT_PAGE_RANGE_RE.finditer(text_without_printed):
        values = [int(group) for group in match.groups() if group]
        if len(values) == 2:
            start, end = sorted(values)
            page_ids_set.update(range(start, end + 1))
    page_ids = tuple(sorted(page_ids_set))
    section_queries = tuple(dict.fromkeys(value.casefold() for value in _matches(SECTION_NUMBER_RE, text)))

    block_types: set[str] = set()
    content_types: set[str] = set()
    heading_roles: set[str] = set()
    raw_types: set[str] = set()
    if TABLE_RE.search(text):
        block_types.add("table")
        content_types.add("table")
    if CHART_RE.search(text):
        content_types.add("chart")
        raw_types.add("chart")
    if FIGURE_RE.search(text):
        block_types.add("image")
        content_types.update(("image", "figure", "chart"))
    if VISUAL_BLOCK_RE.search(text):
        block_types.update(("image", "table"))
    if DOCUMENT_TITLE_RE.search(text):
        content_types.add("heading")
        heading_roles.add("document_title")
    if SECTION_TITLE_RE.search(text):
        content_types.add("heading")
        heading_roles.add("section_heading")
    if HEADER_RE.search(text):
        content_types.add("page_header")
    if FOOTER_RE.search(text):
        content_types.add("page_footer")
    if PAGE_NUMBER_RE.search(text):
        content_types.add("page_number")
    if BODY_RE.search(text):
        content_types.add("body")

    return RetrievalFilter(
        page_ids=page_ids,
        block_types=tuple(sorted(block_types)),
        content_types=tuple(sorted(content_types)),
        heading_roles=tuple(sorted(heading_roles)),
        raw_mineru_types=tuple(sorted(raw_types)),
        printed_page_numbers=tuple(dict.fromkeys(value.casefold() for value in printed_pages)),
        section_queries=section_queries,
    )


def _matches(pattern: re.Pattern[str], text: str) -> tuple[str, ...]:
    result: list[str] = []
    for match in pattern.finditer(text):
        value = next((group for group in match.groups() if group), "")
        if value:
            result.append(value)
    return tuple(result)

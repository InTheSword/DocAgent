from __future__ import annotations

import re

from docagent.retrieval.query_rewrite import rewrite_query


PAGE_RE = re.compile(r"\b(?:page|p\.)\s*(\d+)\b", flags=re.IGNORECASE)
TABLE_RE = re.compile(
    r"\b(table|row|column|revenue|sales|income|profit|expense|cost|value|amount|rate|ratio|average|sum|difference|growth)\b",
    flags=re.IGNORECASE,
)
IMAGE_RE = re.compile(r"\b(image|figure|chart|graph|picture|visual)\b", flags=re.IGNORECASE)
STAT_RE = re.compile(r"\b(how many|number of|count|pages?|tables?|images?|figures?|blocks?|statistics|metadata)\b", flags=re.IGNORECASE)


def generate_rule_queries(
    question: str,
    *,
    task_type: str = "",
    answer_type_hint: str | None = None,
) -> list[str]:
    """Generate deterministic retrieval queries from task type and keywords."""
    normalized_question = " ".join(str(question or "").split()).strip()
    rewrite = rewrite_query(normalized_question, answer_type_hint=answer_type_hint)
    keyword_query = " ".join(rewrite.keywords[:10]).strip()
    queries: list[str] = []

    page_match = PAGE_RE.search(normalized_question)
    if page_match or task_type == "page_lookup":
        page = page_match.group(1) if page_match else ""
        queries.append(f"page {page}".strip())
        if page:
            queries.append(f"text page {page}")

    if TABLE_RE.search(normalized_question) or task_type == "table_lookup_or_calculation":
        queries.append(f"table {keyword_query}".strip())

    if IMAGE_RE.search(normalized_question) or task_type == "visual_pixel_qa":
        queries.append(f"image figure {keyword_query}".strip())

    if STAT_RE.search(normalized_question) or task_type == "document_statistics":
        queries.append(f"metadata {keyword_query}".strip())
        queries.append(f"document statistics {keyword_query}".strip())

    if task_type == "document_summary":
        queries.append(f"summary overview {keyword_query}".strip())

    if keyword_query:
        queries.append(keyword_query)
    if normalized_question:
        queries.append(normalized_question)

    return _dedup(queries)


def _dedup(items: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = " ".join(str(item or "").split()).strip()
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        result.append(normalized)
        seen.add(key)
    return result

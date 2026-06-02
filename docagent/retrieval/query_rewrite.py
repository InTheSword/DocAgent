from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class QueryRewriteResult:
    rewritten_query: str
    keywords: list[str]
    target_evidence_type: list[str]


YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
NUMBER_RE = re.compile(r"\b\d+(?:\.\d+)?%?\b")
TABLE_TERMS = {
    "average",
    "calculated",
    "change",
    "decrease",
    "increase",
    "largest",
    "less",
    "more",
    "percentage",
    "ratio",
    "smallest",
    "table",
    "total",
    "value",
    "amount",
    "revenue",
    "sales",
    "year",
    "years",
}
VISUAL_TERMS = {"chart", "figure", "image", "infographic", "visual"}


def rewrite_query(question: str, answer_type_hint: str | None = None) -> QueryRewriteResult:
    words = re.findall(r"[A-Za-z][A-Za-z0-9_-]+|[\u4e00-\u9fff]+", question)
    years = YEAR_RE.findall(question)
    numbers = NUMBER_RE.findall(question)
    keywords = []
    for item in [*years, *numbers, *words]:
        normalized = item.lower()
        if normalized not in keywords:
            keywords.append(normalized)
    target = ["text"]
    lowered = question.lower()
    if answer_type_hint == "numeric" or any(term in lowered for term in TABLE_TERMS):
        target = ["table", "text"]
    if answer_type_hint == "visual" or any(term in lowered for term in VISUAL_TERMS):
        target = ["image", "text"]
    rewritten = " ".join(keywords)
    return QueryRewriteResult(rewritten_query=rewritten or question, keywords=keywords, target_evidence_type=target)

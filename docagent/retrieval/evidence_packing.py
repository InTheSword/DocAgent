from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from docagent.schemas import EvidenceBlock


ANSWER_TYPE_HINTS = {"numeric", "date", "heading", "source", "text", "unknown"}
FIELD_HINT_TERMS = {
    "index",
    "percentage",
    "percent",
    "rate",
    "share",
    "source",
    "heading",
    "date",
    "total",
    "amount",
    "page",
    "signature",
}
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "etc",
    "for",
    "from",
    "given",
    "how",
    "in",
    "is",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
}
FORBIDDEN_ARTIFACT_KEYS = {
    "answer_page_idx",
    "answers",
    "gold_answers",
    "gold_page_id",
    "gold_page_mapping",
    "gold_page_ordinal",
    "gold_parsed_page_number",
}

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)?", re.IGNORECASE)
DATE_RE = re.compile(
    r"\b(?:"
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|"
    r"\d{4}[/-]\d{1,2}[/-]\d{1,2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}|"
    r"\d{4}"
    r")\b",
    re.IGNORECASE,
)
NUMERIC_RE = re.compile(r"\b\d+\s*-\s*\d+\b|\(\s*\d+(?:\.\d+)?\s*\)|\b\d+(?:\.\d+)?\s*%?|\b\d+(?:\.\d+)?\b")
PERCENT_RE = re.compile(r"(?:\d+(?:\.\d+)?\s*%|\bpercent(?:age)?\b)", re.IGNORECASE)
ABSOLUTE_PATH_RE = re.compile(r"^(?:[a-zA-Z]:/|/|\\\\|//)")


@dataclass(frozen=True)
class QuestionHint:
    answer_type_hint: str
    keywords: list[str]
    numeric_tokens: list[str]
    date_tokens: list[str]
    field_hints: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer_type_hint": self.answer_type_hint,
            "keywords": list(self.keywords),
            "numeric_tokens": list(self.numeric_tokens),
            "date_tokens": list(self.date_tokens),
            "field_hints": list(self.field_hints),
        }


@dataclass(frozen=True)
class TopPageCandidate:
    page: int | None
    page_aggregate_id: str
    retrieval_rank: int
    retrieval_score: float | None
    child_block_ids: list[str]


@dataclass(frozen=True)
class CandidateSpan:
    candidate_id: str
    doc_id: str
    page: int | None
    page_aggregate_id: str
    retrieval_page_rank: int
    block_ids: list[str]
    primary_block_id: str
    block_types: list[str]
    text: str
    table_html: str | None
    image_path: str | None
    visual_summary: str | None
    bbox: list[float] | None
    score: float
    score_breakdown: dict[str, float]
    matched_terms: list[str]
    detected_values: list[str]
    source: str = "rule_candidate_builder"

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "doc_id": self.doc_id,
            "page": self.page,
            "page_aggregate_id": self.page_aggregate_id,
            "retrieval_page_rank": self.retrieval_page_rank,
            "block_ids": list(self.block_ids),
            "primary_block_id": self.primary_block_id,
            "block_types": list(self.block_types),
            "text": self.text,
            "table_html": self.table_html,
            "image_path": self.image_path,
            "visual_summary": self.visual_summary,
            "bbox": self.bbox,
            "score": round(self.score, 6),
            "score_breakdown": {key: round(value, 6) for key, value in self.score_breakdown.items()},
            "matched_terms": list(self.matched_terms),
            "detected_values": list(self.detected_values),
            "source": self.source,
        }


@dataclass(frozen=True)
class _ScoredBlock:
    block: EvidenceBlock
    top_page: TopPageCandidate
    score: float
    score_breakdown: dict[str, float]
    matched_terms: list[str]
    detected_values: list[str]
    reading_order: int


def parse_question_hints(question: str) -> QuestionHint:
    text = question.lower()
    tokens = TOKEN_RE.findall(text)
    keywords: list[str] = []
    seen_keywords: set[str] = set()
    for token in tokens:
        if token in STOPWORDS or len(token) <= 1:
            continue
        if token not in seen_keywords:
            seen_keywords.add(token)
            keywords.append(token)

    field_hints = [term for term in sorted(FIELD_HINT_TERMS) if term in tokens or term in text]
    numeric_tokens = _unique(NUMERIC_RE.findall(question))
    date_tokens = _unique(DATE_RE.findall(question))

    if any(term in text for term in ("date", "when", "year", "month", "day")) or date_tokens:
        answer_type_hint = "date"
    elif any(term in text for term in ("heading", "title", "subject")):
        answer_type_hint = "heading"
    elif any(term in text for term in ("source", "cited", "bottom", "footer")):
        answer_type_hint = "source"
    elif any(term in text for term in ("how many", "amount", "total", "number", "index", "percentage", "percent", "rate", "value")):
        answer_type_hint = "numeric"
    elif any(term in text for term in ("name", "company", "organization", "what is")):
        answer_type_hint = "text"
    else:
        answer_type_hint = "unknown"

    return QuestionHint(
        answer_type_hint=answer_type_hint,
        keywords=keywords,
        numeric_tokens=numeric_tokens,
        date_tokens=date_tokens,
        field_hints=field_hints,
    )


def candidate_artifact_has_gold_leakage(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered.startswith("gold") or lowered in FORBIDDEN_ARTIFACT_KEYS:
                return True
            if candidate_artifact_has_gold_leakage(item):
                return True
    elif isinstance(value, list):
        return any(candidate_artifact_has_gold_leakage(item) for item in value)
    return False


def summarize_candidate_packing(
    records: list[dict[str, Any]],
    *,
    gold_page_aggregate_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    stats = [record.get("packing_stats") or {} for record in records]
    top_pages_by_qid = {
        str(record.get("qid")): [str(page.get("page_aggregate_id")) for page in record.get("top_pages") or []]
        for record in records
    }
    candidate_pages_by_qid = {
        str(record.get("qid")): {
            str(span.get("page_aggregate_id"))
            for span in record.get("candidate_spans") or []
            if span.get("page_aggregate_id") is not None
        }
        for record in records
    }

    def _values(key: str) -> list[float]:
        return [float(item.get(key) or 0.0) for item in stats]

    mean_original_blocks = _mean(_values("original_block_count"))
    mean_candidate_blocks = _mean(_values("candidate_block_count"))
    mean_tokens_before = _mean(_values("estimated_prompt_tokens_before"))
    mean_tokens_after = _mean(_values("estimated_prompt_tokens_after"))
    gold_page_aggregate_ids = gold_page_aggregate_ids or {}
    gold_qids = [qid for qid in top_pages_by_qid if qid in gold_page_aggregate_ids]
    gold_in_candidate_pages = [
        gold_page_aggregate_ids[qid] in top_pages_by_qid.get(qid, [])
        for qid in gold_qids
    ]
    gold_has_candidate_span = [
        gold_page_aggregate_ids[qid] in candidate_pages_by_qid.get(qid, set())
        for qid in gold_qids
    ]
    return {
        "sample_count": len(records),
        "mean_original_page_count": _mean(_values("original_page_count")),
        "mean_original_block_count": mean_original_blocks,
        "mean_candidate_span_count": _mean(_values("candidate_span_count")),
        "mean_candidate_block_count": mean_candidate_blocks,
        "mean_dropped_block_count": _mean(_values("dropped_block_count")),
        "mean_estimated_prompt_tokens_before": mean_tokens_before,
        "mean_estimated_prompt_tokens_after": mean_tokens_after,
        "compression_ratio_blocks": mean_candidate_blocks / mean_original_blocks if mean_original_blocks else 0.0,
        "compression_ratio_tokens": mean_tokens_after / mean_tokens_before if mean_tokens_before else 0.0,
        "candidate_pages_count_distribution": _distribution([len(pages) for pages in top_pages_by_qid.values()]),
        "candidate_span_count_distribution": _distribution([len(record.get("candidate_spans") or []) for record in records]),
        "gold_page_in_candidate_pages_rate": _mean_bool(gold_in_candidate_pages),
        "gold_page_has_candidate_span_rate": _mean_bool(gold_has_candidate_span),
        "no_gold_leakage": not candidate_artifact_has_gold_leakage(records),
    }


class EvidenceCandidateBuilder:
    def __init__(
        self,
        *,
        max_candidate_spans: int = 12,
        max_candidate_spans_per_page: int = 3,
        neighbor_window: int = 1,
        max_candidate_blocks: int = 32,
        candidate_token_budget: int | None = None,
    ) -> None:
        self.max_candidate_spans = max(1, max_candidate_spans)
        self.max_candidate_spans_per_page = max(1, max_candidate_spans_per_page)
        self.neighbor_window = max(0, neighbor_window)
        self.max_candidate_blocks = max(1, max_candidate_blocks)
        self.candidate_token_budget = candidate_token_budget

    def build(
        self,
        *,
        qid: str,
        doc_id: str,
        question: str,
        top_pages: list[TopPageCandidate],
        child_lookup: dict[str, EvidenceBlock],
    ) -> dict[str, Any]:
        hints = parse_question_hints(question)
        page_blocks = _page_blocks(top_pages, child_lookup)
        original_block_ids = [block.block_id for blocks in page_blocks.values() for block in blocks]
        scored = [
            self._score_block(block=block, top_page=top_page, hints=hints)
            for top_page in top_pages
            for block in page_blocks.get(top_page.page_aggregate_id, [])
        ]
        scored.sort(key=lambda item: (-item.score, item.top_page.retrieval_rank, item.reading_order, item.block.block_id))

        spans = self._select_spans(
            doc_id=doc_id,
            scored=scored,
            page_blocks=page_blocks,
            hints=hints,
            child_lookup=child_lookup,
        )
        if len(spans) < min(len(top_pages), self.max_candidate_spans):
            spans = self._fill_fallback_spans(
                doc_id=doc_id,
                spans=spans,
                top_pages=top_pages,
                page_blocks=page_blocks,
                child_lookup=child_lookup,
            )

        span_dicts = [span.to_dict() for span in spans]
        unique_candidate_blocks = _unique(
            block_id
            for span in span_dicts
            for block_id in span.get("block_ids", [])
        )
        before_text = "\n".join(_block_match_text(child_lookup[block_id]) for block_id in original_block_ids if block_id in child_lookup)
        after_text = "\n".join(str(span.get("text") or "") for span in span_dicts)
        return {
            "qid": qid,
            "doc_id": doc_id,
            "question": question,
            "packing_mode": "candidate_spans",
            "top_pages": [
                {
                    "page": top_page.page,
                    "page_aggregate_id": top_page.page_aggregate_id,
                    "retrieval_rank": top_page.retrieval_rank,
                    "retrieval_score": top_page.retrieval_score,
                }
                for top_page in top_pages
            ],
            "question_hints": hints.to_dict(),
            "candidate_spans": span_dicts,
            "packing_stats": {
                "original_page_count": len(top_pages),
                "original_block_count": len(original_block_ids),
                "candidate_span_count": len(span_dicts),
                "candidate_block_count": len(unique_candidate_blocks),
                "dropped_block_count": max(len(set(original_block_ids)) - len(unique_candidate_blocks), 0),
                "estimated_prompt_tokens_before": estimate_prompt_tokens(before_text),
                "estimated_prompt_tokens_after": estimate_prompt_tokens(after_text),
            },
        }

    def _score_block(
        self,
        *,
        block: EvidenceBlock,
        top_page: TopPageCandidate,
        hints: QuestionHint,
    ) -> _ScoredBlock:
        text = _block_match_text(block)
        lowered = text.lower()
        keyword_hits = [keyword for keyword in hints.keywords if keyword in lowered]
        detected_values = _unique([*NUMERIC_RE.findall(text), *DATE_RE.findall(text)])
        lexical_overlap = min(len(keyword_hits) / max(len(hints.keywords), 1), 1.0) * 0.4
        field_hint_bonus = _field_hint_bonus(hints, lowered, block)
        answer_type_bonus = _answer_type_bonus(hints, lowered, block)
        numeric_bonus = 0.0
        if PERCENT_RE.search(text) and ("percentage" in hints.field_hints or "percent" in hints.field_hints):
            numeric_bonus += 0.25
        if detected_values and hints.answer_type_hint in {"numeric", "date"}:
            numeric_bonus += 0.12
        block_type_bonus = _block_type_bonus(block)
        page_rank_bonus = max(0.0, 0.18 - 0.03 * max(top_page.retrieval_rank - 1, 0))
        boilerplate_penalty = _boilerplate_penalty(hints, lowered, block)
        empty_or_noise_penalty = -0.45 if not text.strip() and not block.image_path else 0.0
        breakdown = {
            "lexical_overlap": lexical_overlap,
            "field_hint_bonus": field_hint_bonus,
            "answer_type_bonus": answer_type_bonus,
            "numeric_bonus": numeric_bonus,
            "block_type_bonus": block_type_bonus,
            "page_rank_bonus": page_rank_bonus,
            "boilerplate_penalty": boilerplate_penalty,
            "empty_or_noise_penalty": empty_or_noise_penalty,
        }
        return _ScoredBlock(
            block=block,
            top_page=top_page,
            score=sum(breakdown.values()),
            score_breakdown=breakdown,
            matched_terms=keyword_hits,
            detected_values=detected_values,
            reading_order=_reading_order(block),
        )

    def _select_spans(
        self,
        *,
        doc_id: str,
        scored: list[_ScoredBlock],
        page_blocks: dict[str, list[EvidenceBlock]],
        hints: QuestionHint,
        child_lookup: dict[str, EvidenceBlock],
    ) -> list[CandidateSpan]:
        spans: list[CandidateSpan] = []
        selected_primary_ids: set[str] = set()
        selected_block_ids: set[str] = set()
        per_page_counts: Counter[str] = Counter()
        estimated_tokens = 0
        for item in scored:
            if len(spans) >= self.max_candidate_spans or len(selected_block_ids) >= self.max_candidate_blocks:
                break
            page_id = item.top_page.page_aggregate_id
            if item.block.block_id in selected_primary_ids:
                continue
            if per_page_counts[page_id] >= self.max_candidate_spans_per_page:
                continue
            if item.score <= 0 and spans:
                continue
            block_ids = self._neighbor_block_ids(
                primary=item.block,
                page_blocks=page_blocks.get(page_id, []),
                selected_block_ids=selected_block_ids,
            )
            if not block_ids:
                continue
            candidate = self._make_span(
                doc_id=doc_id,
                index=len(spans) + 1,
                scored=item,
                block_ids=block_ids,
                child_lookup=child_lookup,
            )
            span_tokens = estimate_prompt_tokens(candidate.text)
            if self.candidate_token_budget and estimated_tokens + span_tokens > self.candidate_token_budget and spans:
                continue
            spans.append(candidate)
            selected_primary_ids.add(item.block.block_id)
            selected_block_ids.update(block_ids)
            per_page_counts[page_id] += 1
            estimated_tokens += span_tokens
        return spans

    def _fill_fallback_spans(
        self,
        *,
        doc_id: str,
        spans: list[CandidateSpan],
        top_pages: list[TopPageCandidate],
        page_blocks: dict[str, list[EvidenceBlock]],
        child_lookup: dict[str, EvidenceBlock],
    ) -> list[CandidateSpan]:
        selected_primary_ids = {span.primary_block_id for span in spans}
        selected_block_ids = {block_id for span in spans for block_id in span.block_ids}
        per_page_counts: Counter[str] = Counter(span.page_aggregate_id for span in spans)
        for top_page in top_pages:
            if len(spans) >= self.max_candidate_spans or len(selected_block_ids) >= self.max_candidate_blocks:
                break
            if per_page_counts[top_page.page_aggregate_id] >= self.max_candidate_spans_per_page:
                continue
            blocks = page_blocks.get(top_page.page_aggregate_id, [])
            fallback = next((block for block in blocks if block.block_id not in selected_primary_ids and _block_match_text(block).strip()), None)
            fallback = fallback or next((block for block in blocks if block.block_id not in selected_primary_ids), None)
            if fallback is None:
                continue
            scored = _ScoredBlock(
                block=fallback,
                top_page=top_page,
                score=0.0,
                score_breakdown={
                    "lexical_overlap": 0.0,
                    "field_hint_bonus": 0.0,
                    "answer_type_bonus": 0.0,
                    "numeric_bonus": 0.0,
                    "block_type_bonus": _block_type_bonus(fallback),
                    "page_rank_bonus": max(0.0, 0.18 - 0.03 * max(top_page.retrieval_rank - 1, 0)),
                    "boilerplate_penalty": 0.0,
                    "empty_or_noise_penalty": 0.0,
                },
                matched_terms=[],
                detected_values=_unique([*NUMERIC_RE.findall(_block_match_text(fallback)), *DATE_RE.findall(_block_match_text(fallback))]),
                reading_order=_reading_order(fallback),
            )
            block_ids = self._neighbor_block_ids(
                primary=fallback,
                page_blocks=blocks,
                selected_block_ids=selected_block_ids,
            )
            if not block_ids:
                continue
            spans.append(
                self._make_span(
                    doc_id=doc_id,
                    index=len(spans) + 1,
                    scored=scored,
                    block_ids=block_ids,
                    child_lookup=child_lookup,
                )
            )
            selected_primary_ids.add(fallback.block_id)
            selected_block_ids.update(block_ids)
            per_page_counts[top_page.page_aggregate_id] += 1
        return spans

    def _neighbor_block_ids(
        self,
        *,
        primary: EvidenceBlock,
        page_blocks: list[EvidenceBlock],
        selected_block_ids: set[str],
    ) -> list[str]:
        ordered = sorted(page_blocks, key=lambda block: (_reading_order(block), block.block_id))
        primary_index = next((index for index, block in enumerate(ordered) if block.block_id == primary.block_id), None)
        if primary_index is None:
            return []
        start = max(0, primary_index - self.neighbor_window)
        end = min(len(ordered), primary_index + self.neighbor_window + 1)
        candidate_ids: list[str] = []
        remaining = max(self.max_candidate_blocks - len(selected_block_ids), 0)
        for block in ordered[start:end]:
            if len(candidate_ids) >= remaining:
                break
            if block.block_id in selected_block_ids and block.block_id != primary.block_id:
                continue
            candidate_ids.append(block.block_id)
        if primary.block_id not in candidate_ids and remaining > 0:
            candidate_ids.insert(0, primary.block_id)
        return candidate_ids[:remaining]

    def _make_span(
        self,
        *,
        doc_id: str,
        index: int,
        scored: _ScoredBlock,
        block_ids: list[str],
        child_lookup: dict[str, EvidenceBlock],
    ) -> CandidateSpan:
        blocks = [child_lookup[block_id] for block_id in block_ids if block_id in child_lookup]
        primary = scored.block
        text = "\n".join(part for part in (_block_match_text(block).strip() for block in blocks) if part)
        block_types = _unique(block.block_type for block in blocks)
        table_html = primary.table_html or next((block.table_html for block in blocks if block.table_html), None)
        image_path = _relative_posix_or_none(primary.image_path or next((block.image_path for block in blocks if block.image_path), None))
        visual_summary = primary.visual_summary or next((block.visual_summary for block in blocks if block.visual_summary), None)
        return CandidateSpan(
            candidate_id=f"c{index:04d}",
            doc_id=doc_id,
            page=scored.top_page.page,
            page_aggregate_id=scored.top_page.page_aggregate_id,
            retrieval_page_rank=scored.top_page.retrieval_rank,
            block_ids=list(block_ids),
            primary_block_id=primary.block_id,
            block_types=block_types,
            text=text,
            table_html=table_html,
            image_path=image_path,
            visual_summary=visual_summary,
            bbox=primary.location.bbox,
            score=scored.score,
            score_breakdown=scored.score_breakdown,
            matched_terms=scored.matched_terms,
            detected_values=scored.detected_values,
        )


def estimate_prompt_tokens(text: str) -> int:
    return max(0, int((len(text or "") + 3) / 4))


def _page_blocks(top_pages: list[TopPageCandidate], child_lookup: dict[str, EvidenceBlock]) -> dict[str, list[EvidenceBlock]]:
    by_page: dict[str, list[EvidenceBlock]] = {}
    for top_page in top_pages:
        blocks = [child_lookup[block_id] for block_id in top_page.child_block_ids if block_id in child_lookup]
        by_page[top_page.page_aggregate_id] = sorted(blocks, key=lambda block: (_reading_order(block), block.block_id))
    return by_page


def _block_match_text(block: EvidenceBlock) -> str:
    parts = [
        block.text or "",
        block.table_html or "",
        block.visual_summary or "",
        str(block.metadata.get("section_title") or ""),
        str(block.metadata.get("raw_mineru_type") or ""),
    ]
    return "\n".join(part for part in parts if part).strip()


def _field_hint_bonus(hints: QuestionHint, lowered_text: str, block: EvidenceBlock) -> float:
    bonus = 0.0
    field_hints = set(hints.field_hints)
    if field_hints & {"index", "share", "rate"} and any(term in lowered_text for term in ("index", "segment", "share", "rate")):
        bonus += 0.2
    if field_hints & {"percentage", "percent"} and PERCENT_RE.search(lowered_text):
        bonus += 0.25
    if "source" in field_hints and any(term in lowered_text for term in ("source", "footer", "cited")):
        bonus += 0.2
    if "heading" in field_hints:
        bonus += 0.25 * _heading_strength(block)
    if "date" in field_hints and DATE_RE.search(lowered_text):
        bonus += 0.18
    if field_hints & {"total", "amount"} and any(term in lowered_text for term in ("total", "amount")):
        bonus += 0.14
    if "signature" in field_hints and any(term in lowered_text for term in ("signature", "signed", "signatory")):
        bonus += 0.2
    return min(bonus, 0.45)


def _answer_type_bonus(hints: QuestionHint, lowered_text: str, block: EvidenceBlock) -> float:
    if hints.answer_type_hint == "numeric":
        return 0.18 if NUMERIC_RE.search(lowered_text) else 0.0
    if hints.answer_type_hint == "date":
        return 0.22 if DATE_RE.search(lowered_text) else 0.0
    if hints.answer_type_hint == "heading":
        return 0.3 * _heading_strength(block)
    if hints.answer_type_hint == "source":
        return 0.22 if any(term in lowered_text for term in ("source", "footer", "cited", "bottom")) else 0.0
    if hints.answer_type_hint == "text":
        return 0.05 if lowered_text.strip() else 0.0
    return 0.0


def _block_type_bonus(block: EvidenceBlock) -> float:
    raw_type = str(block.metadata.get("raw_mineru_type") or "").lower()
    if block.block_type == "table":
        return 0.12
    if block.block_type == "text":
        return 0.06
    if block.block_type in {"image", "figure", "visual_summary"} or raw_type == "chart":
        return 0.08 if block.visual_summary else 0.01
    return 0.0


def _boilerplate_penalty(hints: QuestionHint, lowered_text: str, block: EvidenceBlock) -> float:
    if not block.metadata.get("is_boilerplate") and not block.metadata.get("exclude_from_retrieval"):
        return 0.0
    if hints.answer_type_hint == "source" or "source" in hints.field_hints:
        if any(term in lowered_text for term in ("source", "footer", "cited")):
            return -0.03
    return -0.25


def _is_heading(block: EvidenceBlock) -> bool:
    return _heading_strength(block) > 0.0


def _heading_strength(block: EvidenceBlock) -> float:
    raw_type = str(block.metadata.get("raw_mineru_type") or "").lower()
    if raw_type in {"title", "heading"}:
        return 1.0
    text_level = block.metadata.get("text_level")
    try:
        if text_level is not None and int(text_level) <= 2:
            return 1.0
    except (TypeError, ValueError):
        pass
    bbox = block.location.bbox
    return 0.5 if bbox and len(bbox) >= 2 and float(bbox[1]) <= 160 else 0.0


def _reading_order(block: EvidenceBlock) -> int:
    try:
        return int(block.metadata.get("reading_order", 0))
    except (TypeError, ValueError):
        return 0


def _relative_posix_or_none(value: str | None) -> str | None:
    if not value:
        return None
    text = str(value).replace("\\", "/")
    if "://" in text or ABSOLUTE_PATH_RE.match(text):
        return None
    return text


def _distribution(values: list[int]) -> dict[str, int]:
    return {str(key): count for key, count in sorted(Counter(values).items())}


def _mean(values: list[float]) -> float:
    return sum(values) / max(len(values), 1)


def _mean_bool(values: list[bool]) -> float:
    return sum(1 for value in values if value) / max(len(values), 1)


def _unique(values: Any) -> list[Any]:
    seen: set[Any] = set()
    ordered: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered

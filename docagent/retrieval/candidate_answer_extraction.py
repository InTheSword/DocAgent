from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Any

from docagent.eval.answer_metrics import normalize_text


FORBIDDEN_CANDIDATE_ANSWER_KEYS = {
    "answer_page_idx",
    "answers",
    "gold_answers",
    "gold_page_id",
    "gold_page_mapping",
    "gold_page_ordinal",
}

ANSWER_BUCKET_LABELS = {
    "A": "retrieval_gold_miss_top5",
    "B": "gold_page_in_top5_but_no_candidate_span_on_gold_page",
    "C": "gold_answer_not_in_candidate_spans",
    "D": "gold_answer_in_candidate_spans_but_not_extracted",
    "E": "gold_answer_in_candidate_answers_but_model_answer_wrong",
    "F": "gold_answer_in_candidate_answers_and_model_answer_correct",
    "G": "unclear_or_unclassified",
}

NUMERIC_TYPES = {"numeric", "percentage", "index"}
SOURCE_LINE_RE = re.compile(r"^\s*(source|footer|cited)\s*[:\-]\s*(.+?)\s*$", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s<>)]+", re.IGNORECASE)
USMM_RE = re.compile(r"\bUSMM[^\s,;:)]*", re.IGNORECASE)
DATE_RE = re.compile(
    r"\b(?:"
    r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|"
    r"\d{4}[./-]\d{1,2}[./-]\d{1,2}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{2,4}|"
    r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{2,4}|"
    r"\d{4}"
    r")\b",
    re.IGNORECASE,
)
PERCENT_RE = re.compile(
    r"\b-?\d+(?:,\d{3})*(?:\.\d+)?\s*%|\b-?\d+(?:,\d{3})*(?:\.\d+)?\s+percent(?:age)?\b",
    re.IGNORECASE,
)
INDEX_PAREN_RE = re.compile(r"\(\s*(-?\d+(?:,\d{3})*(?:\.\d+)?)\s*\)")
MONEY_RE = re.compile(r"\$-?\d[\d,]*(?:\.\d+)?")
NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?(?![\w.])")
COLON_VALUE_RE = re.compile(r":\s*([^:\n]{2,80})")


def extract_candidate_answers(
    question: str,
    question_hints: dict[str, Any] | None,
    candidate_spans: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic candidate answer board without reading gold data."""

    hints = _normalize_hints(question, question_hints)
    target_type = _target_answer_type(hints)
    raw_candidates: list[dict[str, Any]] = []
    for span in candidate_spans:
        raw_candidates.extend(_extract_from_span(span=span, hints=hints, target_type=target_type))

    candidates = _dedupe_answers(raw_candidates)
    candidates.sort(
        key=lambda item: (
            -float(item.get("score") or 0.0),
            str(item.get("source_candidate_id") or ""),
            str(item.get("answer_type") or ""),
            str(item.get("answer_text") or ""),
        )
    )
    for index, candidate in enumerate(candidates, start=1):
        candidate["candidate_answer_id"] = f"a{index:04d}"

    stats = _answer_board_stats(candidates, target_type=target_type)
    return {
        "question": question,
        "question_hints": hints,
        "candidate_answers": candidates,
        "answer_board_stats": stats,
    }


def build_candidate_answer_board(candidate_record: dict[str, Any]) -> dict[str, Any]:
    board = extract_candidate_answers(
        question=str(candidate_record.get("question") or ""),
        question_hints=candidate_record.get("question_hints") or {},
        candidate_spans=list(candidate_record.get("candidate_spans") or []),
    )
    return {
        "qid": str(candidate_record.get("qid") or ""),
        "doc_id": str(candidate_record.get("doc_id") or ""),
        **board,
    }


def build_candidate_answer_boards(candidate_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [build_candidate_answer_board(record) for record in candidate_records]


def compute_candidate_answer_coverage(
    candidate_answers: list[dict[str, Any]],
    gold_answers: list[str],
) -> dict[str, Any]:
    normalized_gold = [_normalize_answer(answer) for answer in gold_answers if _normalize_answer(answer)]
    normalized_candidates = [
        str(candidate.get("normalized_answer") or _normalize_answer(candidate.get("answer_text") or ""))
        for candidate in candidate_answers
    ]
    first_rank: int | None = None
    for rank, candidate in enumerate(normalized_candidates, start=1):
        if any(_answer_match(candidate, gold) for gold in normalized_gold):
            first_rank = rank
            break
    return {
        "covered": first_rank is not None,
        "first_rank": first_rank,
        "rank_bucket": _rank_bucket(first_rank),
        "candidate_answer_count": len(candidate_answers),
    }


def summarize_candidate_answer_coverage(
    *,
    candidate_records: list[dict[str, Any]],
    answer_boards: list[dict[str, Any]],
    qa_records: list[dict[str, Any]],
) -> dict[str, Any]:
    records_by_qid = {str(record.get("qid")): record for record in candidate_records}
    boards_by_qid = {str(board.get("qid")): board for board in answer_boards}
    rank_distribution = Counter(
        {"rank_1": 0, "rank_2": 0, "rank_3": 0, "rank_4_5": 0, "rank_6_10": 0, "rank_gt10": 0, "missing": 0}
    )
    by_answer_type: dict[str, list[bool]] = defaultdict(list)
    by_question_hint: dict[str, list[bool]] = defaultdict(list)
    span_hits: list[bool] = []
    answer_hits: list[bool] = []
    candidate_counts: list[float] = []
    unique_counts: list[float] = []
    same_type_distractors: list[float] = []
    numeric_distractors: list[float] = []
    no_candidate_answer_count = 0

    for qa in qa_records:
        qid = str(qa.get("qid"))
        candidate_record = records_by_qid.get(qid, {})
        board = boards_by_qid.get(qid, {})
        gold_answers = _qa_answer_list(qa)
        span_hit = candidate_span_contains_answer(candidate_record.get("candidate_spans") or [], gold_answers)
        coverage = compute_candidate_answer_coverage(board.get("candidate_answers") or [], gold_answers)
        answer_hit = bool(coverage["covered"])
        hint = str((board.get("question_hints") or {}).get("answer_type_hint") or "unknown")
        answer_type = str(qa.get("answer_type") or "unknown")
        stats = board.get("answer_board_stats") or {}

        span_hits.append(span_hit)
        answer_hits.append(answer_hit)
        by_answer_type[answer_type].append(answer_hit)
        by_question_hint[hint].append(answer_hit)
        rank_distribution[str(coverage["rank_bucket"])] += 1
        candidate_counts.append(float(stats.get("candidate_answer_count") or 0.0))
        unique_counts.append(float(stats.get("unique_normalized_answer_count") or 0.0))
        same_type_distractors.append(float(stats.get("same_type_distractor_count") or 0.0))
        numeric_distractors.append(float(stats.get("numeric_distractor_count") or 0.0))
        if not board.get("candidate_answers"):
            no_candidate_answer_count += 1

    return {
        "sample_count": len(qa_records),
        "candidate_span_answer_coverage": _mean_bool(span_hits),
        "candidate_answer_coverage": _mean_bool(answer_hits),
        "candidate_answer_coverage_by_answer_type": _group_rates(by_answer_type),
        "candidate_answer_coverage_by_question_hint": _group_rates(by_question_hint),
        "gold_answer_rank_distribution": dict(rank_distribution),
        "mean_candidate_answer_count": _mean(candidate_counts),
        "mean_unique_candidate_answer_count": _mean(unique_counts),
        "mean_same_type_distractor_count": _mean(same_type_distractors),
        "mean_numeric_distractor_count": _mean(numeric_distractors),
        "no_candidate_answer_count": no_candidate_answer_count,
        "candidate_answer_no_gold_leakage": not candidate_answer_artifact_has_gold_leakage(answer_boards),
    }


def bucket_candidate_answer_failures(
    *,
    candidate_records: list[dict[str, Any]],
    answer_boards: list[dict[str, Any]],
    qa_records: list[dict[str, Any]],
    page_retrieval_rows: list[dict[str, Any]] | None = None,
    answer_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    records_by_qid = {str(record.get("qid")): record for record in candidate_records}
    boards_by_qid = {str(board.get("qid")): board for board in answer_boards}
    retrieval_by_qid = _hybrid_retrieval_by_qid(page_retrieval_rows or [])
    answer_results_by_qid = {str(row.get("qid")): row for row in (answer_results or [])}
    answer_results_available = answer_results is not None
    bucket_counts = Counter({label: 0 for label in ANSWER_BUCKET_LABELS})
    records: list[dict[str, Any]] = []

    for qa in qa_records:
        qid = str(qa.get("qid"))
        candidate_record = records_by_qid.get(qid, {})
        board = boards_by_qid.get(qid, {})
        gold_answers = _qa_answer_list(qa)
        span_covered = candidate_span_contains_answer(candidate_record.get("candidate_spans") or [], gold_answers)
        answer_coverage = compute_candidate_answer_coverage(board.get("candidate_answers") or [], gold_answers)
        answer_covered = bool(answer_coverage["covered"])
        retrieval_row = retrieval_by_qid.get(qid)
        candidate_answer_count = len(board.get("candidate_answers") or [])
        gold_page = _gold_page_number(qa)

        bucket = "G"
        reason = "unclassified"
        if _retrieval_gold_miss_top5(retrieval_row):
            bucket = "A"
            reason = "retrieval_gold_miss_top5"
        elif _gold_page_in_top_pages(candidate_record, gold_page) and not _candidate_span_on_gold_page(candidate_record, gold_page):
            bucket = "B"
            reason = "gold_page_in_top5_but_no_candidate_span_on_gold_page"
        elif not span_covered:
            bucket = "C"
            reason = "gold_answer_not_in_candidate_spans"
        elif not answer_covered:
            bucket = "D"
            reason = "gold_answer_in_candidate_spans_but_not_extracted"
        elif answer_results_available:
            model_correct = _answer_result_correct(answer_results_by_qid.get(qid))
            bucket = "F" if model_correct else "E"
            reason = ANSWER_BUCKET_LABELS[bucket]
        else:
            reason = "answer_results_unavailable"

        bucket_counts[bucket] += 1
        records.append(
            {
                "qid": qid,
                "doc_id": qa.get("doc_id"),
                "question": qa.get("question"),
                "bucket": bucket,
                "reason": reason,
                "counts": {
                    "candidate_span_answer_covered": span_covered,
                    "candidate_answer_covered": answer_covered,
                    "candidate_answer_count": candidate_answer_count,
                    "first_candidate_answer_rank": answer_coverage.get("first_rank"),
                },
            }
        )

    return {
        "sample_count": len(qa_records),
        "bucket_labels": ANSWER_BUCKET_LABELS,
        "bucket_counts": dict(bucket_counts),
        "answer_results_status": "available" if answer_results_available else "unavailable",
        "records": records,
    }


def candidate_span_contains_answer(candidate_spans: list[dict[str, Any]], gold_answers: list[str]) -> bool:
    normalized_gold = [_normalize_answer(answer) for answer in gold_answers if _normalize_answer(answer)]
    if not normalized_gold:
        return False
    text = "\n".join(str(span.get("text") or "") for span in candidate_spans)
    normalized_text = _normalize_answer(text)
    return any(_contains_normalized(normalized_text, gold) for gold in normalized_gold)


def candidate_answer_artifact_has_gold_leakage(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            lowered = str(key).lower()
            if lowered.startswith("gold") or lowered in FORBIDDEN_CANDIDATE_ANSWER_KEYS:
                return True
            if candidate_answer_artifact_has_gold_leakage(item):
                return True
    elif isinstance(value, list):
        return any(candidate_answer_artifact_has_gold_leakage(item) for item in value)
    return False


def _extract_from_span(
    *,
    span: dict[str, Any],
    hints: dict[str, Any],
    target_type: str,
) -> list[dict[str, Any]]:
    text = str(span.get("text") or "")
    candidates: list[dict[str, Any]] = []
    candidates.extend(_extract_source_candidates(text, span=span, hints=hints, target_type=target_type))
    candidates.extend(_extract_heading_candidates(text, span=span, hints=hints, target_type=target_type))
    candidates.extend(_extract_regex_candidates(text, span=span, hints=hints, target_type=target_type))
    candidates.extend(_extract_generic_candidates(text, span=span, hints=hints, target_type=target_type, existing=candidates))
    return candidates


def _extract_regex_candidates(
    text: str,
    *,
    span: dict[str, Any],
    hints: dict[str, Any],
    target_type: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for match in INDEX_PAREN_RE.finditer(text):
        candidates.append(
            _make_answer(
                match.group(1),
                answer_type="index",
                rule="parenthesized_index",
                span=span,
                hints=hints,
                target_type=target_type,
                rule_confidence=0.28,
            )
        )
    for match in PERCENT_RE.finditer(text):
        candidates.append(
            _make_answer(
                match.group(0),
                answer_type="percentage",
                rule="percentage",
                span=span,
                hints=hints,
                target_type=target_type,
                rule_confidence=0.22,
            )
        )
    for match in DATE_RE.finditer(text):
        candidates.append(
            _make_answer(
                match.group(0),
                answer_type="date",
                rule="date",
                span=span,
                hints=hints,
                target_type=target_type,
                rule_confidence=0.2,
            )
        )
    for match in MONEY_RE.finditer(text):
        candidates.append(
            _make_answer(
                match.group(0),
                answer_type="numeric",
                rule="money",
                span=span,
                hints=hints,
                target_type=target_type,
                rule_confidence=0.19,
            )
        )
    for match in NUMBER_RE.finditer(text):
        value = match.group(0)
        if _covered_by_existing(value, candidates):
            continue
        candidates.append(
            _make_answer(
                value,
                answer_type="index" if _index_context(text, hints) else "numeric",
                rule="index_context_number" if _index_context(text, hints) else "numeric",
                span=span,
                hints=hints,
                target_type=target_type,
                rule_confidence=0.16,
            )
        )
    return candidates


def _extract_source_candidates(
    text: str,
    *,
    span: dict[str, Any],
    hints: dict[str, Any],
    target_type: str,
) -> list[dict[str, Any]]:
    if target_type != "source" and "source" not in set(hints.get("field_hints") or []):
        return []
    candidates: list[dict[str, Any]] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = SOURCE_LINE_RE.match(stripped)
        if match:
            candidates.append(
                _make_answer(
                    stripped[:160],
                    answer_type="source",
                    rule="source_line",
                    span=span,
                    hints=hints,
                    target_type=target_type,
                    rule_confidence=0.32,
                )
            )
        for url in URL_RE.findall(stripped):
            candidates.append(
                _make_answer(
                    url,
                    answer_type="source",
                    rule="source_url",
                    span=span,
                    hints=hints,
                    target_type=target_type,
                    rule_confidence=0.3,
                )
            )
        usmm = USMM_RE.search(stripped)
        if usmm:
            candidates.append(
                _make_answer(
                    usmm.group(0),
                    answer_type="source",
                    rule="source_usmm",
                    span=span,
                    hints=hints,
                    target_type=target_type,
                    rule_confidence=0.24,
                )
            )
    return candidates


def _extract_heading_candidates(
    text: str,
    *,
    span: dict[str, Any],
    hints: dict[str, Any],
    target_type: str,
) -> list[dict[str, Any]]:
    if target_type != "heading" and "heading" not in set(hints.get("field_hints") or []):
        return []
    first_line = _first_short_line(text, max_words=12, max_chars=90)
    if not first_line:
        return []
    return [
        _make_answer(
            first_line,
            answer_type="heading",
            rule="heading_first_line",
            span=span,
            hints=hints,
            target_type=target_type,
            rule_confidence=0.26 + _bbox_top_bonus(span),
        )
    ]


def _extract_generic_candidates(
    text: str,
    *,
    span: dict[str, Any],
    hints: dict[str, Any],
    target_type: str,
    existing: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if target_type not in {"text", "unknown"} and existing:
        return []
    values: list[str] = []
    for match in COLON_VALUE_RE.finditer(text):
        values.append(match.group(1).strip(" .;\t"))
    first_line = _first_short_line(text, max_words=10, max_chars=80)
    if first_line:
        values.append(first_line)
    candidates = []
    for value in values:
        if not _valid_short_text(value):
            continue
        candidates.append(
            _make_answer(
                value,
                answer_type="text",
                rule="generic_short_text",
                span=span,
                hints=hints,
                target_type=target_type,
                rule_confidence=0.11,
            )
        )
    return candidates[:2]


def _make_answer(
    answer_text: str,
    *,
    answer_type: str,
    rule: str,
    span: dict[str, Any],
    hints: dict[str, Any],
    target_type: str,
    rule_confidence: float,
) -> dict[str, Any]:
    normalized = _normalize_answer(answer_text)
    field_hint_match = _field_hint_match(answer_type, hints)
    answer_type_match = _answer_type_match(answer_type, target_type)
    lexical_context_match = _lexical_context_match(span, hints)
    candidate_span_score = max(0.0, min(float(span.get("score") or 0.0), 1.0)) * 0.1
    breakdown = {
        "field_hint_match": field_hint_match,
        "answer_type_match": answer_type_match,
        "lexical_context_match": lexical_context_match,
        "candidate_span_score": candidate_span_score,
        "rule_confidence": rule_confidence,
    }
    block_ids = [str(block_id) for block_id in (span.get("block_ids") or [])]
    return {
        "candidate_answer_id": "",
        "answer_text": str(answer_text).strip(),
        "normalized_answer": normalized,
        "answer_type": answer_type,
        "source_candidate_id": str(span.get("candidate_id") or ""),
        "source_block_ids": block_ids,
        "page": span.get("page"),
        "block_id": str(span.get("primary_block_id") or (block_ids[0] if block_ids else "")),
        "evidence_text": str(span.get("text") or ""),
        "extraction_rule": rule,
        "score": round(sum(breakdown.values()), 6),
        "score_breakdown": {key: round(value, 6) for key, value in breakdown.items()},
    }


def _normalize_hints(question: str, question_hints: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(question_hints or {})
    answer_type_hint = str(raw.get("answer_type_hint") or "unknown")
    keywords = [str(item).lower() for item in raw.get("keywords") or []]
    field_hints = [str(item).lower() for item in raw.get("field_hints") or []]
    if "index" in question.lower() and "index" not in field_hints:
        field_hints.append("index")
    if "source" in question.lower() and "source" not in field_hints:
        field_hints.append("source")
    if any(term in question.lower() for term in ("heading", "title", "subject")) and "heading" not in field_hints:
        field_hints.append("heading")
    return {
        "answer_type_hint": answer_type_hint,
        "keywords": _unique(keywords),
        "numeric_tokens": [str(item) for item in raw.get("numeric_tokens") or []],
        "date_tokens": [str(item) for item in raw.get("date_tokens") or []],
        "field_hints": _unique(field_hints),
    }


def _target_answer_type(hints: dict[str, Any]) -> str:
    field_hints = set(hints.get("field_hints") or [])
    answer_type_hint = str(hints.get("answer_type_hint") or "unknown")
    if "index" in field_hints:
        return "index"
    if field_hints & {"percentage", "percent"}:
        return "percentage"
    if answer_type_hint in {"date", "heading", "source", "text"}:
        return answer_type_hint
    if answer_type_hint == "numeric":
        return "numeric"
    return "unknown"


def _field_hint_match(answer_type: str, hints: dict[str, Any]) -> float:
    field_hints = set(hints.get("field_hints") or [])
    if answer_type == "index" and "index" in field_hints:
        return 0.3
    if answer_type == "percentage" and field_hints & {"percentage", "percent", "rate", "share"}:
        return 0.25
    if answer_type == "source" and "source" in field_hints:
        return 0.3
    if answer_type == "heading" and "heading" in field_hints:
        return 0.3
    if answer_type == "date" and "date" in field_hints:
        return 0.22
    if answer_type == "numeric" and field_hints & {"total", "amount", "rate", "value"}:
        return 0.16
    return 0.0


def _answer_type_match(answer_type: str, target_type: str) -> float:
    if answer_type == target_type:
        return 0.3
    if target_type == "numeric" and answer_type in NUMERIC_TYPES:
        return 0.16
    if target_type == "unknown":
        return 0.04
    return 0.0


def _lexical_context_match(span: dict[str, Any], hints: dict[str, Any]) -> float:
    keywords = [keyword for keyword in hints.get("keywords") or [] if len(str(keyword)) > 1]
    if not keywords:
        return 0.0
    text = str(span.get("text") or "").lower()
    hits = sum(1 for keyword in keywords if str(keyword).lower() in text)
    return min(hits / max(len(keywords), 1), 1.0) * 0.2


def _answer_board_stats(candidates: list[dict[str, Any]], *, target_type: str) -> dict[str, Any]:
    distribution = Counter(str(candidate.get("answer_type") or "unknown") for candidate in candidates)
    same_type_count = distribution.get(target_type, 0)
    if target_type == "unknown" and distribution:
        same_type_count = max(distribution.values())
    numeric_count = sum(distribution.get(answer_type, 0) for answer_type in NUMERIC_TYPES)
    return {
        "candidate_answer_count": len(candidates),
        "unique_normalized_answer_count": len({candidate.get("normalized_answer") for candidate in candidates}),
        "answer_type_distribution": dict(sorted(distribution.items())),
        "same_type_distractor_count": max(same_type_count - 1, 0),
        "numeric_distractor_count": max(numeric_count - 1, 0),
    }


def _dedupe_answers(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    for candidate in candidates:
        normalized = str(candidate.get("normalized_answer") or "")
        if not normalized:
            continue
        key = (
            normalized,
            str(candidate.get("answer_type") or ""),
            str(candidate.get("source_candidate_id") or ""),
        )
        current = best_by_key.get(key)
        if current is None or float(candidate.get("score") or 0.0) > float(current.get("score") or 0.0):
            best_by_key[key] = candidate
    return list(best_by_key.values())


def _normalize_answer(value: Any) -> str:
    text = str(value or "").replace(",", "")
    text = text.replace("$", "")
    return normalize_text(text)


def _answer_match(candidate: str, gold: str) -> bool:
    return candidate == gold or _contains_normalized(candidate, gold)


def _contains_normalized(container: str, needle: str) -> bool:
    if not container or not needle:
        return False
    if container == needle:
        return True
    return f" {needle} " in f" {container} "


def _rank_bucket(rank: int | None) -> str:
    if rank is None:
        return "missing"
    if rank <= 3:
        return f"rank_{rank}"
    if rank <= 5:
        return "rank_4_5"
    if rank <= 10:
        return "rank_6_10"
    return "rank_gt10"


def _group_rates(groups: dict[str, list[bool]]) -> dict[str, dict[str, Any]]:
    return {
        key: {
            "sample_count": len(values),
            "covered_count": sum(1 for value in values if value),
            "coverage": _mean_bool(values),
        }
        for key, values in sorted(groups.items())
    }


def _qa_answer_list(record: dict[str, Any]) -> list[str]:
    answers = record.get("answers")
    if isinstance(answers, list):
        return [str(item) for item in answers]
    if answers:
        return [str(answers)]
    return []


def _hybrid_retrieval_by_qid(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_qid: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("mode") or "hybrid") == "hybrid":
            by_qid[str(row.get("qid"))] = row
    return by_qid


def _retrieval_gold_miss_top5(row: dict[str, Any] | None) -> bool:
    if row is None:
        return False
    taxonomy = set(row.get("failure_taxonomy") or [])
    if "retrieval_gold_miss_top5" in taxonomy:
        return True
    rank = row.get("gold_page_rank")
    try:
        return rank is None or int(rank) > 5
    except (TypeError, ValueError):
        return True


def _gold_page_number(qa: dict[str, Any]) -> int | None:
    for key in ("gold_page_ordinal", "parsed_page_number"):
        if qa.get(key) is not None:
            try:
                return int(qa[key])
            except (TypeError, ValueError):
                return None
    if qa.get("answer_page_idx") is not None:
        try:
            return int(qa["answer_page_idx"]) + 1
        except (TypeError, ValueError):
            return None
    return None


def _gold_page_in_top_pages(candidate_record: dict[str, Any], gold_page: int | None) -> bool:
    if gold_page is None:
        return False
    return any(_safe_int(page.get("page")) == gold_page for page in candidate_record.get("top_pages") or [])


def _candidate_span_on_gold_page(candidate_record: dict[str, Any], gold_page: int | None) -> bool:
    if gold_page is None:
        return False
    return any(_safe_int(span.get("page")) == gold_page for span in candidate_record.get("candidate_spans") or [])


def _answer_result_correct(row: dict[str, Any] | None) -> bool:
    if not row:
        return False
    metrics = row.get("answer_metrics") or {}
    return bool(metrics.get("answer_hit") or metrics.get("normalized_exact_match"))


def _first_short_line(text: str, *, max_words: int, max_chars: int) -> str:
    for line in text.splitlines():
        cleaned = line.strip(" .;\t")
        if _valid_short_text(cleaned, max_words=max_words, max_chars=max_chars):
            return cleaned
    sentence = re.split(r"[.;\n]", text.strip(), maxsplit=1)[0].strip(" .;\t")
    if _valid_short_text(sentence, max_words=max_words, max_chars=max_chars):
        return sentence
    return ""


def _valid_short_text(value: str, *, max_words: int = 12, max_chars: int = 90) -> bool:
    text = str(value or "").strip()
    if not text or len(text) > max_chars:
        return False
    words = normalize_text(text).split()
    if not words or len(words) > max_words:
        return False
    stopwords = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "is", "of", "on", "or", "the", "to", "with"}
    return any(word not in stopwords for word in words)


def _covered_by_existing(value: str, candidates: list[dict[str, Any]]) -> bool:
    normalized = _normalize_answer(value)
    return any(_answer_match(str(candidate.get("normalized_answer") or ""), normalized) for candidate in candidates)


def _index_context(text: str, hints: dict[str, Any]) -> bool:
    field_hints = set(hints.get("field_hints") or [])
    if "index" not in field_hints:
        return False
    lowered = text.lower()
    return any(term in lowered for term in ("share", "segment", "rate", "franchise", "loss", "index"))


def _bbox_top_bonus(span: dict[str, Any]) -> float:
    bbox = span.get("bbox")
    if not isinstance(bbox, list) or len(bbox) < 2:
        return 0.0
    try:
        return 0.06 if float(bbox[1]) <= 160 else 0.0
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _mean(values: list[float]) -> float:
    return sum(values) / max(len(values), 1)


def _mean_bool(values: list[bool]) -> float:
    return sum(1 for value in values if value) / max(len(values), 1)


def _unique(values: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    ordered: list[Any] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered

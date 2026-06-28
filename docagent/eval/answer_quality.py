from __future__ import annotations

import re
from typing import Any

from docagent.eval.answer_metrics import exact_match, normalize_text, numeric_match, token_f1
from docagent.schemas import EvidenceBlock


REFUSAL_MARKERS = {
    "insufficient evidence",
    "not enough evidence",
    "cannot determine",
    "can't determine",
    "unable to determine",
    "unable to answer",
    "not provided",
    "not found",
    "no evidence",
    "does not mention",
    "无法确定",
    "无法回答",
    "没有足够",
    "未提及",
}


def evaluate_answer(
    *,
    predicted_answer: str,
    gold_answer: str | None,
    answer_type: str,
    eval_method: str,
) -> dict[str, Any]:
    predicted = str(predicted_answer or "")
    gold = str(gold_answer or "")
    normalized_exact = exact_match(predicted, gold) if gold else False
    contains = _contains_normalized(predicted, gold) if gold else False
    f1 = token_f1(predicted, gold) if gold else 0.0
    refusal = is_refusal(predicted)
    if eval_method == "refusal_expected" or answer_type == "refusal":
        correct = refusal
    elif eval_method == "numeric_tolerance" or answer_type == "numeric":
        correct = numeric_match(predicted, gold)
    elif eval_method == "boolean_exact" or answer_type == "boolean":
        correct = normalized_exact
    else:
        correct = normalized_exact or contains
    return {
        "answer_correct": bool(correct),
        "normalized_exact_match": 1.0 if normalized_exact else 0.0,
        "contains_match": bool(contains),
        "token_f1": round(float(f1), 4),
        "is_refusal": bool(refusal),
    }


def evaluate_format(final_answer: dict[str, Any] | None) -> dict[str, Any]:
    data = final_answer if isinstance(final_answer, dict) else {}
    required = {"answer", "evidence_location", "evidence", "reason"}
    missing = sorted(required - set(data))
    answer = str(data.get("answer") or "")
    location = data.get("evidence_location") if isinstance(data.get("evidence_location"), dict) else {}
    reason = str(data.get("reason") or "")
    return {
        "json_valid": isinstance(final_answer, dict),
        "required_fields_present": not missing,
        "missing_fields": missing,
        "answer_non_empty": bool(answer.strip()),
        "evidence_location_present": bool(location),
        "reason_present": bool(reason.strip()),
        "format_valid": bool(isinstance(final_answer, dict) and not missing and answer.strip() and location and reason.strip()),
    }


def validate_citations(
    *,
    citations: list[Any],
    final_answer: dict[str, Any] | None,
    evidence_blocks: list[EvidenceBlock],
) -> dict[str, Any]:
    valid_ids = {block.block_id for block in evidence_blocks}
    pages = {
        int(page)
        for block in evidence_blocks
        for page in (block.page_id, block.location.page)
        if page is not None
    }
    errors: list[str] = []
    citation_count = 0
    for citation in citations:
        if not isinstance(citation, dict):
            errors.append("citation_not_object")
            continue
        citation_count += 1
        _validate_location_object(citation, valid_ids=valid_ids, pages=pages, errors=errors, prefix="citation")
    location = (final_answer or {}).get("evidence_location")
    if isinstance(location, dict) and location:
        _validate_location_object(location, valid_ids=valid_ids, pages=pages, errors=errors, prefix="answer_location")
    return {
        "citation_valid": not errors and citation_count > 0,
        "citation_errors": list(dict.fromkeys(errors)),
        "citation_count": citation_count,
        "supporting_evidence_ids_count": len(valid_ids),
    }


def evaluate_location(
    *,
    final_answer: dict[str, Any] | None,
    citations: list[Any],
    gold_locations: list[dict[str, Any]],
) -> dict[str, Any]:
    if not gold_locations:
        return {"location_correct": True, "location_evaluated": False}
    predicted: list[dict[str, Any]] = []
    location = (final_answer or {}).get("evidence_location")
    if isinstance(location, dict):
        predicted.append(location)
    predicted.extend(citation for citation in citations if isinstance(citation, dict))
    correct = any(_location_matches(candidate, gold) for candidate in predicted for gold in gold_locations)
    return {"location_correct": bool(correct), "location_evaluated": True}


def evidence_contains_keywords(evidence_blocks: list[EvidenceBlock], keywords: list[str]) -> bool:
    if not keywords:
        return True
    text = normalize_text(" ".join(block.retrieval_text for block in evidence_blocks))
    return all(normalize_text(keyword) in text for keyword in keywords)


def is_refusal(text: str) -> bool:
    lowered = str(text or "").casefold()
    return any(marker in lowered for marker in REFUSAL_MARKERS)


def _contains_normalized(text: str, target: str) -> bool:
    normalized_text = normalize_text(text)
    normalized_target = normalize_text(target)
    return bool(normalized_target and normalized_target in normalized_text)


def _validate_location_object(
    location: dict[str, Any],
    *,
    valid_ids: set[str],
    pages: set[int],
    errors: list[str],
    prefix: str,
) -> None:
    block_id = str(location.get("block_id") or "")
    page = _optional_int(location.get("page"))
    if block_id and block_id not in valid_ids:
        errors.append(f"{prefix}_block_missing:{block_id}")
    if page is None:
        errors.append(f"{prefix}_page_missing")
    elif pages and page not in pages:
        errors.append(f"{prefix}_page_missing:{page}")


def _location_matches(candidate: dict[str, Any], gold: dict[str, Any]) -> bool:
    gold_page = _optional_int(gold.get("page"))
    candidate_page = _optional_int(candidate.get("page"))
    if gold_page is not None and candidate_page != gold_page:
        return False
    gold_block_id = str(gold.get("block_id") or "")
    if gold_block_id and str(candidate.get("block_id") or "") != gold_block_id:
        return False
    return gold_page is not None or bool(gold_block_id)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        match = re.search(r"-?\d+", value)
        if not match:
            return None
        value = match.group(0)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

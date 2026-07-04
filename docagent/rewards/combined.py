from __future__ import annotations

from typing import Any

from docagent.rewards.answer_reward import answer_reward
from docagent.rewards.format_reward import format_reward
from docagent.rewards.location_reward import location_reward
from docagent.workflow.answer_contract import normalize_supporting_refs, primary_location_from_output, validate_model_output_v3


def docqa_reward(answer: dict[str, Any], gold_answer: str | list[str], gold_location: dict[str, Any] | None, answer_type: str) -> float:
    fmt = format_reward(answer)
    ans = answer_reward(str(answer.get("answer", "")), gold_answer, answer_type)
    if gold_location:
        loc = location_reward(primary_location_from_output(answer), gold_location)
        grounded_ans = ans if loc == 1.0 else 0.0
        return 0.2 * fmt + 0.6 * grounded_ans + 0.2 * loc
    return 0.25 * fmt + 0.75 * ans


def docqa_v3_reward(
    answer: dict[str, Any],
    gold_answer: str | list[str],
    *,
    positive_refs: list[str],
    answer_type: str = "extractive",
    insufficient_expected: bool = False,
) -> float:
    return docqa_v3_reward_breakdown(
        answer,
        gold_answer,
        positive_refs=positive_refs,
        answer_type=answer_type,
        insufficient_expected=insufficient_expected,
    )["reward"]


def docqa_v3_reward_breakdown(
    answer: dict[str, Any],
    gold_answer: str | list[str],
    *,
    positive_refs: list[str],
    answer_type: str = "extractive",
    insufficient_expected: bool = False,
) -> dict[str, Any]:
    schema_ok, schema_error = validate_model_output_v3(answer)
    fmt = 1.0 if schema_ok else 0.0
    status = str(answer.get("support_status") or "")
    refs = normalize_supporting_refs(answer)
    valid_ref_set = set(positive_refs)
    answer_score = answer_reward(str(answer.get("answer", "")), gold_answer, answer_type)
    if not schema_ok:
        return {
            "reward": 0.0,
            "format_score": fmt,
            "legacy_format_score": format_reward(answer),
            "schema_error": schema_error,
            "answer_score": answer_score,
            "support_status_score": 0.0,
            "positive_ref_score": 0.0,
            "invalid_ref_penalty": 0.0,
            "insufficient_refusal_score": None,
            "support_status": status,
            "supporting_refs": refs,
            "insufficient_expected": insufficient_expected,
        }
    if insufficient_expected:
        status_score = 1.0 if status == "insufficient" else 0.0
        ref_score = 1.0 if not refs else 0.0
        refusal_score = _insufficient_answer_score(str(answer.get("answer", "")), gold_answer)
        reward = 0.2 * fmt + 0.3 * status_score + 0.2 * ref_score + 0.3 * refusal_score
        return {
            "reward": reward,
            "format_score": fmt,
            "legacy_format_score": format_reward(answer),
            "schema_error": None,
            "answer_score": answer_score,
            "support_status_score": status_score,
            "positive_ref_score": ref_score,
            "invalid_ref_penalty": 0.0,
            "insufficient_refusal_score": refusal_score,
            "support_status": status,
            "supporting_refs": refs,
            "insufficient_expected": True,
        }

    status_score = 1.0 if status == "supported" else 0.0
    ref_score = 1.0 if refs and any(ref in valid_ref_set for ref in refs) else 0.0
    invalid_ref_penalty = 0.0 if all(ref in valid_ref_set for ref in refs) else 0.15
    score = 0.15 * fmt + 0.35 * answer_score + 0.2 * status_score + 0.3 * ref_score
    reward = max(0.0, score - invalid_ref_penalty)
    return {
        "reward": reward,
        "format_score": fmt,
        "legacy_format_score": format_reward(answer),
        "schema_error": None,
        "answer_score": answer_score,
        "support_status_score": status_score,
        "positive_ref_score": ref_score,
        "invalid_ref_penalty": invalid_ref_penalty,
        "insufficient_refusal_score": None,
        "support_status": status,
        "supporting_refs": refs,
        "insufficient_expected": False,
    }


def _insufficient_answer_score(answer_text: str, gold_answer: str | list[str]) -> float:
    marker_score = 1.0 if _looks_like_insufficient_answer(answer_text) else 0.0
    gold_values = gold_answer if isinstance(gold_answer, list) else [gold_answer]
    non_empty_gold = [str(item) for item in gold_values if str(item or "").strip()]
    if non_empty_gold:
        return max(marker_score, answer_reward(answer_text, non_empty_gold, "extractive"))
    return marker_score


def _looks_like_insufficient_answer(answer_text: str) -> bool:
    text = " ".join(str(answer_text or "").casefold().split())
    if not text:
        return False
    markers = (
        "insufficient",
        "not enough evidence",
        "cannot determine",
        "can't determine",
        "not provided",
        "not available",
        "not found",
        "no evidence",
        "no candidate",
    )
    return any(marker in text for marker in markers)

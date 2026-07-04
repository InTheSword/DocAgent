from __future__ import annotations

from typing import Any

from docagent.rewards.answer_reward import answer_reward
from docagent.rewards.format_reward import format_reward
from docagent.rewards.location_reward import location_reward
from docagent.workflow.answer_contract import normalize_supporting_refs, primary_location_from_output


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
    fmt = format_reward(answer)
    status = str(answer.get("support_status") or "")
    refs = normalize_supporting_refs(answer)
    valid_ref_set = set(positive_refs)
    answer_score = answer_reward(str(answer.get("answer", "")), gold_answer, answer_type)
    if insufficient_expected:
        status_score = 1.0 if status == "insufficient" else 0.0
        ref_score = 1.0 if not refs else 0.0
        return 0.35 * fmt + 0.4 * status_score + 0.25 * ref_score

    status_score = 1.0 if status == "supported" else 0.0
    ref_score = 1.0 if refs and any(ref in valid_ref_set for ref in refs) else 0.0
    invalid_ref_penalty = 0.0 if all(ref in valid_ref_set for ref in refs) else 0.15
    score = 0.15 * fmt + 0.35 * answer_score + 0.2 * status_score + 0.3 * ref_score
    return max(0.0, score - invalid_ref_penalty)

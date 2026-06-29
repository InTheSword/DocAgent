from __future__ import annotations

from typing import Any

from docagent.rewards.answer_reward import answer_reward
from docagent.rewards.format_reward import format_reward
from docagent.rewards.location_reward import location_reward
from docagent.workflow.answer_contract import primary_location_from_output


def docqa_reward(answer: dict[str, Any], gold_answer: str | list[str], gold_location: dict[str, Any] | None, answer_type: str) -> float:
    fmt = format_reward(answer)
    ans = answer_reward(str(answer.get("answer", "")), gold_answer, answer_type)
    if gold_location:
        loc = location_reward(primary_location_from_output(answer), gold_location)
        grounded_ans = ans if loc == 1.0 else 0.0
        return 0.2 * fmt + 0.6 * grounded_ans + 0.2 * loc
    return 0.25 * fmt + 0.75 * ans

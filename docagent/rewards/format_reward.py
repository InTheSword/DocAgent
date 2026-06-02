from __future__ import annotations

from typing import Any

from docagent.tools.format_check import check_answer_format


def format_reward(answer: dict[str, Any]) -> float:
    return float(check_answer_format(answer)["score"])


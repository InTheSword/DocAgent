from __future__ import annotations

from typing import Any

from docagent.eval.answer_metrics import exact_match, numeric_match, token_f1


def answer_reward(prediction: str, gold: str | list[str], answer_type: str = "extractive") -> float:
    gold_values = gold if isinstance(gold, list) else [gold]
    if answer_type == "numeric":
        return 1.0 if any(numeric_match(prediction, item) for item in gold_values) else 0.0
    if any(exact_match(prediction, item) for item in gold_values):
        return 1.0
    return max(token_f1(prediction, item) for item in gold_values) if gold_values else 0.0


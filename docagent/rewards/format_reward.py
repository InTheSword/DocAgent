from __future__ import annotations

from typing import Any

from docagent.tools.format_check import check_answer_format
from docagent.workflow.answer_contract import validate_candidate_schema, validate_model_output_v3


def format_reward(answer: dict[str, Any]) -> float:
    v3_ok, _ = validate_model_output_v3(answer)
    if v3_ok:
        return 1.0
    legacy = check_answer_format(answer)
    if legacy["success"]:
        return 1.0
    candidate_ok, _ = validate_candidate_schema(answer)
    if candidate_ok:
        return 1.0
    return float(legacy["score"])

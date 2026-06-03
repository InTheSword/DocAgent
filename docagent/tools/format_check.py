from __future__ import annotations

from typing import Any


REQUIRED_FIELDS = {"answer", "evidence_location", "evidence", "reason"}


def check_answer_format(answer: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(answer, dict):
        return {
            "success": False,
            "missing_fields": sorted(REQUIRED_FIELDS),
            "type_errors": ["answer must be a JSON object"],
            "score": 0.0,
        }
    missing = sorted(REQUIRED_FIELDS - set(answer))
    type_errors: list[str] = []
    if "evidence_location" in answer and not isinstance(answer["evidence_location"], dict):
        type_errors.append("evidence_location must be a JSON object")
    return {
        "success": not missing and not type_errors,
        "missing_fields": missing,
        "type_errors": type_errors,
        "score": 1.0 if not missing and not type_errors else 0.5 if answer else 0.0,
    }

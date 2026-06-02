from __future__ import annotations

from typing import Any


REQUIRED_FIELDS = {"answer", "evidence_location", "evidence", "reason"}


def check_answer_format(answer: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(REQUIRED_FIELDS - set(answer))
    return {
        "success": not missing,
        "missing_fields": missing,
        "score": 1.0 if not missing else 0.5 if answer else 0.0,
    }


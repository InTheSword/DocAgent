from __future__ import annotations

from typing import Any


FAILURE_STAGES = {
    "none",
    "scenario_schema_error",
    "ingestion_error",
    "router_error",
    "retrieval_miss",
    "evidence_context_missing_answer",
    "model_api_error",
    "model_output_parse_error",
    "format_error",
    "generation_error",
    "location_error",
    "citation_error",
    "refusal_error",
    "unsupported_task",
    "unknown_error",
}


def classify_failure(
    *,
    status: str,
    expected_task_type: str,
    actual_task_type: str,
    ingestion_error: str = "",
    model_api_error: str = "",
    model_output_parse_error: str = "",
    unsupported: bool = False,
    evidence_context_has_gold: bool = True,
    answer_correct: bool = False,
    format_valid: bool = False,
    citation_valid: bool = False,
    location_correct: bool = False,
    refusal_expected: bool = False,
    refusal_correct: bool = False,
) -> str:
    if ingestion_error:
        return "ingestion_error"
    if actual_task_type != expected_task_type:
        return "router_error"
    if unsupported:
        return "unsupported_task"
    if model_api_error:
        return "model_api_error"
    if model_output_parse_error:
        return "model_output_parse_error"
    if not evidence_context_has_gold:
        return "evidence_context_missing_answer"
    if refusal_expected and not refusal_correct:
        return "refusal_error"
    if not format_valid:
        return "format_error"
    if not citation_valid:
        return "citation_error"
    if answer_correct and not location_correct:
        return "location_error"
    if not answer_correct:
        return "generation_error"
    if status not in {"completed", "passed"}:
        return "unknown_error"
    return "none"


def distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        stage = str(row.get("failure_stage") or "none")
        if stage == "none":
            continue
        counts[stage] = counts.get(stage, 0) + 1
    return dict(sorted(counts.items()))

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

from docagent.workflow.answer_contract import validate_candidate_schema, validate_model_output_v3


REQUIRED_FIELDS = {"answer", "evidence_location", "evidence", "reason"}
CANDIDATE_OUTPUT_FIELDS = {"answer", "reasoning_summary", "citation_block_ids", "citations", "evidence_used"}
MODEL_OUTPUT_V3_FIELDS = {"answer", "supporting_refs", "support_status", "reasoning_summary"}


@dataclass
class ParseResult:
    raw_json_ok: bool
    recovered_json_ok: bool
    schema_ok: bool
    parsed: dict[str, Any] | None
    extracted_json_text: str | None
    had_extra_text: bool
    had_think_tags: bool
    not_ending_with_brace: bool
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def has_thinking_text(text: str) -> bool:
    lowered = text.lower()
    return "<think>" in lowered or "</think>" in lowered


def _strip_think_tail(text: str) -> str:
    if "</think>" in text:
        return text.rsplit("</think>", maxsplit=1)[-1].strip()
    return text.strip()


def _raw_json_object(text: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        return None, str(exc)
    if not isinstance(parsed, dict):
        return None, "top-level JSON value is not an object"
    return parsed, None


def _has_output_field(parsed: dict[str, Any]) -> bool:
    return bool((REQUIRED_FIELDS | CANDIDATE_OUTPUT_FIELDS | MODEL_OUTPUT_V3_FIELDS) & set(parsed))


def _scan_first_json_object(text: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict) and _has_output_field(parsed):
            return parsed, text[index : index + end], None
    return None, None, "no JSON object found"


def _json_value_after_key(text: str, key: str) -> Any:
    marker = f'"{key}"'
    index = text.find(marker)
    if index < 0:
        return None
    colon = text.find(":", index + len(marker))
    if colon < 0:
        return None
    value_start = colon + 1
    while value_start < len(text) and text[value_start].isspace():
        value_start += 1
    try:
        value, _ = json.JSONDecoder().raw_decode(text[value_start:])
    except json.JSONDecodeError:
        return None
    return value


def _recover_partial_output_object(text: str) -> dict[str, Any] | None:
    partial: dict[str, Any] = {}
    answer = _json_value_after_key(text, "answer")
    if isinstance(answer, str):
        partial["answer"] = answer
    location = _json_value_after_key(text, "evidence_location")
    if isinstance(location, dict):
        partial["evidence_location"] = location
    evidence = _json_value_after_key(text, "evidence")
    if isinstance(evidence, str):
        partial["evidence"] = evidence
    reason = _json_value_after_key(text, "reason")
    if isinstance(reason, str):
        partial["reason"] = reason
    reasoning_summary = _json_value_after_key(text, "reasoning_summary")
    if isinstance(reasoning_summary, str):
        partial["reasoning_summary"] = reasoning_summary
    citation_block_ids = _json_value_after_key(text, "citation_block_ids")
    if isinstance(citation_block_ids, list):
        partial["citation_block_ids"] = citation_block_ids
    citations = _json_value_after_key(text, "citations")
    if isinstance(citations, list):
        partial["citations"] = citations
    evidence_used = _json_value_after_key(text, "evidence_used")
    if isinstance(evidence_used, (list, str)):
        partial["evidence_used"] = evidence_used
    supporting_refs = _json_value_after_key(text, "supporting_refs")
    if isinstance(supporting_refs, list):
        partial["supporting_refs"] = supporting_refs
    support_status = _json_value_after_key(text, "support_status")
    if isinstance(support_status, str):
        partial["support_status"] = support_status
    return partial if _has_output_field(partial) else None


def validate_schema(parsed: dict[str, Any] | None, max_reason_chars: int | None = 300) -> tuple[bool, str | None]:
    if not isinstance(parsed, dict):
        return False, "parsed output is not an object"
    v3_ok, v3_error = validate_model_output_v3(parsed, max_reason_chars=max_reason_chars)
    if v3_ok:
        return True, None
    legacy_ok, legacy_error = _validate_legacy_schema(parsed, max_reason_chars=max_reason_chars)
    if legacy_ok:
        return True, None
    candidate_ok, candidate_error = validate_candidate_schema(parsed, max_reason_chars=max_reason_chars)
    if candidate_ok:
        return True, None
    errors = [error for error in (legacy_error, candidate_error, v3_error) if error]
    return False, "; ".join(errors)


def _validate_legacy_schema(
    parsed: dict[str, Any],
    *,
    max_reason_chars: int | None = 300,
) -> tuple[bool, str | None]:
    missing = sorted(REQUIRED_FIELDS - set(parsed))
    if missing:
        return False, f"missing fields: {', '.join(missing)}"
    if not isinstance(parsed.get("answer"), str):
        return False, "answer must be a string"
    if not isinstance(parsed.get("evidence_location"), dict):
        return False, "evidence_location must be an object"
    if not isinstance(parsed.get("evidence"), str):
        return False, "evidence must be a string"
    reason = parsed.get("reason")
    if not isinstance(reason, str):
        return False, "reason must be a string"
    if max_reason_chars is not None and len(reason) > max_reason_chars:
        return False, f"reason exceeds {max_reason_chars} characters"
    return True, None


def parse_generation_output(text: str, max_reason_chars: int | None = 300) -> ParseResult:
    original = text or ""
    stripped = original.strip()
    had_think_tags = has_thinking_text(stripped)
    not_ending_with_brace = bool(stripped and not stripped.endswith("}"))

    parsed, raw_error = _raw_json_object(stripped)
    if parsed is not None:
        schema_ok, schema_error = validate_schema(parsed, max_reason_chars=max_reason_chars)
        return ParseResult(
            raw_json_ok=True,
            recovered_json_ok=False,
            schema_ok=schema_ok,
            parsed=parsed,
            extracted_json_text=stripped,
            had_extra_text=False,
            had_think_tags=had_think_tags,
            not_ending_with_brace=not_ending_with_brace,
            error=schema_error,
        )

    cleaned = _strip_think_tail(stripped)
    recovered, extracted, recover_error = _scan_first_json_object(cleaned)
    if recovered is None:
        recovered = _recover_partial_output_object(cleaned)
        if recovered is not None:
            extracted = None
            recover_error = "partial output object recovered from truncated generation"
    schema_ok, schema_error = validate_schema(recovered, max_reason_chars=max_reason_chars)
    return ParseResult(
        raw_json_ok=False,
        recovered_json_ok=recovered is not None and extracted is not None,
        schema_ok=schema_ok,
        parsed=recovered,
        extracted_json_text=extracted,
        had_extra_text=recovered is not None,
        had_think_tags=had_think_tags,
        not_ending_with_brace=not_ending_with_brace,
        error=schema_error or recover_error or raw_error,
    )

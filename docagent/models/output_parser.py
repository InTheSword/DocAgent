from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any


REQUIRED_FIELDS = {"answer", "evidence_location", "evidence", "reason"}


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


def _scan_first_json_object(text: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed, text[index : index + end], None
    return None, None, "no JSON object found"


def validate_schema(parsed: dict[str, Any] | None, max_reason_chars: int | None = 300) -> tuple[bool, str | None]:
    if not isinstance(parsed, dict):
        return False, "parsed output is not an object"
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
    schema_ok, schema_error = validate_schema(recovered, max_reason_chars=max_reason_chars)
    return ParseResult(
        raw_json_ok=False,
        recovered_json_ok=recovered is not None,
        schema_ok=schema_ok,
        parsed=recovered,
        extracted_json_text=extracted,
        had_extra_text=recovered is not None,
        had_think_tags=had_think_tags,
        not_ending_with_brace=not_ending_with_brace,
        error=schema_error or recover_error or raw_error,
    )

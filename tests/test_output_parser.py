from docagent.models.output_parser import parse_generation_output


def test_parse_strict_json_object() -> None:
    result = parse_generation_output(
        '{"answer": "A", "evidence_location": {"block_id": "b1"}, "evidence": "A", "reason": "supported"}'
    )

    assert result.raw_json_ok
    assert not result.recovered_json_ok
    assert result.schema_ok
    assert result.parsed["answer"] == "A"


def test_parse_recovers_json_after_extra_text_and_think_tags() -> None:
    result = parse_generation_output(
        '<think>hidden</think>\nHere is the answer:\n'
        '{"answer": "A", "evidence_location": {"block_id": "b1"}, "evidence": "A", "reason": "supported"}'
    )

    assert not result.raw_json_ok
    assert result.recovered_json_ok
    assert result.schema_ok
    assert result.had_extra_text
    assert result.had_think_tags


def test_parse_reports_schema_errors() -> None:
    result = parse_generation_output('{"answer": "A", "evidence_location": "b1"}')

    assert result.raw_json_ok
    assert not result.schema_ok
    assert "missing fields" in result.error


def test_parse_reports_incomplete_json() -> None:
    result = parse_generation_output('{"answer": "A"')

    assert not result.raw_json_ok
    assert not result.recovered_json_ok
    assert result.not_ending_with_brace
    assert result.parsed == {"answer": "A"}


def test_parse_rejects_overlong_reason() -> None:
    result = parse_generation_output(
        '{"answer": "A", "evidence_location": {"block_id": "b1"}, "evidence": "A", "reason": "'
        + "x" * 301
        + '"}'
    )

    assert result.raw_json_ok
    assert not result.schema_ok
    assert "reason exceeds" in result.error


def test_parse_truncated_answer_object_does_not_return_nested_location_object() -> None:
    result = parse_generation_output(
        '{"answer": "BSE", '
        '"evidence_location": {"page": 24, "block_id": "ynbx0223_p24_official_ocr"}, '
        '"evidence": "shareholder information monthly high and low quotes'
    )

    assert result.not_ending_with_brace
    assert not result.recovered_json_ok
    assert result.parsed["answer"] == "BSE"
    assert result.parsed["evidence_location"]["block_id"] == "ynbx0223_p24_official_ocr"
    assert "reason" not in result.parsed

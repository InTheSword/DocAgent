from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PARSERS = {"text", "mineru_existing"}
ANSWER_TYPES = {"extractive", "numeric", "boolean", "choice", "refusal"}
EVAL_METHODS = {
    "normalized_exact_or_contains",
    "numeric_tolerance",
    "boolean_exact",
    "refusal_expected",
}


class ScenarioValidationError(ValueError):
    pass


@dataclass(frozen=True)
class GoldLocation:
    page: int
    block_id: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "GoldLocation":
        return cls(
            page=_required_int(payload, "page"),
            block_id=str(payload["block_id"]) if payload.get("block_id") else None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"page": self.page, "block_id": self.block_id}


@dataclass(frozen=True)
class ScenarioCase:
    case_id: str
    doc_key: str
    question: str
    expected_task_type: str
    answer_type: str
    eval_method: str
    file: str = ""
    doc_id: str = ""
    parser: str = "text"
    mineru_output_dir: str = ""
    gold_answer: str | None = None
    gold_locations: list[GoldLocation] = field(default_factory=list)
    gold_evidence_text_contains: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    optional_fixture: bool = False

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ScenarioCase":
        if not isinstance(payload, dict):
            raise ScenarioValidationError("scenario row must be a JSON object")
        case_id = _required_str(payload, "case_id")
        file_value = str(payload.get("file") or "").strip()
        doc_id = str(payload.get("doc_id") or "").strip()
        if not file_value and not doc_id:
            raise ScenarioValidationError(f"{case_id}: either file or doc_id is required")
        parser = _required_str(payload, "parser")
        if parser not in PARSERS:
            raise ScenarioValidationError(f"{case_id}: unsupported parser: {parser}")
        mineru_output_dir = str(payload.get("mineru_output_dir") or "").strip()
        if parser == "mineru_existing" and not mineru_output_dir:
            raise ScenarioValidationError(f"{case_id}: mineru_output_dir is required for mineru_existing")
        answer_type = _required_str(payload, "answer_type")
        if answer_type not in ANSWER_TYPES:
            raise ScenarioValidationError(f"{case_id}: unsupported answer_type: {answer_type}")
        eval_method = _required_str(payload, "eval_method")
        if eval_method not in EVAL_METHODS:
            raise ScenarioValidationError(f"{case_id}: unsupported eval_method: {eval_method}")
        gold_answer = payload.get("gold_answer")
        if answer_type != "refusal" and not str(gold_answer or "").strip():
            raise ScenarioValidationError(f"{case_id}: gold_answer is required for answer_type={answer_type}")
        if answer_type == "refusal" and eval_method != "refusal_expected":
            raise ScenarioValidationError(f"{case_id}: refusal cases must use refusal_expected")
        return cls(
            case_id=case_id,
            doc_key=_required_str(payload, "doc_key"),
            file=file_value,
            doc_id=doc_id,
            parser=parser,
            mineru_output_dir=mineru_output_dir,
            question=_required_str(payload, "question"),
            expected_task_type=_required_str(payload, "expected_task_type"),
            gold_answer=str(gold_answer) if gold_answer is not None else None,
            answer_type=answer_type,
            gold_locations=[
                GoldLocation.from_dict(item)
                for item in _optional_list(payload, "gold_locations")
                if isinstance(item, dict)
            ],
            gold_evidence_text_contains=[str(item) for item in _optional_list(payload, "gold_evidence_text_contains")],
            eval_method=eval_method,
            tags=[str(item) for item in _optional_list(payload, "tags")],
            notes=str(payload.get("notes") or ""),
            optional_fixture=bool(payload.get("optional_fixture", False)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "doc_key": self.doc_key,
            "file": self.file,
            "doc_id": self.doc_id,
            "parser": self.parser,
            "mineru_output_dir": self.mineru_output_dir or None,
            "question": self.question,
            "expected_task_type": self.expected_task_type,
            "gold_answer": self.gold_answer,
            "answer_type": self.answer_type,
            "gold_locations": [location.to_dict() for location in self.gold_locations],
            "gold_evidence_text_contains": list(self.gold_evidence_text_contains),
            "eval_method": self.eval_method,
            "tags": list(self.tags),
            "notes": self.notes,
            "optional_fixture": self.optional_fixture,
        }


def read_scenario_jsonl(path: str | Path) -> list[ScenarioCase]:
    scenario_path = Path(path)
    cases: list[ScenarioCase] = []
    seen: set[str] = set()
    with scenario_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ScenarioValidationError(f"line {line_number}: invalid JSON: {exc}") from exc
            case = ScenarioCase.from_dict(payload)
            if case.case_id in seen:
                raise ScenarioValidationError(f"duplicate case_id: {case.case_id}")
            seen.add(case.case_id)
            cases.append(case)
    if not cases:
        raise ScenarioValidationError("scenario set is empty")
    return cases


def write_scenario_snapshot(path: str | Path, cases: list[ScenarioCase]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case.to_dict(), ensure_ascii=False) + "\n")


def summarize_scenarios(cases: list[ScenarioCase]) -> dict[str, int]:
    return {
        "case_count": len(cases),
        "extractive_count": sum(1 for case in cases if case.answer_type == "extractive"),
        "refusal_count": sum(1 for case in cases if case.answer_type == "refusal"),
        "zh_question_count": sum(1 for case in cases if _contains_cjk(case.question)),
        "en_question_count": sum(1 for case in cases if not _contains_cjk(case.question)),
        "optional_real_doc_count": sum(1 for case in cases if case.optional_fixture),
    }


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise ScenarioValidationError(f"{key} is required")
    return value


def _required_int(payload: dict[str, Any], key: str) -> int:
    try:
        return int(payload[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise ScenarioValidationError(f"{key} must be an integer") from exc


def _optional_list(payload: dict[str, Any], key: str) -> list[Any]:
    value = payload.get(key)
    if value is None:
        return []
    if not isinstance(value, list):
        raise ScenarioValidationError(f"{key} must be a list")
    return value


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)

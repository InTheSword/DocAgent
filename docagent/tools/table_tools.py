from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any

from docagent.schemas import EvidenceBlock
from docagent.storage.repositories import DocumentRepository
from docagent.tools.calculator import calculate


PREVIEW_CHARS = 220
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "between",
    "by",
    "calculate",
    "calculated",
    "change",
    "difference",
    "do",
    "end",
    "ended",
    "for",
    "from",
    "give",
    "how",
    "in",
    "is",
    "me",
    "number",
    "numbers",
    "of",
    "on",
    "respective",
    "respectively",
    "show",
    "table",
    "than",
    "the",
    "this",
    "to",
    "value",
    "was",
    "what",
    "year",
    "years",
}


@dataclass(frozen=True)
class TableCandidate:
    block: EvidenceBlock
    rows: list[list[str]]
    header: list[str]
    data_rows: list[list[str]]
    score: float


class _HTMLTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized == "tr":
            self._current_row = []
        elif normalized in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"td", "th"} and self._current_row is not None and self._current_cell is not None:
            value = _normalize_space(" ".join(self._current_cell))
            self._current_row.append(value)
            self._current_cell = None
        elif normalized == "tr" and self._current_row is not None:
            if any(cell for cell in self._current_row):
                self.rows.append(self._current_row)
            self._current_row = None


def table_lookup_or_calculation(
    repository: DocumentRepository,
    doc_id: str,
    question: str,
    *,
    selected_tools: list[str] | None = None,
) -> dict[str, Any]:
    document = repository.get_document(doc_id)
    if document is None:
        return _unsupported(
            doc_id=doc_id,
            question=question,
            code="document_not_found",
            message="Document was not found.",
            tools_used=selected_tools or ["table_lookup"],
        )

    tools_used = selected_tools or ["table_lookup"]
    blocks = repository.load_evidence_blocks(doc_id)
    table_blocks = [block for block in blocks if block.block_type == "table"]
    if not table_blocks:
        return _unsupported(
            doc_id=doc_id,
            question=question,
            code="table_lookup_unsupported",
            message="No table evidence blocks are available for this document.",
            tools_used=tools_used,
            warnings=["no_table_blocks_found"],
        )

    candidates = [_candidate(block, question) for block in table_blocks]
    candidates = [candidate for candidate in candidates if candidate.rows]
    if not candidates:
        return _unsupported(
            doc_id=doc_id,
            question=question,
            code="table_lookup_unsupported",
            message="Table blocks were found, but no rows could be parsed from table HTML or text.",
            tools_used=tools_used,
            warnings=["table_rows_not_parsed"],
        )

    selected = max(candidates, key=lambda item: item.score)
    wants_calculation = "simple_calculation" in tools_used
    if wants_calculation:
        return _run_calculation(doc_id=doc_id, question=question, candidate=selected, tools_used=tools_used)
    return _run_lookup(doc_id=doc_id, question=question, candidate=selected, tools_used=tools_used)


def _candidate(block: EvidenceBlock, question: str) -> TableCandidate:
    rows = _rows_from_block(block)
    header, data_rows = _split_header(rows)
    table_text = " ".join([" ".join(row) for row in rows] + [_caption(block), block.retrieval_text])
    query_tokens = _content_tokens(question)
    table_tokens = set(_content_tokens(table_text))
    years = set(_years(question))
    score = float(len(query_tokens & table_tokens))
    score += 2.0 * sum(1 for year in years if year in table_text)
    score += 0.5 if _caption(block) else 0.0
    return TableCandidate(block=block, rows=rows, header=header, data_rows=data_rows, score=score)


def _run_lookup(*, doc_id: str, question: str, candidate: TableCandidate, tools_used: list[str]) -> dict[str, Any]:
    value = _select_lookup_value(candidate, question)
    citation = _citation(candidate.block)
    if value is None:
        return _unsupported(
            doc_id=doc_id,
            question=question,
            code="table_lookup_unsupported",
            message="A table was found, but a matching row or value could not be selected from the question.",
            tools_used=tools_used,
            citations=[citation],
            warnings=["table_value_not_found"],
        )

    label = str(value.get("row_label") or value.get("column") or "value")
    answer = f"{label}: {value['value']}"
    reasoning = (
        "Selected the table block whose row/header text best matched the question, "
        "then returned the matching cell value."
    )
    return _success(
        doc_id=doc_id,
        question=question,
        answer=answer,
        reasoning_summary=reasoning,
        candidate=candidate,
        tools_used=["table_lookup"],
        citations=[citation],
        structured_result={
            "operation": "table_lookup",
            "selected_table": _table_summary(candidate),
            "selected_value": value,
        },
    )


def _run_calculation(*, doc_id: str, question: str, candidate: TableCandidate, tools_used: list[str]) -> dict[str, Any]:
    values = _calculation_values(candidate, question)
    citation = _citation(candidate.block)
    if len(values) < 2:
        return _unsupported(
            doc_id=doc_id,
            question=question,
            code="simple_calculation_unsupported",
            message="A traceable calculation requires at least two numeric values from the selected table.",
            tools_used=tools_used,
            citations=[citation],
            warnings=["calculation_inputs_not_found"],
        )

    operation = _calculation_operation(question)
    expression, suffix = _expression_for_operation(values, operation)
    calculated = calculate(expression)
    if not calculated.get("success"):
        return _unsupported(
            doc_id=doc_id,
            question=question,
            code="simple_calculation_failed",
            message=str(calculated.get("error") or "Calculation failed."),
            tools_used=tools_used,
            citations=[citation],
            warnings=["calculation_failed"],
        )

    result = float(calculated["result"])
    result_text = _format_number(result)
    if suffix:
        result_text = f"{result_text}{suffix}"
    answer = f"The {operation.replace('_', ' ')} is {result_text}."
    reasoning = (
        "Selected numeric inputs from the cited table block and evaluated a simple traceable expression."
    )
    return _success(
        doc_id=doc_id,
        question=question,
        answer=answer,
        reasoning_summary=reasoning,
        candidate=candidate,
        tools_used=["table_lookup", "simple_calculation"],
        citations=[citation],
        structured_result={
            "operation": "simple_calculation",
            "selected_table": _table_summary(candidate),
            "inputs": values,
            "calculation": {
                "operation": operation,
                "expression": expression,
                "result": result,
                "result_text": result_text,
            },
        },
    )


def _success(
    *,
    doc_id: str,
    question: str,
    answer: str,
    reasoning_summary: str,
    candidate: TableCandidate,
    tools_used: list[str],
    citations: list[dict[str, Any]],
    structured_result: dict[str, Any],
) -> dict[str, Any]:
    evidence_used = [_evidence_from_citation(citation) for citation in citations]
    return {
        "status": "success",
        "tool": "table_lookup_or_calculation",
        "task_type": "table_lookup_or_calculation",
        "doc_id": doc_id,
        "question": question,
        "answer": answer,
        "reasoning_summary": reasoning_summary,
        "evidence_used": evidence_used,
        "citations": citations,
        "supporting_evidence_ids": [candidate.block.block_id],
        "tools_used": tools_used,
        "structured_result": {
            "status": "success",
            "task_type": "table_lookup_or_calculation",
            **structured_result,
        },
        "warnings": [],
        "error": {},
    }


def _unsupported(
    *,
    doc_id: str,
    question: str,
    code: str,
    message: str,
    tools_used: list[str],
    citations: list[dict[str, Any]] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    citations = citations or []
    return {
        "status": "error",
        "tool": "table_lookup_or_calculation",
        "task_type": "table_lookup_or_calculation",
        "doc_id": doc_id,
        "question": question,
        "answer": "",
        "reasoning_summary": message,
        "evidence_used": [_evidence_from_citation(citation) for citation in citations],
        "citations": citations,
        "supporting_evidence_ids": [str(citation.get("block_id")) for citation in citations if citation.get("block_id")],
        "tools_used": tools_used,
        "structured_result": {
            "status": "unsupported",
            "task_type": "table_lookup_or_calculation",
            "reason": code,
        },
        "warnings": list(dict.fromkeys(warnings or [])),
        "error": {"type": code, "message": message},
    }


def _select_lookup_value(candidate: TableCandidate, question: str) -> dict[str, Any] | None:
    rows = _selectable_rows(candidate.data_rows or candidate.rows)
    years = _years(question)
    repeated_values = _activity_values(candidate, question)
    if repeated_values and _asks_for_multiple_activity_values(question):
        return {
            "value": ", ".join(str(value["text"]) for value in repeated_values),
            "column": repeated_values[0].get("column", ""),
            "row": [value.get("row") for value in repeated_values],
            "row_label": _activity_label(question) or "values",
        }
    if _asks_for_year_values(question):
        header_years = _year_labels_from_header(candidate.header)
        if header_years:
            return {
                "value": ", ".join(header_years),
                "column": "years",
                "row": candidate.header,
                "row_label": "years",
            }
    row_required_labels = [] if _header_has_any_label(candidate.header, years) else years
    best_row = _best_row(rows, question, required_labels=row_required_labels)
    if best_row is None:
        return None
    requested_columns = _requested_lookup_columns(candidate.header, question)
    if len(requested_columns) >= 2 and _asks_for_multiple_column_values(question):
        selected_values = []
        for index in requested_columns:
            value_index = _aligned_column_index(candidate.header, best_row, index)
            if value_index is None or value_index >= len(best_row):
                continue
            selected_values.append(
                {
                    "value": _lookup_display_value(best_row[value_index], candidate.header[index] if index < len(candidate.header) else ""),
                    "raw_value": best_row[value_index],
                    "column": candidate.header[index] if index < len(candidate.header) else "",
                }
            )
        if selected_values:
            return {
                "value": ", ".join(str(item["value"]) for item in selected_values),
                "raw_value": ", ".join(str(item["raw_value"]) for item in selected_values),
                "column": ", ".join(str(item["column"]) for item in selected_values if item.get("column")),
                "row": best_row,
                "row_label": _row_label(best_row, years),
            }
    if _asks_for_name_value(question):
        name_index = _name_column(candidate.header)
        if name_index is not None and name_index < len(best_row):
            return {
                "value": best_row[name_index],
                "raw_value": best_row[name_index],
                "column": candidate.header[name_index] if name_index < len(candidate.header) else "",
                "row": best_row,
                "row_label": _row_label(best_row, years),
            }
    column_index = _priority_column(candidate.header, question)
    if column_index is None:
        column_index = _metric_column(candidate.header, question)
    if column_index is None:
        column_index = _year_column(candidate.header, years)
    column_index = _aligned_column_index(candidate.header, best_row, column_index)
    if column_index is None or column_index >= len(best_row):
        column_index = _last_numeric_column(best_row, exclude_values=set(years))
    if column_index is None:
        return None
    raw_value = best_row[column_index]
    column = candidate.header[column_index] if column_index < len(candidate.header) else ""
    return {
        "value": _lookup_display_value(raw_value, column),
        "raw_value": raw_value,
        "column": column,
        "row": best_row,
        "row_label": _row_label(best_row, years),
    }


def _calculation_values(candidate: TableCandidate, question: str) -> list[dict[str, Any]]:
    years = _calculation_years(question)
    rows = _selectable_rows(candidate.data_rows or candidate.rows)
    column_index = _metric_column(candidate.header, question)
    operation = _calculation_operation(question)
    values: list[dict[str, Any]] = []
    high_low_values = _high_low_values(candidate, question)
    if len(high_low_values) >= 2:
        return high_low_values
    if operation == "percentage_of_total":
        percentage_values = _percentage_of_total_values(candidate, question)
        if len(percentage_values) >= 2:
            return percentage_values
    if operation == "average":
        row_values = _average_values_from_best_row(candidate, question, years)
        if len(row_values) >= 2:
            return row_values

    if years and _header_has_any_label(candidate.header, years):
        row = _best_row(rows, question, required_labels=[])
        if row is not None:
            for year in years:
                value_index = _header_label_index(candidate.header, year)
                value_index = _aligned_column_index(candidate.header, row, value_index)
                if value_index is None or value_index >= len(row):
                    continue
                numeric = _parse_number(row[value_index])
                if numeric is None:
                    continue
                values.append(
                    {
                        "label": year,
                        "value": numeric,
                        "text": row[value_index],
                        "row": row,
                        "column": candidate.header[value_index] if value_index < len(candidate.header) else "",
                    }
                )
        if len(values) >= 2:
            return values[:2]

    if years:
        for year in years:
            row = _best_row(rows, question, required_labels=[year])
            if row is None:
                continue
            value_index = column_index if column_index is not None and column_index < len(row) else None
            value_index = _aligned_column_index(candidate.header, row, value_index)
            if value_index is None:
                value_index = _last_numeric_column(row, exclude_values={year})
            if value_index is None:
                continue
            numeric = _parse_number(row[value_index])
            if numeric is None:
                continue
            values.append(
                {
                    "label": year,
                    "value": numeric,
                    "text": row[value_index],
                    "row": row,
                    "column": candidate.header[value_index] if value_index < len(candidate.header) else "",
                }
            )
    if len(values) >= 2:
        return values[:2]

    scored_cells: list[dict[str, Any]] = []
    for row in rows:
        for index, cell in enumerate(row):
            numeric = _parse_number(cell)
            if numeric is None:
                continue
            if str(int(numeric)) in years and numeric >= 1900:
                continue
            scored_cells.append(
                {
                    "label": _row_label(row, years) or f"row {len(scored_cells) + 1}",
                    "value": numeric,
                    "text": cell,
                    "row": row,
                    "column": candidate.header[index] if index < len(candidate.header) else "",
                }
            )
    return scored_cells[:2]


def _expression_for_operation(values: list[dict[str, Any]], operation: str) -> tuple[str, str]:
    first = float(values[0]["value"])
    second = float(values[1]["value"])
    if operation == "average":
        terms = [str(float(value["value"])) for value in values]
        return f"({' + '.join(terms)}) / {len(terms)}", ""
    if operation == "sum":
        return f"{first} + {second}", ""
    if operation == "percentage_of_total":
        return f"({first} / {second}) * 100", "%"
    if operation == "percentage_change":
        return f"(({second} - {first}) / {abs(first)}) * 100", "%"
    return f"{second} - {first}", ""


def _calculation_operation(question: str) -> str:
    normalized = question.casefold()
    if "average" in normalized or "mean" in normalized:
        return "average"
    if re.search(r"\bas\s+a\s+percentage\s+of\b|\bwhat\s+percentage\s+of\b", normalized):
        return "percentage_of_total"
    if any(
        token in normalized
        for token in (
            "percent change",
            "percentage change",
            "percentage increase",
            "percentage decrease",
            "percent increase",
            "percent decrease",
            "growth rate",
            "% change",
        )
    ):
        return "percentage_change"
    if any(token in normalized for token in ("sum", "total of", "add ")) or _asks_for_total_across_values(normalized):
        return "sum"
    return "difference"


def _requires_calculation(question: str) -> bool:
    normalized = question.casefold()
    return any(
        token in normalized
        for token in (
            "difference",
            "average",
            "mean",
            "subtract",
            "minus",
            "increase",
            "decrease",
            "change",
            "sum",
            "add ",
            "percentage",
            "percent",
            "% change",
        )
    )


def _average_values_from_best_row(candidate: TableCandidate, question: str, years: list[str]) -> list[dict[str, Any]]:
    rows = _selectable_rows(candidate.data_rows or candidate.rows)
    activity_values = _activity_values(candidate, question)
    if len(activity_values) >= 2:
        return activity_values

    if years and _header_has_any_label(candidate.header, years):
        row = _best_row(rows, question, required_labels=[])
        if row is not None:
            values: list[dict[str, Any]] = []
            for year in years:
                value_index = _header_label_index(candidate.header, year)
                value_index = _aligned_column_index(candidate.header, row, value_index)
                if value_index is None or value_index >= len(row):
                    continue
                numeric = _parse_number(row[value_index])
                if numeric is None:
                    continue
                values.append(
                    {
                        "label": year,
                        "value": numeric,
                        "text": row[value_index],
                        "row": row,
                        "column": candidate.header[value_index] if value_index < len(candidate.header) else "",
                    }
                )
            return values

    row = _best_row(rows, question, required_labels=[])
    if row is None:
        return []
    values = []
    max_values = len(years) if years else 0
    for index, cell in enumerate(row):
        numeric = _parse_number(cell)
        if numeric is None:
            continue
        if _is_year_cell(cell):
            continue
        values.append(
            {
                "label": _row_label(row, years) or f"row value {len(values) + 1}",
                "value": numeric,
                "text": cell,
                "row": row,
                "column": candidate.header[index] if index < len(candidate.header) else "",
            }
        )
        if max_values and len(values) >= max_values:
            break
    return values


def _percentage_of_total_values(candidate: TableCandidate, question: str) -> list[dict[str, Any]]:
    rows = _selectable_rows(candidate.data_rows or candidate.rows)
    value_column = _metric_column(candidate.header, question)
    target_row = _best_row(rows, _percentage_target_phrase(question) or question, required_labels=[])
    denominator_row = _best_row(rows, _percentage_denominator_phrase(question) or "total", required_labels=[])
    if target_row is None or denominator_row is None:
        return []
    values: list[dict[str, Any]] = []
    for label, row in (("numerator", target_row), ("denominator", denominator_row)):
        value_index = value_column if value_column is not None and value_column < len(row) else None
        value_index = _aligned_column_index(candidate.header, row, value_index)
        if value_index is None or value_index >= len(row):
            value_index = _last_numeric_column(row, exclude_values=set(_years(question)))
        if value_index is None:
            continue
        numeric = _parse_number(row[value_index])
        if numeric is None:
            continue
        values.append(
            {
                "label": _row_label(row, []),
                "value": numeric,
                "text": row[value_index],
                "row": row,
                "column": candidate.header[value_index] if value_index < len(candidate.header) else "",
                "role": label,
            }
        )
    return values


def _percentage_target_phrase(question: str) -> str:
    match = re.search(r"\bof\s+(.+?)\s+as\s+a\s+percentage\s+of\b", question or "", flags=re.I)
    return match.group(1) if match else ""


def _percentage_denominator_phrase(question: str) -> str:
    match = re.search(r"\bas\s+a\s+percentage\s+of\s+(.+?)(?:\?|$)", question or "", flags=re.I)
    return match.group(1) if match else ""


def _best_row(rows: list[list[str]], question: str, *, required_labels: list[str]) -> list[str] | None:
    query_tokens = _content_tokens(question)
    best: tuple[float, list[str]] | None = None
    context_tokens: set[str] = set()
    for row in rows:
        if _is_section_context_row(row):
            context_tokens = _content_tokens(row[0])
            continue
        row_text = " ".join(row)
        if required_labels and not any(label in row_text for label in required_labels):
            continue
        row_tokens = set(_content_tokens(row_text))
        label_tokens = set(_content_tokens(row[0] if row else ""))
        score = 2.0 * len(query_tokens & label_tokens)
        score += 0.75 * len(query_tokens & (row_tokens | context_tokens))
        score += 3.0 * sum(1 for label in required_labels if label in row_text)
        score += 0.1 * len(row)
        if not _has_non_year_number(row):
            score -= 2.0
        if best is None or score > best[0]:
            best = (score, row)
        if _starts_activity_context(row):
            context_tokens = _content_tokens(row[0])
    return best[1] if best is not None else None


def _high_low_values(candidate: TableCandidate, question: str) -> list[dict[str, Any]]:
    query_tokens = _content_tokens(question)
    if not {"high", "low"}.issubset(query_tokens):
        return []
    rows = _selectable_rows(candidate.data_rows or candidate.rows)
    high_row = _row_with_label(rows, "high")
    low_row = _row_with_label(rows, "low")
    if high_row is None or low_row is None:
        return []
    column_index = _question_column(candidate.header, question)
    values: list[dict[str, Any]] = []
    for label, row in (("low", low_row), ("high", high_row)):
        value_index = _aligned_column_index(candidate.header, row, column_index)
        if value_index is None or value_index >= len(row):
            value_index = _last_numeric_column(row, exclude_values=set(_years(question)))
        if value_index is None:
            continue
        numeric = _parse_number(row[value_index])
        if numeric is None:
            continue
        values.append(
            {
                "label": label,
                "value": numeric,
                "text": row[value_index],
                "row": row,
                "column": candidate.header[value_index] if value_index < len(candidate.header) else "",
            }
        )
    return values


def _activity_values(candidate: TableCandidate, question: str) -> list[dict[str, Any]]:
    label = _activity_label(question)
    if not label:
        return []
    rows = _selectable_rows(candidate.data_rows or candidate.rows)
    matches = [row for row in rows if _row_label_matches(row, label)]
    if len(matches) < 2:
        return []
    selected_rows = [matches[0], matches[-1]]
    values: list[dict[str, Any]] = []
    for row in selected_rows:
        value_index = _first_numeric_column(row)
        if value_index is None:
            continue
        numeric = _parse_number(row[value_index])
        if numeric is None:
            continue
        values.append(
            {
                "label": label,
                "value": numeric,
                "text": row[value_index],
                "row": row,
                "column": candidate.header[value_index] if value_index < len(candidate.header) else "",
            }
        )
    return values


def _activity_label(question: str) -> str | None:
    normalized = question.casefold()
    for label in ("granted", "vested", "forfeited", "exercised"):
        if re.search(rf"\b{label}\b", normalized):
            return label
    return None


def _asks_for_multiple_activity_values(question: str) -> bool:
    normalized = question.casefold()
    return "respective" in normalized or "respectively" in normalized


def _asks_for_multiple_column_values(question: str) -> bool:
    normalized = question.casefold()
    return "respective" in normalized or "respectively" in normalized or bool(re.search(r"\band\s+between\b", normalized))


def _asks_for_name_value(question: str) -> bool:
    normalized = question.casefold()
    return bool(re.search(r"\bwho\b|\bwhat\s+is\s+the\s+name\b", normalized))


def _asks_for_total_across_values(normalized_question: str) -> bool:
    if any(token in normalized_question for token in ("difference", "change", "increase", "decrease", "percentage", "percent")):
        return False
    if not re.search(r"\btotal\b", normalized_question):
        return False
    return bool(re.search(r"\b(?:and|across|combined|together)\b", normalized_question))


def _row_label_matches(row: list[str], label: str) -> bool:
    first = (row[0] if row else "").casefold().strip()
    return bool(re.fullmatch(rf"{re.escape(label)}\.?", first))


def _row_with_label(rows: list[list[str]], label: str) -> list[str] | None:
    for row in rows:
        first = (row[0] if row else "").casefold().strip()
        if first == label:
            return row
    return None


def _question_column(header: list[str], question: str) -> int | None:
    if not header:
        return None
    query_tokens = _content_tokens(question)
    years = set(_years(question))
    best: tuple[float, int] | None = None
    for index, value in enumerate(header):
        header_tokens = set(_content_tokens(value))
        if not header_tokens:
            continue
        score = float(len(query_tokens & header_tokens))
        score += 2.0 * sum(1 for year in years if year in str(value))
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, index)
    return best[1] if best is not None else None


def _priority_column(header: list[str], question: str) -> int | None:
    normalized_question = _normalize_for_match(question)
    phrase_groups = [
        ("as reported",),
        ("less than 1 year", "less than one year"),
        ("2-5 years", "2 5 years", "between 2-5 years"),
        ("first quarter",),
        ("second quarter",),
        ("third quarter",),
        ("fourth quarter",),
        ("total",),
    ]
    for phrases in phrase_groups:
        if not any(phrase in normalized_question for phrase in phrases):
            continue
        for index, value in enumerate(header):
            normalized_header = _normalize_for_match(value)
            if any(phrase in normalized_header for phrase in phrases):
                return index
    return None


def _requested_lookup_columns(header: list[str], question: str) -> list[int]:
    normalized_question = _normalize_for_match(question)
    requested: list[int] = []
    phrase_groups = [
        ("less than 1 year", "less than one year"),
        ("2-5 years", "2 5 years", "between 2-5 years"),
        ("first quarter",),
        ("second quarter",),
        ("third quarter",),
        ("fourth quarter",),
    ]
    for phrases in phrase_groups:
        if not any(phrase in normalized_question for phrase in phrases):
            continue
        for index, value in enumerate(header):
            normalized_header = _normalize_for_match(value)
            if any(phrase in normalized_header for phrase in phrases) and index not in requested:
                requested.append(index)
    return requested


def _name_column(header: list[str]) -> int | None:
    for index, value in enumerate(header):
        normalized = _normalize_for_match(value)
        if normalized in {"name", "names"} or normalized.endswith(" name"):
            return index
    return 0 if header else None


def _metric_column(header: list[str], question: str) -> int | None:
    if not header:
        return None
    query_tokens = _content_tokens(question)
    best: tuple[float, int] | None = None
    for index, name in enumerate(header):
        header_tokens = set(_content_tokens(name))
        if not header_tokens:
            continue
        score = float(len(query_tokens & header_tokens))
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, index)
    return best[1] if best is not None else None


def _header_has_any_label(header: list[str], labels: list[str]) -> bool:
    return any(_header_label_index(header, label) is not None for label in labels)


def _header_label_index(header: list[str], label: str) -> int | None:
    if not label:
        return None
    for index, value in enumerate(header):
        if label in str(value):
            return index
    return None


def _normalize_for_match(value: Any) -> str:
    normalized = str(value or "").casefold()
    normalized = normalized.replace("one", "1")
    normalized = re.sub(r"[–—-]", "-", normalized)
    normalized = re.sub(r"[^a-z0-9%$.-]+", " ", normalized)
    return _normalize_space(normalized)


def _year_column(header: list[str], years: list[str]) -> int | None:
    for year in years:
        index = _header_label_index(header, year)
        if index is not None:
            return index
    return None


def _year_labels_from_header(header: list[str]) -> list[str]:
    labels: list[str] = []
    for value in header:
        for year in _years(str(value)):
            if year not in labels:
                labels.append(year)
    return labels


def _aligned_column_index(header: list[str], row: list[str], index: int | None) -> int | None:
    if index is None:
        return None
    if len(row) == len(header) + 1 and row and _parse_number(row[0]) is None:
        return index + 1
    return index


def _selectable_rows(rows: list[list[str]]) -> list[list[str]]:
    filtered = [row for row in rows if not _is_header_like_row(row)]
    return filtered or rows


def _is_header_like_row(row: list[str]) -> bool:
    if not row:
        return True
    numeric_cells = [cell for cell in row if _parse_number(cell) is not None]
    if not numeric_cells:
        return False
    year_cells = [cell for cell in numeric_cells if _is_year_cell(cell)]
    if len(year_cells) == len(numeric_cells) and len(numeric_cells) >= 1:
        return True
    return False


def _is_section_context_row(row: list[str]) -> bool:
    if not row:
        return False
    first = _normalize_space(row[0])
    if not first:
        return False
    if not first.endswith(":"):
        return False
    return not any(_parse_number(cell) is not None for cell in row[1:])


def _starts_activity_context(row: list[str]) -> bool:
    first = (row[0] if row else "").casefold()
    return bool(re.match(r"\s*(?:nonvested|outstanding)\s+at\b", first))


def _has_non_year_number(row: list[str]) -> bool:
    return _first_numeric_column(row) is not None


def _first_numeric_column(row: list[str]) -> int | None:
    for index, cell in enumerate(row):
        numeric = _parse_number(cell)
        if numeric is None:
            continue
        if _is_year_cell(cell):
            continue
        return index
    return None


def _is_year_cell(value: str) -> bool:
    return bool(re.fullmatch(r"(?:19|20)\d{2}", str(value or "").strip()))


def _last_numeric_column(row: list[str], *, exclude_values: set[str]) -> int | None:
    for index in range(len(row) - 1, -1, -1):
        value = _parse_number(row[index])
        if value is None:
            continue
        if row[index].strip() in exclude_values:
            continue
        return index
    return None


def _row_label(row: list[str], preferred: list[str]) -> str:
    row_text = " ".join(row)
    for value in preferred:
        if value in row_text:
            return value
    return row[0] if row else ""


def _rows_from_block(block: EvidenceBlock) -> list[list[str]]:
    rows = _rows_from_html(block.table_html or "")
    if rows:
        return rows
    return _rows_from_text(block.text or block.retrieval_text)


def _rows_from_html(html: str) -> list[list[str]]:
    if not html.strip():
        return []
    parser = _HTMLTableParser()
    parser.feed(html)
    return [row for row in parser.rows if any(cell for cell in row)]


def _rows_from_text(text: str) -> list[list[str]]:
    normalized = _normalize_space(re.sub(r"<[^>]+>", " ", text or ""))
    if not normalized:
        return []
    lines = [_normalize_space(line) for line in re.split(r"[\r\n]+", text or "") if _normalize_space(line)]
    rows = [_tokenize_row(line) for line in lines if len(_tokenize_row(line)) >= 2]
    if len(rows) >= 2:
        return rows

    tokens = _tokenize_row(normalized)
    year_positions = [index for index, token in enumerate(tokens) if re.fullmatch(r"(?:19|20)\d{2}", token)]
    inferred_rows: list[list[str]] = []
    for position in year_positions:
        next_numeric = next(
            (token for token in tokens[position + 1 :] if _parse_number(token) is not None and token != tokens[position]),
            "",
        )
        if next_numeric:
            inferred_rows.append([tokens[position], next_numeric])
    if inferred_rows:
        return [["Year", "Value"], *inferred_rows]
    return [tokens] if len(tokens) >= 2 else []


def _tokenize_row(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z0-9%/&().-]*|\(?-?\$?\d[\d,]*(?:\.\d+)?%?\)?", text or "")


def _split_header(rows: list[list[str]]) -> tuple[list[str], list[list[str]]]:
    if not rows:
        return [], []
    header_rows: list[list[str]] = []
    data_start = 0
    for index, row in enumerate(rows):
        if _looks_like_initial_header_row(row) or (header_rows and _looks_like_header_continuation(row)):
            header_rows.append(row)
            data_start = index + 1
            continue
        break
    if header_rows:
        return _merge_header_rows(header_rows), rows[data_start:] or rows
    first = rows[0]
    if any(_parse_number(cell) is None for cell in first):
        return first, rows[1:] or rows
    return [], rows


def _looks_like_initial_header_row(row: list[str]) -> bool:
    if not row:
        return True
    cells = [_normalize_space(cell) for cell in row]
    non_empty = [cell for cell in cells if cell]
    if not non_empty:
        return True
    first = cells[0] if cells else ""
    numeric_cells = [cell for cell in non_empty if _parse_number(cell) is not None]
    year_cells = [cell for cell in numeric_cells if _is_year_cell(cell)]
    if numeric_cells and len(year_cells) == len(numeric_cells):
        return True
    if first == "":
        return True
    if re.fullmatch(r"\([^)]*(?:millions|thousands|usd|dollars)[^)]*\)", first, flags=re.I):
        return True
    return False


def _looks_like_header_continuation(row: list[str]) -> bool:
    cells = [_normalize_space(cell) for cell in row]
    non_empty = [cell for cell in cells if cell]
    if len(non_empty) < 2:
        return False
    if any(_parse_number(cell) is not None for cell in non_empty):
        return False
    label_tokens = {
        "period",
        "year",
        "years",
        "quarter",
        "quarters",
        "total",
        "reported",
        "balance",
        "balances",
        "obligations",
        "name",
        "age",
        "title",
    }
    row_tokens = set(_content_tokens(" ".join(non_empty)))
    return bool(row_tokens & label_tokens)


def _merge_header_rows(header_rows: list[list[str]]) -> list[str]:
    width = max((len(row) for row in header_rows), default=0)
    merged: list[str] = []
    for index in range(width):
        parts: list[str] = []
        for row in header_rows:
            if index >= len(row):
                continue
            value = _normalize_space(row[index])
            if value and value not in parts:
                parts.append(value)
        merged.append(_normalize_space(" ".join(parts)))
    return merged


def _citation(block: EvidenceBlock) -> dict[str, Any]:
    caption = _caption(block)
    citation = {
        "doc_id": block.doc_id,
        "page": _block_page(block),
        "block_id": block.block_id,
        "block_type": block.block_type,
        "text_preview": _preview(block.retrieval_text or block.text or block.table_html or ""),
    }
    if caption:
        citation["table_caption"] = caption
    return citation


def _evidence_from_citation(citation: dict[str, Any]) -> dict[str, Any]:
    return {
        "doc_id": citation.get("doc_id") or "",
        "page": citation.get("page"),
        "block_id": citation.get("block_id") or "",
        "block_type": citation.get("block_type") or "",
        "text_preview": citation.get("text_preview") or "",
        "table_caption": citation.get("table_caption") or "",
    }


def _table_summary(candidate: TableCandidate) -> dict[str, Any]:
    return {
        "doc_id": candidate.block.doc_id,
        "page": _block_page(candidate.block),
        "block_id": candidate.block.block_id,
        "block_type": candidate.block.block_type,
        "caption": _caption(candidate.block),
        "header": candidate.header,
        "row_count": len(candidate.data_rows or candidate.rows),
        "score": candidate.score,
    }


def _caption(block: EvidenceBlock) -> str:
    for key in ("table_caption", "caption", "chart_caption", "title"):
        value = block.metadata.get(key)
        if value:
            if isinstance(value, list):
                return _normalize_space(" ".join(str(item) for item in value))
            return _normalize_space(str(value))
    return ""


def _block_page(block: EvidenceBlock) -> int | None:
    if block.page_id is not None:
        return int(block.page_id)
    if block.location.page is not None:
        return int(block.location.page)
    return None


def _parse_number(value: str) -> float | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    negative = bool(re.search(r"\(\s*\$?\s*-?\d", cleaned)) and ")" in cleaned
    cleaned = cleaned.replace("$", "").replace(",", "").replace("%", "")
    cleaned = cleaned.replace("(", "").replace(")", "")
    cleaned = re.sub(r"\s+", "", cleaned)
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return -abs(parsed) if negative else parsed


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _format_one_decimal(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _lookup_display_value(value: str, column: str) -> str:
    numeric = _parse_number(value)
    if numeric is None or numeric <= 0:
        return value
    normalized_column = column.casefold()
    if "000" not in normalized_column:
        return value
    if "$" not in column and "usd" not in normalized_column:
        return value
    return f"{value} (about ${_format_one_decimal(numeric / 1000)} million)"


def _years(text: str) -> list[str]:
    values = re.findall(r"\b(?:19|20)\d{2}\b", text or "")
    for short in re.findall(r"\bFY\s*([0-9]{2})\b", text or "", flags=re.I):
        year = int(short)
        values.append(str(2000 + year if year < 50 else 1900 + year))
    return list(dict.fromkeys(values))


def _asks_for_year_values(text: str) -> bool:
    normalized = (text or "").casefold()
    return bool(re.search(r"\b(?:which|what)\s+years?\b|\bin\s+which\s+years?\b", normalized))


def _calculation_years(text: str) -> list[str]:
    normalized = text or ""
    in_from = re.search(r"\bin\s+((?:19|20)\d{2})\s+from\s+((?:19|20)\d{2})\b", normalized, flags=re.I)
    if in_from:
        return [in_from.group(2), in_from.group(1)]
    from_to = re.search(r"\bfrom\s+((?:19|20)\d{2})\s+to\s+((?:19|20)\d{2})\b", normalized, flags=re.I)
    if from_to:
        return [from_to.group(1), from_to.group(2)]
    return _years(normalized)


def _content_tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9%]+", (text or "").casefold())
        if token and token not in STOPWORDS and len(token) > 1
    }


def _preview(text: str, limit: int = PREVIEW_CHARS) -> str:
    return _normalize_space(text)[:limit]


def _normalize_space(text: str) -> str:
    return " ".join((text or "").split())

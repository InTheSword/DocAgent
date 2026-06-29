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
    "change",
    "difference",
    "do",
    "for",
    "from",
    "give",
    "how",
    "in",
    "is",
    "me",
    "of",
    "on",
    "show",
    "table",
    "than",
    "the",
    "this",
    "to",
    "value",
    "was",
    "what",
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
    wants_calculation = "simple_calculation" in tools_used or _requires_calculation(question)
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
    rows = candidate.data_rows or candidate.rows
    years = _years(question)
    best_row = _best_row(rows, question, required_labels=years)
    if best_row is None:
        return None
    column_index = _metric_column(candidate.header, question)
    if column_index is None or column_index >= len(best_row):
        column_index = _last_numeric_column(best_row, exclude_values=set(years))
    if column_index is None:
        return None
    return {
        "value": best_row[column_index],
        "column": candidate.header[column_index] if column_index < len(candidate.header) else "",
        "row": best_row,
        "row_label": _row_label(best_row, years),
    }


def _calculation_values(candidate: TableCandidate, question: str) -> list[dict[str, Any]]:
    years = _years(question)
    rows = candidate.data_rows or candidate.rows
    column_index = _metric_column(candidate.header, question)
    values: list[dict[str, Any]] = []
    if years:
        for year in years:
            row = _best_row(rows, question, required_labels=[year])
            if row is None:
                continue
            value_index = column_index if column_index is not None and column_index < len(row) else None
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
    if operation == "sum":
        return f"{first} + {second}", ""
    if operation == "percentage_change":
        return f"(({second} - {first}) / {abs(first)}) * 100", "%"
    return f"{second} - {first}", ""


def _calculation_operation(question: str) -> str:
    normalized = question.casefold()
    if any(token in normalized for token in ("percent change", "percentage change", "growth rate", "% change")):
        return "percentage_change"
    if any(token in normalized for token in ("sum", "total of", "add ")):
        return "sum"
    return "difference"


def _requires_calculation(question: str) -> bool:
    normalized = question.casefold()
    return any(
        token in normalized
        for token in (
            "difference",
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


def _best_row(rows: list[list[str]], question: str, *, required_labels: list[str]) -> list[str] | None:
    query_tokens = _content_tokens(question)
    best: tuple[float, list[str]] | None = None
    for row in rows:
        row_text = " ".join(row)
        if required_labels and not any(label in row_text for label in required_labels):
            continue
        score = float(len(query_tokens & set(_content_tokens(row_text))))
        score += 3.0 * sum(1 for label in required_labels if label in row_text)
        score += 0.1 * len(row)
        if best is None or score > best[0]:
            best = (score, row)
    return best[1] if best is not None else None


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
    return [[cell for cell in row if cell] for row in parser.rows if any(cell for cell in row)]


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
    first = rows[0]
    if any(_parse_number(cell) is None for cell in first):
        return first, rows[1:] or rows
    return [], rows


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
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()").replace("$", "").replace(",", "").replace("%", "")
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return -parsed if negative else parsed


def _format_number(value: float) -> str:
    if value.is_integer():
        return str(int(value))
    return f"{value:.4f}".rstrip("0").rstrip(".")


def _years(text: str) -> list[str]:
    return list(dict.fromkeys(re.findall(r"\b(?:19|20)\d{2}\b", text or "")))


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

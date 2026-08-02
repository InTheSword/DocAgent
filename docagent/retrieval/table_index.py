from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from docagent.schemas import Chunk


SUPPORTED_AGGREGATIONS = {"count", "sum", "avg", "min", "max"}


@dataclass(frozen=True)
class TableStructuredQuery:
    """Exact table-row constraints produced by an upstream query planner."""

    filters: dict[str, str] = field(default_factory=dict)
    select_columns: tuple[str, ...] = ()
    aggregation: str | None = None
    aggregation_column: str | None = None

    @classmethod
    def from_value(
        cls,
        value: "TableStructuredQuery | dict[str, object] | None",
    ) -> "TableStructuredQuery | None":
        if value is None or isinstance(value, cls):
            return value
        filters = value.get("filters") or value.get("where") or {}
        return cls(
            filters={str(key): str(item) for key, item in dict(filters).items()},
            select_columns=tuple(str(item) for item in value.get("select_columns") or ()),
            aggregation=str(value["aggregation"]).casefold() if value.get("aggregation") else None,
            aggregation_column=str(value["aggregation_column"]) if value.get("aggregation_column") else None,
        )

    @property
    def is_empty(self) -> bool:
        return not (self.filters or self.select_columns or self.aggregation)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {}
        if self.filters:
            payload["filters"] = dict(self.filters)
        if self.select_columns:
            payload["select_columns"] = list(self.select_columns)
        if self.aggregation:
            payload["aggregation"] = self.aggregation
        if self.aggregation_column:
            payload["aggregation_column"] = self.aggregation_column
        return payload


@dataclass(frozen=True)
class TableStructuredHit:
    block: Chunk
    matched_rows: list[dict[str, str]]
    selected_rows: list[dict[str, str]]
    aggregate: dict[str, object] | None
    score: float

    def to_dict(self) -> dict[str, object]:
        return {
            "block_id": self.block.block_id,
            "page": self.block.page_id,
            "matched_rows": self.matched_rows,
            "selected_rows": self.selected_rows,
            "aggregate": self.aggregate,
        }


class TableRelationalIndex:
    """In-memory exact row index over normalized table Chunk metadata."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = [
            chunk
            for chunk in chunks
            if chunk.block_type == "table"
            and chunk.metadata.get("table_headers")
            and chunk.metadata.get("table_rows")
            and (
                chunk.metadata.get("include_in_structured_table_index") is True
                or (
                    chunk.metadata.get("include_in_structured_table_index") is not False
                    and chunk.is_indexable
                )
            )
        ]

    def search(
        self,
        query: TableStructuredQuery,
        *,
        top_k: int,
        allowed_block_ids: set[str] | None = None,
    ) -> list[TableStructuredHit]:
        if query.is_empty:
            return []
        if query.aggregation and query.aggregation not in SUPPORTED_AGGREGATIONS:
            raise ValueError(f"unsupported table aggregation: {query.aggregation}")

        hits: list[TableStructuredHit] = []
        for chunk in self.chunks:
            if allowed_block_ids is not None and chunk.block_id not in allowed_block_ids:
                continue
            hit = _query_chunk(chunk, query)
            if hit is not None:
                hits.append(hit)
        hits.sort(key=lambda item: (-item.score, _reading_order(item.block), item.block.block_id))
        return hits[:top_k]


def _query_chunk(chunk: Chunk, query: TableStructuredQuery) -> TableStructuredHit | None:
    headers = [str(value).strip() for value in chunk.metadata.get("table_headers") or []]
    header_lookup = {header.casefold(): header for header in headers}
    filter_columns = {
        header_lookup.get(column.casefold()): expected
        for column, expected in query.filters.items()
    }
    if None in filter_columns:
        return None
    selected_columns = [header_lookup.get(column.casefold()) for column in query.select_columns]
    if any(column is None for column in selected_columns):
        return None
    aggregation_column = (
        header_lookup.get(query.aggregation_column.casefold())
        if query.aggregation_column
        else None
    )
    if query.aggregation not in {None, "count"} and aggregation_column is None:
        return None

    rows = [
        {
            header: str(row[index]).strip() if index < len(row) else ""
            for index, header in enumerate(headers)
        }
        for row in chunk.metadata.get("table_rows") or []
    ]
    matched_rows = [
        row
        for row in rows
        if all(_normalized_cell(row[column]) == _normalized_cell(expected) for column, expected in filter_columns.items())
    ]
    if not matched_rows:
        return None

    selected_rows = [
        {column: row[column] for column in selected_columns}
        for row in matched_rows
    ] if selected_columns else matched_rows
    aggregate = _aggregate_rows(
        matched_rows,
        operation=query.aggregation,
        column=aggregation_column,
    )
    score = 1.0 + len(filter_columns) + (1.0 if query.aggregation else 0.0)
    return TableStructuredHit(
        block=chunk,
        matched_rows=matched_rows,
        selected_rows=selected_rows,
        aggregate=aggregate,
        score=score,
    )


def _aggregate_rows(
    rows: list[dict[str, str]],
    *,
    operation: str | None,
    column: str | None,
) -> dict[str, object] | None:
    if operation is None:
        return None
    if operation == "count":
        return {"operation": operation, "column": column, "value": len(rows)}
    values = [
        value
        for row in rows
        if (value := _numeric_value(row[column])) is not None
    ]
    if not values:
        return None
    if operation == "sum":
        result = sum(values)
    elif operation == "avg":
        result = sum(values) / len(values)
    elif operation == "min":
        result = min(values)
    else:
        result = max(values)
    return {"operation": operation, "column": column, "value": result}


def _numeric_value(value: str) -> float | None:
    text = value.strip().replace(",", "")
    negative = text.startswith("(") and text.endswith(")")
    match = re.search(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text)
    if match is None:
        return None
    number = float(match.group())
    return -abs(number) if negative else number


def _normalized_cell(value: Any) -> str:
    return " ".join(str(value).split()).casefold()


def _reading_order(chunk: Chunk) -> int:
    return int(chunk.metadata.get("reading_order") or 0)

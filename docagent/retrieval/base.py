from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from docagent.schemas import Chunk


@dataclass(frozen=True)
class RetrievalFilter:
    """Structured constraints applied before sparse or dense candidate ranking."""

    page_ids: tuple[int, ...] = ()
    block_ids: tuple[str, ...] = ()
    block_types: tuple[str, ...] = ()
    content_types: tuple[str, ...] = ()
    heading_roles: tuple[str, ...] = ()
    raw_mineru_types: tuple[str, ...] = ()
    printed_page_numbers: tuple[str, ...] = ()
    section_ids: tuple[str, ...] = ()
    section_queries: tuple[str, ...] = ()
    feature_tags: tuple[str, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.page_ids,
                self.block_ids,
                self.block_types,
                self.content_types,
                self.heading_roles,
                self.raw_mineru_types,
                self.printed_page_numbers,
                self.section_ids,
                self.section_queries,
                self.feature_tags,
            )
        )

    def matches(self, block: Chunk) -> bool:
        if self.page_ids and block.page_id not in self.page_ids:
            return False
        if self.block_ids and block.block_id not in self.block_ids:
            return False
        if self.block_types and block.block_type not in self.block_types:
            return False
        content_type = str(block.metadata.get("content_type") or block.block_type)
        if self.content_types and content_type not in self.content_types:
            return False
        if self.heading_roles and str(block.metadata.get("heading_role") or "") not in self.heading_roles:
            return False
        if self.raw_mineru_types and str(block.metadata.get("raw_mineru_type") or "") not in self.raw_mineru_types:
            return False
        if self.printed_page_numbers:
            printed = str(block.metadata.get("printed_page_number") or "").casefold()
            if printed not in {value.casefold() for value in self.printed_page_numbers}:
                return False
        if self.section_ids and str(block.metadata.get("section_id") or "") not in self.section_ids:
            return False
        if self.section_queries:
            section_text = " > ".join(str(item) for item in block.metadata.get("section_path") or []).casefold()
            if not any(value.casefold() in section_text for value in self.section_queries):
                return False
        if self.feature_tags:
            block_tags = {str(value).casefold() for value in block.metadata.get("feature_tags") or []}
            if not all(value.casefold() in block_tags for value in self.feature_tags):
                return False
        return True

    def to_dict(self) -> dict[str, list[object]]:
        payload: dict[str, list[object]] = {}
        for key, values in (
            ("page_ids", self.page_ids),
            ("block_ids", self.block_ids),
            ("block_types", self.block_types),
            ("content_types", self.content_types),
            ("heading_roles", self.heading_roles),
            ("raw_mineru_types", self.raw_mineru_types),
            ("printed_page_numbers", self.printed_page_numbers),
            ("section_ids", self.section_ids),
            ("section_queries", self.section_queries),
            ("feature_tags", self.feature_tags),
        ):
            if values:
                payload[key] = list(values)
        return payload


@dataclass
class RetrievalCandidate:
    block: Chunk
    bm25_score: float | None = None
    dense_score: float | None = None
    table_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    ranks: dict[str, int] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)

    def display_score(self) -> float:
        for value in (self.rerank_score, self.rrf_score, self.dense_score, self.bm25_score, self.table_score):
            if value is not None:
                return float(value)
        return 0.0

    def to_trace_dict(self, final_rank: int | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "block_id": self.block.block_id,
            "doc_id": self.block.doc_id,
            "page": self.block.page_id,
            "block_type": self.block.block_type,
            "bm25_score": self.bm25_score,
            "dense_score": self.dense_score,
            "table_score": self.table_score,
            "rrf_score": self.rrf_score,
            "rerank_score": self.rerank_score,
            "ranks": self.ranks,
            "sources": self.sources,
        }
        if final_rank is not None:
            payload["final_rank"] = final_rank
        return payload


@dataclass
class RetrievalResult:
    rewritten_query: str
    candidates: list[RetrievalCandidate]
    metadata: dict[str, object] = field(default_factory=dict)


class Retriever(Protocol):
    def retrieve(
        self,
        *,
        doc_id: str | None,
        question: str,
        top_k: int,
        answer_type_hint: str | None = None,
        filters: RetrievalFilter | None = None,
        query_intent: str | None = None,
        table_query: dict[str, object] | None = None,
        enable_query_rewrite: bool = True,
    ) -> RetrievalResult:
        ...

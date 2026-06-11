from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from docagent.schemas import EvidenceBlock


@dataclass
class RetrievalCandidate:
    block: EvidenceBlock
    bm25_score: float | None = None
    dense_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None
    ranks: dict[str, int] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)

    def display_score(self) -> float:
        for value in (self.rerank_score, self.rrf_score, self.dense_score, self.bm25_score):
            if value is not None:
                return float(value)
        return 0.0

    def to_trace_dict(self, final_rank: int | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "block_id": self.block.block_id,
            "page": self.block.page_id,
            "block_type": self.block.block_type,
            "bm25_score": self.bm25_score,
            "dense_score": self.dense_score,
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
    ) -> RetrievalResult:
        ...


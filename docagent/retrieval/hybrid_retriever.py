from __future__ import annotations

from docagent.retrieval.bm25_index import BM25Index
from docagent.retrieval.query_rewrite import rewrite_query
from docagent.schemas import EvidenceBlock


class HybridRetriever:
    def __init__(self, blocks: list[EvidenceBlock]) -> None:
        self.blocks = blocks
        self.bm25 = BM25Index(blocks)

    def retrieve(
        self,
        question: str,
        top_k: int = 5,
        answer_type_hint: str | None = None,
    ) -> tuple[str, list[tuple[EvidenceBlock, float]]]:
        rewrite = rewrite_query(question, answer_type_hint=answer_type_hint)
        query = f"{question} {rewrite.rewritten_query}".strip()
        hits = self.bm25.search(query, top_k=top_k)
        return rewrite.rewritten_query, hits


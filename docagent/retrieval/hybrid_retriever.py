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
        candidate_k = min(len(self.blocks), max(top_k * 10, top_k))
        hits = self.bm25.search(query, top_k=candidate_k)
        if not hits:
            return rewrite.rewritten_query, hits
        max_score = max(score for _block, score in hits) or 1.0
        target_types = set(rewrite.target_evidence_type)
        reranked = []
        for block, score in hits:
            boost = 0.0
            if block.block_type in target_types:
                boost += 0.10 * max_score
            if answer_type_hint == "numeric" and block.block_type == "table":
                boost += 0.45 * max_score
            reranked.append((block, score + boost))
        reranked.sort(key=lambda item: item[1], reverse=True)
        return rewrite.rewritten_query, reranked[:top_k]

from __future__ import annotations

from docagent.retrieval.base import RetrievalCandidate
from docagent.schemas import EvidenceBlock


def reciprocal_rank_fusion(
    rankings: dict[str, list[tuple[EvidenceBlock, float]]],
    *,
    rrf_k: int = 60,
) -> list[RetrievalCandidate]:
    by_block_id: dict[str, RetrievalCandidate] = {}
    for source, hits in rankings.items():
        for rank, (block, score) in enumerate(hits, start=1):
            candidate = by_block_id.setdefault(block.block_id, RetrievalCandidate(block=block))
            candidate.sources.append(source)
            candidate.ranks[source] = rank
            candidate.rrf_score = (candidate.rrf_score or 0.0) + 1.0 / (rrf_k + rank)
            if source == "bm25":
                candidate.bm25_score = score
            elif source == "dense":
                candidate.dense_score = score
    return sorted(
        by_block_id.values(),
        key=lambda item: (-(item.rrf_score or 0.0), min(item.ranks.values()), item.block.block_id),
    )


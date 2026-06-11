from __future__ import annotations

from docagent.retrieval.base import RetrievalCandidate
from docagent.retrieval.reranker import KeywordOverlapReranker
from docagent.schemas import EvidenceBlock, EvidenceLocation


def _candidate(block_id: str, text: str) -> RetrievalCandidate:
    return RetrievalCandidate(
        block=EvidenceBlock(
            doc_id="doc",
            block_id=block_id,
            block_type="text",
            text=text,
            location=EvidenceLocation(page=0, block_id=block_id),
        ),
        ranks={"rrf": 1},
    )


def test_keyword_overlap_reranker_sorts_candidates() -> None:
    candidates = [_candidate("b1", "invoice date"), _candidate("b2", "total revenue")]
    reranked = KeywordOverlapReranker().score(query="what is the invoice date", candidates=candidates)

    assert reranked[0].block.block_id == "b1"
    assert reranked[0].rerank_score is not None


from __future__ import annotations

from docagent.retrieval.fusion import reciprocal_rank_fusion
from docagent.schemas import EvidenceBlock, EvidenceLocation


def _block(block_id: str) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="doc",
        block_id=block_id,
        block_type="text",
        text=block_id,
        location=EvidenceLocation(page=0, block_id=block_id),
    )


def test_rrf_fusion_deduplicates_and_records_ranks() -> None:
    b1 = _block("b1")
    b2 = _block("b2")

    fused = reciprocal_rank_fusion(
        {
            "bm25": [(b1, 10.0), (b2, 2.0)],
            "dense": [(b2, 0.9), (b1, 0.5)],
        },
        rrf_k=60,
    )

    assert [item.block.block_id for item in fused] == ["b1", "b2"]
    assert fused[0].ranks == {"bm25": 1, "dense": 2}
    assert fused[1].sources == ["bm25", "dense"]


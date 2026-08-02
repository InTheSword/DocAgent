from __future__ import annotations

import numpy as np

from docagent.retrieval.bm25_index import BM25Index, tokenize
from docagent.retrieval.dense_encoder import HashDenseEncoder
from docagent.retrieval.dense_index import DenseIndex
from docagent.schemas import Chunk, EvidenceBlock, EvidenceLocation


def _block(block_id: str, text: str, *, excluded: bool = False) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="doc",
        block_id=block_id,
        block_type="text",
        text=text,
        page_id=1,
        location=EvidenceLocation(page=1, block_id=block_id),
        metadata={"exclude_from_retrieval": excluded},
    )


def test_evidence_block_indexable_contract() -> None:
    assert EvidenceBlock is Chunk
    assert _block("valid", "retrievable text").is_indexable is True
    assert _block("empty", "").is_indexable is False
    assert _block("excluded", "page header", excluded=True).is_indexable is False


def test_bm25_index_ignores_non_indexable_chunks() -> None:
    index = BM25Index(
        [
            _block("valid", "invoice date"),
            _block("empty", ""),
            _block("excluded", "invoice header", excluded=True),
        ]
    )

    assert [block.block_id for block in index.blocks] == ["valid"]
    assert [block.block_id for block, _score in index.search("invoice", top_k=5)] == ["valid"]


def test_retrieval_normalizes_fullwidth_compatibility_characters_without_changing_source_text() -> None:
    block = _block("fullwidth", "Ｔａｋｅｍｕｒａ １５")

    assert block.text == "Ｔａｋｅｍｕｒａ １５"
    assert "Takemura 15" in block.retrieval_text
    assert tokenize("Ｔａｋｅｍｕｒａ １５") == ["takemura", "15"]
    assert BM25Index([block]).search("Takemura 15")[0][0].block_id == "fullwidth"


def test_dense_index_can_be_built_from_filtered_chunks() -> None:
    blocks = [_block("valid", "invoice date"), _block("empty", "")]
    indexable = [block for block in blocks if block.is_indexable]
    encoder = HashDenseEncoder()
    embeddings = np.asarray(
        encoder.encode_documents([block.retrieval_text for block in indexable]),
        dtype=np.float32,
    )

    index = DenseIndex.build(blocks=indexable, embeddings=embeddings, model_id=encoder.model_id)

    assert [block.block_id for block in index.blocks] == ["valid"]

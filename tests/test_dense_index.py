from __future__ import annotations

import numpy as np

from docagent.retrieval.dense_index import DenseIndex, evidence_hash
from docagent.schemas import EvidenceBlock, EvidenceLocation


def _block(block_id: str, text: str) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="doc",
        block_id=block_id,
        block_type="text",
        text=text,
        location=EvidenceLocation(page=0, block_id=block_id),
    )


def test_dense_index_numpy_search_and_save_load(tmp_path) -> None:
    blocks = [_block("b1", "invoice date"), _block("b2", "revenue table")]
    embeddings = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    index = DenseIndex(blocks=blocks, embeddings=embeddings, model_id="mock-bge", backend="numpy")

    hits = index.search(np.asarray([[0.9, 0.1]], dtype=np.float32), top_k=2)
    metadata = index.save(tmp_path)
    loaded = DenseIndex.load(index_dir=tmp_path, blocks=blocks)

    assert hits[0].block.block_id == "b1"
    assert metadata["backend"] == "numpy"
    assert metadata["evidence_hash"] == evidence_hash(blocks)
    assert loaded.search(np.asarray([[0.1, 0.9]], dtype=np.float32), top_k=1)[0].block.block_id == "b2"


def test_dense_index_missing_fails_with_clear_error(tmp_path) -> None:
    blocks = [_block("b1", "invoice date")]

    try:
        DenseIndex.load(index_dir=tmp_path, blocks=blocks)
    except FileNotFoundError as exc:
        assert "index_metadata.json" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")


def test_dense_index_query_dimension_mismatch_fails_before_backend_search() -> None:
    blocks = [_block("b1", "invoice date")]
    index = DenseIndex(
        blocks=blocks,
        embeddings=np.asarray([[1.0, 0.0]], dtype=np.float32),
        model_id="mock-bge",
        backend="numpy",
    )

    try:
        index.search(np.asarray([[1.0, 0.0, 0.0]], dtype=np.float32), top_k=1)
    except ValueError as exc:
        message = str(exc)
        assert "dense query embedding dimension mismatch" in message
        assert "query_dim=3" in message
        assert "index_dim=2" in message
        assert "mock-bge" in message
    else:
        raise AssertionError("expected ValueError")


def test_dense_index_rejects_stale_chunk_text(tmp_path) -> None:
    blocks = [_block("b1", "invoice date")]
    index = DenseIndex(
        blocks=blocks,
        embeddings=np.asarray([[1.0, 0.0]], dtype=np.float32),
        model_id="mock-bge",
        backend="numpy",
    )
    index.save(tmp_path)
    changed = [_block("b1", "invoice due date")]

    try:
        DenseIndex.load(index_dir=tmp_path, blocks=changed)
    except ValueError as exc:
        assert "evidence hash" in str(exc)
        assert "rebuild" in str(exc)
    else:
        raise AssertionError("expected stale dense index failure")

from __future__ import annotations

import json

import numpy as np
import pytest

from docagent.retrieval.base import RetrievalCandidate
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.fusion import reciprocal_rank_fusion
from docagent.schemas import EvidenceBlock, EvidenceLocation
from scripts.smoke_phase2_real_retrieval import (
    DENSE_BACKEND,
    RERANKER_BACKEND,
    candidate_payload,
    dense_metadata_path,
    validate_real_backends,
)


def _block(block_id: str, text: str = "invoice date") -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="doc",
        block_id=block_id,
        block_type="text",
        text=text,
        page_id=1,
        location=EvidenceLocation(page=1, block_id=block_id, bbox=[0, 1, 2, 3]),
    )


def test_real_dense_model_id_uses_distinct_cache_files_and_loads_block_mapping(tmp_path) -> None:
    blocks = [_block("b1"), _block("b2", "revenue table")]
    embeddings = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    index = DenseIndex(blocks=blocks, embeddings=embeddings, model_id="bge-m3-dense-1024", backend="numpy")

    metadata = index.save(tmp_path, artifact_prefix="bge-m3-dense-1024")
    metadata_path = dense_metadata_path(tmp_path, "bge-m3-dense-1024")
    loaded = DenseIndex.load(index_dir=tmp_path, blocks=list(reversed(blocks)), metadata_path=metadata_path)

    assert index.model_id != "hash-dense-256"
    assert metadata_path.is_file()
    assert not (tmp_path / "index_metadata_hash-dense-256.json").exists()
    assert metadata["model_id"] == "bge-m3-dense-1024"
    assert metadata["metadata_path"] == str(metadata_path)
    assert "bge-m3-dense-1024" in str(metadata["embeddings_path"])
    assert [block.block_id for block in loaded.blocks] == ["b1", "b2"]


def test_cache_metadata_path_includes_model_id(tmp_path) -> None:
    real_path = dense_metadata_path(tmp_path, "bge-m3-dense-1024")
    other_path = dense_metadata_path(tmp_path, "bge-m3-dense-1024-v2")

    assert real_path.name == "index_metadata_bge-m3-dense-1024.json"
    assert real_path != other_path


def test_rrf_and_candidate_payload_keep_stage_ranks_and_reranker_metadata() -> None:
    b1 = _block("b1")
    b2 = _block("b2")
    fused = reciprocal_rank_fusion(
        {
            "bm25": [(b1, 2.0), (b2, 1.0)],
            "dense": [(b2, 0.9), (b1, 0.4)],
        },
        rrf_k=60,
    )
    for rank, candidate in enumerate(fused, start=1):
        candidate.ranks["rrf"] = rank
        candidate.rerank_score = 4.0 - rank
        candidate.ranks["reranker"] = rank

    payload = candidate_payload(
        fused[0],
        final_rank=1,
        dense_model_id="bge-m3-dense-1024",
        reranker_model_path="/root/autodl-tmp/models/bge-reranker-v2-m3",
    )

    assert payload["block_id"] == "b1"
    assert payload["page"] == 1
    assert payload["bm25_rank"] == 1
    assert payload["dense_rank"] == 2
    assert payload["rrf_rank"] == 1
    assert payload["reranker_score"] == pytest.approx(3.0)
    assert payload["reranker_rank"] == 1
    assert payload["final_rank"] == 1
    assert payload["dense_backend"] == DENSE_BACKEND
    assert payload["reranker_backend"] == RERANKER_BACKEND
    json.dumps(payload, ensure_ascii=False)


def test_validate_real_backends_rejects_mock_or_keyword_fallback() -> None:
    validate_real_backends(
        dense_backend=DENSE_BACKEND,
        reranker_backend=RERANKER_BACKEND,
        dense_model_id="bge-m3-dense-1024",
    )

    with pytest.raises(RuntimeError, match="dense_backend"):
        validate_real_backends(
            dense_backend="hash",
            reranker_backend=RERANKER_BACKEND,
            dense_model_id="bge-m3-dense-1024",
        )
    with pytest.raises(RuntimeError, match="reranker_backend"):
        validate_real_backends(
            dense_backend=DENSE_BACKEND,
            reranker_backend="keyword",
            dense_model_id="bge-m3-dense-1024",
        )
    with pytest.raises(RuntimeError, match="mock dense index"):
        validate_real_backends(
            dense_backend=DENSE_BACKEND,
            reranker_backend=RERANKER_BACKEND,
            dense_model_id="hash-dense-256",
        )


def test_smoke_json_shape_is_serializable() -> None:
    candidate = RetrievalCandidate(
        block=_block("b1"),
        bm25_score=1.0,
        dense_score=0.8,
        rrf_score=0.03,
        rerank_score=4.0,
        ranks={"bm25": 1, "dense": 1, "rrf": 1, "reranker": 1},
        sources=["bm25", "dense"],
    )
    payload = {
        "command": "phase2_real_retrieval_smoke",
        "status": "success",
        "dense": {
            "backend": DENSE_BACKEND,
            "model_id": "bge-m3-dense-1024",
            "index_saved": True,
            "index_reloaded": True,
        },
        "reranker": {"backend": RERANKER_BACKEND},
        "candidates": [
            candidate_payload(
                candidate,
                final_rank=1,
                dense_model_id="bge-m3-dense-1024",
                reranker_model_path="/root/autodl-tmp/models/bge-reranker-v2-m3",
            )
        ],
        "no_mock_fallback": True,
    }

    encoded = json.dumps(payload, ensure_ascii=False)
    assert "hash-dense-256" not in encoded
    assert "keyword" not in encoded

from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np

from docagent.retrieval.base import RetrievalCandidate
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig
from docagent.retrieval.reranker import CrossEncoderReranker, CrossEncoderRerankerConfig
from docagent.schemas import EvidenceBlock, EvidenceLocation


def test_dense_encoder_passes_flagembedding_devices(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    class FakeBGEM3FlagModel:
        def __init__(self, model_path: str, **kwargs) -> None:
            calls.append({"model_path": model_path, "kwargs": kwargs})

        def encode(self, texts, **kwargs):
            return {"dense_vecs": np.ones((len(texts), 3), dtype=np.float32)}

    fake_module = types.SimpleNamespace(BGEM3FlagModel=FakeBGEM3FlagModel)
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_module)

    model_path = tmp_path / "bge-m3"
    model_path.mkdir()
    encoder = DenseEncoder(
        DenseEncoderConfig(
            model_path=str(model_path),
            device="cuda:1",
            use_fp16=True,
        )
    )

    embeddings = encoder.encode_documents(["alpha", "beta"])

    assert embeddings.shape == (2, 3)
    assert calls[0]["kwargs"]["devices"] == "cuda:1"
    assert "device" not in calls[0]["kwargs"]
    assert calls[0]["kwargs"]["use_fp16"] is True


def test_cross_encoder_reranker_passes_flagembedding_devices(monkeypatch, tmp_path: Path) -> None:
    calls: list[dict] = []

    class FakeFlagReranker:
        def __init__(self, model_path: str, **kwargs) -> None:
            calls.append({"model_path": model_path, "kwargs": kwargs})

        def compute_score(self, pairs, **kwargs):
            return [0.1, 0.9]

    fake_module = types.SimpleNamespace(FlagReranker=FakeFlagReranker)
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_module)

    model_path = tmp_path / "bge-reranker-v2-m3"
    model_path.mkdir()
    reranker = CrossEncoderReranker(
        CrossEncoderRerankerConfig(
            model_path=str(model_path),
            device="cuda:1",
            use_fp16=True,
        )
    )
    candidates = [
        _candidate("b1", "irrelevant passage", rrf_rank=1),
        _candidate("b2", "relevant passage", rrf_rank=2),
    ]

    reranked = reranker.score(query="query", candidates=candidates)

    assert [candidate.block.block_id for candidate in reranked] == ["b2", "b1"]
    assert calls[0]["kwargs"]["devices"] == "cuda:1"
    assert "device" not in calls[0]["kwargs"]
    assert calls[0]["kwargs"]["use_fp16"] is True


def _candidate(block_id: str, text: str, *, rrf_rank: int) -> RetrievalCandidate:
    return RetrievalCandidate(
        block=EvidenceBlock(
            doc_id="doc",
            block_id=block_id,
            block_type="text",
            text=text,
            location=EvidenceLocation(page=1, block_id=block_id),
        ),
        ranks={"rrf": rrf_rank},
    )

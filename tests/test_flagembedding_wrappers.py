from __future__ import annotations

import sys
import types
from pathlib import Path

import numpy as np
import pytest
import torch

from docagent.retrieval.base import RetrievalCandidate
from docagent.retrieval.dense_encoder import DenseEncoder, DenseEncoderConfig
from docagent.retrieval.hybrid_retriever import HybridRetriever
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


def test_cross_encoder_reranker_uses_transformers_pair_scoring(monkeypatch, tmp_path: Path) -> None:
    state = _install_fake_transformers(monkeypatch)

    model_path = tmp_path / "bge-reranker-v2-m3"
    model_path.mkdir()
    reranker = CrossEncoderReranker(
        CrossEncoderRerankerConfig(
            model_path=str(model_path),
            device="cpu",
            use_fp16=True,
            batch_size=2,
            max_length=17,
        )
    )
    candidates = [
        _candidate("b1", "irrelevant passage", rrf_rank=1),
        _candidate("b2", "relevant passage", rrf_rank=2),
        _candidate("b3", "partly relevant passage", rrf_rank=3),
    ]

    reranked = reranker.score(query="query", candidates=candidates)

    assert [candidate.rerank_score for candidate in candidates] == pytest.approx([0.1, 0.9, 0.4])
    assert [candidate.block.block_id for candidate in reranked] == ["b2", "b3", "b1"]
    assert [candidate.ranks["reranker"] for candidate in reranked] == [1, 2, 3]
    reranker.score(query="query", candidates=[_candidate("b4", "another passage", rrf_rank=4)])

    assert len(state["tokenizer_calls"]) == 3
    assert state["tokenizer_calls"][0]["queries"] == ["query", "query"]
    assert state["tokenizer_calls"][0]["passages"] == ["irrelevant passage", "relevant passage"]
    assert state["tokenizer_calls"][0]["kwargs"]["max_length"] == 17
    assert state["tokenizer_calls"][0]["kwargs"]["return_tensors"] == "pt"
    assert state["prepare_for_model_calls"] == 0
    assert state["tokenizer_loads"] == 1
    assert state["model_loads"] == 1
    assert state["model"].to_calls == ["cpu"]
    assert state["model"].half_calls == 0
    assert reranker.metadata == {
        "backend": "transformers_sequence_classification",
        "model_path": str(model_path),
        "device": "cpu",
        "dtype": "float32",
        "max_length": 17,
    }


def test_cross_encoder_reranker_does_not_fallback_to_keyword(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "transformers", None)
    model_path = tmp_path / "bge-reranker-v2-m3"
    model_path.mkdir()
    reranker = CrossEncoderReranker(CrossEncoderRerankerConfig(model_path=str(model_path)))

    with pytest.raises(RuntimeError, match="transformers and torch are required"):
        reranker.score(query="query", candidates=[_candidate("b1", "query terms", rrf_rank=1)])


def test_hybrid_retriever_metadata_includes_reranker_metadata() -> None:
    class FakeReranker:
        metadata = {
            "backend": "transformers_sequence_classification",
            "model_path": "/models/reranker",
            "device": "cuda:1",
            "dtype": "float16",
            "max_length": 1024,
        }

    block = _candidate("b1", "invoice date", rrf_rank=1).block
    result = HybridRetriever([block], reranker=FakeReranker()).retrieve_result(
        doc_id="doc",
        question="invoice date",
        top_k=1,
        mode="bm25",
    )

    assert result.metadata["reranker"] == FakeReranker.metadata


def _install_fake_transformers(monkeypatch) -> dict:
    state = {
        "tokenizer_loads": 0,
        "model_loads": 0,
        "tokenizer_calls": [],
        "prepare_for_model_calls": 0,
        "model": None,
    }

    class FakeTokenizer:
        def __call__(self, queries, passages, **kwargs):
            assert isinstance(queries, list)
            assert isinstance(passages, list)
            assert len(queries) == len(passages)
            state["tokenizer_calls"].append(
                {
                    "queries": list(queries),
                    "passages": list(passages),
                    "kwargs": kwargs,
                }
            )
            return {
                "input_ids": torch.ones((len(queries), 2), dtype=torch.long),
                "attention_mask": torch.ones((len(queries), 2), dtype=torch.long),
            }

        def prepare_for_model(self, *args, **kwargs):
            state["prepare_for_model_calls"] += 1
            raise AssertionError("prepare_for_model must not be called")

    class FakeAutoTokenizer:
        @classmethod
        def from_pretrained(cls, model_path: str, **kwargs):
            state["tokenizer_loads"] += 1
            assert kwargs["local_files_only"] is True
            return FakeTokenizer()

    class FakeModel:
        def __init__(self) -> None:
            self.to_calls: list[str] = []
            self.half_calls = 0
            self.eval_calls = 0
            self._scores = iter([0.1, 0.9, 0.4, 0.2])

        def half(self):
            self.half_calls += 1
            return self

        def to(self, device: str):
            self.to_calls.append(device)
            return self

        def eval(self):
            self.eval_calls += 1
            return self

        def __call__(self, **kwargs):
            batch_size = int(kwargs["input_ids"].shape[0])
            values = [next(self._scores) for _ in range(batch_size)]
            return types.SimpleNamespace(logits=torch.tensor(values, dtype=torch.float32).reshape(batch_size, 1))

    class FakeAutoModelForSequenceClassification:
        @classmethod
        def from_pretrained(cls, model_path: str, **kwargs):
            state["model_loads"] += 1
            assert kwargs["local_files_only"] is True
            state["model"] = FakeModel()
            return state["model"]

    fake_module = types.SimpleNamespace(
        AutoTokenizer=FakeAutoTokenizer,
        AutoModelForSequenceClassification=FakeAutoModelForSequenceClassification,
    )
    monkeypatch.setitem(sys.modules, "transformers", fake_module)
    return state


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

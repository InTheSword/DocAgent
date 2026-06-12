from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from docagent.retrieval.base import RetrievalCandidate
from docagent.retrieval.bm25_index import tokenize


class Reranker(Protocol):
    def score(self, *, query: str, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
        ...


@dataclass
class CrossEncoderRerankerConfig:
    model_path: str
    device: str = "cpu"
    use_fp16: bool = False
    batch_size: int = 8
    max_length: int = 1024


class CrossEncoderReranker:
    def __init__(self, config: CrossEncoderRerankerConfig) -> None:
        self.config = config
        self._model = None

    def _load_model(self):
        if self._model is not None:
            return self._model
        if not Path(self.config.model_path).exists():
            raise FileNotFoundError(f"reranker model path does not exist: {self.config.model_path}")
        try:
            from FlagEmbedding import FlagReranker
        except ImportError as exc:
            raise RuntimeError("FlagEmbedding is required for bge-reranker-v2-m3") from exc
        self._model = FlagReranker(
            self.config.model_path,
            use_fp16=self.config.use_fp16,
            devices=self.config.device,
        )
        return self._model

    def score(self, *, query: str, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
        if not candidates:
            return []
        model = self._load_model()
        pairs = [[query, candidate.block.retrieval_text] for candidate in candidates]
        scores = model.compute_score(
            pairs,
            batch_size=self.config.batch_size,
            max_length=self.config.max_length,
        )
        if not isinstance(scores, list):
            scores = [scores]
        for candidate, score in zip(candidates, scores):
            candidate.rerank_score = float(score)
        return sorted(
            candidates,
            key=lambda item: (-(item.rerank_score or 0.0), item.ranks.get("rrf", 10**9), item.block.block_id),
        )


class KeywordOverlapReranker:
    """Small deterministic reranker for tests and no-card smoke runs."""

    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "form",
        "from",
        "full",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "which",
        "who",
        "whose",
    }

    def score(self, *, query: str, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
        query_terms = {term for term in tokenize(query) if term not in self.stopwords}
        if not query_terms:
            query_terms = set(tokenize(query))
        for candidate in candidates:
            text_terms = set(tokenize(candidate.block.retrieval_text))
            candidate.rerank_score = float(len(query_terms & text_terms))
        return sorted(
            candidates,
            key=lambda item: (-(item.rerank_score or 0.0), item.ranks.get("rrf", 10**9), item.block.block_id),
        )

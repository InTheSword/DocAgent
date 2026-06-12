from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

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
    local_files_only: bool = True


class CrossEncoderReranker:
    backend = "transformers_sequence_classification"

    def __init__(self, config: CrossEncoderRerankerConfig) -> None:
        self.config = config
        self._tokenizer = None
        self._model = None
        self._device: str | None = None
        self._dtype = "float32"

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "model_path": self.config.model_path,
            "device": self._device or self.config.device,
            "dtype": self._dtype,
            "max_length": self.config.max_length,
        }

    def _load_model(self):
        if self._model is not None:
            return self._tokenizer, self._model
        if not Path(self.config.model_path).exists():
            raise FileNotFoundError(f"reranker model path does not exist: {self.config.model_path}")
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("transformers and torch are required for bge-reranker-v2-m3") from exc

        device = self._resolve_device(torch)
        tokenizer = AutoTokenizer.from_pretrained(
            self.config.model_path,
            local_files_only=self.config.local_files_only,
        )
        model = AutoModelForSequenceClassification.from_pretrained(
            self.config.model_path,
            local_files_only=self.config.local_files_only,
        )
        if self.config.use_fp16 and device.startswith("cuda"):
            model = model.half()
            self._dtype = "float16"
        else:
            self._dtype = "float32"
        model = model.to(device)
        model.eval()

        self._tokenizer = tokenizer
        self._model = model
        self._device = device
        return self._tokenizer, self._model

    def score(self, *, query: str, candidates: list[RetrievalCandidate]) -> list[RetrievalCandidate]:
        if not candidates:
            return []
        tokenizer, model = self._load_model()
        scores = self._score_pairs(tokenizer=tokenizer, model=model, query=query, candidates=candidates)
        for candidate, score in zip(candidates, scores):
            candidate.rerank_score = float(score)
        reranked = sorted(
            candidates,
            key=lambda item: (-(item.rerank_score or 0.0), item.ranks.get("rrf", 10**9), item.block.block_id),
        )
        for rank, candidate in enumerate(reranked, start=1):
            candidate.ranks["reranker"] = rank
        return reranked

    def _resolve_device(self, torch: Any) -> str:
        device = self.config.device
        if device.startswith("cuda") and not torch.cuda.is_available():
            raise RuntimeError(f"CUDA device requested for reranker but unavailable: {device}")
        return device

    def _score_pairs(self, *, tokenizer: Any, model: Any, query: str, candidates: list[RetrievalCandidate]) -> list[float]:
        import torch

        scores: list[float] = []
        for start in range(0, len(candidates), self.config.batch_size):
            batch = candidates[start : start + self.config.batch_size]
            queries = [query for _ in batch]
            passages = [candidate.block.retrieval_text for candidate in batch]
            inputs = tokenizer(
                queries,
                passages,
                padding=True,
                truncation=True,
                max_length=self.config.max_length,
                return_tensors="pt",
            )
            inputs = {
                key: value.to(self._device or self.config.device) if hasattr(value, "to") else value
                for key, value in inputs.items()
            }
            with torch.inference_mode():
                output = model(**inputs, return_dict=True)
            logits = output.logits
            if logits.ndim == 2 and logits.shape[1] == 1:
                values = logits[:, 0]
            elif logits.ndim == 1:
                values = logits
            else:
                raise RuntimeError(f"reranker model must return one logit per pair, got shape={tuple(logits.shape)}")
            scores.extend(float(value) for value in values.float().detach().cpu().tolist())
        if len(scores) != len(candidates):
            raise RuntimeError(f"reranker returned {len(scores)} scores for {len(candidates)} candidates")
        return scores


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

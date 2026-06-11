from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from docagent.retrieval.bm25_index import tokenize

import numpy as np


@dataclass
class DenseEncoderConfig:
    model_path: str
    device: str = "cpu"
    use_fp16: bool = False
    batch_size: int = 16
    max_length: int = 1024
    normalize_embeddings: bool = True


class DenseEncoder:
    def __init__(self, config: DenseEncoderConfig) -> None:
        self.config = config
        self._model = None

    @property
    def model_id(self) -> str:
        return self.config.model_path

    def _load_model(self):
        if self._model is not None:
            return self._model
        if not Path(self.config.model_path).exists():
            raise FileNotFoundError(f"dense model path does not exist: {self.config.model_path}")
        try:
            from FlagEmbedding import BGEM3FlagModel
        except ImportError as exc:
            raise RuntimeError("FlagEmbedding is required for BGE-M3 dense retrieval") from exc
        self._model = BGEM3FlagModel(
            self.config.model_path,
            use_fp16=self.config.use_fp16,
            device=self.config.device,
        )
        return self._model

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def _encode(self, texts: list[str]) -> np.ndarray:
        clean_texts = [text for text in texts if text and text.strip()]
        if not clean_texts:
            return np.zeros((0, 0), dtype=np.float32)
        model = self._load_model()
        result = model.encode(
            clean_texts,
            batch_size=self.config.batch_size,
            max_length=self.config.max_length,
            return_dense=True,
        )
        vectors = result.get("dense_vecs") if isinstance(result, dict) else result
        array = np.asarray(vectors, dtype=np.float32)
        if self.config.normalize_embeddings:
            array = _normalize(array)
        return array


class HashDenseEncoder:
    """Deterministic local encoder for no-download Phase 2 smoke tests."""

    def __init__(self, *, dimension: int = 256) -> None:
        self.dimension = dimension

    @property
    def model_id(self) -> str:
        return f"hash-dense-{self.dimension}"

    def encode_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def encode_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts)

    def _encode(self, texts: list[str]) -> np.ndarray:
        vectors = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in tokenize(text):
                digest = hashlib.sha256(token.encode("utf-8")).digest()
                bucket = int.from_bytes(digest[:8], "big") % self.dimension
                vectors[row, bucket] += 1.0
        return _normalize(vectors)


def _normalize(array: np.ndarray) -> np.ndarray:
    if array.size == 0:
        return array.astype(np.float32)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (array / norms).astype(np.float32)

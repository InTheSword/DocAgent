from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from docagent.retrieval.dense_encoder import _normalize
from docagent.schemas import EvidenceBlock


@dataclass
class DenseSearchResult:
    block: EvidenceBlock
    score: float
    rank: int


class DenseIndex:
    def __init__(
        self,
        *,
        blocks: list[EvidenceBlock],
        embeddings: np.ndarray,
        model_id: str,
        normalized: bool = True,
        backend: str = "numpy",
    ) -> None:
        if len(blocks) != len(embeddings):
            raise ValueError("blocks and embeddings must have the same length")
        self.blocks = blocks
        self.embeddings = _normalize(embeddings.astype(np.float32)) if normalized else embeddings.astype(np.float32)
        self.model_id = model_id
        self.normalized = normalized
        self.backend = backend
        self._faiss_index = None
        if backend == "faiss":
            self._faiss_index = self._build_faiss_index()

    @classmethod
    def build(cls, *, blocks: list[EvidenceBlock], embeddings: np.ndarray, model_id: str) -> "DenseIndex":
        backend = "faiss" if _faiss_available() else "numpy"
        return cls(blocks=blocks, embeddings=embeddings, model_id=model_id, normalized=True, backend=backend)

    @classmethod
    def load(cls, *, index_dir: str | Path, blocks: list[EvidenceBlock]) -> "DenseIndex":
        path = Path(index_dir)
        metadata = json.loads((path / "index_metadata.json").read_text(encoding="utf-8"))
        embeddings = np.load(metadata["embeddings_path"])
        blocks_by_id = {block.block_id: block for block in blocks}
        ordered_blocks = [blocks_by_id[block_id] for block_id in metadata["block_ids"] if block_id in blocks_by_id]
        if len(ordered_blocks) != len(embeddings):
            raise ValueError("dense index metadata block_ids do not match loaded evidence blocks")
        return cls(
            blocks=ordered_blocks,
            embeddings=embeddings,
            model_id=str(metadata.get("model_id") or ""),
            normalized=bool(metadata.get("normalized", True)),
            backend=str(metadata.get("backend") or "numpy"),
        )

    def search(self, query_embedding: np.ndarray, top_k: int = 5) -> list[DenseSearchResult]:
        if len(self.blocks) == 0:
            return []
        query = np.asarray(query_embedding, dtype=np.float32)
        if query.ndim == 2:
            query = query[0]
        query = _normalize(query.reshape(1, -1))[0]
        if self._faiss_index is not None:
            scores, indices = self._faiss_index.search(query.reshape(1, -1), min(top_k, len(self.blocks)))
            pairs = [(int(idx), float(score)) for idx, score in zip(indices[0], scores[0]) if idx >= 0]
        else:
            scores = self.embeddings @ query
            order = np.argsort(-scores)[:top_k]
            pairs = [(int(idx), float(scores[idx])) for idx in order]
        return [
            DenseSearchResult(block=self.blocks[idx], score=score, rank=rank)
            for rank, (idx, score) in enumerate(pairs, start=1)
        ]

    def save(self, output_dir: str | Path) -> dict[str, object]:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        embeddings_path = path / "dense_embeddings.npy"
        metadata_path = path / "index_metadata.json"
        np.save(embeddings_path, self.embeddings)
        faiss_path: str | None = None
        if self._faiss_index is not None:
            try:
                import faiss
            except ImportError as exc:
                raise RuntimeError("FAISS backend was selected but faiss is unavailable") from exc
            faiss_file = path / "dense_index.faiss"
            faiss.write_index(self._faiss_index, str(faiss_file))
            faiss_path = str(faiss_file)
        metadata = {
            "model_id": self.model_id,
            "embedding_dim": int(self.embeddings.shape[1]) if self.embeddings.ndim == 2 else 0,
            "normalized": self.normalized,
            "backend": self.backend,
            "block_ids": [block.block_id for block in self.blocks],
            "embeddings_path": str(embeddings_path),
            "faiss_path": faiss_path,
        }
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        return metadata

    def _build_faiss_index(self):
        try:
            import faiss
        except ImportError as exc:
            raise RuntimeError("FAISS backend was requested but faiss is unavailable") from exc
        if self.embeddings.size == 0:
            return None
        index = faiss.IndexFlatIP(self.embeddings.shape[1])
        index.add(self.embeddings)
        return index


def _faiss_available() -> bool:
    try:
        import faiss  # noqa: F401
    except ImportError:
        return False
    return True

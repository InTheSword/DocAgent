from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from docagent.retrieval.dense_encoder import _normalize
from docagent.schemas import Chunk


def evidence_hash(blocks: list[Chunk]) -> str:
    payload = [
        {
            "block_id": block.block_id,
            "retrieval_text": block.retrieval_text,
            "content_hash": block.metadata.get("content_hash"),
            "chunk_contract_version": block.metadata.get("chunk_contract_version"),
        }
        for block in blocks
    ]
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass
class DenseSearchResult:
    block: Chunk
    score: float
    rank: int


class DenseIndex:
    def __init__(
        self,
        *,
        blocks: list[Chunk],
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
    def build(cls, *, blocks: list[Chunk], embeddings: np.ndarray, model_id: str) -> "DenseIndex":
        backend = "faiss" if _faiss_available() else "numpy"
        return cls(blocks=blocks, embeddings=embeddings, model_id=model_id, normalized=True, backend=backend)

    @classmethod
    def load(
        cls,
        *,
        index_dir: str | Path,
        blocks: list[Chunk],
        metadata_path: str | Path | None = None,
    ) -> "DenseIndex":
        path = Path(index_dir)
        metadata_file = Path(metadata_path) if metadata_path is not None else path / "index_metadata.json"
        metadata = json.loads(metadata_file.read_text(encoding="utf-8"))
        embeddings = np.load(metadata["embeddings_path"])
        blocks_by_id = {block.block_id: block for block in blocks}
        ordered_blocks = [blocks_by_id[block_id] for block_id in metadata["block_ids"] if block_id in blocks_by_id]
        if len(ordered_blocks) != len(embeddings):
            raise ValueError("dense index metadata block_ids do not match loaded evidence blocks")
        expected_hash = str(metadata.get("evidence_hash") or "")
        current_hash = evidence_hash(ordered_blocks)
        if not expected_hash or expected_hash != current_hash:
            raise ValueError("dense index evidence hash does not match current chunks; rebuild the dense index")
        return cls(
            blocks=ordered_blocks,
            embeddings=embeddings,
            model_id=str(metadata.get("model_id") or ""),
            normalized=bool(metadata.get("normalized", True)),
            backend=str(metadata.get("backend") or "numpy"),
        )

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 5,
        *,
        allowed_block_ids: set[str] | None = None,
    ) -> list[DenseSearchResult]:
        if len(self.blocks) == 0:
            return []
        query = np.asarray(query_embedding, dtype=np.float32)
        if query.ndim == 2:
            query = query[0]
        index_dim = int(self.embeddings.shape[1]) if self.embeddings.ndim == 2 else 0
        query_dim = int(query.shape[0]) if query.ndim == 1 else 0
        if query_dim != index_dim:
            raise ValueError(
                "dense query embedding dimension mismatch: "
                f"query_dim={query_dim}, index_dim={index_dim}, model_id={self.model_id}"
            )
        query = _normalize(query.reshape(1, -1))[0]
        if allowed_block_ids is not None:
            eligible = [
                index
                for index, block in enumerate(self.blocks)
                if block.block_id in allowed_block_ids
            ]
            if not eligible:
                return []
            eligible_array = np.asarray(eligible, dtype=np.int64)
            scores = self.embeddings[eligible_array] @ query
            order = np.argsort(-scores)[: min(top_k, len(eligible))]
            pairs = [(eligible[int(idx)], float(scores[int(idx)])) for idx in order]
        elif self._faiss_index is not None:
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

    def save(self, output_dir: str | Path, *, artifact_prefix: str | None = None) -> dict[str, object]:
        path = Path(output_dir)
        path.mkdir(parents=True, exist_ok=True)
        suffix = f"_{_safe_artifact_prefix(artifact_prefix)}" if artifact_prefix else ""
        embeddings_path = path / f"dense_embeddings{suffix}.npy"
        metadata_path = path / f"index_metadata{suffix}.json"
        np.save(embeddings_path, self.embeddings)
        faiss_path: str | None = None
        if self._faiss_index is not None:
            try:
                import faiss
            except ImportError as exc:
                raise RuntimeError("FAISS backend was selected but faiss is unavailable") from exc
            faiss_file = path / f"dense_index{suffix}.faiss"
            faiss.write_index(self._faiss_index, str(faiss_file))
            faiss_path = str(faiss_file)
        metadata = {
            "model_id": self.model_id,
            "embedding_dim": int(self.embeddings.shape[1]) if self.embeddings.ndim == 2 else 0,
            "normalized": self.normalized,
            "backend": self.backend,
            "block_ids": [block.block_id for block in self.blocks],
            "evidence_hash": evidence_hash(self.blocks),
            "chunk_contract_versions": sorted(
                {
                    str(block.metadata.get("chunk_contract_version"))
                    for block in self.blocks
                    if block.metadata.get("chunk_contract_version")
                }
            ),
            "embeddings_path": str(embeddings_path),
            "faiss_path": faiss_path,
            "metadata_path": str(metadata_path),
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


def _safe_artifact_prefix(prefix: str | None) -> str:
    if not prefix:
        return ""
    if any(part in prefix for part in ("/", "\\", ":", "\0")):
        raise ValueError(f"dense index artifact_prefix must be a filename stem, got: {prefix!r}")
    return prefix

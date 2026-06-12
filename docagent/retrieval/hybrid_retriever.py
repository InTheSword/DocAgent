from __future__ import annotations

import time

from docagent.retrieval.bm25_index import BM25Index
from docagent.retrieval.base import RetrievalCandidate, RetrievalResult
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.fusion import reciprocal_rank_fusion
from docagent.retrieval.query_rewrite import rewrite_query
from docagent.retrieval.reranker import Reranker
from docagent.schemas import EvidenceBlock


class HybridRetriever:
    def __init__(
        self,
        blocks: list[EvidenceBlock],
        *,
        dense_index: DenseIndex | None = None,
        reranker: Reranker | None = None,
        mode: str = "bm25",
        bm25_top_n: int = 20,
        dense_top_n: int = 20,
        fusion_top_n: int = 20,
        rrf_k: int = 60,
    ) -> None:
        self.blocks = blocks
        self.bm25 = BM25Index(blocks)
        self.dense_index = dense_index
        self.reranker = reranker
        self.mode = mode
        self.bm25_top_n = bm25_top_n
        self.dense_top_n = dense_top_n
        self.fusion_top_n = fusion_top_n
        self.rrf_k = rrf_k

    def retrieve(
        self,
        question: str,
        top_k: int = 5,
        answer_type_hint: str | None = None,
    ) -> tuple[str, list[tuple[EvidenceBlock, float]]]:
        rewrite = rewrite_query(question, answer_type_hint=answer_type_hint)
        query = f"{question} {rewrite.rewritten_query}".strip()
        candidate_k = min(len(self.blocks), max(top_k * 10, top_k))
        hits = self.bm25.search(query, top_k=candidate_k)
        if not hits:
            return rewrite.rewritten_query, hits
        max_score = max(score for _block, score in hits) or 1.0
        target_types = set(rewrite.target_evidence_type)
        reranked = []
        for block, score in hits:
            boost = 0.0
            if block.block_type in target_types:
                boost += 0.10 * max_score
            if answer_type_hint == "numeric" and block.block_type == "table":
                boost += 0.45 * max_score
            reranked.append((block, score + boost))
        reranked.sort(key=lambda item: item[1], reverse=True)
        return rewrite.rewritten_query, reranked[:top_k]

    def retrieve_result(
        self,
        *,
        doc_id: str | None,
        question: str,
        top_k: int = 5,
        answer_type_hint: str | None = None,
        mode: str | None = None,
        query_embedding=None,
    ) -> RetrievalResult:
        active_mode = mode or self.mode
        start = time.perf_counter()
        rewrite = rewrite_query(question, answer_type_hint=answer_type_hint)
        query = f"{question} {rewrite.rewritten_query}".strip()
        candidate_blocks = [block for block in self.blocks if doc_id is None or block.doc_id == doc_id]
        bm25 = BM25Index(candidate_blocks)
        timings: dict[str, float] = {}

        bm25_start = time.perf_counter()
        bm25_hits = bm25.search(query, top_k=min(len(candidate_blocks), max(self.bm25_top_n, top_k)))
        timings["bm25"] = (time.perf_counter() - bm25_start) * 1000

        if active_mode == "bm25":
            candidates = [
                RetrievalCandidate(block=block, bm25_score=score, ranks={"bm25": rank}, sources=["bm25"])
                for rank, (block, score) in enumerate(bm25_hits[:top_k], start=1)
            ]
            return RetrievalResult(
                rewritten_query=rewrite.rewritten_query,
                candidates=candidates,
                metadata=self._metadata(active_mode, timings, len(candidate_blocks), top_k),
            )

        if active_mode in {"dense", "hybrid", "hybrid_rerank"} and self.dense_index is None:
            raise RuntimeError(f"{active_mode} retrieval requires a dense index")
        if active_mode == "hybrid_rerank" and self.reranker is None:
            raise RuntimeError("hybrid_rerank retrieval requires an enabled reranker")

        dense_hits: list[tuple[EvidenceBlock, float]] = []
        if active_mode in {"dense", "hybrid", "hybrid_rerank"}:
            if query_embedding is None:
                raise RuntimeError("dense retrieval requires query_embedding unless a caller supplies an encoder")
            dense_start = time.perf_counter()
            dense_results = self.dense_index.search(query_embedding, top_k=min(self.dense_top_n, len(candidate_blocks)))
            dense_hits = [(item.block, item.score) for item in dense_results]
            timings["dense"] = (time.perf_counter() - dense_start) * 1000

        if active_mode == "dense":
            candidates = [
                RetrievalCandidate(block=block, dense_score=score, ranks={"dense": rank}, sources=["dense"])
                for rank, (block, score) in enumerate(dense_hits[:top_k], start=1)
            ]
            return RetrievalResult(
                rewritten_query=rewrite.rewritten_query,
                candidates=candidates,
                metadata=self._metadata(active_mode, timings, len(candidate_blocks), top_k),
            )

        fusion_start = time.perf_counter()
        candidates = reciprocal_rank_fusion({"bm25": bm25_hits, "dense": dense_hits}, rrf_k=self.rrf_k)[: self.fusion_top_n]
        for rank, candidate in enumerate(candidates, start=1):
            candidate.ranks["rrf"] = rank
        timings["fusion"] = (time.perf_counter() - fusion_start) * 1000

        if active_mode == "hybrid_rerank":
            rerank_start = time.perf_counter()
            candidates = self.reranker.score(query=query, candidates=candidates)
            timings["rerank"] = (time.perf_counter() - rerank_start) * 1000

        metadata = self._metadata(active_mode, timings, len(candidate_blocks), top_k)
        metadata["latency_ms"] = (time.perf_counter() - start) * 1000
        return RetrievalResult(rewritten_query=rewrite.rewritten_query, candidates=candidates[:top_k], metadata=metadata)

    def _metadata(
        self,
        mode: str,
        timings: dict[str, float],
        num_blocks: int,
        final_top_k: int,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "retriever_mode": mode,
            "num_blocks": num_blocks,
            "bm25_top_n": self.bm25_top_n,
            "dense_top_n": self.dense_top_n,
            "fusion_top_n": self.fusion_top_n,
            "final_top_k": final_top_k,
            "rrf_k": self.rrf_k,
            "reranker_enabled": self.reranker is not None,
            "latency_ms": timings,
        }
        reranker_metadata = getattr(self.reranker, "metadata", None)
        if isinstance(reranker_metadata, dict):
            metadata["reranker"] = reranker_metadata
        return metadata

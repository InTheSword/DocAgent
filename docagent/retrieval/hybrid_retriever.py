from __future__ import annotations

import time

from docagent.retrieval.bm25_index import BM25Index
from docagent.retrieval.base import RetrievalCandidate, RetrievalResult
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.fusion import reciprocal_rank_fusion
from docagent.retrieval.query_planner import QueryPlannerOutput, plan_queries
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
        enable_query_planning: bool = False,
        query_planner_mode: str = "hybrid",
        query_planner_task_type: str = "",
        document_profile: dict[str, object] | None = None,
        query_plan: QueryPlannerOutput | dict[str, object] | None = None,
        query_planner_env_file=None,
        query_planner_model_override: str | None = None,
        query_planner_llm_client=None,
        query_planner_env=None,
    ) -> RetrievalResult:
        active_mode = mode or self.mode
        start = time.perf_counter()
        rewrite = rewrite_query(question, answer_type_hint=answer_type_hint)
        query = f"{question} {rewrite.rewritten_query}".strip()
        planner_output = _coerce_query_plan(query_plan)
        if planner_output is None and enable_query_planning:
            planner_output = plan_queries(
                question=question,
                task_type=query_planner_task_type,
                document_profile=document_profile,
                mode=query_planner_mode,
                answer_type_hint=answer_type_hint,
                llm_client=query_planner_llm_client,
                env_file=query_planner_env_file,
                model_override=query_planner_model_override,
                env=query_planner_env,
            )
        active_queries = planner_output.final_queries if planner_output is not None else [query]
        candidate_blocks = [block for block in self.blocks if doc_id is None or block.doc_id == doc_id]
        candidate_block_ids = {block.block_id for block in candidate_blocks}
        bm25 = BM25Index(candidate_blocks)
        timings: dict[str, float] = {}

        bm25_start = time.perf_counter()
        bm25_rankings = {
            _source_name("bm25", index, active_queries): bm25.search(
                active_query,
                top_k=min(len(candidate_blocks), max(self.bm25_top_n, top_k)),
            )
            for index, active_query in enumerate(active_queries)
        }
        bm25_hits = bm25_rankings.get("bm25") or []
        timings["bm25"] = (time.perf_counter() - bm25_start) * 1000

        if active_mode == "bm25":
            candidates = reciprocal_rank_fusion(bm25_rankings, rrf_k=self.rrf_k)[:top_k]
            for rank, candidate in enumerate(candidates, start=1):
                candidate.ranks["final"] = rank
            return RetrievalResult(
                rewritten_query=_retrieval_query_label(rewrite.rewritten_query, planner_output),
                candidates=candidates,
                metadata=self._metadata(active_mode, timings, len(candidate_blocks), top_k, planner_output),
            )

        if active_mode in {"dense", "hybrid", "hybrid_rerank"} and self.dense_index is None:
            raise RuntimeError(f"{active_mode} retrieval requires a dense index")
        if active_mode == "hybrid_rerank" and self.reranker is None:
            raise RuntimeError("hybrid_rerank retrieval requires an enabled reranker")

        dense_rankings: dict[str, list[tuple[EvidenceBlock, float]]] = {}
        if active_mode in {"dense", "hybrid", "hybrid_rerank"} and candidate_blocks:
            if query_embedding is None:
                raise RuntimeError("dense retrieval requires query_embedding unless a caller supplies an encoder")
            dense_start = time.perf_counter()
            dense_search_top_k = len(self.dense_index.blocks) if doc_id is not None else min(self.dense_top_n, len(candidate_blocks))
            for index, embedding in enumerate(_query_embeddings(query_embedding, len(active_queries))):
                dense_results = self.dense_index.search(embedding, top_k=dense_search_top_k)
                dense_results = [
                    item
                    for item in dense_results
                    if not candidate_block_ids or item.block.block_id in candidate_block_ids
                ][: self.dense_top_n]
                dense_rankings[_source_name("dense", index, active_queries)] = [(item.block, item.score) for item in dense_results]
            timings["dense"] = (time.perf_counter() - dense_start) * 1000

        if active_mode == "dense":
            candidates = reciprocal_rank_fusion(dense_rankings, rrf_k=self.rrf_k)[:top_k]
            for rank, candidate in enumerate(candidates, start=1):
                candidate.ranks["final"] = rank
            return RetrievalResult(
                rewritten_query=_retrieval_query_label(rewrite.rewritten_query, planner_output),
                candidates=candidates,
                metadata=self._metadata(active_mode, timings, len(candidate_blocks), top_k, planner_output),
            )

        fusion_start = time.perf_counter()
        candidates = reciprocal_rank_fusion({**bm25_rankings, **dense_rankings}, rrf_k=self.rrf_k)[: self.fusion_top_n]
        for rank, candidate in enumerate(candidates, start=1):
            candidate.ranks["rrf"] = rank
        timings["fusion"] = (time.perf_counter() - fusion_start) * 1000

        if active_mode == "hybrid_rerank":
            rerank_start = time.perf_counter()
            candidates = self.reranker.score(query=active_queries[0] if active_queries else query, candidates=candidates)
            timings["rerank"] = (time.perf_counter() - rerank_start) * 1000

        metadata = self._metadata(active_mode, timings, len(candidate_blocks), top_k, planner_output)
        metadata["latency_ms"] = (time.perf_counter() - start) * 1000
        return RetrievalResult(
            rewritten_query=_retrieval_query_label(rewrite.rewritten_query, planner_output),
            candidates=candidates[:top_k],
            metadata=metadata,
        )

    def _metadata(
        self,
        mode: str,
        timings: dict[str, float],
        num_blocks: int,
        final_top_k: int,
        query_plan: QueryPlannerOutput | None = None,
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
        if query_plan is not None:
            metadata["query_planner"] = query_plan.to_dict()
        reranker_metadata = getattr(self.reranker, "metadata", None)
        if isinstance(reranker_metadata, dict):
            metadata["reranker"] = reranker_metadata
        return metadata


def _source_name(prefix: str, index: int, queries: list[str]) -> str:
    return prefix if len(queries) == 1 else f"{prefix}:q{index + 1}"


def _retrieval_query_label(rewritten_query: str, query_plan: QueryPlannerOutput | None) -> str:
    if query_plan is None:
        return rewritten_query
    return " | ".join(query_plan.final_queries)


def _coerce_query_plan(value: QueryPlannerOutput | dict[str, object] | None) -> QueryPlannerOutput | None:
    if value is None:
        return None
    if isinstance(value, QueryPlannerOutput):
        return value
    final_queries = [str(item) for item in value.get("final_queries") or [] if str(item).strip()]
    if not final_queries:
        return None
    return QueryPlannerOutput(
        question=str(value.get("question") or ""),
        rule_queries=[str(item) for item in value.get("rule_queries") or [] if str(item).strip()],
        llm_queries=[str(item) for item in value.get("llm_queries") or [] if str(item).strip()],
        final_queries=final_queries,
        mode=str(value.get("mode") or "hybrid"),
        warnings=[str(item) for item in value.get("warnings") or []],
        llm_status=str(value.get("llm_status") or "not_started"),
        error=dict(value.get("error") or {}),
    )


def _query_embeddings(query_embedding, query_count: int):
    ndim = getattr(query_embedding, "ndim", None)
    if ndim == 2 and getattr(query_embedding, "shape", [0])[0] == query_count:
        return [query_embedding[index] for index in range(query_count)]
    return [query_embedding]

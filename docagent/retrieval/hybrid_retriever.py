from __future__ import annotations

import time

from docagent.retrieval.bm25_index import BM25Index
from docagent.retrieval.base import RetrievalCandidate, RetrievalFilter, RetrievalResult
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.fusion import reciprocal_rank_fusion
from docagent.retrieval.metadata_filter import infer_metadata_filter
from docagent.retrieval.query_planner import QueryPlannerOutput, plan_queries
from docagent.retrieval.query_rewrite import rewrite_query
from docagent.retrieval.reranker import Reranker
from docagent.retrieval.table_index import TableRelationalIndex, TableStructuredHit, TableStructuredQuery
from docagent.schemas import Chunk


class HybridRetriever:
    def __init__(
        self,
        blocks: list[Chunk],
        *,
        dense_index: DenseIndex | None = None,
        reranker: Reranker | None = None,
        mode: str = "bm25",
        bm25_top_n: int = 20,
        dense_top_n: int = 20,
        fusion_top_n: int = 20,
        rrf_k: int = 60,
    ) -> None:
        self.blocks = [block for block in blocks if block.is_indexable]
        self.bm25 = BM25Index(self.blocks)
        self.dense_index = dense_index
        self.table_index = TableRelationalIndex(self.blocks)
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
    ) -> tuple[str, list[tuple[Chunk, float]]]:
        rewrite = rewrite_query(question, answer_type_hint=answer_type_hint)
        query = f"{question} {rewrite.rewritten_query}".strip()
        metadata_filter = infer_metadata_filter(question)
        candidate_blocks = [
            block
            for block in self.blocks
            if metadata_filter.is_empty or metadata_filter.matches(block)
        ]
        candidate_k = min(len(candidate_blocks), max(top_k * 10, top_k))
        hits = BM25Index(candidate_blocks).search(query, top_k=candidate_k)
        if not hits and not metadata_filter.is_empty:
            hits = [(block, 1.0) for block in candidate_blocks[:candidate_k]]
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
        filters: RetrievalFilter | None = None,
        query_intent: str | None = None,
        table_query: TableStructuredQuery | dict[str, object] | None = None,
        enable_query_rewrite: bool = True,
    ) -> RetrievalResult:
        active_mode = mode or self.mode
        start = time.perf_counter()
        rewrite = rewrite_query(question, answer_type_hint=answer_type_hint) if enable_query_rewrite else None
        rewritten_query = rewrite.rewritten_query if rewrite is not None else question
        query = f"{question} {rewritten_query}".strip() if rewrite is not None else question
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
        metadata_filter = filters if filters is not None else infer_metadata_filter(question)
        filter_source = "explicit" if filters is not None else ("inferred" if not metadata_filter.is_empty else "none")
        table_intent = str(query_intent or "").casefold() == "table"
        filter_conflict = False
        if table_intent:
            metadata_filter, filter_conflict = _with_table_constraint(metadata_filter)
            filter_source = "query_intent" if filter_source == "none" else f"{filter_source}+query_intent"
        structured_query = TableStructuredQuery.from_value(table_query) if table_intent else None
        scoped_blocks = [block for block in self.blocks if doc_id is None or block.doc_id == doc_id]
        candidate_blocks = [
            block
            for block in scoped_blocks
            if not filter_conflict and (metadata_filter.is_empty or metadata_filter.matches(block))
        ]
        candidate_block_ids = {block.block_id for block in candidate_blocks}
        bm25 = BM25Index(candidate_blocks)
        timings: dict[str, float] = {}
        table_hits: list[TableStructuredHit] = []
        table_rankings: dict[str, list[tuple[Chunk, float]]] = {}
        if structured_query is not None and not structured_query.is_empty:
            table_start = time.perf_counter()
            table_hits = self.table_index.search(
                structured_query,
                top_k=min(len(candidate_blocks), max(self.fusion_top_n, top_k)),
                allowed_block_ids=candidate_block_ids,
            )
            table_rankings["table_structured"] = [
                (item.block, item.score)
                for item in table_hits
            ]
            timings["table_structured"] = (time.perf_counter() - table_start) * 1000

        bm25_start = time.perf_counter()
        bm25_rankings = {
            _source_name("bm25", index, active_queries): bm25.search(
                active_query,
                top_k=min(len(candidate_blocks), max(self.bm25_top_n, top_k)),
            )
            for index, active_query in enumerate(active_queries)
        }
        timings["bm25"] = (time.perf_counter() - bm25_start) * 1000

        if active_mode == "bm25":
            rankings = {**bm25_rankings, **table_rankings}
            candidates = reciprocal_rank_fusion(rankings, rrf_k=self.rrf_k)[:top_k]
            if not candidates and not metadata_filter.is_empty:
                candidates = _constraint_candidates(candidate_blocks, top_k=top_k)
            for rank, candidate in enumerate(candidates, start=1):
                candidate.ranks["final"] = rank
            return RetrievalResult(
                rewritten_query=_retrieval_query_label(rewritten_query, planner_output),
                candidates=candidates,
                metadata=self._metadata(
                    active_mode,
                    timings,
                    len(scoped_blocks),
                    len(candidate_blocks),
                    top_k,
                    planner_output,
                    metadata_filter,
                    filter_source,
                    query_intent,
                    structured_query,
                    table_hits,
                    enable_query_rewrite,
                ),
            )

        if active_mode in {"dense", "hybrid", "hybrid_rerank"} and self.dense_index is None:
            raise RuntimeError(f"{active_mode} retrieval requires a dense index")
        if active_mode == "hybrid_rerank" and self.reranker is None:
            raise RuntimeError("hybrid_rerank retrieval requires an enabled reranker")

        dense_rankings: dict[str, list[tuple[Chunk, float]]] = {}
        if active_mode in {"dense", "hybrid", "hybrid_rerank"} and candidate_blocks:
            if query_embedding is None:
                raise RuntimeError("dense retrieval requires query_embedding unless a caller supplies an encoder")
            dense_start = time.perf_counter()
            for index, embedding in enumerate(_query_embeddings(query_embedding, len(active_queries))):
                dense_results = self.dense_index.search(
                    embedding,
                    top_k=min(self.dense_top_n, len(candidate_blocks)),
                    allowed_block_ids=candidate_block_ids,
                )
                dense_rankings[_source_name("dense", index, active_queries)] = [(item.block, item.score) for item in dense_results]
            timings["dense"] = (time.perf_counter() - dense_start) * 1000

        if active_mode == "dense":
            candidates = reciprocal_rank_fusion(
                {**dense_rankings, **table_rankings},
                rrf_k=self.rrf_k,
            )[:top_k]
            for rank, candidate in enumerate(candidates, start=1):
                candidate.ranks["final"] = rank
            return RetrievalResult(
                rewritten_query=_retrieval_query_label(rewritten_query, planner_output),
                candidates=candidates,
                metadata=self._metadata(
                    active_mode,
                    timings,
                    len(scoped_blocks),
                    len(candidate_blocks),
                    top_k,
                    planner_output,
                    metadata_filter,
                    filter_source,
                    query_intent,
                    structured_query,
                    table_hits,
                    enable_query_rewrite,
                ),
            )

        fusion_start = time.perf_counter()
        candidates = reciprocal_rank_fusion(
            {**bm25_rankings, **dense_rankings, **table_rankings},
            rrf_k=self.rrf_k,
        )[: self.fusion_top_n]
        for rank, candidate in enumerate(candidates, start=1):
            candidate.ranks["rrf"] = rank
        timings["fusion"] = (time.perf_counter() - fusion_start) * 1000

        if active_mode == "hybrid_rerank":
            rerank_start = time.perf_counter()
            candidates = self.reranker.score(query=active_queries[0] if active_queries else query, candidates=candidates)
            timings["rerank"] = (time.perf_counter() - rerank_start) * 1000

        metadata = self._metadata(
            active_mode,
            timings,
            len(scoped_blocks),
            len(candidate_blocks),
            top_k,
            planner_output,
            metadata_filter,
            filter_source,
            query_intent,
            structured_query,
            table_hits,
            enable_query_rewrite,
        )
        metadata["latency_ms"] = (time.perf_counter() - start) * 1000
        return RetrievalResult(
            rewritten_query=_retrieval_query_label(rewritten_query, planner_output),
            candidates=candidates[:top_k],
            metadata=metadata,
        )

    def _metadata(
        self,
        mode: str,
        timings: dict[str, float],
        pre_filter_block_count: int,
        post_filter_block_count: int,
        final_top_k: int,
        query_plan: QueryPlannerOutput | None = None,
        metadata_filter: RetrievalFilter | None = None,
        filter_source: str = "none",
        query_intent: str | None = None,
        table_query: TableStructuredQuery | None = None,
        table_hits: list[TableStructuredHit] | None = None,
        query_rewrite_enabled: bool = True,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "retriever_mode": mode,
            "num_blocks": post_filter_block_count,
            "pre_filter_block_count": pre_filter_block_count,
            "post_filter_block_count": post_filter_block_count,
            "metadata_filter": metadata_filter.to_dict() if metadata_filter is not None else {},
            "metadata_filter_source": filter_source,
            "query_rewrite_enabled": query_rewrite_enabled,
            "retrieval_routes": self._retrieval_routes(
                mode,
                table_query is not None and not table_query.is_empty,
            ),
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
        if query_intent:
            metadata["query_intent"] = query_intent
        if table_query is not None and not table_query.is_empty:
            metadata["table_structured_query"] = table_query.to_dict()
            metadata["table_structured_results"] = [
                hit.to_dict()
                for hit in table_hits or []
            ]
        reranker_metadata = getattr(self.reranker, "metadata", None)
        if isinstance(reranker_metadata, dict):
            metadata["reranker"] = reranker_metadata
        return metadata

    @staticmethod
    def _retrieval_routes(mode: str, table_structured: bool = False) -> list[str]:
        routes = {
            "bm25": ["bm25"],
            "dense": ["dense"],
            "hybrid": ["bm25", "dense"],
            "hybrid_rerank": ["bm25", "dense"],
        }.get(mode, [mode])
        if table_structured:
            routes.append("table_structured")
        return routes


def _source_name(prefix: str, index: int, queries: list[str]) -> str:
    return prefix if len(queries) == 1 else f"{prefix}:q{index + 1}"


def _retrieval_query_label(rewritten_query: str, query_plan: QueryPlannerOutput | None) -> str:
    if query_plan is None:
        return rewritten_query
    return " | ".join(query_plan.final_queries)


def _coerce_query_plan(value: QueryPlannerOutput | dict[str, object] | object | None) -> QueryPlannerOutput | None:
    if value is None:
        return None
    if isinstance(value, QueryPlannerOutput):
        return value
    if hasattr(value, "retrieval_queries"):
        final_queries = [
            str(item)
            for item in getattr(value, "retrieval_queries", ())
            if str(item).strip()
        ]
        question = str(getattr(value, "original_question", ""))
        warnings = [str(item) for item in getattr(value, "warnings", ()) if str(item).strip()]
        mode = "m1"
    elif isinstance(value, dict):
        final_queries = [
            str(item)
            for item in (value.get("retrieval_queries") or value.get("final_queries") or [])
            if str(item).strip()
        ]
        question = str(value.get("original_question") or value.get("question") or "")
        warnings = [str(item) for item in value.get("warnings") or []]
        mode = str(value.get("mode") or ("m1" if value.get("retrieval_queries") else "hybrid"))
    else:
        raise TypeError("query_plan must be QueryPlannerOutput, QueryPlan, or a mapping")
    if not final_queries:
        return None
    return QueryPlannerOutput(
        question=question,
        rule_queries=[],
        llm_queries=[],
        final_queries=final_queries,
        query_sources={"rule": [], "llm": []},
        mode=mode,
        warnings=warnings,
    )


def _query_embeddings(query_embedding, query_count: int):
    ndim = getattr(query_embedding, "ndim", None)
    if ndim == 2 and getattr(query_embedding, "shape", [0])[0] == query_count:
        return [query_embedding[index] for index in range(query_count)]
    return [query_embedding]


def _with_table_constraint(filters: RetrievalFilter) -> tuple[RetrievalFilter, bool]:
    block_conflict = bool(filters.block_types and "table" not in filters.block_types)
    content_conflict = bool(filters.content_types and "table" not in filters.content_types)
    return (
        RetrievalFilter(
            page_ids=filters.page_ids,
            block_ids=filters.block_ids,
            block_types=("table",),
            content_types=("table",),
            heading_roles=filters.heading_roles,
            raw_mineru_types=filters.raw_mineru_types,
            printed_page_numbers=filters.printed_page_numbers,
            section_ids=filters.section_ids,
            section_queries=filters.section_queries,
            feature_tags=filters.feature_tags,
        ),
        block_conflict or content_conflict,
    )


def _constraint_candidates(blocks: list[Chunk], *, top_k: int) -> list[RetrievalCandidate]:
    ordered = sorted(
        blocks,
        key=lambda block: (
            block.page_id if block.page_id is not None else 10**9,
            int(block.metadata.get("page_reading_order") or block.metadata.get("reading_order") or 0),
            block.block_id,
        ),
    )
    return [
        RetrievalCandidate(
            block=block,
            sources=["constraint_filter"],
        )
        for block in ordered[:top_k]
    ]

from __future__ import annotations

from docagent.retrieval.base import RetrievalResult
from docagent.retrieval.dense_encoder import DenseEncoder
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.hybrid_retriever import HybridRetriever
from docagent.retrieval.query_planner import QueryPlannerOutput, plan_queries
from docagent.retrieval.reranker import Reranker
from docagent.schemas import EvidenceBlock


class IndexedDocumentRetriever:
    def __init__(
        self,
        blocks: list[EvidenceBlock],
        *,
        mode: str = "bm25",
        dense_encoder: DenseEncoder | None = None,
        dense_index: DenseIndex | None = None,
        reranker: Reranker | None = None,
        bm25_top_n: int = 20,
        dense_top_n: int = 20,
        fusion_top_n: int = 20,
        rrf_k: int = 60,
        enable_query_planning: bool = False,
        query_planner_mode: str = "hybrid",
        query_planner_task_type: str = "",
        document_profile: dict[str, object] | None = None,
        query_plan: QueryPlannerOutput | None = None,
        query_planner_env_file=None,
        query_planner_model_override: str | None = None,
        query_planner_llm_client=None,
        query_planner_env=None,
    ) -> None:
        self.mode = mode
        self.dense_encoder = dense_encoder
        self.enable_query_planning = enable_query_planning
        self.query_planner_mode = query_planner_mode
        self.query_planner_task_type = query_planner_task_type
        self.document_profile = document_profile or {}
        self.query_plan = query_plan
        self.query_planner_env_file = query_planner_env_file
        self.query_planner_model_override = query_planner_model_override
        self.query_planner_llm_client = query_planner_llm_client
        self.query_planner_env = query_planner_env
        self.hybrid = HybridRetriever(
            blocks,
            dense_index=dense_index,
            reranker=reranker,
            mode=mode,
            bm25_top_n=bm25_top_n,
            dense_top_n=dense_top_n,
            fusion_top_n=fusion_top_n,
            rrf_k=rrf_k,
        )

    def retrieve(
        self,
        *,
        doc_id: str | None,
        question: str,
        top_k: int,
        answer_type_hint: str | None = None,
    ) -> RetrievalResult:
        query_plan = self.query_plan
        if query_plan is None and self.enable_query_planning:
            query_plan = plan_queries(
                question=question,
                task_type=self.query_planner_task_type,
                document_profile=self.document_profile,
                mode=self.query_planner_mode,
                answer_type_hint=answer_type_hint,
                llm_client=self.query_planner_llm_client,
                env_file=self.query_planner_env_file,
                model_override=self.query_planner_model_override,
                env=self.query_planner_env,
            )
        query_embedding = None
        if self.mode in {"dense", "hybrid", "hybrid_rerank"}:
            if self.dense_encoder is None:
                raise RuntimeError(f"{self.mode} retrieval requires a dense encoder")
            query_texts = query_plan.final_queries if query_plan is not None else [question]
            query_embedding = self.dense_encoder.encode_queries(query_texts)
        return self.hybrid.retrieve_result(
            doc_id=doc_id,
            question=question,
            top_k=top_k,
            answer_type_hint=answer_type_hint,
            query_embedding=query_embedding,
            query_plan=query_plan,
        )

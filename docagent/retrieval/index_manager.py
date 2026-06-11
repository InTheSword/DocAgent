from __future__ import annotations

from docagent.retrieval.base import RetrievalResult
from docagent.retrieval.dense_encoder import DenseEncoder
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.hybrid_retriever import HybridRetriever
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
    ) -> None:
        self.mode = mode
        self.dense_encoder = dense_encoder
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
        query_embedding = None
        if self.mode in {"dense", "hybrid", "hybrid_rerank"}:
            if self.dense_encoder is None:
                raise RuntimeError(f"{self.mode} retrieval requires a dense encoder")
            query_embedding = self.dense_encoder.encode_queries([question])
        return self.hybrid.retrieve_result(
            doc_id=doc_id,
            question=question,
            top_k=top_k,
            answer_type_hint=answer_type_hint,
            query_embedding=query_embedding,
        )


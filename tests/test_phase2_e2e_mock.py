from __future__ import annotations

from docagent.models.base import HeuristicAnswerPolicy
from docagent.retrieval.dense_encoder import HashDenseEncoder
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.index_manager import IndexedDocumentRetriever
from docagent.retrieval.reranker import KeywordOverlapReranker
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.workflow.graph import run_qa_workflow


def test_phase2_mock_hybrid_retriever_runs_workflow() -> None:
    blocks = [
        EvidenceBlock(
            doc_id="doc",
            block_id="b1",
            block_type="text",
            text="Invoice Date: March 12, 2020",
            location=EvidenceLocation(page=1, block_id="b1"),
        ),
        EvidenceBlock(
            doc_id="doc",
            block_id="b2",
            block_type="text",
            text="Total Revenue: 1280",
            location=EvidenceLocation(page=2, block_id="b2"),
        ),
    ]
    encoder = HashDenseEncoder()
    dense_index = DenseIndex.build(blocks=blocks, embeddings=encoder.encode_documents([block.retrieval_text for block in blocks]), model_id=encoder.model_id)
    retriever = IndexedDocumentRetriever(
        blocks,
        mode="hybrid_rerank",
        dense_encoder=encoder,
        dense_index=dense_index,
        reranker=KeywordOverlapReranker(),
    )

    state = run_qa_workflow(
        qid="q1",
        doc_id="doc",
        question="What is the invoice date?",
        blocks=blocks,
        answer_policy=HeuristicAnswerPolicy(),
        retriever=retriever,
        top_k=1,
    )

    assert state.status == "completed"
    assert state.retrieved_blocks[0].block_id == "b1"
    assert state.trace[0]["retriever_mode"] == "hybrid_rerank"
    assert state.location_check["success"] is True

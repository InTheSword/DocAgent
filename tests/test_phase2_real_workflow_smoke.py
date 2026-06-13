from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from docagent.models.base import GenerationResult
from docagent.retrieval.base import RetrievalCandidate, RetrievalResult
from docagent.retrieval.dense_index import DenseIndex
from docagent.retrieval.hybrid_retriever import HybridRetriever
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import TraceRepository
from docagent.workflow.graph import run_qa_workflow
from scripts.smoke_phase2_real_workflow import (
    DENSE_BACKEND,
    RERANKER_BACKEND,
    build_success_payload,
    selected_doc_blocks,
    validate_no_mock_fallback,
    validate_run_artifacts,
)


class FakePolicy:
    mode = "grpo"

    def __init__(self, *, location: dict[str, Any] | None = None) -> None:
        self.location = location if location is not None else {"page": 1, "block_id": "smoke_invoice_p1_b1"}
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> GenerationResult:
        self.calls.append(kwargs)
        parsed = {
            "answer": "March 12, 2020",
            "evidence_location": self.location,
            "evidence": "Invoice Date: March 12, 2020",
            "reason": "The invoice date is stated in the retrieved evidence block.",
        }
        return GenerationResult(
            raw_text=json.dumps(parsed),
            parsed=parsed,
            prompt_text="prompt without gold",
            prompt_token_count=3,
            completion_token_count=12,
            finish_reason="stop",
            latency_ms=1.0,
            metadata={"parse_result": {"raw_json_ok": True, "schema_ok": True}},
        )


class FakeRetriever:
    def __init__(self, block: EvidenceBlock) -> None:
        self.block = block

    def retrieve(self, *, doc_id: str | None, question: str, top_k: int, answer_type_hint: str | None = None):
        assert doc_id == "smoke_invoice"
        candidate = RetrievalCandidate(
            block=self.block,
            bm25_score=2.0,
            dense_score=0.9,
            rrf_score=0.03,
            rerank_score=4.0,
            ranks={"bm25": 1, "dense": 1, "rrf": 1, "reranker": 1},
            sources=["bm25", "dense"],
        )
        return RetrievalResult(
            rewritten_query="invoice date",
            candidates=[candidate],
            metadata={
                "retriever_mode": "hybrid_rerank",
                "dense_backend": DENSE_BACKEND,
                "dense_model_id": "bge-m3-dense-1024",
                "reranker_backend": RERANKER_BACKEND,
                "no_mock_fallback": True,
            },
        )


def _block(block_id: str, *, doc_id: str = "smoke_invoice", text: str = "Invoice Date: March 12, 2020") -> EvidenceBlock:
    return EvidenceBlock(
        doc_id=doc_id,
        page_id=1,
        block_id=block_id,
        block_type="text",
        text=text,
        location=EvidenceLocation(page=1, block_id=block_id),
    )


def _args(tmp_path) -> SimpleNamespace:
    return SimpleNamespace(
        base_model_path="/root/autodl-tmp/models/Qwen3-1.7B",
        adapter_path="outputs/checkpoints/qwen3-docagent-trl-grpo-mpdocvqa-retrieved-grounded-100step-20260606_105535",
        qwen_device="cuda:0",
        gold_block_id="smoke_invoice_p1_b1",
    )


def test_hybrid_retriever_dense_path_respects_doc_id_filter() -> None:
    doc_block = _block("doc1_b1", doc_id="doc1", text="invoice date")
    other_block = _block("doc2_b1", doc_id="doc2", text="invoice date")
    blocks = [doc_block, other_block]
    embeddings = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    dense_index = DenseIndex(blocks=blocks, embeddings=embeddings, model_id="bge-m3-dense-1024", backend="numpy")
    retriever = HybridRetriever(blocks, dense_index=dense_index, mode="hybrid", dense_top_n=2)

    result = retriever.retrieve_result(
        doc_id="doc1",
        question="invoice date",
        top_k=2,
        mode="hybrid",
        query_embedding=np.asarray([[0.0, 1.0]], dtype=np.float32),
    )

    assert result.candidates
    assert all(candidate.block.doc_id == "doc1" for candidate in result.candidates)
    assert {candidate.block.block_id for candidate in result.candidates} == {"doc1_b1"}


def test_workflow_smoke_payload_persists_retrieval_and_answer_trace(tmp_path) -> None:
    block = _block("smoke_invoice_p1_b1")
    repo = TraceRepository(connect(tmp_path / "workflow.sqlite"))
    policy = FakePolicy()
    state = run_qa_workflow(
        qid="smoke_invoice_date",
        doc_id="smoke_invoice",
        question="What is the invoice date?",
        blocks=[block],
        answer_policy=policy,
        top_k=1,
        answer_type_hint="extractive",
        trace_repository=repo,
        retriever=FakeRetriever(block),
    )

    artifacts = validate_run_artifacts(
        state=state,
        trace_repository=repo,
        doc_id="smoke_invoice",
        gold_block_id="smoke_invoice_p1_b1",
    )
    payload = build_success_payload(
        args=_args(tmp_path),
        sample=SimpleNamespace(qid="smoke_invoice_date", doc_id="smoke_invoice"),
        state=state,
        artifacts=artifacts,
        sqlite_path=tmp_path / "workflow.sqlite",
    )

    assert policy.calls[0]["question"] == "What is the invoice date?"
    assert "gold" not in policy.calls[0]
    assert payload["status"] == "success"
    assert payload["retrieval"]["all_candidates_same_doc"] is True
    assert payload["retrieval"]["gold_block_in_top_k"] is True
    assert payload["validation"]["final_location_in_top_k"] is True
    assert payload["trace"]["persisted"] is True
    assert payload["trace"]["retrieval_trace_present"] is True
    assert payload["trace"]["answer_trace_present"] is True
    assert payload["no_gold_leakage"] is True
    assert payload["no_mock_fallback"] is True
    json.dumps(payload, ensure_ascii=False)


def test_workflow_repair_uses_top_k_without_gold(tmp_path) -> None:
    block = _block("smoke_invoice_p1_b1")
    repo = TraceRepository(connect(tmp_path / "workflow.sqlite"))
    policy = FakePolicy(location={"block_id": "outside_top_k"})
    state = run_qa_workflow(
        qid="smoke_invoice_date",
        doc_id="smoke_invoice",
        question="What is the invoice date?",
        blocks=[block],
        answer_policy=policy,
        top_k=1,
        answer_type_hint="extractive",
        trace_repository=repo,
        retriever=FakeRetriever(block),
    )

    assert state.repair_attempted is True
    assert state.final_answer["evidence_location"]["block_id"] == "smoke_invoice_p1_b1"
    assert "gold" not in policy.calls[0]


def test_selected_doc_blocks_and_no_mock_fallback_guards() -> None:
    sample = SimpleNamespace(evidence=[_block("b1"), _block("b2", doc_id="other")])

    assert [block.doc_id for block in selected_doc_blocks([sample], doc_id="smoke_invoice")] == ["smoke_invoice"]
    validate_no_mock_fallback(
        dense_backend=DENSE_BACKEND,
        reranker_backend=RERANKER_BACKEND,
        policy_mode="grpo",
    )
    with pytest.raises(RuntimeError, match="dense_backend"):
        validate_no_mock_fallback(dense_backend="hash", reranker_backend=RERANKER_BACKEND, policy_mode="grpo")
    with pytest.raises(RuntimeError, match="reranker_backend"):
        validate_no_mock_fallback(dense_backend=DENSE_BACKEND, reranker_backend="keyword", policy_mode="grpo")
    with pytest.raises(RuntimeError, match="GRPO"):
        validate_no_mock_fallback(dense_backend=DENSE_BACKEND, reranker_backend=RERANKER_BACKEND, policy_mode="heuristic")

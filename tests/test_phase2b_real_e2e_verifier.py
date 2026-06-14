from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from docagent.models.base import GenerationResult
from docagent.retrieval.base import RetrievalCandidate, RetrievalResult
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import TraceRepository
from scripts.verify_phase2b_real_e2e import (
    DOC_ID,
    CachedRetriever,
    ScenarioQA,
    aggregate_metrics,
    artifact_path,
    build_report,
    candidate_payload,
    failure_cases,
    run_answer_phase,
    validate_no_mock_fallback,
    validate_scenario_qa,
)


class FakePolicy:
    mode = "grpo"

    def __init__(
        self,
        *,
        answer: str = "103 050",
        location: dict[str, Any] | None = None,
        parsed: dict[str, Any] | None | object = ...,
        parse_result: dict[str, Any] | None = None,
    ) -> None:
        self.answer = answer
        self.location = location or {"page": 1, "block_id": f"{DOC_ID}_p001_b0012"}
        self.parsed = parsed
        self.parse_result = parse_result or {"raw_json_ok": True, "schema_ok": True}
        self.calls: list[dict[str, Any]] = []

    def generate(self, **kwargs: Any) -> GenerationResult:
        self.calls.append(kwargs)
        if self.parsed is ...:
            parsed = {
                "answer": self.answer,
                "evidence_location": self.location,
                "evidence": "Prostate 103 050",
                "reason": "The retrieved table contains the answer.",
            }
        else:
            parsed = self.parsed
        return GenerationResult(
            raw_text=json.dumps(parsed, ensure_ascii=False) if parsed is not None else "not json",
            parsed=parsed,
            prompt_text="prompt without gold",
            prompt_token_count=3,
            completion_token_count=8,
            finish_reason="stop",
            latency_ms=1.0,
            metadata={"parse_result": self.parse_result},
        )


class RaisingPolicy:
    mode = "grpo"

    def generate(self, **kwargs: Any) -> GenerationResult:
        raise RuntimeError("generation failed")


def _block(
    block_id: str,
    *,
    text: str = "Rank Cancer site Number of cases Percent 1st Prostate 103 050 20.4%",
    page: int = 1,
    block_type: str = "table",
    boilerplate: bool = False,
) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id=DOC_ID,
        page_id=page,
        block_id=block_id,
        block_type=block_type,
        text=text if block_type != "table" else "",
        table_html=text if block_type == "table" else None,
        location=EvidenceLocation(page=page, block_id=block_id, bbox=[0, 1, 2, 3]),
        metadata={
            "raw_mineru_type": "table" if block_type == "table" else "text",
            "is_boilerplate": boilerplate,
            "exclude_from_retrieval": boilerplate,
            "reading_order": 1,
        },
    )


def _qa(qid: str = "q1", block_id: str | None = None) -> ScenarioQA:
    return ScenarioQA(
        qid=qid,
        doc_id=DOC_ID,
        question="In the male top five cancers table, how many prostate cases were reported?",
        answers=["103 050"],
        answer_type="table_lookup",
        gold_pages=[1],
        gold_block_ids=[block_id or f"{DOC_ID}_p001_b0012"],
        evidence_note="Prostate row has 103 050 cases.",
        verified=True,
    )


def _retrieval_result(block: EvidenceBlock, *, include_gold: bool = True) -> RetrievalResult:
    candidate_block = block if include_gold else _block(f"{DOC_ID}_p001_b9999", text="Other 1")
    candidate = RetrievalCandidate(
        block=candidate_block,
        bm25_score=2.0,
        dense_score=0.8,
        rrf_score=0.03,
        rerank_score=4.0,
        ranks={"bm25": 1, "dense": 2, "rrf": 1, "reranker": 1},
        sources=["bm25", "dense"],
    )
    return RetrievalResult(
        rewritten_query="male top five cancers prostate cases",
        candidates=[candidate],
        metadata={
            "retriever_mode": "hybrid_rerank",
            "dense_backend": "bge_m3",
            "dense_model_id": "bge-m3-dense-1024",
            "index_backend": "faiss",
            "sparse_backend": "bm25",
            "fusion": "rrf",
            "reranker_backend": "transformers_sequence_classification",
            "rewrite_backend": "deterministic_keyword_v1",
            "no_mock_fallback": True,
        },
    )


def test_scenario_qa_validator_accepts_real_contract_and_rejects_bad_records() -> None:
    block = _block(f"{DOC_ID}_p001_b0012")
    summary = validate_scenario_qa([_qa()], {block.block_id: block})

    assert summary["sample_count"] == 1
    assert summary["answer_type_counts"] == {"table_lookup": 1}

    with pytest.raises(RuntimeError, match="duplicate qid"):
        validate_scenario_qa([_qa("dup"), _qa("dup")], {block.block_id: block})
    with pytest.raises(RuntimeError, match="empty answer"):
        validate_scenario_qa([_qa().__class__(**{**_qa().to_dict(), "answers": [""]})], {block.block_id: block})
    with pytest.raises(RuntimeError, match="gold block id"):
        bad = _qa().__class__(**{**_qa().to_dict(), "question": f"Use {block.block_id} to answer."})
        validate_scenario_qa([bad], {block.block_id: block})


def test_candidate_payload_keeps_scores_ranks_and_structure_metadata() -> None:
    block = _block(f"{DOC_ID}_p001_b0012")
    candidate = _retrieval_result(block).candidates[0]
    payload = candidate_payload(candidate, final_rank=1)

    assert payload["block_id"] == block.block_id
    assert payload["page"] == 1
    assert payload["block_type"] == "table"
    assert payload["bm25_rank"] == 1
    assert payload["dense_rank"] == 2
    assert payload["rrf_rank"] == 1
    assert payload["reranker_rank"] == 1
    assert payload["raw_mineru_type"] == "table"
    assert payload["is_boilerplate"] is False
    assert payload["dense_backend"] == "bge_m3"
    assert payload["index_backend"] == "faiss"
    assert payload["reranker_backend"] == "transformers_sequence_classification"


def test_cached_retrieval_workflow_persists_trace_and_report(tmp_path: Path) -> None:
    block = _block(f"{DOC_ID}_p001_b0012")
    sample = _qa()
    conn = connect(tmp_path / "docagent.sqlite")
    repo = TraceRepository(conn)
    rows = run_answer_phase(
        samples=[sample],
        blocks=[block],
        retrieval_cache={f"{DOC_ID}\0{sample.question}": _retrieval_result(block)},
        policy=FakePolicy(),
        trace_repository=repo,
        top_k=1,
    )
    conn.close()
    retrieval_metrics, answer_metrics, location_metrics = aggregate_metrics(rows, top_k=1)

    assert rows[0]["status"] == "completed"
    assert rows[0]["trace"]["retrieval_trace_present"] is True
    assert rows[0]["trace"]["generation_trace_present"] is True
    assert rows[0]["failure_taxonomy"] == []
    assert retrieval_metrics["recall_at_1"] == 1.0
    assert answer_metrics["normalized_exact_match"] == 1.0
    assert location_metrics["block_location_hit"] == 1.0

    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.4\n/Type /Page\n")
    document_dir = tmp_path / "documents" / DOC_ID
    document_dir.mkdir(parents=True)
    report = build_report(
        args=SimpleNamespace(source_pdf=str(source), top_k=1),
        work_dir=tmp_path,
        document_dir=document_dir,
        sqlite_path=tmp_path / "docagent.sqlite",
        ingestion={
            "quality": {
                "raw_block_count": 1,
                "converted_block_count": 1,
                "content_list_page_count": 1,
                "boilerplate_count": 0,
                "missing_image_reference_count": 0,
            }
        },
        qa_validation={"sample_count": 1, "answer_type_counts": {"table_lookup": 1}},
        model_metadata={"index_backend": "faiss"},
        rows=rows,
        absolute_hits=[],
    )

    assert report["status"] == "success"
    assert report["result_type"] == "real-document scenario acceptance"
    assert report["trace"]["sqlite_persisted"] is True
    assert not Path(report["artifact_paths"]["sqlite"]).is_absolute()
    json.dumps(report, ensure_ascii=False)


def test_failure_taxonomy_separates_retrieval_answer_location_and_json(tmp_path: Path) -> None:
    block = _block(f"{DOC_ID}_p001_b0012")
    sample = _qa()
    conn = connect(tmp_path / "docagent.sqlite")
    repo = TraceRepository(conn)
    rows = run_answer_phase(
        samples=[sample],
        blocks=[block],
        retrieval_cache={f"{DOC_ID}\0{sample.question}": _retrieval_result(block, include_gold=False)},
        policy=FakePolicy(
            answer="wrong",
            location={"page": 2, "block_id": "outside_top_k"},
            parsed=None,
            parse_result={"raw_json_ok": False, "schema_ok": False},
        ),
        trace_repository=repo,
        top_k=1,
    )
    conn.close()
    cases = failure_cases(rows)

    assert rows[0]["status"] == "completed"
    assert "retrieval_miss" in rows[0]["failure_taxonomy"]
    assert "answer_miss" in rows[0]["failure_taxonomy"]
    assert "location_miss" in rows[0]["failure_taxonomy"]
    assert "json_invalid" in rows[0]["failure_taxonomy"]
    assert cases and cases[0]["qid"] == sample.qid


def test_workflow_exception_is_captured_as_failure_case(tmp_path: Path) -> None:
    block = _block(f"{DOC_ID}_p001_b0012")
    sample = _qa()
    conn = connect(tmp_path / "docagent.sqlite")
    repo = TraceRepository(conn)
    rows = run_answer_phase(
        samples=[sample],
        blocks=[block],
        retrieval_cache={f"{DOC_ID}\0{sample.question}": _retrieval_result(block)},
        policy=RaisingPolicy(),
        trace_repository=repo,
        top_k=1,
    )
    conn.close()

    assert rows[0]["status"] == "failed"
    assert rows[0]["failure_taxonomy"] == ["workflow_error"]
    assert failure_cases(rows)[0]["error"].startswith("RuntimeError")


def test_no_mock_fallback_guard_rejects_fake_backends() -> None:
    validate_no_mock_fallback(
        dense_backend="bge_m3",
        reranker_backend="transformers_sequence_classification",
        answer_policy="grpo",
        dense_model_id="bge-m3-dense-1024",
    )
    with pytest.raises(RuntimeError, match="dense_backend"):
        validate_no_mock_fallback(
            dense_backend="hash",
            reranker_backend="transformers_sequence_classification",
            answer_policy="grpo",
            dense_model_id="bge-m3-dense-1024",
        )
    with pytest.raises(RuntimeError, match="reranker_backend"):
        validate_no_mock_fallback(
            dense_backend="bge_m3",
            reranker_backend="keyword",
            answer_policy="grpo",
            dense_model_id="bge-m3-dense-1024",
        )
    with pytest.raises(RuntimeError, match="answer_policy"):
        validate_no_mock_fallback(
            dense_backend="bge_m3",
            reranker_backend="transformers_sequence_classification",
            answer_policy="heuristic",
            dense_model_id="bge-m3-dense-1024",
        )


def test_cli_returns_nonzero_on_infrastructure_failure(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/verify_phase2b_real_e2e.py",
            "--source-pdf",
            str(tmp_path / "missing.pdf"),
            "--mineru-output",
            str(tmp_path / "missing_mineru"),
            "--qa-path",
            str(tmp_path / "missing.jsonl"),
            "--work-dir",
            str(tmp_path / "work"),
        ],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)

    assert result.returncode == 1
    assert payload["status"] == "failed"
    assert "FileNotFoundError" in payload["exception"]

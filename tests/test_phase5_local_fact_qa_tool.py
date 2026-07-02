from __future__ import annotations

import json
from pathlib import Path

from docagent.ingestion.document_registry import DocumentRecord
from docagent.schemas import EvidenceBlock, EvidenceLocation, QAState
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository, TraceRepository
from docagent.tools.local_fact_qa import local_fact_qa


def _repository_with_document(tmp_path: Path) -> DocumentRepository:
    conn = connect(tmp_path / "docagent.sqlite")
    repository = DocumentRepository(conn)
    repository.upsert_document(
        DocumentRecord(
            doc_id="doc1",
            sha256="a" * 64,
            original_name="invoice.pdf",
            mime_type="application/pdf",
            file_size=123,
            file_path=str(tmp_path / "documents" / "doc1" / "source" / "original.pdf"),
            document_dir=str(tmp_path / "documents" / "doc1"),
            page_count=1,
            parser_backend="mineru_existing",
            parse_status="parsed",
            index_status="not_started",
        )
    )
    repository.save_evidence_blocks(
        [
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_text",
                block_type="text",
                text="Invoice Date: March 12, 2020",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_text"),
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_total",
                block_type="text",
                text="Total: 42 USD",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_total"),
            ),
        ]
    )
    return repository


def _fake_workflow(**kwargs) -> QAState:
    state = QAState(
        qid=kwargs["qid"],
        question=kwargs["question"],
        doc_id=kwargs["doc_id"],
        answer_type=kwargs.get("answer_type_hint"),
    )
    state.run_id = "fake-run"
    state.status = "completed"
    state.rewritten_query = kwargs["question"]
    state.retrieved_blocks = kwargs["blocks"][: kwargs["top_k"]]
    state.final_answer = {
        "answer": "March 12, 2020",
        "evidence_location": {"page": 1, "block_id": "doc1_p001_text"},
        "evidence": "Invoice Date: March 12, 2020",
        "reason": "fake workflow for wrapper test",
    }
    return state


def _fake_candidate_workflow(**kwargs) -> QAState:
    state = _fake_workflow(**kwargs)
    state.final_answer = {
        "answer": "March 12, 2020",
        "evidence_location": {"page": 1, "block_id": "doc1_p001_text"},
        "evidence": "Invoice Date: March 12, 2020",
        "reason": "The selected block contains the invoice date.",
        "reasoning_summary": "The selected block contains the invoice date.",
        "citation_block_ids": ["doc1_p001_text"],
        "citations": [
            {
                "doc_id": "doc1",
                "page": 1,
                "block_id": "doc1_p001_text",
                "block_type": "text",
                "text_preview": "Invoice Date: March 12, 2020",
            }
        ],
        "evidence_used": [
            {
                "doc_id": "doc1",
                "page": 1,
                "block_id": "doc1_p001_text",
                "block_type": "text",
                "text_preview": "Invoice Date: March 12, 2020",
            }
        ],
        "citation_validation": {
            "requested_block_ids": ["doc1_p001_text", "missing"],
            "valid_block_ids": ["doc1_p001_text"],
            "invalid_block_ids": ["missing"],
        },
    }
    return state


def test_local_fact_qa_fake_workflow_success_is_json_serializable(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = local_fact_qa(
        {"doc_id": "doc1", "question": "What is the invoice date?"},
        document_repository=repository,
        workflow_runner=_fake_workflow,
    )

    assert result["status"] == "success"
    assert result["tool_name"] == "local_fact_qa"
    assert result["answer"] == "March 12, 2020"
    assert result["tools_used"] == ["local_fact_qa"]
    assert result["trace_path"] == ""
    assert result["run_id"] == "fake-run"
    assert isinstance(result["citations"], list)
    assert isinstance(result["supporting_evidence_ids"], list)
    assert result["citations"][0]["page"] == 1
    assert result["citations"][0]["block_id"] == "doc1_p001_text"
    assert result["supporting_evidence_ids"] == ["doc1_p001_text", "doc1_p001_total"]
    json.dumps(result)


def test_local_fact_qa_exposes_candidate_schema_citations(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = local_fact_qa(
        {"doc_id": "doc1", "question": "What is the invoice date?"},
        document_repository=repository,
        workflow_runner=_fake_candidate_workflow,
    )

    assert result["status"] == "success"
    assert result["reasoning_summary"] == "The selected block contains the invoice date."
    assert [item["block_id"] for item in result["citations"]] == ["doc1_p001_text"]
    assert [item["block_id"] for item in result["evidence_used"]] == ["doc1_p001_text"]
    assert result["citation_validation"]["invalid_block_ids"] == ["missing"]


def test_missing_doc_id_returns_structured_error(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = local_fact_qa(
        {"doc_id": "missing", "question": "What is the invoice date?"},
        document_repository=repository,
    )

    assert result["status"] == "error"
    assert result["error"]["type"] == "document_not_found"
    assert result["answer"] == ""
    assert result["citations"] == []
    assert result["supporting_evidence_ids"] == []
    assert result["tools_used"] == ["local_fact_qa"]
    json.dumps(result)


def test_empty_question_returns_structured_error(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = local_fact_qa({"doc_id": "doc1", "question": "   "}, document_repository=repository)

    assert result["status"] == "error"
    assert result["error"]["type"] == "invalid_question"
    assert result["workflow_status"] == "not_started"


def test_dry_run_success_path_does_not_generate_answer(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = local_fact_qa(
        {"doc_id": "doc1", "question": "What is the invoice date?", "options": {"dry_run": True, "top_k": 1}},
        document_repository=repository,
    )

    assert result["status"] == "success"
    assert result["answer"] == ""
    assert result["workflow_status"] == "dry_run"
    assert result["supporting_evidence_ids"] == ["doc1_p001_text"]
    assert "dry_run_no_answer_generated" in result["warnings"]


def test_router_plan_query_rewrite_is_used_by_workflow(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)
    captured = {}

    def fake_workflow(**kwargs) -> QAState:
        captured["question"] = kwargs["question"]
        return _fake_workflow(**kwargs)

    result = local_fact_qa(
        {
            "doc_id": "doc1",
            "question": "Can you tell me the invoice date in this PDF?",
            "router_plan": {
                "task_type": "local_fact_qa",
                "selected_tools": ["local_fact_qa"],
                "target_evidence_types": ["text"],
                "query_rewrite": "invoice date",
            },
        },
        document_repository=repository,
        workflow_runner=fake_workflow,
    )

    assert captured["question"] == "invoice date"
    assert result["query_used"] == "invoice date"
    assert result["router_plan_summary"]["query_rewrite"] == "invoice date"


def test_default_workflow_reuses_heuristic_answer_policy(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)
    trace_repository = TraceRepository(repository.conn)

    result = local_fact_qa(
        {"doc_id": "doc1", "question": "What is the invoice date?"},
        document_repository=repository,
        trace_repository=trace_repository,
    )

    assert result["status"] == "success"
    assert result["answer"] == "March 12, 2020"
    assert result["run_id"]
    assert result["trace_path"] == ""
    assert result["supporting_evidence_ids"][0] == "doc1_p001_text"
    assert trace_repository.get_run(result["run_id"])["status"] == "completed"
    assert trace_repository.list_traces(result["run_id"])


def test_trace_path_field_uses_explicit_option_only(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = local_fact_qa(
        {
            "doc_id": "doc1",
            "question": "What is the invoice date?",
            "options": {"dry_run": True, "trace_path": "outputs/traces/local.sqlite"},
        },
        document_repository=repository,
    )

    assert result["trace_path"] == "outputs/traces/local.sqlite"


def test_no_evidence_blocks_returns_structured_error(tmp_path: Path) -> None:
    conn = connect(tmp_path / "docagent.sqlite")
    repository = DocumentRepository(conn)
    repository.upsert_document(
        DocumentRecord(
            doc_id="doc-empty",
            sha256="b" * 64,
            original_name="empty.pdf",
            mime_type="application/pdf",
            file_size=1,
            file_path=str(tmp_path / "empty.pdf"),
            document_dir=str(tmp_path / "documents" / "doc-empty"),
            page_count=0,
            parser_backend="mineru_existing",
            parse_status="parsed",
            index_status="not_started",
        )
    )

    result = local_fact_qa(
        {"doc_id": "doc-empty", "question": "What is the invoice date?"},
        document_repository=repository,
    )

    assert result["status"] == "error"
    assert result["error"]["type"] == "no_evidence_blocks"


def test_workflow_failure_reports_exception_type_even_without_message(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    class EmptyWorkflowError(Exception):
        pass

    def failing_workflow(**_kwargs):
        raise EmptyWorkflowError()

    result = local_fact_qa(
        {"doc_id": "doc1", "question": "What is the invoice date?"},
        document_repository=repository,
        workflow_runner=failing_workflow,
    )

    assert result["status"] == "error"
    assert result["error"]["type"] == "workflow_failed"
    assert result["error"]["message"] == "EmptyWorkflowError"
    assert result["error"]["cause_type"] == "EmptyWorkflowError"


def test_wrapper_does_not_call_external_api_or_vlm_in_dry_run(tmp_path: Path) -> None:
    repository = _repository_with_document(tmp_path)

    result = local_fact_qa(
        {"doc_id": "doc1", "question": "What is the invoice date?", "options": {"dry_run": True}},
        document_repository=repository,
    )

    assert result["status"] == "success"
    assert "dry_run_no_answer_generated" in result["warnings"]
    assert result["final_answer"] == {}

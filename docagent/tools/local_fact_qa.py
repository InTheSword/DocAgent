from __future__ import annotations

from typing import Any, Callable

from docagent.models.base import AnswerPolicy, HeuristicAnswerPolicy
from docagent.retrieval.base import Retriever
from docagent.schemas import EvidenceBlock, QAState
from docagent.storage.repositories import DocumentRepository, TraceRepository
from docagent.workflow.graph import run_qa_workflow
from docagent.workflow.answer_contract import citation_from_block, evidence_used_from_blocks


WorkflowRunner = Callable[..., QAState]

DEFAULT_TOP_K = 5


def local_fact_qa(
    payload: dict[str, Any],
    *,
    document_repository: DocumentRepository,
    trace_repository: TraceRepository | None = None,
    answer_policy: AnswerPolicy | None = None,
    retriever: Retriever | None = None,
    workflow_runner: WorkflowRunner = run_qa_workflow,
) -> dict[str, Any]:
    doc_id = str(payload.get("doc_id") or "").strip()
    question = str(payload.get("question") or "").strip()
    router_plan = payload.get("router_plan") if isinstance(payload.get("router_plan"), dict) else {}
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}

    if not question:
        return _error(doc_id, question, "invalid_question", "Question is required.")
    if not doc_id or document_repository.get_document(doc_id) is None:
        return _error(doc_id, question, "document_not_found", f"Document not found: {doc_id}")

    blocks = document_repository.load_evidence_blocks(doc_id)
    if not blocks:
        return _error(doc_id, question, "no_evidence_blocks", f"No evidence blocks found for document: {doc_id}")

    top_k = _positive_int(options.get("top_k"), DEFAULT_TOP_K)
    query = _planned_query(question, router_plan)
    trace_path = str(options.get("trace_path") or "")
    warnings = _initial_warnings(router_plan, options)

    if bool(options.get("dry_run", False)):
        preview_blocks = blocks[:top_k]
        return _success(
            doc_id=doc_id,
            question=question,
            answer="",
            blocks=preview_blocks,
            trace_path=trace_path,
            run_id="",
            query_used=query,
            router_plan=router_plan,
            warnings=[*warnings, "dry_run_no_answer_generated"],
            workflow_status="dry_run",
            final_answer={},
            workflow_trace=[],
        )

    policy = answer_policy or HeuristicAnswerPolicy()
    try:
        state = workflow_runner(
            qid=str(options.get("qid") or f"local_fact_qa_{doc_id}"),
            doc_id=doc_id,
            question=query,
            blocks=blocks,
            answer_policy=policy,
            top_k=top_k,
            answer_type_hint=str(options.get("answer_type_hint") or "extractive"),
            trace_repository=trace_repository,
            retriever=retriever,
            preserve_input_order=bool(options.get("preserve_input_order", False)),
            rank_aware_context=bool(options.get("rank_aware_context", False)),
        )
    except Exception as exc:
        return _error(
            doc_id,
            question,
            "workflow_failed",
            str(exc),
            trace_path=trace_path,
            warnings=warnings,
        )

    return _success(
        doc_id=doc_id,
        question=question,
        answer=str(state.final_answer.get("answer") or ""),
        blocks=state.retrieved_blocks,
        trace_path=trace_path,
        run_id=state.run_id or "",
        query_used=query,
        router_plan=router_plan,
        warnings=warnings,
        workflow_status=state.status,
        final_answer=state.final_answer,
        workflow_trace=state.trace,
    )


def _success(
    *,
    doc_id: str,
    question: str,
    answer: str,
    blocks: list[EvidenceBlock],
    trace_path: str,
    run_id: str,
    query_used: str,
    router_plan: dict[str, Any],
    warnings: list[str],
    workflow_status: str,
    final_answer: dict[str, Any],
    workflow_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    citations = _final_answer_citations(final_answer, blocks)
    evidence_used = _final_answer_evidence_used(final_answer, citations)
    reasoning_summary = str(final_answer.get("reasoning_summary") or final_answer.get("reason") or "")
    return {
        "tool_name": "local_fact_qa",
        "status": "success",
        "doc_id": doc_id,
        "question": question,
        "answer": answer,
        "reasoning_summary": reasoning_summary,
        "evidence_used": evidence_used,
        "citations": citations,
        "supporting_evidence_ids": [block.block_id for block in blocks],
        "tools_used": ["local_fact_qa"],
        "trace_path": trace_path,
        "warnings": list(dict.fromkeys(warnings)),
        "run_id": run_id,
        "query_used": query_used,
        "router_plan_summary": _router_plan_summary(router_plan),
        "workflow_status": workflow_status,
        "final_answer": final_answer,
        "citation_validation": final_answer.get("citation_validation") or {},
        "workflow_trace": workflow_trace or [],
    }


def _error(
    doc_id: str,
    question: str,
    error_type: str,
    message: str,
    *,
    trace_path: str = "",
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "tool_name": "local_fact_qa",
        "status": "error",
        "doc_id": doc_id,
        "question": question,
        "answer": "",
        "reasoning_summary": "",
        "evidence_used": [],
        "citations": [],
        "supporting_evidence_ids": [],
        "tools_used": ["local_fact_qa"],
        "trace_path": trace_path,
        "warnings": list(dict.fromkeys(warnings or [])),
        "run_id": "",
        "query_used": "",
        "router_plan_summary": {},
        "workflow_status": "not_started",
        "final_answer": {},
        "error": {"type": error_type, "message": message},
    }


def _planned_query(question: str, router_plan: dict[str, Any]) -> str:
    rewrite = str(router_plan.get("query_rewrite") or "").strip()
    return rewrite or question


def _router_plan_summary(router_plan: dict[str, Any]) -> dict[str, Any]:
    if not router_plan:
        return {}
    return {
        key: router_plan[key]
        for key in ["task_type", "selected_tools", "target_evidence_types", "query_rewrite"]
        if key in router_plan
    }


def _initial_warnings(router_plan: dict[str, Any], options: dict[str, Any]) -> list[str]:
    warnings = []
    if router_plan and router_plan.get("task_type") not in {None, "local_fact_qa", "table_lookup_or_calculation"}:
        warnings.append("router_plan_task_type_not_local_fact_qa")
    if options.get("evidence_packing"):
        warnings.append("evidence_packing_option_deferred_to_workflow")
    return warnings


def _final_answer_citations(final_answer: dict[str, Any], blocks: list[EvidenceBlock]) -> list[dict[str, Any]]:
    raw_citations = final_answer.get("citations")
    if isinstance(raw_citations, list) and raw_citations:
        return [dict(item) for item in raw_citations if isinstance(item, dict)]
    block_by_id = {block.block_id: block for block in blocks}
    citation_ids = final_answer.get("citation_block_ids")
    if isinstance(citation_ids, list) and citation_ids:
        return [citation_from_block(block_by_id[block_id]) for block_id in citation_ids if block_id in block_by_id]
    location = final_answer.get("evidence_location") if isinstance(final_answer, dict) else {}
    block_id = str((location or {}).get("block_id") or "")
    if block_id in block_by_id:
        return [citation_from_block(block_by_id[block_id])]
    return [citation_from_block(block) for block in blocks]


def _final_answer_evidence_used(final_answer: dict[str, Any], citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence_used = final_answer.get("evidence_used")
    if isinstance(evidence_used, list):
        return [dict(item) for item in evidence_used if isinstance(item, dict)]
    if isinstance(evidence_used, str) and evidence_used.strip():
        return [{"text_preview": evidence_used}]
    citation_blocks = [
        EvidenceBlock(
            doc_id=str(citation.get("doc_id") or ""),
            block_id=str(citation.get("block_id") or ""),
            block_type=str(citation.get("block_type") or "text"),
            text=str(citation.get("text_preview") or ""),
            page_id=citation.get("page"),
        )
        for citation in citations
        if citation.get("block_id")
    ]
    if citation_blocks:
        return evidence_used_from_blocks(citation_blocks)
    return []


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default

from __future__ import annotations

from typing import Any, Callable

from docagent.models.base import AnswerPolicy, HeuristicAnswerPolicy
from docagent.retrieval.base import Retriever
from docagent.schemas import EvidenceBlock, QAState
from docagent.storage.repositories import DocumentRepository, TraceRepository
from docagent.workflow.graph import run_qa_workflow


WorkflowRunner = Callable[..., QAState]

DEFAULT_TOP_K = 5
DEFAULT_TEXT_PREVIEW_CHARS = 180


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
) -> dict[str, Any]:
    return {
        "tool_name": "local_fact_qa",
        "status": "success",
        "doc_id": doc_id,
        "question": question,
        "answer": answer,
        "citations": [_citation(block) for block in blocks],
        "supporting_evidence_ids": [block.block_id for block in blocks],
        "tools_used": ["local_fact_qa"],
        "trace_path": trace_path,
        "warnings": list(dict.fromkeys(warnings)),
        "run_id": run_id,
        "query_used": query_used,
        "router_plan_summary": _router_plan_summary(router_plan),
        "workflow_status": workflow_status,
        "final_answer": final_answer,
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


def _citation(block: EvidenceBlock) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "page": block.location.page if block.location.page is not None else block.page_id,
            "block_id": block.block_id,
            "text_preview": _text_preview(block.retrieval_text),
        }.items()
        if value not in {None, ""}
    }


def _text_preview(text: str, limit: int = DEFAULT_TEXT_PREVIEW_CHARS) -> str:
    normalized = " ".join((text or "").split())
    return normalized[:limit]


def _positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default

from __future__ import annotations

from typing import Any

from docagent.models.base import AnswerPolicy
from docagent.retrieval.base import Retriever
from docagent.retrieval.hybrid_retriever import HybridRetriever
from docagent.retrieval.query_rewrite import rewrite_query
from docagent.schemas import EvidenceBlock, QAState
from docagent.storage.repositories import TraceRepository
from docagent.tools.answer_repair import repair_answer
from docagent.tools.format_check import check_answer_format
from docagent.tools.location_check import check_location
from docagent.tools.visual_review import visual_review
from docagent.workflow.output_adapter import canonicalize_output
from docagent.workflow.prompts import build_evidence_context


def _trace(
    state: QAState,
    repository: TraceRepository | None,
    node_name: str,
    *,
    input_summary: dict[str, Any] | None = None,
    output_summary: dict[str, Any] | None = None,
    success: bool = True,
    latency_ms: float | None = None,
    error: str | None = None,
) -> None:
    payload = {
        "step": node_name,
        "node": node_name,
        "success": success,
        **(output_summary or {}),
    }
    if latency_ms is not None:
        payload["latency_ms"] = latency_ms
    if error:
        payload["error"] = error
    state.trace.append(payload)
    if repository is not None and state.run_id:
        repository.append_trace(
            run_id=state.run_id,
            step_index=len(state.trace) - 1,
            node_name=node_name,
            input_summary=input_summary,
            output_summary=output_summary,
            success=success,
            latency_ms=latency_ms,
            error=error,
        )


def _citation_ids_from_tool_results(tool_results: list[dict[str, Any]]) -> list[str]:
    ids: list[str] = []
    for result in tool_results:
        if not isinstance(result, dict):
            continue
        for key in ("citations", "evidence_used"):
            values = result.get(key)
            if not isinstance(values, list):
                continue
            for item in values:
                if isinstance(item, dict) and str(item.get("block_id") or "").strip():
                    ids.append(str(item["block_id"]))
    return list(dict.fromkeys(ids))


def _citation_allowlist_blocks(
    retrieved_blocks: list[EvidenceBlock],
    all_blocks: list[EvidenceBlock],
    preferred_block_ids: list[str],
) -> list[EvidenceBlock]:
    merged: list[EvidenceBlock] = []
    seen: set[str] = set()
    for block in retrieved_blocks:
        if block.block_id in seen:
            continue
        seen.add(block.block_id)
        merged.append(block)
    by_id = {block.block_id: block for block in all_blocks}
    for block_id in preferred_block_ids:
        block = by_id.get(block_id)
        if block is None or block.block_id in seen:
            continue
        seen.add(block.block_id)
        merged.append(block)
    return merged


def run_qa_workflow(
    qid: str,
    question: str,
    blocks: list[EvidenceBlock],
    *,
    answer_policy: AnswerPolicy | None = None,
    top_k: int = 5,
    answer_type_hint: str | None = None,
    doc_id: str | None = None,
    trace_repository: TraceRepository | None = None,
    run_id: str | None = None,
    preserve_input_order: bool = False,
    retriever: Retriever | None = None,
    rank_aware_context: bool = False,
    tool_results: list[dict[str, Any]] | None = None,
) -> QAState:
    if answer_policy is None:
        raise ValueError("answer_policy is required; pass HeuristicAnswerPolicy explicitly for tests or smoke runs")
    policy_mode = getattr(answer_policy, "mode", "unknown")
    state = QAState(qid=qid, question=question, doc_id=doc_id, answer_type=answer_type_hint)
    state.table_results = list(tool_results or [])
    if trace_repository is not None:
        state.run_id = trace_repository.create_run(
            run_id=run_id,
            qid=qid,
            doc_id=doc_id,
            question=question,
            policy_mode=policy_mode,
        )
    state.status = "running"
    if preserve_input_order:
        rewrite = rewrite_query(question, answer_type_hint=answer_type_hint)
        state.rewritten_query = rewrite.rewritten_query
        state.retrieved_blocks = list(blocks[:top_k])
        retrieval_metadata: dict[str, Any] = {"retriever_mode": "input_order"}
        retrieval_candidates: list[dict[str, object]] = []
    elif retriever is not None:
        retrieval_result = retriever.retrieve(
            doc_id=doc_id,
            question=question,
            top_k=top_k,
            answer_type_hint=answer_type_hint,
        )
        state.rewritten_query = retrieval_result.rewritten_query
        state.retrieved_blocks = [candidate.block for candidate in retrieval_result.candidates]
        retrieval_metadata = dict(retrieval_result.metadata)
        retrieval_candidates = [
            candidate.to_trace_dict(final_rank=rank)
            for rank, candidate in enumerate(retrieval_result.candidates, start=1)
        ]
    else:
        legacy_retriever = HybridRetriever(blocks)
        rewritten_query, hits = legacy_retriever.retrieve(question, top_k=top_k, answer_type_hint=answer_type_hint)
        state.rewritten_query = rewritten_query
        state.retrieved_blocks = [block for block, _score in hits]
        retrieval_metadata = {"retriever_mode": "legacy_bm25"}
        retrieval_candidates = [
            {"block_id": block.block_id, "page": block.page_id, "score": score, "final_rank": rank}
            for rank, (block, score) in enumerate(hits, start=1)
        ]
    _trace(
        state,
        trace_repository,
        "retrieve_evidence",
        input_summary={"question": question, "top_k": top_k, "answer_type": answer_type_hint},
        output_summary={
            "query": state.rewritten_query,
            "num_hits": len(state.retrieved_blocks),
            "preserve_input_order": preserve_input_order,
            "block_ids": [block.block_id for block in state.retrieved_blocks],
            "candidates": retrieval_candidates,
            **retrieval_metadata,
        },
    )

    for block in state.retrieved_blocks:
        if block.block_type in {"image", "figure"}:
            result = visual_review(block, question)
            state.visual_results.append(result)
            _trace(
                state,
                trace_repository,
                "visual_review",
                input_summary={"block_id": block.block_id},
                output_summary={"block_id": block.block_id, "result": result},
            )

    all_tool_results = [*state.table_results, *state.visual_results]
    preferred_citation_block_ids = _citation_ids_from_tool_results(all_tool_results)
    citation_allowlist_blocks = _citation_allowlist_blocks(
        state.retrieved_blocks,
        blocks,
        preferred_citation_block_ids,
    )
    evidence_context = build_evidence_context(
        question=question,
        task_type=answer_type_hint or "local_fact_qa",
        evidence_blocks=state.retrieved_blocks,
        rank_aware_context=rank_aware_context,
    )
    _trace(
        state,
        trace_repository,
        "build_evidence_context",
        input_summary={
            "question": question,
            "answer_type": answer_type_hint,
            "block_ids": [block.block_id for block in state.retrieved_blocks],
        },
        output_summary={
            "task_type": evidence_context["task_type"],
            "selected_block_ids": evidence_context["selected_block_ids"],
            "dropped_block_ids": evidence_context["dropped_block_ids"],
            "preferred_citation_block_ids": preferred_citation_block_ids,
            "citation_allowlist_block_ids": [block.block_id for block in citation_allowlist_blocks],
            "evidence_context_hash": evidence_context["evidence_context_hash"],
            "truncation_applied": evidence_context["truncation_applied"],
            "tool_result_count": len(state.table_results),
        },
    )

    try:
        generation = answer_policy.generate(
            question=question,
            evidence_blocks=state.retrieved_blocks,
            tool_results=all_tool_results,
            answer_type=answer_type_hint,
            qid=qid,
        )
        raw_draft = generation.parsed or {}
        state.parse_result = dict(generation.metadata.get("parse_result") or {})
        raw_evidence_ref_map = generation.metadata.get("evidence_ref_map")
        evidence_ref_map = raw_evidence_ref_map if isinstance(raw_evidence_ref_map, dict) else None
        canonical_draft = (
            canonicalize_output(
                raw_draft,
                citation_allowlist_blocks,
                preferred_citation_block_ids=preferred_citation_block_ids,
                evidence_ref_map=evidence_ref_map,
            )
            if raw_draft
            else {}
        )
        state.draft_answer = canonical_draft
        prompt_version = generation.metadata.get("prompt_version")
        selected_block_ids = generation.metadata.get("selected_block_ids") or evidence_context["selected_block_ids"]
        dropped_block_ids = generation.metadata.get("dropped_block_ids") or evidence_context["dropped_block_ids"]
        evidence_context_hash = generation.metadata.get("evidence_context_hash") or evidence_context["evidence_context_hash"]
        truncation_applied = bool(generation.metadata.get("truncation_applied") or evidence_context["truncation_applied"])
        state.generation_metadata = {
            key: value
            for key, value in {
                "policy_mode": policy_mode,
                "prompt_version": prompt_version,
                "task_type": generation.metadata.get("task_type") or answer_type_hint or "local_fact_qa",
                "selected_block_ids": selected_block_ids,
                "dropped_block_ids": dropped_block_ids,
                "preferred_citation_block_ids": preferred_citation_block_ids,
                "citation_allowlist_block_ids": [block.block_id for block in citation_allowlist_blocks],
                "evidence_context_hash": evidence_context_hash,
                "prompt_token_count": generation.prompt_token_count,
                "tool_result_count": len(state.table_results),
                "truncation_applied": truncation_applied,
                "completion_token_count": generation.completion_token_count,
                "finish_reason": generation.finish_reason,
                "latency_ms": generation.latency_ms,
                "raw_model_output": generation.raw_text,
                "raw_parsed_output": raw_draft,
                "canonical_output": canonical_draft,
                **generation.metadata,
            }.items()
            if key != "parse_result"
        }
        _trace(
            state,
            trace_repository,
            "generate_answer",
            input_summary={
                "policy_mode": policy_mode,
                "evidence_ids": [block.block_id for block in state.retrieved_blocks],
                "tool_result_count": len(state.table_results),
            },
            output_summary={
                "policy_mode": policy_mode,
                "prompt_version": prompt_version,
                "task_type": state.generation_metadata["task_type"],
                "tool_result_count": len(state.table_results),
                "selected_block_ids": selected_block_ids,
                "dropped_block_ids": dropped_block_ids,
                "preferred_citation_block_ids": preferred_citation_block_ids,
                "citation_allowlist_block_ids": [block.block_id for block in citation_allowlist_blocks],
                "evidence_context_hash": evidence_context_hash,
                "prompt_token_count": generation.prompt_token_count,
                "truncation_applied": truncation_applied,
                "completion_token_count": generation.completion_token_count,
                "parse_result": state.parse_result,
                "raw_model_output": generation.raw_text,
                "raw_parsed_output": raw_draft,
                "canonical_output": canonical_draft,
            },
            latency_ms=generation.latency_ms,
        )
    except Exception as exc:
        state.status = "failed"
        state.error = str(exc)
        _trace(state, trace_repository, "generate_answer", success=False, error=str(exc))
        if trace_repository is not None and state.run_id:
            trace_repository.fail_run(run_id=state.run_id, error=str(exc))
        raise

    state.format_check = check_answer_format(state.draft_answer)
    state.location_check = check_location(state.draft_answer, citation_allowlist_blocks)
    _trace(state, trace_repository, "check_format", output_summary=state.format_check, success=state.format_check["success"])
    _trace(
        state,
        trace_repository,
        "check_location",
        output_summary=state.location_check,
        success=state.location_check["success"],
    )

    if not state.format_check["success"] or not state.location_check["success"]:
        state.repair_attempted = True
        state.final_answer = repair_answer(state.draft_answer, citation_allowlist_blocks)
        state.repair_result = {
            "format_failed": not state.format_check["success"],
            "location_failed": not state.location_check["success"],
        }
        state.format_check = check_answer_format(state.final_answer)
        state.location_check = check_location(state.final_answer, citation_allowlist_blocks)
        state.final_answer = canonicalize_output(
            state.final_answer,
            citation_allowlist_blocks,
            preferred_citation_block_ids=preferred_citation_block_ids,
            evidence_ref_map=evidence_ref_map,
        )
        state.repair_result.update(
            {
                "format_success": state.format_check["success"],
                "location_success": state.location_check["success"],
            }
        )
        _trace(
            state,
            trace_repository,
            "answer_repair",
            input_summary={"repair_reason": state.repair_result},
            output_summary={
                "repair_attempted": state.repair_attempted,
                "repair_result": state.repair_result,
                "canonical_output": state.final_answer,
                "format_validation": state.format_check,
                "location_validation": state.location_check,
            },
            success=state.format_check["success"] and state.location_check["success"],
        )
    else:
        state.final_answer = state.draft_answer
    state.status = "completed"
    _trace(
        state,
        trace_repository,
        "finalize",
        output_summary={
            "canonical_output": state.final_answer,
            "format_validation": state.format_check,
            "location_validation": state.location_check,
            "repair_attempted": state.repair_attempted,
            "repair_result": state.repair_result,
            "status": state.status,
        },
    )
    if trace_repository is not None and state.run_id:
        trace_repository.complete_run(run_id=state.run_id, final_answer=state.final_answer)
    return state

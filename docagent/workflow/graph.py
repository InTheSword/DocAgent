from __future__ import annotations

from typing import Any

from docagent.models.base import AnswerPolicy
from docagent.retrieval.hybrid_retriever import HybridRetriever
from docagent.retrieval.query_rewrite import rewrite_query
from docagent.schemas import EvidenceBlock, QAState
from docagent.storage.repositories import TraceRepository
from docagent.tools.answer_repair import repair_answer
from docagent.tools.format_check import check_answer_format
from docagent.tools.location_check import check_location
from docagent.tools.visual_review import visual_review


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
) -> QAState:
    if answer_policy is None:
        raise ValueError("answer_policy is required; pass HeuristicAnswerPolicy explicitly for tests or smoke runs")
    policy_mode = getattr(answer_policy, "mode", "unknown")
    state = QAState(qid=qid, question=question, doc_id=doc_id, answer_type=answer_type_hint)
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
    else:
        retriever = HybridRetriever(blocks)
        rewritten_query, hits = retriever.retrieve(question, top_k=top_k, answer_type_hint=answer_type_hint)
        state.rewritten_query = rewritten_query
        state.retrieved_blocks = [block for block, _score in hits]
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

    try:
        generation = answer_policy.generate(
            question=question,
            evidence_blocks=state.retrieved_blocks,
            tool_results=[*state.table_results, *state.visual_results],
            answer_type=answer_type_hint,
            qid=qid,
        )
        state.draft_answer = generation.parsed or {}
        state.generation_metadata = {
            key: value
            for key, value in {
                "policy_mode": policy_mode,
                "prompt_token_count": generation.prompt_token_count,
                "completion_token_count": generation.completion_token_count,
                "finish_reason": generation.finish_reason,
                "latency_ms": generation.latency_ms,
                **generation.metadata,
            }.items()
            if key != "parse_result"
        }
        state.parse_result = dict(generation.metadata.get("parse_result") or {})
        _trace(
            state,
            trace_repository,
            "generate_answer",
            input_summary={
                "policy_mode": policy_mode,
                "evidence_ids": [block.block_id for block in state.retrieved_blocks],
            },
            output_summary={
                "policy_mode": policy_mode,
                "prompt_token_count": generation.prompt_token_count,
                "completion_token_count": generation.completion_token_count,
                "parse_result": state.parse_result,
                "raw_preview": generation.raw_text[:500],
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
    state.location_check = check_location(state.draft_answer, state.retrieved_blocks)
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
        state.final_answer = repair_answer(state.draft_answer, state.retrieved_blocks)
        state.repair_result = {
            "format_failed": not state.format_check["success"],
            "location_failed": not state.location_check["success"],
        }
        state.format_check = check_answer_format(state.final_answer)
        state.location_check = check_location(state.final_answer, state.retrieved_blocks)
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
            output_summary={"repair_result": state.repair_result, "final_answer": state.final_answer},
            success=state.format_check["success"] and state.location_check["success"],
        )
    else:
        state.final_answer = state.draft_answer
    state.status = "completed"
    _trace(
        state,
        trace_repository,
        "finalize",
        output_summary={"final_answer": state.final_answer, "status": state.status},
    )
    if trace_repository is not None and state.run_id:
        trace_repository.complete_run(run_id=state.run_id, final_answer=state.final_answer)
    return state

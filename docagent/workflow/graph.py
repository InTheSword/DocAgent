from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

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

INSUFFICIENT_ANSWER_MARKERS = (
    "insufficient evidence",
    "not enough evidence",
    "cannot answer",
    "can't answer",
    "unable to answer",
    "no evidence",
    "证据不足",
    "无法回答",
    "无法确定",
)
VISUAL_QUESTION_MARKERS = (
    "image",
    "figure",
    "chart",
    "graph",
    "visual",
    "picture",
    "图片",
    "图像",
    "图表",
    "视觉",
)


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


def _emit_progress(
    callback: Callable[[str, dict[str, Any]], None] | None,
    stage: str,
    **payload: Any,
) -> None:
    if callback is None:
        return
    callback(stage, payload)


def _recovery_windows(top_k: int, pool_size: int, *, max_attempts: int = 3) -> list[tuple[int, int]]:
    window = max(1, int(top_k))
    starts = [0, window // 2, window]
    windows: list[tuple[int, int]] = []
    for start in starts[: max(1, max_attempts)]:
        if start >= pool_size:
            continue
        end = min(start + window, pool_size)
        if end <= start:
            continue
        pair = (start, end)
        if pair not in windows:
            windows.append(pair)
    return windows


def _has_valid_citation(answer: dict[str, Any]) -> bool:
    citation_ids = [str(item).strip() for item in answer.get("citation_block_ids") or [] if str(item).strip()]
    if citation_ids:
        return True
    citations = answer.get("citations")
    if isinstance(citations, list) and any(isinstance(item, dict) and item.get("block_id") for item in citations):
        return True
    validation = answer.get("citation_validation")
    if isinstance(validation, dict):
        valid_ids = validation.get("valid_block_ids") or validation.get("valid_supporting_refs") or []
        return any(str(item).strip() for item in valid_ids)
    return False


def _looks_insufficient_answer(answer: str) -> bool:
    text = str(answer or "").casefold()
    return any(marker.casefold() in text for marker in INSUFFICIENT_ANSWER_MARKERS)


def _question_looks_visual(question: str, answer_type_hint: str | None) -> bool:
    hint = str(answer_type_hint or "").casefold()
    if hint in {"visual", "image", "figure", "chart", "visual_pixel_qa"}:
        return True
    text = str(question or "").casefold()
    return any(marker.casefold() in text for marker in VISUAL_QUESTION_MARKERS)


def _recovery_trigger_reason(
    *,
    question: str,
    answer_type_hint: str | None,
    draft_answer: dict[str, Any],
    final_answer: dict[str, Any],
    successful_visual_result_count: int,
    visual_review_mode: str,
) -> str | None:
    support_status = str(final_answer.get("support_status") or draft_answer.get("support_status") or "").strip()
    if support_status == "insufficient":
        return "support_status_insufficient"
    answer = str(final_answer.get("answer") or draft_answer.get("answer") or "").strip()
    if not answer:
        return "answer_empty"
    if _looks_insufficient_answer(answer):
        return "answer_insufficient_text"
    if support_status == "supported" and (not _has_valid_citation(draft_answer) or not _has_valid_citation(final_answer)):
        return "supported_without_valid_citation"
    if (
        str(visual_review_mode or "off") != "off"
        and _question_looks_visual(question, answer_type_hint)
        and successful_visual_result_count <= 0
    ):
        return "visual_evidence_missing"
    return None


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
    visual_review_mode: str = "off",
    visual_review_document_dir: str | Path | None = None,
    visual_review_env_file: Path | None = None,
    visual_reviewer: Callable[..., dict[str, Any]] | None = None,
    max_visual_reviews: int | None = None,
    enable_evidence_recovery: bool = False,
    max_evidence_recovery_attempts: int = 3,
    evidence_recovery_pool_k: int | None = None,
    progress_callback: Callable[[str, dict[str, Any]], None] | None = None,
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
    def retrieve_blocks(retrieval_top_k: int, step_name: str) -> tuple[list[EvidenceBlock], dict[str, Any]]:
        _emit_progress(progress_callback, "retrieve_evidence", top_k=retrieval_top_k, step=step_name)
        if preserve_input_order:
            rewrite = rewrite_query(question, answer_type_hint=answer_type_hint)
            retrieved = list(blocks[:retrieval_top_k])
            metadata: dict[str, Any] = {
                "query": rewrite.rewritten_query,
                "num_hits": len(retrieved),
                "preserve_input_order": True,
                "block_ids": [block.block_id for block in retrieved],
                "candidates": [],
                "retriever_mode": "input_order",
            }
        elif retriever is not None:
            retrieval_result = retriever.retrieve(
                doc_id=doc_id,
                question=question,
                top_k=retrieval_top_k,
                answer_type_hint=answer_type_hint,
            )
            retrieved = [candidate.block for candidate in retrieval_result.candidates]
            metadata = {
                "query": retrieval_result.rewritten_query,
                "num_hits": len(retrieved),
                "preserve_input_order": False,
                "block_ids": [block.block_id for block in retrieved],
                "candidates": [
                    candidate.to_trace_dict(final_rank=rank)
                    for rank, candidate in enumerate(retrieval_result.candidates, start=1)
                ],
                **dict(retrieval_result.metadata),
            }
        else:
            legacy_retriever = HybridRetriever(blocks)
            rewritten_query, hits = legacy_retriever.retrieve(
                question,
                top_k=retrieval_top_k,
                answer_type_hint=answer_type_hint,
            )
            retrieved = [block for block, _score in hits]
            metadata = {
                "query": rewritten_query,
                "num_hits": len(retrieved),
                "preserve_input_order": False,
                "block_ids": [block.block_id for block in retrieved],
                "candidates": [
                    {"block_id": block.block_id, "page": block.page_id, "score": score, "final_rank": rank}
                    for rank, (block, score) in enumerate(hits, start=1)
                ],
                "retriever_mode": "legacy_bm25",
            }
        state.rewritten_query = str(metadata.get("query") or "")
        _trace(
            state,
            trace_repository,
            step_name,
            input_summary={"question": question, "top_k": retrieval_top_k, "answer_type": answer_type_hint},
            output_summary=metadata,
        )
        return retrieved, metadata

    def run_attempt(
        *,
        attempt_blocks: list[EvidenceBlock],
        attempt_index: int,
        window_start: int,
        window_end: int,
        trigger_reason: str,
    ) -> dict[str, Any]:
        _emit_progress(
            progress_callback,
            "evidence_recovery_attempt" if attempt_index else "generate_answer",
            attempt_index=attempt_index,
            window_rank_start=window_start,
            window_rank_end=window_end,
            trigger_reason=trigger_reason,
        )
        attempt_visual_results: list[dict[str, Any]] = []
        visual_review_count = 0
        for block in attempt_blocks:
            if block.block_type not in {"image", "figure"}:
                continue
            if max_visual_reviews is not None and visual_review_count >= max_visual_reviews:
                continue
            visual_review_count += 1
            _emit_progress(progress_callback, "visual_review", attempt_index=attempt_index, block_type=block.block_type)
            reviewer = visual_reviewer or visual_review
            result = reviewer(
                block,
                question,
                mode=visual_review_mode,
                document_dir=visual_review_document_dir,
                env_file=visual_review_env_file,
            )
            state.visual_results.append(result)
            attempt_visual_results.append(result)
            _trace(
                state,
                trace_repository,
                "visual_review",
                input_summary={"block_id": block.block_id, "attempt_index": attempt_index},
                output_summary={
                    "attempt_index": attempt_index,
                    "block_id": block.block_id,
                    "status": result.get("status"),
                    "used_vlm": bool((result.get("structured_result") or {}).get("used_vlm")),
                    "result": result,
                },
            )

        successful_visual_results = [
            result
            for result in attempt_visual_results
            if isinstance(result, dict) and str(result.get("status") or "") == "success"
        ]
        all_tool_results = [*state.table_results, *successful_visual_results]
        preferred_citation_block_ids = _citation_ids_from_tool_results(all_tool_results)
        citation_allowlist_blocks = _citation_allowlist_blocks(attempt_blocks, blocks, preferred_citation_block_ids)
        evidence_context = build_evidence_context(
            question=question,
            task_type=answer_type_hint or "local_fact_qa",
            evidence_blocks=attempt_blocks,
            rank_aware_context=rank_aware_context,
        )
        _trace(
            state,
            trace_repository,
            "build_evidence_context",
            input_summary={
                "question": question,
                "answer_type": answer_type_hint,
                "attempt_index": attempt_index,
                "block_ids": [block.block_id for block in attempt_blocks],
            },
            output_summary={
                "attempt_index": attempt_index,
                "task_type": evidence_context["task_type"],
                "selected_block_ids": evidence_context["selected_block_ids"],
                "dropped_block_ids": evidence_context["dropped_block_ids"],
                "preferred_citation_block_ids": preferred_citation_block_ids,
                "citation_allowlist_block_ids": [block.block_id for block in citation_allowlist_blocks],
                "evidence_context_hash": evidence_context["evidence_context_hash"],
                "truncation_applied": evidence_context["truncation_applied"],
                "tool_result_count": len(all_tool_results),
            },
        )

        try:
            generation = answer_policy.generate(
                question=question,
                evidence_blocks=attempt_blocks,
                tool_results=all_tool_results,
                answer_type=answer_type_hint,
                qid=qid,
            )
        except Exception as exc:
            state.status = "failed"
            state.error = str(exc)
            _trace(state, trace_repository, "generate_answer", success=False, error=str(exc))
            if trace_repository is not None and state.run_id:
                trace_repository.fail_run(run_id=state.run_id, error=str(exc))
            raise

        raw_draft = generation.parsed or {}
        parse_result = dict(generation.metadata.get("parse_result") or {})
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
        prompt_version = generation.metadata.get("prompt_version")
        selected_block_ids = generation.metadata.get("selected_block_ids") or evidence_context["selected_block_ids"]
        dropped_block_ids = generation.metadata.get("dropped_block_ids") or evidence_context["dropped_block_ids"]
        evidence_context_hash = generation.metadata.get("evidence_context_hash") or evidence_context["evidence_context_hash"]
        truncation_applied = bool(generation.metadata.get("truncation_applied") or evidence_context["truncation_applied"])
        generation_metadata = {
            key: value
            for key, value in {
                "policy_mode": policy_mode,
                "prompt_version": prompt_version,
                "task_type": generation.metadata.get("task_type") or answer_type_hint or "local_fact_qa",
                "attempt_index": attempt_index,
                "window_rank_start": window_start,
                "window_rank_end": window_end,
                "selected_block_ids": selected_block_ids,
                "dropped_block_ids": dropped_block_ids,
                "preferred_citation_block_ids": preferred_citation_block_ids,
                "citation_allowlist_block_ids": [block.block_id for block in citation_allowlist_blocks],
                "evidence_context_hash": evidence_context_hash,
                "prompt_token_count": generation.prompt_token_count,
                "tool_result_count": len(all_tool_results),
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
                "attempt_index": attempt_index,
                "evidence_ids": [block.block_id for block in attempt_blocks],
                "tool_result_count": len(all_tool_results),
            },
            output_summary={
                "attempt_index": attempt_index,
                "policy_mode": policy_mode,
                "prompt_version": prompt_version,
                "task_type": generation_metadata["task_type"],
                "tool_result_count": len(all_tool_results),
                "selected_block_ids": selected_block_ids,
                "dropped_block_ids": dropped_block_ids,
                "preferred_citation_block_ids": preferred_citation_block_ids,
                "citation_allowlist_block_ids": [block.block_id for block in citation_allowlist_blocks],
                "evidence_context_hash": evidence_context_hash,
                "prompt_token_count": generation.prompt_token_count,
                "truncation_applied": truncation_applied,
                "completion_token_count": generation.completion_token_count,
                "parse_result": parse_result,
                "raw_model_output": generation.raw_text,
                "raw_parsed_output": raw_draft,
                "canonical_output": canonical_draft,
            },
            latency_ms=generation.latency_ms,
        )

        format_check = check_answer_format(canonical_draft)
        location_check = check_location(canonical_draft, citation_allowlist_blocks)
        _trace(
            state,
            trace_repository,
            "check_format",
            output_summary={"attempt_index": attempt_index, **format_check},
            success=format_check["success"],
        )
        _trace(
            state,
            trace_repository,
            "check_location",
            output_summary={"attempt_index": attempt_index, **location_check},
            success=location_check["success"],
        )

        repair_attempted = False
        repair_result: dict[str, Any] | None = None
        final_answer = canonical_draft
        if not format_check["success"] or not location_check["success"]:
            repair_attempted = True
            final_answer = repair_answer(canonical_draft, citation_allowlist_blocks)
            repair_result = {
                "format_failed": not format_check["success"],
                "location_failed": not location_check["success"],
            }
            format_check = check_answer_format(final_answer)
            location_check = check_location(final_answer, citation_allowlist_blocks)
            final_answer = canonicalize_output(
                final_answer,
                citation_allowlist_blocks,
                preferred_citation_block_ids=preferred_citation_block_ids,
                evidence_ref_map=evidence_ref_map,
            )
            repair_result.update(
                {
                    "format_success": format_check["success"],
                    "location_success": location_check["success"],
                }
            )
            _trace(
                state,
                trace_repository,
                "answer_repair",
                input_summary={"repair_reason": repair_result, "attempt_index": attempt_index},
                output_summary={
                    "attempt_index": attempt_index,
                    "repair_attempted": repair_attempted,
                    "repair_result": repair_result,
                    "canonical_output": final_answer,
                    "format_validation": format_check,
                    "location_validation": location_check,
                },
                success=format_check["success"] and location_check["success"],
            )
        trigger = _recovery_trigger_reason(
            question=question,
            answer_type_hint=answer_type_hint,
            draft_answer=canonical_draft,
            final_answer=final_answer,
            successful_visual_result_count=len(successful_visual_results),
            visual_review_mode=visual_review_mode,
        )
        return {
            "attempt_index": attempt_index,
            "window_rank_start": window_start,
            "window_rank_end": window_end,
            "window_block_ids": [block.block_id for block in attempt_blocks],
            "window_blocks": attempt_blocks,
            "trigger_reason": trigger,
            "draft_answer": canonical_draft,
            "final_answer": final_answer,
            "parse_result": parse_result,
            "generation_metadata": generation_metadata,
            "format_check": format_check,
            "location_check": location_check,
            "repair_attempted": repair_attempted,
            "repair_result": repair_result,
        }

    def apply_attempt(snapshot: dict[str, Any]) -> None:
        state.retrieved_blocks = list(snapshot["window_blocks"])
        state.draft_answer = dict(snapshot["draft_answer"])
        state.final_answer = dict(snapshot["final_answer"])
        state.parse_result = dict(snapshot["parse_result"])
        state.generation_metadata = dict(snapshot["generation_metadata"])
        state.format_check = dict(snapshot["format_check"])
        state.location_check = dict(snapshot["location_check"])
        state.repair_attempted = bool(snapshot["repair_attempted"])
        state.repair_result = snapshot["repair_result"]

    initial_blocks, _initial_retrieval_metadata = retrieve_blocks(top_k, "retrieve_evidence")
    initial_snapshot = run_attempt(
        attempt_blocks=initial_blocks,
        attempt_index=0,
        window_start=1,
        window_end=len(initial_blocks),
        trigger_reason="initial",
    )
    selected_snapshot = initial_snapshot
    attempts: list[dict[str, Any]] = []
    recovery_status = "disabled" if not enable_evidence_recovery else "not_triggered"

    def record_recovery_attempt(snapshot: dict[str, Any], *, accepted: bool) -> None:
        summary = {
            "attempt_index": snapshot["attempt_index"],
            "window_rank_start": snapshot["window_rank_start"],
            "window_rank_end": snapshot["window_rank_end"],
            "window_block_count": len(snapshot["window_block_ids"]),
            "window_block_ids": snapshot["window_block_ids"],
            "trigger_reason": snapshot["trigger_reason"],
            "accepted": accepted,
        }
        attempts.append(summary)
        _trace(
            state,
            trace_repository,
            "evidence_recovery_attempt",
            output_summary=summary,
            success=accepted,
        )

    if enable_evidence_recovery and initial_snapshot["trigger_reason"]:
        record_recovery_attempt(initial_snapshot, accepted=False)
        pool_k = int(evidence_recovery_pool_k or min(max(top_k * 2, top_k), 40))
        pool_blocks, _pool_metadata = retrieve_blocks(pool_k, "retrieve_evidence_recovery_pool")
        windows = _recovery_windows(top_k, len(pool_blocks), max_attempts=max_evidence_recovery_attempts)
        recovery_status = "exhausted"
        for attempt_index, (start, end) in enumerate(windows[1:], start=1):
            window_blocks = pool_blocks[start:end]
            if not window_blocks:
                continue
            snapshot = run_attempt(
                attempt_blocks=window_blocks,
                attempt_index=attempt_index,
                window_start=start + 1,
                window_end=end,
                trigger_reason=str(initial_snapshot["trigger_reason"] or "recovery"),
            )
            accepted = snapshot["trigger_reason"] is None
            record_recovery_attempt(snapshot, accepted=accepted)
            if accepted:
                selected_snapshot = snapshot
                recovery_status = "recovered"
                break
    elif enable_evidence_recovery:
        recovery_status = "not_triggered"

    apply_attempt(selected_snapshot)
    state.evidence_recovery = {
        "enabled": bool(enable_evidence_recovery),
        "status": recovery_status,
        "initial_trigger_reason": initial_snapshot["trigger_reason"],
        "selected_attempt_index": selected_snapshot["attempt_index"],
        "max_attempts": max(1, int(max_evidence_recovery_attempts)),
        "attempts": attempts,
    }
    state.generation_metadata["evidence_recovery"] = state.evidence_recovery
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
            "evidence_recovery": state.evidence_recovery,
            "status": state.status,
        },
    )
    if trace_repository is not None and state.run_id:
        trace_repository.complete_run(run_id=state.run_id, final_answer=state.final_answer)
    return state

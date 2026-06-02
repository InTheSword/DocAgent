from __future__ import annotations

from docagent.retrieval.hybrid_retriever import HybridRetriever
from docagent.schemas import EvidenceBlock, QAState
from docagent.tools.answer_repair import repair_answer
from docagent.tools.format_check import check_answer_format
from docagent.tools.location_check import check_location
from docagent.tools.visual_review import visual_review
from docagent.workflow.answer_policy import heuristic_answer


def run_qa_workflow(
    qid: str,
    question: str,
    blocks: list[EvidenceBlock],
    top_k: int = 5,
    answer_type_hint: str | None = None,
) -> QAState:
    state = QAState(qid=qid, question=question)
    retriever = HybridRetriever(blocks)
    rewritten_query, hits = retriever.retrieve(question, top_k=top_k, answer_type_hint=answer_type_hint)
    state.rewritten_query = rewritten_query
    state.retrieved_blocks = [block for block, _score in hits]
    state.trace.append({"step": "retrieve_evidence", "query": rewritten_query, "num_hits": len(hits)})

    for block in state.retrieved_blocks:
        if block.block_type in {"image", "figure"}:
            result = visual_review(block, question)
            state.visual_results.append(result)
            state.trace.append({"step": "visual_review", "block_id": block.block_id, "success": True})

    state.draft_answer = heuristic_answer(question, state.retrieved_blocks)
    state.trace.append({"step": "generate_answer", "success": True})

    state.format_check = check_answer_format(state.draft_answer)
    state.location_check = check_location(state.draft_answer, state.retrieved_blocks)
    state.trace.append({"step": "check_format", **state.format_check})
    state.trace.append({"step": "check_location", **state.location_check})

    if not state.format_check["success"] or not state.location_check["success"]:
        state.final_answer = repair_answer(state.draft_answer, state.retrieved_blocks)
        state.trace.append({"step": "answer_repair", "success": True})
    else:
        state.final_answer = state.draft_answer
    return state


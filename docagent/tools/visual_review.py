from __future__ import annotations

from docagent.schemas import EvidenceBlock


def visual_review(block: EvidenceBlock, question: str) -> dict[str, str]:
    if block.visual_summary:
        summary = block.visual_summary
    else:
        summary = block.text or "Visual review is not available in the local MVP."
    return {
        "block_id": block.block_id,
        "question": question,
        "visual_summary": summary,
        "answer_candidate": "",
        "confidence": "low",
    }


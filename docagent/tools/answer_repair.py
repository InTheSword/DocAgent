from __future__ import annotations

from typing import Any

from docagent.schemas import EvidenceBlock


def repair_answer(answer: dict[str, Any], retrieved_blocks: list[EvidenceBlock]) -> dict[str, Any]:
    repaired = dict(answer)
    if "answer" not in repaired:
        repaired["answer"] = ""
    if "evidence" not in repaired:
        repaired["evidence"] = retrieved_blocks[0].retrieval_text if retrieved_blocks else ""
    if "evidence_location" not in repaired:
        if retrieved_blocks:
            repaired["evidence_location"] = retrieved_blocks[0].location.to_dict()
        else:
            repaired["evidence_location"] = {}
    if "reason" not in repaired:
        repaired["reason"] = "Generated from retrieved evidence."
    return repaired


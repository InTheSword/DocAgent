from __future__ import annotations

from typing import Any

from docagent.schemas import EvidenceBlock


def repair_answer(answer: dict[str, Any], retrieved_blocks: list[EvidenceBlock]) -> dict[str, Any]:
    repaired = dict(answer) if isinstance(answer, dict) else {}
    if "answer" not in repaired:
        repaired["answer"] = ""
    if "evidence" not in repaired:
        repaired["evidence"] = retrieved_blocks[0].retrieval_text if retrieved_blocks else ""
    location = repaired.get("evidence_location")
    valid_blocks = {block.block_id for block in retrieved_blocks}
    valid_pages = {block.location.page for block in retrieved_blocks if block.location.page is not None}
    location_valid = (
        isinstance(location, dict)
        and (
            (location.get("block_id") in valid_blocks if location.get("block_id") else False)
            or (location.get("page") in valid_pages if location.get("page") is not None else False)
        )
    )
    if not location_valid:
        repaired["evidence_location"] = retrieved_blocks[0].location.to_dict() if retrieved_blocks else {}
    if "reason" not in repaired:
        repaired["reason"] = "Generated from retrieved evidence."
    return repaired

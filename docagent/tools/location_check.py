from __future__ import annotations

from typing import Any

from docagent.schemas import EvidenceBlock


def check_location(answer: dict[str, Any], retrieved_blocks: list[EvidenceBlock]) -> dict[str, Any]:
    location = answer.get("evidence_location") or {}
    valid_pages = {block.location.page for block in retrieved_blocks if block.location.page is not None}
    valid_blocks = {block.block_id for block in retrieved_blocks}
    page = location.get("page")
    block_id = location.get("block_id")
    page_ok = page in valid_pages if page is not None else False
    block_ok = block_id in valid_blocks if block_id else False
    return {
        "success": page_ok or block_ok,
        "page_ok": page_ok,
        "block_ok": block_ok,
        "predicted": location,
    }


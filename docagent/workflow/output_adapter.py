from __future__ import annotations

from typing import Any

from docagent.schemas import EvidenceBlock


CANONICAL_OUTPUT_FIELDS = ("answer", "evidence_location", "evidence", "reason")


def _block_by_id(blocks: list[EvidenceBlock]) -> dict[str, EvidenceBlock]:
    return {block.block_id: block for block in blocks}


def canonicalize_output(output: dict[str, Any] | None, evidence_blocks: list[EvidenceBlock]) -> dict[str, Any]:
    data = output if isinstance(output, dict) else {}
    raw_location = data.get("evidence_location")
    location = dict(raw_location) if isinstance(raw_location, dict) else {}
    block_id = location.get("block_id")
    block = _block_by_id(evidence_blocks).get(str(block_id)) if block_id else None
    if block is not None:
        location["doc_id"] = block.doc_id
        location["block_id"] = block.block_id
        if location.get("page") is None:
            location["page"] = block.location.page if block.location.page is not None else block.page_id
        if location.get("bbox") is None and block.location.bbox is not None:
            location["bbox"] = block.location.bbox
    elif "doc_id" not in location and evidence_blocks:
        location["doc_id"] = evidence_blocks[0].doc_id
    return {
        "answer": str(data.get("answer") or ""),
        "evidence_location": {key: value for key, value in location.items() if value is not None},
        "evidence": str(data.get("evidence") or ""),
        "reason": str(data.get("reason") or ""),
    }

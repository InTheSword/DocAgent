from __future__ import annotations

from typing import Any

from docagent.schemas import EvidenceBlock


ANSWER_CANDIDATE_SCHEMA = {
    "answer": "final candidate answer string",
    "reasoning_summary": "short user-facing explanation, not hidden reasoning",
    "citation_block_ids": ["block_id values selected from the provided evidence pack"],
    "evidence_used": [
        {
            "block_id": "selected evidence block id",
            "text_preview": "short text/table/image caption preview",
        }
    ],
}

ANSWER_CANDIDATE_REQUIRED_FIELDS = {"answer", "reasoning_summary"}


def candidate_citation_ids(output: dict[str, Any] | None) -> list[str]:
    if not isinstance(output, dict):
        return []
    raw_ids = output.get("citation_block_ids")
    ids: list[str] = []
    if isinstance(raw_ids, list):
        ids.extend(str(item) for item in raw_ids if str(item or "").strip())
    citations = output.get("citations")
    if isinstance(citations, list):
        for item in citations:
            if isinstance(item, dict) and str(item.get("block_id") or "").strip():
                ids.append(str(item["block_id"]))
    evidence_used = output.get("evidence_used")
    if isinstance(evidence_used, list):
        for item in evidence_used:
            if isinstance(item, dict) and str(item.get("block_id") or "").strip():
                ids.append(str(item["block_id"]))
    return list(dict.fromkeys(ids))


def is_candidate_output(output: dict[str, Any] | None) -> bool:
    if not isinstance(output, dict):
        return False
    if not ANSWER_CANDIDATE_REQUIRED_FIELDS.issubset(output):
        return False
    return "citation_block_ids" in output or "citations" in output or "evidence_used" in output


def validate_candidate_schema(
    output: dict[str, Any] | None,
    *,
    max_reason_chars: int | None = 300,
) -> tuple[bool, str | None]:
    if not isinstance(output, dict):
        return False, "parsed output is not an object"
    missing = sorted(ANSWER_CANDIDATE_REQUIRED_FIELDS - set(output))
    if "citation_block_ids" not in output and "citations" not in output and "evidence_used" not in output:
        missing.append("citation_block_ids")
    if missing:
        return False, f"missing fields: {', '.join(missing)}"
    if not isinstance(output.get("answer"), str):
        return False, "answer must be a string"
    reasoning_summary = output.get("reasoning_summary")
    if not isinstance(reasoning_summary, str):
        return False, "reasoning_summary must be a string"
    if max_reason_chars is not None and len(reasoning_summary) > max_reason_chars:
        return False, f"reasoning_summary exceeds {max_reason_chars} characters"
    citation_ids = output.get("citation_block_ids")
    if "citation_block_ids" in output and not isinstance(citation_ids, list):
        return False, "citation_block_ids must be a list"
    citations = output.get("citations")
    if "citations" in output and not isinstance(citations, list):
        return False, "citations must be a list"
    evidence_used = output.get("evidence_used")
    if "evidence_used" in output and not isinstance(evidence_used, (list, str)):
        return False, "evidence_used must be a list or string"
    return True, None


def citation_from_block(block: EvidenceBlock) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "doc_id": block.doc_id,
            "page": block.location.page if block.location.page is not None else block.page_id,
            "block_id": block.block_id,
            "block_type": block.block_type,
            "text_preview": _preview(block),
            "table_id": block.location.table_id,
            "image_id": block.location.image_id,
            "image_path": block.image_path,
        }.items()
        if value not in {None, ""}
    }


def evidence_used_from_blocks(blocks: list[EvidenceBlock]) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in {
                "doc_id": block.doc_id,
                "page": block.location.page if block.location.page is not None else block.page_id,
                "block_id": block.block_id,
                "block_type": block.block_type,
                "text_preview": _preview(block),
            }.items()
            if value not in {None, ""}
        }
        for block in blocks
    ]


def filtered_citation_blocks(
    output: dict[str, Any] | None,
    evidence_blocks: list[EvidenceBlock],
) -> tuple[list[EvidenceBlock], list[str]]:
    by_id = {block.block_id: block for block in evidence_blocks}
    requested_ids = candidate_citation_ids(output)
    selected: list[EvidenceBlock] = []
    invalid: list[str] = []
    for block_id in requested_ids:
        block = by_id.get(block_id)
        if block is None:
            invalid.append(block_id)
            continue
        selected.append(block)
    return selected, invalid


def _preview(block: EvidenceBlock, limit: int = 220) -> str:
    text = " ".join(block.retrieval_text.split())
    return text[:limit]

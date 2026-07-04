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

MODEL_OUTPUT_V3_SCHEMA = {
    "answer": "final answer string, or an evidence-insufficient response",
    "supporting_refs": ["temporary evidence candidate refs such as E1, E2"],
    "support_status": "supported or insufficient",
    "reasoning_summary": "short user-facing explanation, not hidden reasoning",
}

MODEL_OUTPUT_V3_REQUIRED_FIELDS = {"answer", "supporting_refs", "support_status", "reasoning_summary"}
MODEL_OUTPUT_V3_SUPPORT_STATUSES = {"supported", "insufficient"}

EVIDENCE_CANDIDATE_KINDS = {
    "text",
    "table",
    "ocr",
    "markdown",
    "image",
    "calculation_result",
    "tool_observation",
}


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


def primary_location_from_output(output: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(output, dict):
        return {}
    legacy_location = output.get("evidence_location")
    if isinstance(legacy_location, dict):
        return dict(legacy_location)
    for key in ("citations", "evidence_used"):
        value = output.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            location = _location_fields(item)
            if location:
                return location
    citation_ids = output.get("citation_block_ids")
    if isinstance(citation_ids, list):
        for block_id in citation_ids:
            if str(block_id or "").strip():
                return {"block_id": str(block_id)}
    return {}


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


def normalize_supporting_refs(output: dict[str, Any] | None) -> list[str]:
    if not isinstance(output, dict):
        return []
    raw_refs = output.get("supporting_refs")
    if not isinstance(raw_refs, list):
        return []
    refs: list[str] = []
    for item in raw_refs:
        ref = str(item or "").strip()
        if ref:
            refs.append(ref)
    return list(dict.fromkeys(refs))


def is_model_output_v3(output: dict[str, Any] | None) -> bool:
    if not isinstance(output, dict):
        return False
    return bool(MODEL_OUTPUT_V3_REQUIRED_FIELDS & set(output)) and "supporting_refs" in output


def validate_model_output_v3(
    output: dict[str, Any] | None,
    *,
    allowed_refs: set[str] | None = None,
    max_reason_chars: int | None = 300,
) -> tuple[bool, str | None]:
    if not isinstance(output, dict):
        return False, "parsed output is not an object"
    missing = sorted(MODEL_OUTPUT_V3_REQUIRED_FIELDS - set(output))
    if missing:
        return False, f"missing fields: {', '.join(missing)}"
    if not isinstance(output.get("answer"), str):
        return False, "answer must be a string"
    if not isinstance(output.get("reasoning_summary"), str):
        return False, "reasoning_summary must be a string"
    if max_reason_chars is not None and len(str(output.get("reasoning_summary") or "")) > max_reason_chars:
        return False, f"reasoning_summary exceeds {max_reason_chars} characters"
    support_status = str(output.get("support_status") or "")
    if support_status not in MODEL_OUTPUT_V3_SUPPORT_STATUSES:
        return False, "support_status must be supported or insufficient"
    if not isinstance(output.get("supporting_refs"), list):
        return False, "supporting_refs must be a list"
    refs = normalize_supporting_refs(output)
    if support_status == "supported" and not refs:
        return False, "supported output requires at least one supporting_ref"
    if support_status == "insufficient" and refs:
        return False, "insufficient output must not include supporting_refs"
    if allowed_refs is not None:
        invalid = [ref for ref in refs if ref not in allowed_refs]
        if invalid:
            return False, f"invalid supporting_refs: {', '.join(invalid)}"
    return True, None


def evidence_ref_map_from_blocks(blocks: list[EvidenceBlock]) -> dict[str, dict[str, Any]]:
    ref_map: dict[str, dict[str, Any]] = {}
    for index, block in enumerate(blocks, start=1):
        citation = citation_from_block(block)
        ref_map[f"E{index}"] = {
            key: value
            for key, value in {
                "source_kind": "evidence_block",
                "doc_id": citation.get("doc_id"),
                "page": citation.get("page"),
                "block_id": citation.get("block_id"),
                "block_type": citation.get("block_type"),
                "preview": citation.get("text_preview"),
                "table_caption": citation.get("table_caption"),
                "image_caption": citation.get("image_caption"),
                "nearby_text": citation.get("nearby_text"),
            }.items()
            if value not in {None, ""}
        }
    return ref_map


def citation_from_block(block: EvidenceBlock) -> dict[str, Any]:
    table_caption = _metadata_text(block, "table_caption")
    image_caption = _metadata_text(block, "caption", "image_caption", "chart_caption")
    nearby_text = _metadata_preview(block, "nearby_text")
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
            "table_caption": table_caption,
            "image_caption": image_caption,
            "nearby_text": nearby_text,
        }.items()
        if value not in {None, ""}
    }


def evidence_used_from_blocks(blocks: list[EvidenceBlock]) -> list[dict[str, Any]]:
    return [_evidence_used_from_block(block) for block in blocks]


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


def _evidence_used_from_block(block: EvidenceBlock) -> dict[str, Any]:
    citation = citation_from_block(block)
    return {
        key: value
        for key, value in {
            "doc_id": citation.get("doc_id"),
            "page": citation.get("page"),
            "block_id": citation.get("block_id"),
            "block_type": citation.get("block_type"),
            "text_preview": citation.get("text_preview"),
            "table_caption": citation.get("table_caption"),
            "image_caption": citation.get("image_caption"),
            "nearby_text": citation.get("nearby_text"),
            "image_path": citation.get("image_path"),
        }.items()
        if value not in {None, ""}
    }


def _metadata_text(block: EvidenceBlock, *keys: str) -> str:
    parts: list[str] = []
    for key in keys:
        value = block.metadata.get(key)
        if isinstance(value, list):
            parts.extend(str(item).strip() for item in value if str(item or "").strip())
        elif value not in {None, ""}:
            parts.append(str(value).strip())
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        compact = " ".join(part.split())
        marker = compact.casefold()
        if not compact or marker in seen:
            continue
        seen.add(marker)
        result.append(compact)
    return " ".join(result)


def _metadata_preview(block: EvidenceBlock, *keys: str, limit: int = 220) -> str:
    text = _metadata_text(block, *keys)
    if len(text) <= limit:
        return text
    preview = text[:limit]
    split_at = max(preview.rfind(" "), preview.rfind(";"), preview.rfind(","))
    if split_at >= int(limit * 0.5):
        preview = preview[:split_at]
    return preview.rstrip(" ,;:-")


def _location_fields(item: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "doc_id": item.get("doc_id"),
            "page": item.get("page"),
            "block_id": item.get("block_id"),
            "table_id": item.get("table_id"),
            "image_id": item.get("image_id"),
            "bbox": item.get("bbox"),
        }.items()
        if value is not None and value != ""
    }

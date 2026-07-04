from __future__ import annotations

from typing import Any

from docagent.schemas import EvidenceBlock
from docagent.workflow.answer_contract import (
    citation_from_block,
    evidence_ref_map_from_blocks,
    evidence_used_from_blocks,
    filtered_citation_blocks,
    is_candidate_output,
    is_model_output_v3,
    normalize_supporting_refs,
)


CANONICAL_OUTPUT_FIELDS = ("answer", "evidence_location", "evidence", "reason")


def _block_by_id(blocks: list[EvidenceBlock]) -> dict[str, EvidenceBlock]:
    return {block.block_id: block for block in blocks}


def canonicalize_output(
    output: dict[str, Any] | None,
    evidence_blocks: list[EvidenceBlock],
    *,
    preferred_citation_block_ids: list[str] | None = None,
    evidence_ref_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    data = output if isinstance(output, dict) else {}
    if is_model_output_v3(data):
        return _canonicalize_model_output_v3(
            data,
            evidence_blocks,
            evidence_ref_map=evidence_ref_map,
        )
    if is_candidate_output(data):
        return _canonicalize_candidate_output(
            data,
            evidence_blocks,
            preferred_citation_block_ids=preferred_citation_block_ids,
        )
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


def render_user_answer_text(output: dict[str, Any]) -> str:
    answer = str(output.get("answer") or "").strip()
    source_lines: list[str] = []
    sources = output.get("citations") if isinstance(output.get("citations"), list) else []
    for citation in sources:
        if not isinstance(citation, dict):
            continue
        preview = str(citation.get("text_preview") or citation.get("table_caption") or citation.get("image_caption") or "").strip()
        if not preview:
            continue
        page = citation.get("page")
        block_type = str(citation.get("block_type") or "evidence")
        location = f"Page {page}, {block_type}" if page is not None else block_type
        source_lines.append(f"- {location}: {preview}")
    if not source_lines:
        return answer
    return f"{answer}\n\nSources:\n" + "\n".join(source_lines)


def _canonicalize_model_output_v3(
    data: dict[str, Any],
    evidence_blocks: list[EvidenceBlock],
    *,
    evidence_ref_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    ref_map = evidence_ref_map or evidence_ref_map_from_blocks(evidence_blocks)
    refs = normalize_supporting_refs(data)
    selected_blocks, invalid_refs, unmapped_refs = _blocks_for_supporting_refs(refs, ref_map, evidence_blocks)
    support_status = str(data.get("support_status") or "")
    if support_status == "insufficient":
        selected_blocks = []
    first_block = selected_blocks[0] if selected_blocks else None
    evidence_used = evidence_used_from_blocks(selected_blocks)
    if not evidence_used and support_status == "supported":
        evidence_used = _evidence_used_from_ref_map(refs, ref_map)
    evidence_text = str(evidence_used[0].get("text_preview") or evidence_used[0].get("preview") or "") if evidence_used else ""
    reasoning_summary = str(data.get("reasoning_summary") or "")
    citation_ids = [block.block_id for block in selected_blocks]
    return {
        "answer": str(data.get("answer") or ""),
        "evidence_location": _location_from_block(first_block) if first_block is not None else {},
        "evidence": evidence_text,
        "reason": reasoning_summary,
        "reasoning_summary": reasoning_summary,
        "support_status": support_status,
        "supporting_refs": refs,
        "citation_block_ids": citation_ids,
        "citations": [citation_from_block(block) for block in selected_blocks],
        "evidence_used": evidence_used,
        "citation_validation": {
            "requested_supporting_refs": refs,
            "valid_supporting_refs": [ref for ref in refs if ref in ref_map and ref not in invalid_refs],
            "invalid_supporting_refs": invalid_refs,
            "unmapped_supporting_refs": unmapped_refs,
            "valid_block_ids": citation_ids,
            "allowlist_size": len(evidence_blocks),
            "evidence_ref_map_size": len(ref_map),
        },
    }


def _canonicalize_candidate_output(
    data: dict[str, Any],
    evidence_blocks: list[EvidenceBlock],
    *,
    preferred_citation_block_ids: list[str] | None = None,
) -> dict[str, Any]:
    cited_blocks, invalid_ids = filtered_citation_blocks(data, evidence_blocks)
    preferred_ids = _unique_ids(preferred_citation_block_ids or [])
    preferred_blocks, missing_preferred_ids = _blocks_for_ids(preferred_ids, evidence_blocks)
    cited_blocks = _merge_blocks(preferred_blocks, cited_blocks)
    first_block = cited_blocks[0] if cited_blocks else None
    location = _location_from_block(first_block) if first_block is not None else {}
    raw_evidence_used = data.get("evidence_used")
    evidence_used = _normalize_evidence_used(raw_evidence_used, cited_blocks)
    evidence_used.extend(_missing_evidence_used(cited_blocks, evidence_used))
    evidence_text = str(data.get("evidence") or "")
    if not evidence_text and evidence_used:
        evidence_text = str(evidence_used[0].get("text_preview") or "")
    reasoning_summary = str(data.get("reasoning_summary") or data.get("reason") or "")
    requested_ids = _requested_ids(data)
    canonical = {
        "answer": str(data.get("answer") or ""),
        "evidence_location": location,
        "evidence": evidence_text,
        "reason": reasoning_summary,
        "reasoning_summary": reasoning_summary,
        "citation_block_ids": [block.block_id for block in cited_blocks],
        "citations": [citation_from_block(block) for block in cited_blocks],
        "evidence_used": evidence_used,
        "citation_validation": {
            "requested_block_ids": requested_ids,
            "valid_block_ids": [block.block_id for block in cited_blocks],
            "invalid_block_ids": invalid_ids,
            "preferred_block_ids": preferred_ids,
            "added_preferred_block_ids": [block.block_id for block in preferred_blocks if block.block_id not in requested_ids],
            "missing_preferred_block_ids": missing_preferred_ids,
            "allowlist_size": len(evidence_blocks),
        },
    }
    return canonical


def _location_from_block(block: EvidenceBlock | None) -> dict[str, Any]:
    if block is None:
        return {}
    location = block.location.to_dict()
    location["doc_id"] = block.doc_id
    location["block_id"] = block.block_id
    if location.get("page") is None:
        location["page"] = block.location.page if block.location.page is not None else block.page_id
    return {key: value for key, value in location.items() if value is not None}


def _normalize_evidence_used(value: Any, cited_blocks: list[EvidenceBlock]) -> list[dict[str, Any]]:
    allowed = {block.block_id: block for block in cited_blocks}
    if isinstance(value, str):
        return [{"text_preview": value}] if value.strip() else []
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        block_id = str(item.get("block_id") or "")
        if block_id and block_id not in allowed:
            continue
        merged = dict(item)
        if block_id:
            block = allowed[block_id]
            citation = citation_from_block(block)
            merged.setdefault("doc_id", block.doc_id)
            merged.setdefault("page", block.location.page if block.location.page is not None else block.page_id)
            merged.setdefault("block_type", block.block_type)
            for key in ("text_preview", "table_caption", "image_caption", "nearby_text", "image_path"):
                value = citation.get(key)
                if value not in {None, ""}:
                    merged.setdefault(key, value)
        normalized.append({key: value for key, value in merged.items() if value not in {None, ""}})
    return normalized


def _requested_ids(data: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    raw = data.get("citation_block_ids")
    if isinstance(raw, list):
        ids.extend(str(item) for item in raw if str(item or "").strip())
    for key in ("citations", "evidence_used"):
        value = data.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict) and str(item.get("block_id") or "").strip():
                ids.append(str(item["block_id"]))
    return list(dict.fromkeys(ids))


def _unique_ids(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in values if str(item or "").strip()))


def _blocks_for_ids(block_ids: list[str], evidence_blocks: list[EvidenceBlock]) -> tuple[list[EvidenceBlock], list[str]]:
    by_id = _block_by_id(evidence_blocks)
    blocks: list[EvidenceBlock] = []
    missing: list[str] = []
    for block_id in block_ids:
        block = by_id.get(block_id)
        if block is None:
            missing.append(block_id)
            continue
        blocks.append(block)
    return blocks, missing


def _blocks_for_supporting_refs(
    refs: list[str],
    ref_map: dict[str, dict[str, Any]],
    evidence_blocks: list[EvidenceBlock],
) -> tuple[list[EvidenceBlock], list[str], list[str]]:
    by_id = _block_by_id(evidence_blocks)
    blocks: list[EvidenceBlock] = []
    invalid_refs: list[str] = []
    unmapped_refs: list[str] = []
    for ref in refs:
        entry = ref_map.get(ref)
        if entry is None:
            invalid_refs.append(ref)
            continue
        candidate_ids = []
        block_id = entry.get("block_id")
        if block_id:
            candidate_ids.append(str(block_id))
        for derived_ref in entry.get("derived_from_refs") or []:
            derived = ref_map.get(str(derived_ref))
            if isinstance(derived, dict) and derived.get("block_id"):
                candidate_ids.append(str(derived["block_id"]))
        matched = False
        for block_id in candidate_ids:
            block = by_id.get(block_id)
            if block is None:
                continue
            blocks.append(block)
            matched = True
        if not matched:
            unmapped_refs.append(ref)
    return _merge_blocks([], blocks), invalid_refs, unmapped_refs


def _evidence_used_from_ref_map(refs: list[str], ref_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for ref in refs:
        entry = ref_map.get(ref)
        if not isinstance(entry, dict):
            continue
        rows.append(
            {
                key: value
                for key, value in {
                    "ref": ref,
                    "source_kind": entry.get("source_kind"),
                    "block_type": entry.get("block_type"),
                    "page": entry.get("page"),
                    "text_preview": entry.get("preview") or entry.get("display_text"),
                }.items()
                if value not in {None, ""}
            }
        )
    return rows


def _merge_blocks(first: list[EvidenceBlock], second: list[EvidenceBlock]) -> list[EvidenceBlock]:
    merged: list[EvidenceBlock] = []
    seen: set[str] = set()
    for block in [*first, *second]:
        if block.block_id in seen:
            continue
        seen.add(block.block_id)
        merged.append(block)
    return merged


def _missing_evidence_used(cited_blocks: list[EvidenceBlock], evidence_used: list[dict[str, Any]]) -> list[dict[str, Any]]:
    used_ids = {str(item.get("block_id")) for item in evidence_used if isinstance(item, dict) and item.get("block_id")}
    missing_blocks = [block for block in cited_blocks if block.block_id not in used_ids]
    return evidence_used_from_blocks(missing_blocks)

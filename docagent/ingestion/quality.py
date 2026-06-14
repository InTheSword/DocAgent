from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

from docagent.ingestion.hashing import sha256_file
from docagent.parser.mineru_converter import find_content_list, raw_content_list_stats
from docagent.schemas import EvidenceBlock


def _relative_posix(path: Path, document_dir: Path) -> str:
    try:
        return path.resolve().relative_to(document_dir.resolve()).as_posix()
    except ValueError:
        return path.name if path.is_absolute() else path.as_posix()


def _file_info(path: Path | None, document_dir: Path) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return {
        "path": _relative_posix(path, document_dir),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def _pdf_page_count(path: Path) -> int | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    # Good enough for a compact quality report when no PDF dependency is present.
    return len(re.findall(rb"/Type\s*/Page\b", data)) or None


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _layout_info(mineru_output_dir: Path, document_dir: Path) -> dict[str, Any]:
    layout_path = mineru_output_dir / "layout.json"
    data = _read_json(layout_path)
    if data is None:
        return {
            "layout_path": _relative_posix(layout_path, document_dir),
            "layout_readable": False,
            "layout_page_count": None,
            "mineru_backend": None,
            "mineru_version": None,
            "mineru_ocr_enable": None,
            "mineru_vlm_ocr_enable": None,
        }
    return {
        "layout_path": _relative_posix(layout_path, document_dir),
        "layout_readable": True,
        "layout_page_count": len(data.get("pdf_info") or []),
        "mineru_backend": data.get("_backend"),
        "mineru_version": data.get("_version_name"),
        "mineru_ocr_enable": data.get("_ocr_enable"),
        "mineru_vlm_ocr_enable": data.get("_vlm_ocr_enable"),
    }


def _source_manifest(document_dir: Path, mineru_output_dir: Path) -> dict[str, Any]:
    for path in (
        document_dir / "mineru_source_manifest.json",
        mineru_output_dir / "source_manifest.json",
        mineru_output_dir.parent / "source_manifest.json",
    ):
        data = _read_json(path)
        if data is not None:
            data = dict(data)
            data["manifest_path"] = _relative_posix(path, document_dir)
            return data
    return {}


def _origin_pdf(mineru_output_dir: Path) -> Path | None:
    candidates = sorted(mineru_output_dir.glob("*_origin.pdf"))
    return candidates[0] if candidates else None


def _block_id_unique(blocks: list[EvidenceBlock]) -> bool:
    block_ids = [block.block_id for block in blocks]
    return len(block_ids) == len(set(block_ids))


def _reading_order_contiguous(blocks: list[EvidenceBlock]) -> bool:
    values = [block.metadata.get("reading_order") for block in blocks]
    if any(not isinstance(value, int) for value in values):
        return False
    return sorted(values) == list(range(1, len(values) + 1))


def _adjacency_valid(blocks: list[EvidenceBlock]) -> bool:
    by_id = {block.block_id: block for block in blocks}
    if len(by_id) != len(blocks):
        return False
    for index, block in enumerate(blocks):
        prev_id = block.metadata.get("previous_block_id")
        next_id = block.metadata.get("next_block_id")
        if index == 0:
            if prev_id is not None:
                return False
        elif prev_id != blocks[index - 1].block_id:
            return False
        if index + 1 == len(blocks):
            if next_id is not None:
                return False
        elif next_id != blocks[index + 1].block_id:
            return False
        if prev_id is not None and prev_id not in by_id:
            return False
        if next_id is not None and next_id not in by_id:
            return False
    return True


def _missing_main_content_count(blocks: list[EvidenceBlock]) -> int:
    count = 0
    for block in blocks:
        if block.block_type == "table" and not (block.text or block.table_html):
            count += 1
        elif block.block_type == "image" and not (block.text or block.image_path):
            count += 1
        elif block.block_type == "text" and not block.text:
            count += 1
    return count


def _missing_retrieval_content_count(blocks: list[EvidenceBlock]) -> int:
    return _missing_main_content_count([block for block in blocks if not block.metadata.get("exclude_from_retrieval")])


def _empty_boilerplate_block_ids(blocks: list[EvidenceBlock]) -> list[str]:
    return [
        block.block_id
        for block in blocks
        if block.metadata.get("is_boilerplate") and not (block.text or block.table_html or block.image_path)
    ]


def _raw_keys(content_list_path: Path) -> set[str]:
    try:
        data = json.loads(content_list_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return set()
    if isinstance(data, dict):
        data = data.get("content_list") or data.get("blocks") or []
    keys: set[str] = set()
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                keys.update(item)
    return keys


def build_structure_quality_report(
    *,
    doc_id: str,
    source_pdf: str | Path,
    mineru_output_dir: str | Path,
    document_dir: str | Path,
    blocks: list[EvidenceBlock],
    page_blocks: list[EvidenceBlock],
) -> dict[str, Any]:
    source_path = Path(source_pdf)
    mineru_dir = Path(mineru_output_dir)
    doc_dir = Path(document_dir)
    content_list = find_content_list(mineru_dir)
    raw_stats = raw_content_list_stats(content_list)
    layout = _layout_info(mineru_dir, doc_dir)
    manifest = _source_manifest(doc_dir, mineru_dir)
    origin_pdf = _origin_pdf(mineru_dir)
    source_info = _file_info(source_path, doc_dir)
    origin_info = _file_info(origin_pdf, doc_dir)
    warnings: list[str] = []

    same_binary = None
    if source_info and origin_info:
        same_binary = source_info["sha256"] == origin_info["sha256"]
        if not same_binary:
            warnings.append("mineru_origin_pdf_sha256_differs_from_source_pdf")

    missing_image_blocks = [
        block.block_id
        for block in blocks
        if block.image_path and not block.metadata.get("resource_exists")
    ]
    if missing_image_blocks:
        warnings.append("missing_image_references")

    raw_distribution = raw_stats["raw_type_distribution"]
    known_types = {"text", "title", "paragraph", "list", "table", "image", "figure", "chart", "header", "footer", "page_number"}
    unknown_raw_types = sorted(raw_type for raw_type in raw_distribution if raw_type not in known_types)
    if unknown_raw_types:
        warnings.append("unknown_raw_types_present")

    block_id_unique = _block_id_unique(blocks)
    adjacency_valid = _adjacency_valid(blocks)
    reading_order_contiguous = _reading_order_contiguous(blocks)
    if not block_id_unique:
        warnings.append("duplicate_block_ids")
    if not adjacency_valid:
        warnings.append("invalid_previous_next_links")
    if not reading_order_contiguous:
        warnings.append("non_contiguous_reading_order")

    image_ref_count = sum(1 for block in blocks if block.image_path)
    table_count = sum(1 for block in blocks if block.block_type == "table")
    chart_count = sum(1 for block in blocks if block.metadata.get("raw_mineru_type") == "chart")
    boilerplate_count = sum(1 for block in blocks if block.metadata.get("is_boilerplate"))
    table_html_count = sum(1 for block in blocks if block.table_html)
    missing_bbox_count = sum(1 for block in blocks if block.location.bbox is None)
    missing_content_count = _missing_main_content_count(blocks)
    missing_retrieval_content_count = _missing_retrieval_content_count(blocks)
    empty_boilerplate_block_ids = _empty_boilerplate_block_ids(blocks)

    failed = not blocks or not block_id_unique or not adjacency_valid or bool(missing_image_blocks)
    status = "failed" if failed else "passed_with_warnings" if warnings else "passed"
    consumed_fields = {
        "type",
        "block_type",
        "page_idx",
        "page",
        "page_id",
        "bbox",
        "text",
        "content",
        "table_text",
        "table_html",
        "table_body",
        "table_caption",
        "table_footnote",
        "caption",
        "image_caption",
        "chart_caption",
        "chart_footnote",
        "nearby_text",
        "image_path",
        "img_path",
        "sub_type",
        "text_level",
    }

    return {
        "doc_id": doc_id,
        "source_pdf": source_info,
        "mineru_origin_pdf": origin_info,
        "same_binary": same_binary,
        "batch_id": manifest.get("mineru_batch_id"),
        "mineru_model": manifest.get("mineru_model_version"),
        "mineru_backend": layout["mineru_backend"],
        "mineru_version": layout["mineru_version"],
        "mineru_ocr_enable": layout["mineru_ocr_enable"],
        "mineru_vlm_ocr_enable": layout["mineru_vlm_ocr_enable"],
        "source_pdf_page_count": _pdf_page_count(source_path),
        "layout_page_count": layout["layout_page_count"],
        "content_list_page_count": raw_stats["content_list_pages"],
        "content_list_file": _relative_posix(content_list, doc_dir),
        "raw_block_count": raw_stats["raw_block_count"],
        "converted_block_count": len(blocks),
        "page_document_count": len(page_blocks),
        "raw_type_distribution": raw_distribution,
        "converted_type_distribution": dict(sorted(Counter(block.block_type for block in blocks).items())),
        "missing_page_count": raw_stats["missing_page_count"],
        "missing_or_invalid_bbox_count": raw_stats["missing_or_invalid_bbox_count"],
        "missing_converted_bbox_count": missing_bbox_count,
        "missing_main_content_count": missing_content_count,
        "missing_main_content_includes_boilerplate": True,
        "missing_retrieval_content_count": missing_retrieval_content_count,
        "block_id_unique": block_id_unique,
        "reading_order_contiguous": reading_order_contiguous,
        "adjacency_valid": adjacency_valid,
        "boilerplate_count": boilerplate_count,
        "empty_boilerplate_count": len(empty_boilerplate_block_ids),
        "empty_boilerplate_block_ids": empty_boilerplate_block_ids,
        "table_count": table_count,
        "table_html_count": table_html_count,
        "chart_count": chart_count,
        "image_reference_count": image_ref_count,
        "missing_image_reference_count": len(missing_image_blocks),
        "missing_image_reference_block_ids": missing_image_blocks,
        "unknown_raw_types": unknown_raw_types,
        "preserved_but_not_consumed_fields": sorted(_raw_keys(content_list) - consumed_fields),
        "warnings": warnings,
        "overall_status": status,
    }

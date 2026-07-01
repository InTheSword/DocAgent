from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.parser.mineru_converter import build_page_blocks, content_list_to_blocks
from scripts.run_final_eval_subset import as_list, normalize_text


SCRIPT_VERSION = "mineru-evidence-artifact-audit-v1"
EVALUATION_SCOPE = "mineru_artifact_to_evidence_audit_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "mineru_evidence_artifact_audit"
RESOURCE_PATH_KEYS = (
    "image_path",
    "img_path",
    "image_url",
    "img_url",
    "table_image_path",
    "table_img_path",
    "table_image_url",
    "table_img_url",
)


def repo_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def safe_relpath(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"mineru_evidence_artifact_audit_{stamp}"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def compact(text: str) -> str:
    return " ".join(str(text or "").split())


def text_preview(text: str, answers: list[str], *, max_chars: int = 500) -> str:
    normalized = compact(text)
    lowered = normalized.lower()
    for answer in answers:
        needle = compact(answer).lower()
        if needle and needle in lowered:
            start = max(0, lowered.index(needle) - 180)
            return normalized[start : start + max_chars]
    return normalized[:max_chars]


def answer_hit(text: str, answers: list[str]) -> bool:
    normalized = normalize_text(text)
    return any(answer and normalize_text(answer) in normalized for answer in answers)


def page_from_item(item: dict[str, Any]) -> int | None:
    for key in ("page_idx", "page", "page_id"):
        value = item.get(key)
        if value is None:
            continue
        try:
            return int(value) + 1
        except (TypeError, ValueError):
            return None
    return None


def clean_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return compact(" ".join(clean_text(item) for item in value))
    if isinstance(value, dict):
        return compact(" ".join(clean_text(item) for item in value.values()))
    return compact(re.sub(r"<[^>]+>", " ", str(value)))


def item_text(item: dict[str, Any]) -> str:
    raw_type = str(item.get("type") or item.get("block_type") or "").lower()
    keys = ["text", "content"]
    if raw_type == "table":
        keys = ["table_caption", "table_text", "table_body", "table_html", "table_footnote", *keys]
    if raw_type in {"image", "figure", "chart"}:
        keys = ["caption", "image_caption", "chart_caption", "nearby_text", *keys]
    return "\n".join(part for key in keys if (part := clean_text(item.get(key)))).strip()


def is_remote_resource(value: str) -> bool:
    return bool(re.match(r"^https?://", str(value or "").strip(), flags=re.IGNORECASE))


def raw_resource_stats(items: list[dict[str, Any]]) -> dict[str, Any]:
    key_counts: Counter[str] = Counter()
    raw_type_counts: Counter[str] = Counter()
    remote_count = 0
    local_count = 0
    table_resource_count = 0
    image_resource_count = 0
    examples: list[dict[str, Any]] = []
    for item in items:
        raw_type = str(item.get("type") or item.get("block_type") or "").lower()
        keys = [key for key in RESOURCE_PATH_KEYS if item.get(key)]
        if not keys:
            continue
        raw_type_counts[raw_type or "unknown"] += 1
        if raw_type == "table":
            table_resource_count += 1
        if raw_type in {"image", "figure", "chart"}:
            image_resource_count += 1
        for key in keys:
            value = str(item.get(key) or "")
            key_counts[key] += 1
            if is_remote_resource(value):
                remote_count += 1
            else:
                local_count += 1
            if len(examples) < 5:
                examples.append(
                    {
                        "page": page_from_item(item),
                        "raw_type": raw_type,
                        "key": key,
                        "is_remote": is_remote_resource(value),
                        "value_preview": value[:180],
                    }
                )
    return {
        "raw_resource_item_count": sum(raw_type_counts.values()),
        "raw_resource_reference_count": sum(key_counts.values()),
        "raw_remote_resource_reference_count": remote_count,
        "raw_local_resource_reference_count": local_count,
        "raw_table_resource_item_count": table_resource_count,
        "raw_image_resource_item_count": image_resource_count,
        "raw_resource_key_counts": dict(sorted(key_counts.items())),
        "raw_resource_type_counts": dict(sorted(raw_type_counts.items())),
        "raw_resource_examples": examples,
    }


def load_content_items(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if isinstance(payload, dict):
        payload = payload.get("content_list") or payload.get("blocks") or payload.get("items") or []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def content_list_stats(path: Path | None, answers: list[str], gold_pages: set[int]) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {"path": "", "exists": False}
    items = load_content_items(path)
    page_texts: dict[int, list[str]] = {}
    gold_hit_items: list[dict[str, Any]] = []
    for item in items:
        page = page_from_item(item)
        if page is not None:
            text = item_text(item)
            page_texts.setdefault(page, []).append(text)
            if page in gold_pages and answer_hit(text, answers):
                gold_hit_items.append(
                    {
                        "page": page,
                        "raw_type": str(item.get("type") or item.get("block_type") or ""),
                        "keys": sorted(str(key) for key in item.keys())[:30],
                        "text_char_count": len(text),
                        "text_preview": text_preview(text, answers, max_chars=240),
                    }
                )
    gold_text = "\n".join(
        "\n".join(parts) for page, parts in sorted(page_texts.items()) if page in gold_pages
    )
    all_text = "\n".join("\n".join(parts) for _, parts in sorted(page_texts.items()))
    return {
        "path": safe_relpath(path),
        "exists": True,
        "item_count": len(items),
        "page_count": len(page_texts),
        "gold_page_char_count": len(gold_text),
        "all_text_char_count": len(all_text),
        "gold_page_answer_hit": answer_hit(gold_text, answers),
        "any_page_answer_hit": answer_hit(all_text, answers),
        "gold_page_answer_hit_items": gold_hit_items[:5],
        "gold_page_preview": text_preview(gold_text, answers),
        "resource_stats": raw_resource_stats(items),
    }


def block_resource_stats(blocks: list[Any]) -> dict[str, Any]:
    key_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    remote_count = 0
    local_existing_count = 0
    local_missing_count = 0
    unknown_existence_count = 0
    examples: list[dict[str, Any]] = []
    for block in blocks:
        image_path = str(getattr(block, "image_path", "") or "")
        if not image_path:
            continue
        metadata = getattr(block, "metadata", {}) or {}
        key = str(metadata.get("resource_key") or "image_path")
        key_counts[key] += 1
        type_counts[str(getattr(block, "block_type", "") or "unknown")] += 1
        is_remote = bool(metadata.get("resource_is_remote")) or is_remote_resource(image_path)
        exists = metadata.get("resource_exists")
        if is_remote:
            remote_count += 1
        elif exists is True:
            local_existing_count += 1
        elif exists is False:
            local_missing_count += 1
        else:
            unknown_existence_count += 1
        if len(examples) < 5:
            examples.append(
                {
                    "block_id": str(getattr(block, "block_id", "") or ""),
                    "page": getattr(block, "page_id", None),
                    "block_type": str(getattr(block, "block_type", "") or ""),
                    "resource_key": key,
                    "is_remote": is_remote,
                    "resource_exists": exists,
                    "image_path_preview": image_path[:180],
                }
            )
    return {
        "resource_reference_count": sum(key_counts.values()),
        "remote_resource_reference_count": remote_count,
        "local_existing_resource_reference_count": local_existing_count,
        "local_missing_resource_reference_count": local_missing_count,
        "unknown_resource_existence_count": unknown_existence_count,
        "resource_key_counts": dict(sorted(key_counts.items())),
        "resource_block_type_counts": dict(sorted(type_counts.items())),
        "resource_examples": examples,
    }


def converted_evidence_stats(
    *,
    path: Path | None,
    ingested_doc_id: str,
    mineru_dir: Path | None,
    answers: list[str],
    gold_pages: set[int],
) -> dict[str, Any]:
    if path is None or not path.is_file() or mineru_dir is None or not ingested_doc_id:
        return {"available": False, "block_count": 0}
    try:
        blocks = content_list_to_blocks(
            doc_id=ingested_doc_id,
            content_list_path=path,
            document_dir=mineru_dir.parent,
            resource_root=mineru_dir,
        )
        page_blocks = build_page_blocks(ingested_doc_id, blocks)
    except Exception as exc:
        return {
            "available": False,
            "block_count": 0,
            "error": {"type": type(exc).__name__, "message": compact(str(exc))[:240]},
        }
    gold_text = "\n".join(
        block.retrieval_text
        for block in page_blocks
        if block.page_id is not None and int(block.page_id) in gold_pages
    )
    gold_child_blocks = [
        block
        for block in blocks
        if block.page_id is not None and int(block.page_id) in gold_pages
    ]
    child_hit_blocks = [block for block in gold_child_blocks if answer_hit(block.retrieval_text, answers)]
    return {
        "available": True,
        "block_count": len(blocks),
        "page_block_count": len(page_blocks),
        "gold_page_child_block_count": len(gold_child_blocks),
        "gold_page_child_type_counts": dict(Counter(block.block_type for block in gold_child_blocks)),
        "gold_page_answer_hit": answer_hit(gold_text, answers),
        "gold_page_child_answer_hit_count": len(child_hit_blocks),
        "gold_page_answer_block_ids": [block.block_id for block in child_hit_blocks[:5]],
        "gold_page_text_char_count": len(gold_text),
        "gold_page_preview": text_preview(gold_text, answers),
        "resource_stats": block_resource_stats(blocks),
    }


def full_markdown_stats(mineru_dir: Path, answers: list[str]) -> dict[str, Any]:
    candidates = sorted(mineru_dir.rglob("full.md"))
    if not candidates:
        return {"path": "", "exists": False}
    path = candidates[0]
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    return {
        "path": safe_relpath(path),
        "exists": True,
        "char_count": len(text),
        "answer_hit": answer_hit(text, answers),
        "preview": text_preview(text, answers),
    }


def find_content_list(mineru_dir: Path, *, v2: bool = False) -> Path | None:
    for path in sorted(mineru_dir.rglob("*content_list*.json")):
        is_v2 = path.name.endswith("_content_list_v2.json") or path.name == "content_list_v2.json"
        if is_v2 == v2:
            return path
    return None


def manifest_stats(mineru_dir: Path) -> dict[str, Any]:
    path = mineru_dir / "mineru_api_manifest.json"
    payload = load_json(path)
    parse_options = payload.get("parse_options") if isinstance(payload.get("parse_options"), dict) else {}
    submission = payload.get("submission_payload") if isinstance(payload.get("submission_payload"), dict) else {}
    files = submission.get("files") if isinstance(submission.get("files"), list) else []
    first_file = files[0] if files and isinstance(files[0], dict) else {}
    return {
        "path": safe_relpath(path),
        "exists": path.is_file(),
        "status": payload.get("status") or "",
        "model_version": parse_options.get("model_version") or payload.get("model_version") or "",
        "parse_options_is_ocr": parse_options.get("is_ocr"),
        "submission_file_is_ocr": first_file.get("is_ocr"),
        "api_attempt_count": payload.get("api_attempt_count"),
        "retry_error_count": len(payload.get("retry_errors") or []),
        "result_zip_size": payload.get("result_zip_size"),
    }


def db_page_stats(
    *,
    repository: DocumentRepository | None,
    ingested_doc_id: str,
    gold_pages: set[int],
    answers: list[str],
) -> dict[str, Any]:
    if repository is None or not ingested_doc_id:
        return {"db_available": repository is not None, "block_count": 0}
    blocks = repository.load_evidence_blocks(ingested_doc_id, include_page_blocks=True)
    page_texts = [
        block.retrieval_text
        for block in blocks
        if block.block_type == "page" and block.page_id is not None and int(block.page_id) in gold_pages
    ]
    child_blocks = [
        block
        for block in blocks
        if block.block_type != "page" and block.page_id is not None and int(block.page_id) in gold_pages
    ]
    gold_text = "\n".join(page_texts)
    return {
        "db_available": True,
        "block_count": len(blocks),
        "page_block_count": sum(1 for block in blocks if block.block_type == "page"),
        "gold_page_text_char_count": len(gold_text),
        "gold_page_answer_hit": answer_hit(gold_text, answers),
        "gold_page_child_block_count": len(child_blocks),
        "gold_page_child_type_counts": dict(Counter(block.block_type for block in child_blocks)),
        "gold_page_preview": text_preview(gold_text, answers),
        "resource_stats": block_resource_stats([block for block in blocks if block.block_type != "page"]),
    }


def aggregate_resource_stats(rows: list[dict[str, Any]], section: str) -> dict[str, Any]:
    key_counts: Counter[str] = Counter()
    total = 0
    remote = 0
    local_existing = 0
    local_missing = 0
    unknown = 0
    raw_item_count = 0
    for row in rows:
        stats = ((row.get(section) or {}).get("resource_stats") or {})
        if section == "ordinary_content_list":
            total += int(stats.get("raw_resource_reference_count") or 0)
            remote += int(stats.get("raw_remote_resource_reference_count") or 0)
            local_existing += int(stats.get("raw_local_resource_reference_count") or 0)
            raw_item_count += int(stats.get("raw_resource_item_count") or 0)
            key_counts.update(stats.get("raw_resource_key_counts") or {})
        else:
            total += int(stats.get("resource_reference_count") or 0)
            remote += int(stats.get("remote_resource_reference_count") or 0)
            local_existing += int(stats.get("local_existing_resource_reference_count") or 0)
            local_missing += int(stats.get("local_missing_resource_reference_count") or 0)
            unknown += int(stats.get("unknown_resource_existence_count") or 0)
            key_counts.update(stats.get("resource_key_counts") or {})
    return {
        "resource_item_count": raw_item_count,
        "resource_reference_count": total,
        "remote_resource_reference_count": remote,
        "local_existing_resource_reference_count": local_existing,
        "local_missing_resource_reference_count": local_missing,
        "unknown_resource_existence_count": unknown,
        "resource_key_counts": dict(sorted(key_counts.items())),
    }


def diagnostic_bucket(row: dict[str, Any]) -> str:
    if not row["mineru_dir_exists"]:
        return "mineru_output_missing"
    manifest = row["mineru_manifest"]
    if manifest.get("parse_options_is_ocr") is False or manifest.get("submission_file_is_ocr") is False:
        return "mineru_ocr_disabled_or_uncertain"
    ordinary = row["ordinary_content_list"]
    full_md = row["full_md"]
    converted = row.get("converted_evidence", {})
    db = row["db_evidence"]
    if ordinary.get("gold_page_answer_hit") and not converted.get("gold_page_answer_hit"):
        return "raw_content_list_gold_page_has_answer_but_converter_missing"
    if converted.get("gold_page_answer_hit") and not db.get("gold_page_answer_hit"):
        return "converted_gold_page_has_answer_but_db_missing"
    if ordinary.get("gold_page_answer_hit") and not db.get("gold_page_answer_hit"):
        return "raw_content_list_gold_page_has_answer_but_db_missing"
    if full_md.get("answer_hit") and not ordinary.get("any_page_answer_hit"):
        return "markdown_has_answer_but_content_list_missing"
    if ordinary.get("any_page_answer_hit") and not ordinary.get("gold_page_answer_hit"):
        return "raw_mineru_answer_on_non_gold_page"
    if db.get("gold_page_answer_hit"):
        return "db_gold_page_has_answer"
    if full_md.get("answer_hit") or ordinary.get("any_page_answer_hit"):
        return "raw_mineru_has_answer_but_gold_page_or_conversion_mismatch"
    return "raw_mineru_answer_not_found"


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [row for row in read_jsonl(path) if isinstance(row, dict)]


def selected_sample_rows(rows: list[dict[str, Any]], sample_ids: set[str], max_samples: int | None) -> list[dict[str, Any]]:
    selected = [row for row in rows if not sample_ids or str(row.get("sample_id") or "") in sample_ids]
    if max_samples is not None:
        selected = selected[: max(0, int(max_samples))]
    return selected


def audit_row(
    sample: dict[str, Any],
    *,
    document_rows_by_doc: dict[str, dict[str, Any]],
    document_root: Path | None,
    repository: DocumentRepository | None,
) -> dict[str, Any]:
    doc_id = str(sample.get("doc_id") or "")
    document_row = document_rows_by_doc.get(doc_id, {})
    ingested_doc_id = str(sample.get("ingested_doc_id") or document_row.get("ingested_doc_id") or "")
    answers = [str(item) for item in as_list(sample.get("answers")) if str(item)]
    gold_pages = {int(page) for page in sample.get("gold_pages") or [] if str(page).isdigit()}
    mineru_dir = document_root / ingested_doc_id / "mineru" if document_root is not None and ingested_doc_id else None
    mineru_dir_exists = bool(mineru_dir and mineru_dir.is_dir())
    ordinary_path = find_content_list(mineru_dir) if mineru_dir_exists else None
    ordinary = content_list_stats(ordinary_path, answers, gold_pages)
    v2 = content_list_stats(find_content_list(mineru_dir, v2=True) if mineru_dir_exists else None, answers, gold_pages)
    row = {
        "sample_id": str(sample.get("sample_id") or ""),
        "doc_id": doc_id,
        "ingested_doc_id": ingested_doc_id,
        "source_document": str(sample.get("source_document") or ""),
        "question": str(sample.get("question") or ""),
        "answers": answers,
        "gold_pages": sorted(gold_pages),
        "mineru_dir": safe_relpath(mineru_dir),
        "mineru_dir_exists": mineru_dir_exists,
        "mineru_manifest": manifest_stats(mineru_dir) if mineru_dir_exists else {"exists": False},
        "ordinary_content_list": ordinary,
        "content_list_v2": v2,
        "converted_evidence": converted_evidence_stats(
            path=ordinary_path,
            ingested_doc_id=ingested_doc_id,
            mineru_dir=mineru_dir,
            answers=answers,
            gold_pages=gold_pages,
        ),
        "full_md": full_markdown_stats(mineru_dir, answers) if mineru_dir_exists else {"exists": False},
        "db_evidence": db_page_stats(
            repository=repository,
            ingested_doc_id=ingested_doc_id,
            gold_pages=gold_pages,
            answers=answers,
        ),
    }
    row["diagnostic_bucket"] = diagnostic_bucket(row)
    return row


def summarize(
    *,
    run_id: str,
    artifact_dir: Path,
    evidence_run_dir: Path,
    db_path: Path | None,
    rows: list[dict[str, Any]],
    missing: list[str],
) -> dict[str, Any]:
    buckets = Counter(row.get("diagnostic_bucket") for row in rows)
    raw_resources = aggregate_resource_stats(rows, "ordinary_content_list")
    converted_resources = aggregate_resource_stats(rows, "converted_evidence")
    db_resources = aggregate_resource_stats(rows, "db_evidence")
    return {
        "command": "audit_mineru_evidence_artifacts",
        "status": "failed" if missing else "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only" if not missing else "blocked",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "source_evidence_run_dir": safe_relpath(evidence_run_dir),
        "db_path": safe_relpath(db_path),
        "row_count": len(rows),
        "missing": missing,
        "bucket_counts": dict(sorted(buckets.items())),
        "manifest_ocr_enabled_or_requested_rate": rate(
            sum(
                1
                for row in rows
                if row.get("mineru_manifest", {}).get("parse_options_is_ocr") is True
                or row.get("mineru_manifest", {}).get("submission_file_is_ocr") is True
            ),
            len(rows),
        ),
        "ordinary_gold_page_answer_hit_rate": rate(
            sum(1 for row in rows if row.get("ordinary_content_list", {}).get("gold_page_answer_hit")),
            len(rows),
        ),
        "markdown_answer_hit_rate": rate(sum(1 for row in rows if row.get("full_md", {}).get("answer_hit")), len(rows)),
        "converted_gold_page_answer_hit_rate": rate(
            sum(1 for row in rows if row.get("converted_evidence", {}).get("gold_page_answer_hit")),
            len(rows),
        ),
        "db_gold_page_answer_hit_rate": rate(
            sum(1 for row in rows if row.get("db_evidence", {}).get("gold_page_answer_hit")),
            len(rows),
        ),
        "raw_resource_stats": raw_resources,
        "converted_resource_stats": converted_resources,
        "db_resource_stats": db_resources,
        "used_qwen": False,
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "recommendation": {
            "next_action": "rerun_mpdocvqa_evidence_with_mineru_ocr_if_raw_artifacts_show_ocr_disabled",
            "do_not_train_yet": True,
            "reason": (
                "This audit separates raw MinerU artifact availability from EvidenceBlock persistence. "
                "It does not call models, change retrieval, alter gold pages, or create training data."
            ),
        },
    }


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# MinerU Evidence Artifact Audit",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- row_count: {summary.get('row_count', 0)}",
        f"- manifest_ocr_enabled_or_requested_rate: {summary.get('manifest_ocr_enabled_or_requested_rate')}",
        f"- ordinary_gold_page_answer_hit_rate: {summary.get('ordinary_gold_page_answer_hit_rate')}",
        f"- markdown_answer_hit_rate: {summary.get('markdown_answer_hit_rate')}",
        f"- converted_gold_page_answer_hit_rate: {summary.get('converted_gold_page_answer_hit_rate')}",
        f"- db_gold_page_answer_hit_rate: {summary.get('db_gold_page_answer_hit_rate')}",
        f"- raw_resource_reference_count: {(summary.get('raw_resource_stats') or {}).get('resource_reference_count', 0)}",
        f"- converted_resource_reference_count: {(summary.get('converted_resource_stats') or {}).get('resource_reference_count', 0)}",
        f"- db_resource_reference_count: {(summary.get('db_resource_stats') or {}).get('resource_reference_count', 0)}",
        "",
        "## Buckets",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("bucket_counts") or {}).items())],
        "",
        "This is diagnostic only. It does not call Qwen, tune retrieval, change MP-DocVQA gold pages, or create training data.",
    ]
    if summary.get("missing"):
        lines.extend(["", "## Missing", "", *[f"- {item}" for item in summary["missing"]]])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files = []
    for artifact in artifact_paths:
        if artifact.is_file():
            files.append({"path": safe_relpath(artifact), "size_bytes": artifact.stat().st_size, "sha256": sha256_file(artifact)})
    write_json(path, {"run_id": run_id, "script_version": SCRIPT_VERSION, "files": files})


def sync_outputs(sync_dir: Path, paths: dict[str, Path]) -> None:
    sync_dir.mkdir(parents=True, exist_ok=True)
    for key in ("result", "summary", "summary_md", "preview", "manifest"):
        if paths[key].is_file():
            shutil.copy2(paths[key], sync_dir / paths[key].name)


def audit_mineru_evidence_artifacts(
    *,
    evidence_run_dir: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    db_path: Path | None = None,
    sample_ids: set[str] | None = None,
    max_samples: int | None = None,
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary_path = evidence_run_dir / "summary.json"
    evidence_summary = load_json(summary_path)
    documents_path = evidence_run_dir / "documents.jsonl"
    samples_path = evidence_run_dir / "sample_evidence_manifest.jsonl"
    document_root = repo_path(evidence_summary.get("document_root")) if evidence_summary.get("document_root") else None
    db_path = db_path or (repo_path(evidence_summary.get("db_path")) if evidence_summary.get("db_path") else None)

    missing = [
        safe_relpath(path)
        for path in (summary_path, documents_path, samples_path)
        if not path.is_file()
    ]
    if document_root is None or not document_root.is_dir():
        missing.append("document_root_missing")
    if db_path is None or not db_path.is_file():
        missing.append("db_path_missing")

    document_rows = load_rows(documents_path)
    sample_rows = selected_sample_rows(load_rows(samples_path), sample_ids or set(), max_samples)
    repository: DocumentRepository | None = None
    conn: sqlite3.Connection | None = None
    try:
        if db_path is not None and db_path.is_file():
            conn = connect(db_path)
            repository = DocumentRepository(conn)
        rows = [
            audit_row(
                sample,
                document_rows_by_doc={str(row.get("doc_id") or ""): row for row in document_rows},
                document_root=document_root,
                repository=repository,
            )
            for sample in sample_rows
        ]
    finally:
        if conn is not None:
            conn.close()

    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "rows": artifact_dir / "rows.jsonl",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }
    summary = summarize(
        run_id=run_id,
        artifact_dir=artifact_dir,
        evidence_run_dir=evidence_run_dir,
        db_path=db_path,
        rows=rows,
        missing=missing,
    )
    summary.update(
        {
            "summary_path": safe_relpath(paths["summary"]),
            "summary_markdown_path": safe_relpath(paths["summary_md"]),
            "rows_path": safe_relpath(paths["rows"]),
            "preview_path": safe_relpath(paths["preview"]),
            "manifest_path": safe_relpath(paths["manifest"]),
            "artifact_paths": [safe_relpath(path) for path in paths.values()],
        }
    )
    result = {
        "command": summary["command"],
        "status": summary["status"],
        "run_id": run_id,
        "row_count": len(rows),
        "bucket_counts": summary["bucket_counts"],
        "manifest_ocr_enabled_or_requested_rate": summary["manifest_ocr_enabled_or_requested_rate"],
        "ordinary_gold_page_answer_hit_rate": summary["ordinary_gold_page_answer_hit_rate"],
        "markdown_answer_hit_rate": summary["markdown_answer_hit_rate"],
        "converted_gold_page_answer_hit_rate": summary["converted_gold_page_answer_hit_rate"],
        "db_gold_page_answer_hit_rate": summary["db_gold_page_answer_hit_rate"],
        "raw_resource_stats": summary["raw_resource_stats"],
        "converted_resource_stats": summary["converted_resource_stats"],
        "db_resource_stats": summary["db_resource_stats"],
        "recommendation": summary["recommendation"],
        "artifact_paths": summary["artifact_paths"],
        "used_training": False,
        "formal_benchmark_acceptance": False,
    }
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_jsonl(paths["rows"], rows)
    write_json(paths["preview"], rows[:12])
    write_json(paths["result"], result)
    write_manifest(paths["manifest"], run_id=run_id, artifact_paths=list(paths.values()))
    if sync_output_root is not None:
        sync_dir = sync_output_root / run_id
        summary["sync_bundle_path"] = safe_relpath(sync_dir)
        result["sync_bundle_path"] = safe_relpath(sync_dir)
        write_json(paths["summary"], summary)
        write_json(paths["result"], result)
        sync_outputs(sync_dir, paths)
    return {**result, **summary}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit MinerU raw artifacts against persisted EvidenceBlocks.")
    parser.add_argument("--evidence-run-dir", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--db-path")
    parser.add_argument("--sample-ids", default="")
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--sync-output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    sample_ids = {item.strip() for item in str(args.sample_ids or "").split(",") if item.strip()}
    result = audit_mineru_evidence_artifacts(
        evidence_run_dir=repo_path(args.evidence_run_dir) or Path(args.evidence_run_dir),
        output_root=repo_path(args.output_dir) or Path(args.output_dir),
        run_id=args.run_id,
        db_path=repo_path(args.db_path),
        sample_ids=sample_ids,
        max_samples=args.max_samples,
        sync_output_root=repo_path(args.sync_output_dir) if args.sync_output_dir else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

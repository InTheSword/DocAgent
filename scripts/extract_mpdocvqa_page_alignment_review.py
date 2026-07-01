from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.inspect_mpdocvqa_ocr_page_alignment import page_text
from scripts.inspect_mpdocvqa_page_index_alignment import load_document_manifests, source_page_id_for_ordinal
from scripts.inspect_mpdocvqa_retrieval import as_int_set, as_str_list, load_blocks


SCRIPT_VERSION = "mpdocvqa-page-alignment-manual-review-v1"
EVALUATION_SCOPE = "mpdocvqa_page_alignment_manual_review_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_page_alignment_manual_review"
DEFAULT_SUBSET_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_val_subset"
REVIEW_BUCKETS = {
    "answer_on_gold_minus_one_page",
    "answer_on_gold_plus_one_page",
    "answer_elsewhere_in_document",
    "answer_not_found_in_document_text",
    "gold_page_without_retrievable_blocks",
}


def repo_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def safe_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"mpdocvqa_page_alignment_manual_review_{stamp}"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
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
            end = min(len(normalized), start + max_chars)
            return normalized[start:end]
    return normalized[:max_chars]


def page_ordinals(values: Any) -> list[int]:
    return sorted(as_int_set(values))


def document_pdf_path(subset_root: Path, document_manifest: dict[str, Any]) -> dict[str, Any]:
    pdf_value = str(document_manifest.get("pdf_path") or "")
    if not pdf_value:
        return {"path": "", "exists": False}
    pdf_path = subset_root / pdf_value
    return {"path": safe_relpath(pdf_path), "exists": pdf_path.is_file()}


def page_file_for_ordinal(subset_root: Path, document_manifest: dict[str, Any], page: int) -> Path | None:
    for item in document_manifest.get("pages") or []:
        if not isinstance(item, dict):
            continue
        try:
            ordinal = int(item.get("page_ordinal"))
        except (TypeError, ValueError):
            continue
        if ordinal != page:
            continue
        page_file = str(item.get("page_file") or "")
        return subset_root / page_file if page_file else None
    ordered = document_manifest.get("ordered_page_files") or []
    if isinstance(ordered, list) and 1 <= page <= len(ordered):
        return subset_root / str(ordered[page - 1])
    return None


def page_review_record(
    *,
    subset_root: Path,
    document_manifest: dict[str, Any],
    block_by_id: dict[str, Any],
    page: int,
    answers: list[str],
    role: str,
) -> dict[str, Any]:
    page_file = page_file_for_ordinal(subset_root, document_manifest, page)
    text = page_text(block_by_id, {page}) if block_by_id else ""
    page_file_path = safe_relpath(page_file) if page_file is not None else ""
    return {
        "role": role,
        "page": page,
        "source_page_id": source_page_id_for_ordinal(document_manifest, page),
        "page_file": page_file_path,
        "page_file_exists": bool(page_file and page_file.is_file()),
        "ocr_text_preview": text_preview(text, answers),
        "ocr_text_char_count": len(text),
    }


def adjacent_pages(page: int, page_count: int | None) -> list[int]:
    pages = [page - 1, page + 1]
    if page_count is not None:
        pages = [value for value in pages if 1 <= value <= page_count]
    else:
        pages = [value for value in pages if value >= 1]
    return pages


def review_bucket(row: dict[str, Any]) -> str:
    bucket = str(row.get("page_index_bucket") or "")
    if bucket in {"answer_on_gold_minus_one_page", "answer_on_gold_plus_one_page"}:
        return "manual_compare_gold_and_adjacent_page_images"
    if bucket == "answer_elsewhere_in_document":
        return "manual_check_gold_annotation_or_duplicate_answer"
    if bucket == "answer_not_found_in_document_text":
        return "manual_check_ocr_text_or_answer_alias"
    if bucket == "gold_page_without_retrievable_blocks":
        return "manual_check_mineru_page_block_materialization"
    return "manual_review_unclassified"


def review_pages(row: dict[str, Any], document_manifest: dict[str, Any]) -> list[tuple[int, str]]:
    page_count = None
    try:
        page_count = int(document_manifest.get("page_count"))
    except (TypeError, ValueError):
        page_count = None
    pages: list[tuple[int, str]] = []
    for page in page_ordinals(row.get("alignment_gold_pages") or []):
        pages.append((page, "gold_page"))
        for adjacent in adjacent_pages(page, page_count):
            pages.append((adjacent, "adjacent_to_gold_page"))
    for page in page_ordinals(row.get("answer_hit_pages") or []):
        pages.append((page, "answer_hit_page"))
    seen: set[int] = set()
    unique: list[tuple[int, str]] = []
    for page, role in pages:
        if page in seen:
            continue
        seen.add(page)
        unique.append((page, role))
    return unique


def load_page_index_rows(run_dir: Path) -> tuple[list[dict[str, Any]], str]:
    rows_path = run_dir / "rows.jsonl"
    if not rows_path.is_file():
        return [], ""
    return [row for row in read_jsonl(rows_path) if isinstance(row, dict)], safe_relpath(rows_path)


def extract_review_row(
    row: dict[str, Any],
    *,
    subset_root: Path,
    document_manifests_by_doc: dict[str, dict[str, Any]],
    blocks_by_doc: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    doc_id = str(row.get("doc_id") or "")
    ingested_doc_id = str(row.get("ingested_doc_id") or "")
    document_manifest = document_manifests_by_doc.get(doc_id, {})
    block_by_id = blocks_by_doc.get(ingested_doc_id, {})
    answers = as_str_list(row.get("answers") or [])
    pages = [
        page_review_record(
            subset_root=subset_root,
            document_manifest=document_manifest,
            block_by_id=block_by_id,
            page=page,
            answers=answers,
            role=role,
        )
        for page, role in review_pages(row, document_manifest)
    ]
    return {
        "sample_id": str(row.get("sample_id") or ""),
        "doc_id": doc_id,
        "ingested_doc_id": ingested_doc_id,
        "source_document": str(row.get("source_document") or ""),
        "question": str(row.get("question") or ""),
        "answers": answers,
        "page_index_bucket": str(row.get("page_index_bucket") or ""),
        "review_bucket": review_bucket(row),
        "document_pdf": document_pdf_path(subset_root, document_manifest),
        "document_window_page_count": row.get("document_window_page_count"),
        "document_window_ordered_page_ids": row.get("document_window_ordered_page_ids") or [],
        "alignment_gold_pages": page_ordinals(row.get("alignment_gold_pages") or []),
        "answer_hit_pages": page_ordinals(row.get("answer_hit_pages") or []),
        "current_gold_source_page_ids": row.get("current_gold_source_page_ids") or [],
        "answer_hit_source_page_ids": row.get("answer_hit_source_page_ids") or [],
        "qa_answer_page_idx": row.get("qa_answer_page_idx"),
        "qa_gold_page_ordinal": row.get("qa_gold_page_ordinal"),
        "qa_gold_page_id": str(row.get("qa_gold_page_id") or ""),
        "answer_page_minus_alignment_gold_page_delta": row.get("answer_page_minus_alignment_gold_page_delta"),
        "mapping_consistency": {
            "qa_ordinal_minus_answer_idx": row.get("qa_ordinal_minus_answer_idx"),
            "final_manifest_minus_qa_gold_page_delta": row.get("final_manifest_minus_qa_gold_page_delta"),
            "sample_evidence_minus_manifest_gold_page_delta": row.get(
                "sample_evidence_minus_manifest_gold_page_delta"
            ),
        },
        "page_reviews": pages,
        "manual_review_instruction": "Compare the listed page images and OCR previews. Do not change MP-DocVQA page mapping unless the manifest fields disagree; otherwise classify the issue as OCR/text-match, duplicate answer text, or evidence-block materialization.",
    }


def should_review(row: dict[str, Any]) -> bool:
    return str(row.get("page_index_bucket") or "") in REVIEW_BUCKETS


def recommendation(summary: dict[str, Any], review_count: int) -> dict[str, Any]:
    source_recommendation = summary.get("recommendation") or {}
    if review_count:
        next_action = "manual_check_page_alignment_review_rows_before_retrieval_changes"
    else:
        next_action = "continue_mpdocvqa_retrieval_diagnostics_before_training"
    return {
        "next_action": next_action,
        "do_not_train_yet": True,
        "reason": (
            "The page-index audit found internally consistent MP-DocVQA window-page mappings. "
            "This extraction prepares manual/OCR review rows only; it does not repair gold pages, "
            "change retrieval, call models, or create training data."
        ),
        "source_next_action": source_recommendation.get("next_action"),
    }


def extract_mpdocvqa_page_alignment_review(
    *,
    page_index_run_dir: Path,
    subset_root: Path,
    mpdocvqa_db_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_summary = load_json(page_index_run_dir / "summary.json")
    source_result = load_json(page_index_run_dir / "result.json")
    source_rows, source_rows_path = load_page_index_rows(page_index_run_dir)
    missing = [
        safe_relpath(path)
        for path in (page_index_run_dir / "summary.json", page_index_run_dir / "result.json", mpdocvqa_db_path)
        if not path.is_file()
    ]
    if not source_rows_path:
        missing.append("rows.jsonl")
    documents_jsonl = subset_root / "documents.jsonl"
    if not documents_jsonl.is_file():
        missing.append(safe_relpath(documents_jsonl))
    if missing:
        summary = {
            "command": "extract_mpdocvqa_page_alignment_review",
            "status": "failed",
            "quality_status": "blocked",
            "run_id": run_id,
            "artifact_dir": safe_relpath(artifact_dir),
            "missing": missing,
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
        return write_outputs(artifact_dir=artifact_dir, summary=summary, review_rows=[], sync_output_root=sync_output_root)

    review_source_rows = [row for row in source_rows if should_review(row)]
    document_manifests_by_doc = load_document_manifests(subset_root)
    blocks_by_doc, db_available = load_blocks(review_source_rows, mpdocvqa_db_path)
    review_rows = [
        extract_review_row(
            row,
            subset_root=subset_root,
            document_manifests_by_doc=document_manifests_by_doc,
            blocks_by_doc=blocks_by_doc,
        )
        for row in review_source_rows
    ]
    bucket_counts = Counter(row["review_bucket"] for row in review_rows)
    page_index_bucket_counts = Counter(row["page_index_bucket"] for row in review_rows)
    source_run_id = str(source_summary.get("run_id") or source_result.get("run_id") or page_index_run_dir.name)
    summary = {
        "command": "extract_mpdocvqa_page_alignment_review",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "source_run_id": source_run_id,
        "source_run_dir": safe_relpath(page_index_run_dir),
        "source_rows_path": source_rows_path,
        "subset_root": safe_relpath(subset_root),
        "mpdocvqa_db_path": safe_relpath(mpdocvqa_db_path),
        "mpdocvqa_db_available": db_available,
        "source_inspected_count": len(source_rows),
        "review_row_count": len(review_rows),
        "review_bucket_counts": dict(sorted(bucket_counts.items())),
        "page_index_bucket_counts": dict(sorted(page_index_bucket_counts.items())),
        "source_page_index_mapping_rates": {
            "qa_gold_page_ordinal_consistent_with_answer_page_idx_rate": source_summary.get(
                "qa_gold_page_ordinal_consistent_with_answer_page_idx_rate"
            ),
            "manifest_consistent_with_qa_gold_page_rate": source_summary.get(
                "manifest_consistent_with_qa_gold_page_rate"
            ),
            "sample_evidence_consistent_with_manifest_gold_page_rate": source_summary.get(
                "sample_evidence_consistent_with_manifest_gold_page_rate"
            ),
        },
        "page_file_exists_rate": rate(
            sum(1 for row in review_rows for page in row["page_reviews"] if page.get("page_file_exists")),
            sum(1 for row in review_rows for page in row["page_reviews"]),
        ),
        "used_qwen": bool(source_summary.get("used_qwen", True)),
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "recommendation": recommendation(source_summary, len(review_rows)),
    }
    return write_outputs(
        artifact_dir=artifact_dir,
        summary=summary,
        review_rows=review_rows,
        sync_output_root=sync_output_root,
    )


def write_outputs(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
    review_rows: list[dict[str, Any]],
    sync_output_root: Path | None,
) -> dict[str, Any]:
    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "manual_review": artifact_dir / "manual_review.jsonl",
        "manual_review_md": artifact_dir / "manual_review.md",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }
    summary.update(
        {
            "summary_path": safe_relpath(paths["summary"]),
            "summary_markdown_path": safe_relpath(paths["summary_md"]),
            "manual_review_path": safe_relpath(paths["manual_review"]),
            "manual_review_markdown_path": safe_relpath(paths["manual_review_md"]),
            "preview_path": safe_relpath(paths["preview"]),
            "manifest_path": safe_relpath(paths["manifest"]),
        }
    )
    result = {
        "command": summary["command"],
        "status": summary["status"],
        "run_id": summary["run_id"],
        "artifact_dir": summary["artifact_dir"],
        "quality_status": summary["quality_status"],
        "review_row_count": summary.get("review_row_count", 0),
        "review_bucket_counts": summary.get("review_bucket_counts", {}),
        "page_index_bucket_counts": summary.get("page_index_bucket_counts", {}),
        "source_page_index_mapping_rates": summary.get("source_page_index_mapping_rates", {}),
        "recommendation": summary.get("recommendation", {}),
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    preview = review_rows[:12]
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_jsonl(paths["manual_review"], review_rows)
    write_manual_review_markdown(paths["manual_review_md"], review_rows)
    write_json(paths["preview"], preview)
    write_json(paths["result"], result)
    write_manifest(paths["manifest"], run_id=str(summary["run_id"]), artifact_paths=list(paths.values()))
    if sync_output_root is not None:
        sync_bundle_path = safe_relpath(sync_output_root / str(summary["run_id"]))
        summary["sync_bundle_path"] = sync_bundle_path
        result["sync_bundle_path"] = sync_bundle_path
        write_json(paths["summary"], summary)
        write_json(paths["result"], result)
        sync_outputs(sync_output_root / str(summary["run_id"]), paths)
    return {**result, **summary, "artifact_paths": [safe_relpath(path) for path in paths.values()]}


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    recommendation_payload = summary.get("recommendation") or {}
    lines = [
        "# MP-DocVQA Page Alignment Manual Review",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- source_run_id: `{summary.get('source_run_id')}`",
        f"- review_row_count: {summary.get('review_row_count', 0)}",
        f"- page_file_exists_rate: {summary.get('page_file_exists_rate', 0.0)}",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary.get('validation_subset_used_for_training')).lower()}`",
        "",
        "## Review Buckets",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("review_bucket_counts") or {}).items())],
        "",
        "## Page-Index Buckets",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("page_index_bucket_counts") or {}).items())],
        "",
        "## Recommendation",
        "",
        f"- next_action: `{recommendation_payload.get('next_action')}`",
        f"- do_not_train_yet: `{str(recommendation_payload.get('do_not_train_yet')).lower()}`",
        f"- reason: {recommendation_payload.get('reason')}",
        "",
        "This extraction is diagnostic only. It does not call models, start training, change gold pages, or tune retrieval.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manual_review_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Manual Review Rows",
        "",
        "Use these rows to compare the current input-document page images with OCR previews. Page numbers are window-PDF pages, not printed page labels.",
        "",
    ]
    for row in rows:
        lines.extend(
            [
                f"## {row.get('sample_id')}",
                "",
                f"- bucket: `{row.get('review_bucket')}` / `{row.get('page_index_bucket')}`",
                f"- doc_id: `{row.get('doc_id')}`",
                f"- question: {row.get('question')}",
                f"- answers: {row.get('answers')}",
                f"- document_pdf: `{(row.get('document_pdf') or {}).get('path')}`",
                f"- gold_pages: {row.get('alignment_gold_pages')} -> {row.get('current_gold_source_page_ids')}",
                f"- answer_hit_pages: {row.get('answer_hit_pages')} -> {row.get('answer_hit_source_page_ids')}",
                "",
                "Pages:",
            ]
        )
        for page in row.get("page_reviews") or []:
            lines.extend(
                [
                    f"- page {page.get('page')} `{page.get('source_page_id')}` ({page.get('role')}): `{page.get('page_file')}`",
                    f"  - OCR: {page.get('ocr_text_preview')}",
                ]
            )
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files: list[dict[str, Any]] = []
    for artifact in artifact_paths:
        if not artifact.is_file():
            continue
        files.append({"path": safe_relpath(artifact), "size_bytes": artifact.stat().st_size, "sha256": sha256_file(artifact)})
    write_json(path, {"run_id": run_id, "script_version": SCRIPT_VERSION, "files": files})


def sync_outputs(sync_dir: Path, paths: dict[str, Path]) -> None:
    sync_dir.mkdir(parents=True, exist_ok=True)
    for key in ("result", "summary", "summary_md", "manual_review_md", "preview", "manifest"):
        if paths[key].is_file():
            shutil.copy2(paths[key], sync_dir / paths[key].name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Extract MP-DocVQA page-alignment manual review rows.")
    parser.add_argument("--page-index-run-dir", required=True, help="Page-index alignment inspection artifact directory.")
    parser.add_argument("--subset-root", default=str(DEFAULT_SUBSET_ROOT), help="Prepared MP-DocVQA subset root.")
    parser.add_argument("--mpdocvqa-db-path", required=True, help="SQLite DB with MP-DocVQA EvidenceBlocks.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--sync-output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = extract_mpdocvqa_page_alignment_review(
        page_index_run_dir=repo_path(args.page_index_run_dir) or Path(args.page_index_run_dir),
        subset_root=repo_path(args.subset_root) or Path(args.subset_root),
        mpdocvqa_db_path=repo_path(args.mpdocvqa_db_path) or Path(args.mpdocvqa_db_path),
        output_root=repo_path(args.output_dir) or Path(args.output_dir),
        run_id=args.run_id,
        sync_output_root=repo_path(args.sync_output_dir) if args.sync_output_dir else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

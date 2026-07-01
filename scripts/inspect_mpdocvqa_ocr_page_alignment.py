from __future__ import annotations

import argparse
import hashlib
import json
import re
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
from scripts.inspect_mpdocvqa_retrieval import as_int_set, as_str_list, block_page, block_retrieval_text, load_blocks
from scripts.run_final_eval_subset import normalize_text, parse_number


SCRIPT_VERSION = "mpdocvqa-ocr-page-alignment-inspect-v1"
EVALUATION_SCOPE = "mpdocvqa_ocr_page_alignment_inspection_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_ocr_page_alignment_inspect"


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
    return f"mpdocvqa_ocr_page_alignment_inspect_{stamp}"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_rows(run_dir: Path) -> tuple[list[dict[str, Any]], str, str]:
    path = run_dir / "rows.jsonl"
    if path.is_file():
        return [row for row in read_jsonl(path) if isinstance(row, dict)], "alignment_source_rows", safe_relpath(path)
    return [], "missing", ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def page_text(block_by_id: dict[str, Any], pages: set[int]) -> str:
    texts: list[str] = []
    for block in block_by_id.values():
        if block_page(block) in pages:
            text = block_retrieval_text(block)
            if text:
                texts.append(text)
    return "\n".join(texts)


def document_pages(block_by_id: dict[str, Any]) -> set[int]:
    pages: set[int] = set()
    for block in block_by_id.values():
        page = block_page(block)
        if page is not None:
            pages.add(page)
    return pages


def page_has_retrievable_text(block_by_id: dict[str, Any], page: int) -> bool:
    for block in block_by_id.values():
        if block_page(block) == page and getattr(block, "block_type", "") != "page" and block_retrieval_text(block):
            return True
    return False


def numeric_values(text: str) -> list[float]:
    values: list[float] = []
    for match in re.finditer(r"\(?-?\$?\d[\d,]*(?:\.\d+)?%?\)?", text):
        value = parse_number(match.group(0))
        if value is not None:
            values.append(value)
    return values


def numeric_answer_hit(text: str, answers: list[str]) -> bool:
    expected = [parse_number(answer) for answer in answers]
    expected = [value for value in expected if value is not None]
    if not expected:
        return False
    observed = numeric_values(text)
    for expected_value in expected:
        tolerance = max(0.01, 0.001 * abs(expected_value))
        if any(abs(value - expected_value) <= tolerance for value in observed):
            return True
    return False


def answer_hit(text: str, answers: list[str]) -> bool:
    normalized = normalize_text(text)
    exact_hit = any(answer and normalize_text(answer) in normalized for answer in answers)
    return exact_hit or numeric_answer_hit(text, answers)


def answer_hit_pages(block_by_id: dict[str, Any], answers: list[str]) -> list[int]:
    pages: list[int] = []
    for page in sorted(document_pages(block_by_id)):
        if answer_hit(page_text(block_by_id, {page}), answers):
            pages.append(page)
    return pages


def shifted_pages(gold_pages: set[int], delta: int, available_pages: set[int]) -> set[int]:
    return {page + delta for page in gold_pages if page + delta in available_pages}


def min_page_distance(gold_pages: set[int], pages: list[int]) -> int | None:
    if not gold_pages or not pages:
        return None
    return min(abs(page - gold_page) for page in pages for gold_page in gold_pages)


def alignment_bucket(
    *,
    gold_pages: set[int],
    available_pages: set[int],
    hit_pages: list[int],
    gold_retrievable_pages: list[int],
) -> str:
    hit_set = set(hit_pages)
    if gold_pages and hit_set.intersection(gold_pages):
        return "answer_on_gold_page"
    if hit_set.intersection(shifted_pages(gold_pages, -1, available_pages)):
        return "answer_on_gold_minus_one_page"
    if hit_set.intersection(shifted_pages(gold_pages, 1, available_pages)):
        return "answer_on_gold_plus_one_page"
    if hit_pages:
        return "answer_elsewhere_in_document"
    if not gold_retrievable_pages:
        return "gold_page_without_retrievable_blocks"
    return "answer_not_found_in_document_text"


def inspect_row(row: dict[str, Any], blocks_by_doc: dict[str, dict[str, Any]], index: int) -> dict[str, Any]:
    ingested_doc_id = str(row.get("ingested_doc_id") or "")
    block_by_id = blocks_by_doc.get(ingested_doc_id, {})
    gold_pages = as_int_set(row.get("gold_pages") or [])
    retrieved_pages = as_int_set(row.get("retrieved_pages") or [])
    selected_pages = as_int_set(row.get("selected_pages") or [])
    citation_pages = as_int_set(row.get("citation_pages") or [])
    answers = as_str_list(row.get("answers") or [])
    pages = document_pages(block_by_id)
    hit_pages = answer_hit_pages(block_by_id, answers)
    hit_page_set = set(hit_pages)
    gold_retrievable_pages = [page for page in sorted(gold_pages) if page_has_retrievable_text(block_by_id, page)]
    bucket = alignment_bucket(
        gold_pages=gold_pages,
        available_pages=pages,
        hit_pages=hit_pages,
        gold_retrievable_pages=gold_retrievable_pages,
    )
    return {
        "source_row_index": index,
        "source_run_id": str(row.get("source_run_id") or ""),
        "sample_id": str(row.get("sample_id") or ""),
        "doc_id": str(row.get("doc_id") or ""),
        "ingested_doc_id": ingested_doc_id,
        "source_document": str(row.get("source_document") or ""),
        "row_bucket": str(row.get("row_bucket") or row.get("bucket") or ""),
        "source_diagnostic_bucket": str(row.get("diagnostic_bucket") or ""),
        "alignment_bucket": bucket,
        "question": str(row.get("question") or ""),
        "answers": answers,
        "gold_pages": sorted(gold_pages),
        "retrieved_pages": sorted(retrieved_pages),
        "selected_pages": sorted(selected_pages),
        "citation_pages": sorted(citation_pages),
        "answer_hit_pages": hit_pages,
        "retrieved_answer_page_hit": bool(hit_page_set and hit_page_set.intersection(retrieved_pages)),
        "selected_answer_page_hit": bool(hit_page_set and hit_page_set.intersection(selected_pages)),
        "citation_answer_page_hit": bool(hit_page_set and hit_page_set.intersection(citation_pages)),
        "gold_minus_one_pages": sorted(shifted_pages(gold_pages, -1, pages)),
        "gold_plus_one_pages": sorted(shifted_pages(gold_pages, 1, pages)),
        "gold_retrievable_pages": gold_retrievable_pages,
        "min_answer_page_distance_from_gold": min_page_distance(gold_pages, hit_pages),
        "available_page_count": len(pages),
        "gold_page_text_preview": page_text(block_by_id, gold_pages)[:400],
        "first_answer_page_text_preview": page_text(block_by_id, {hit_pages[0]})[:400] if hit_pages else "",
    }


def recommendation(bucket_counts: Counter[str]) -> dict[str, Any]:
    if bucket_counts.get("answer_on_gold_minus_one_page", 0) or bucket_counts.get("answer_on_gold_plus_one_page", 0):
        next_action = "inspect_mpdocvqa_page_index_alignment_before_retrieval_changes"
    elif bucket_counts.get("answer_elsewhere_in_document", 0):
        next_action = "inspect_mpdocvqa_gold_page_mapping_before_retrieval_changes"
    elif bucket_counts.get("gold_page_without_retrievable_blocks", 0):
        next_action = "inspect_mineru_page_block_text_before_training"
    elif bucket_counts.get("answer_not_found_in_document_text", 0):
        next_action = "inspect_ocr_answer_text_availability_before_training"
    else:
        next_action = "continue_retrieval_diagnostics_before_training"
    return {
        "next_action": next_action,
        "do_not_train_yet": True,
        "reason": "This inspection checks answer text page alignment in existing MP-DocVQA EvidenceBlocks only; it does not call models, create training data, or tune against validation examples.",
    }


def inspect_mpdocvqa_ocr_page_alignment(
    *,
    run_dir: Path,
    mpdocvqa_db_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_summary = load_json(run_dir / "summary.json")
    source_result = load_json(run_dir / "result.json")
    rows, rows_scope, rows_path = load_rows(run_dir)
    missing = [safe_relpath(path) for path in (run_dir / "summary.json", run_dir / "result.json") if not path.is_file()]
    if rows_scope == "missing":
        missing.append("rows.jsonl")
    if not mpdocvqa_db_path.is_file():
        missing.append(safe_relpath(mpdocvqa_db_path))
    if missing:
        summary = {
            "command": "inspect_mpdocvqa_ocr_page_alignment",
            "status": "failed",
            "quality_status": "blocked",
            "run_id": run_id,
            "artifact_dir": safe_relpath(artifact_dir),
            "missing": missing,
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
        return write_outputs(artifact_dir=artifact_dir, summary=summary, rows=[], preview=[], sync_output_root=sync_output_root)

    target_rows = [
        row
        for row in rows
        if str(row.get("row_bucket") or "") == "retrieval_gold_page_miss"
        and str(row.get("diagnostic_bucket") or "")
        in {"gold_page_answer_text_not_found", "gold_page_without_retrievable_blocks"}
        and str(row.get("ingested_doc_id") or "")
    ]
    blocks_by_doc, db_available = load_blocks(target_rows, mpdocvqa_db_path)
    inspected_rows = [inspect_row(row, blocks_by_doc, index) for index, row in enumerate(target_rows)]
    bucket_counts = Counter(str(row.get("alignment_bucket") or "") for row in inspected_rows)
    source_run_id = str(source_summary.get("run_id") or source_result.get("run_id") or run_dir.name)
    answer_found_count = sum(1 for row in inspected_rows if row.get("answer_hit_pages"))
    adjacent_count = bucket_counts.get("answer_on_gold_minus_one_page", 0) + bucket_counts.get("answer_on_gold_plus_one_page", 0)
    retrieved_answer_page_hit_count = sum(1 for row in inspected_rows if row.get("retrieved_answer_page_hit"))
    selected_answer_page_hit_count = sum(1 for row in inspected_rows if row.get("selected_answer_page_hit"))
    citation_answer_page_hit_count = sum(1 for row in inspected_rows if row.get("citation_answer_page_hit"))
    summary = {
        "command": "inspect_mpdocvqa_ocr_page_alignment",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "source_run_id": source_run_id,
        "source_run_dir": safe_relpath(run_dir),
        "rows_scope": rows_scope,
        "rows_path": rows_path,
        "mpdocvqa_db_path": safe_relpath(mpdocvqa_db_path),
        "mpdocvqa_db_available": db_available,
        "inspected_count": len(inspected_rows),
        "answer_found_anywhere_count": answer_found_count,
        "answer_found_anywhere_rate": rate(answer_found_count, len(inspected_rows)),
        "answer_found_adjacent_page_count": adjacent_count,
        "answer_found_adjacent_page_rate": rate(adjacent_count, len(inspected_rows)),
        "retrievable_answer_page_count": answer_found_count,
        "retrieved_answer_page_hit_count": retrieved_answer_page_hit_count,
        "retrieved_answer_page_hit_rate": rate(retrieved_answer_page_hit_count, len(inspected_rows)),
        "retrieved_answer_page_hit_rate_among_answer_found": rate(retrieved_answer_page_hit_count, answer_found_count),
        "selected_answer_page_hit_count": selected_answer_page_hit_count,
        "selected_answer_page_hit_rate": rate(selected_answer_page_hit_count, len(inspected_rows)),
        "selected_answer_page_hit_rate_among_answer_found": rate(selected_answer_page_hit_count, answer_found_count),
        "citation_answer_page_hit_count": citation_answer_page_hit_count,
        "citation_answer_page_hit_rate": rate(citation_answer_page_hit_count, len(inspected_rows)),
        "citation_answer_page_hit_rate_among_answer_found": rate(citation_answer_page_hit_count, answer_found_count),
        "alignment_bucket_counts": dict(sorted(bucket_counts.items())),
        "used_qwen": bool(source_summary.get("used_qwen", True)),
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "recommendation": recommendation(bucket_counts),
    }
    preview = inspected_rows[:16]
    return write_outputs(
        artifact_dir=artifact_dir,
        summary=summary,
        rows=inspected_rows,
        preview=preview,
        sync_output_root=sync_output_root,
    )


def write_outputs(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    preview: list[dict[str, Any]],
    sync_output_root: Path | None,
) -> dict[str, Any]:
    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "rows": artifact_dir / "rows.jsonl",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }
    summary.update(
        {
            "summary_path": safe_relpath(paths["summary"]),
            "summary_markdown_path": safe_relpath(paths["summary_md"]),
            "rows_path": safe_relpath(paths["rows"]),
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
        "inspected_count": summary.get("inspected_count", 0),
        "answer_found_anywhere_rate": summary.get("answer_found_anywhere_rate", 0.0),
        "answer_found_adjacent_page_rate": summary.get("answer_found_adjacent_page_rate", 0.0),
        "retrieved_answer_page_hit_rate": summary.get("retrieved_answer_page_hit_rate", 0.0),
        "retrieved_answer_page_hit_rate_among_answer_found": summary.get(
            "retrieved_answer_page_hit_rate_among_answer_found", 0.0
        ),
        "selected_answer_page_hit_rate": summary.get("selected_answer_page_hit_rate", 0.0),
        "selected_answer_page_hit_rate_among_answer_found": summary.get(
            "selected_answer_page_hit_rate_among_answer_found", 0.0
        ),
        "citation_answer_page_hit_rate": summary.get("citation_answer_page_hit_rate", 0.0),
        "citation_answer_page_hit_rate_among_answer_found": summary.get(
            "citation_answer_page_hit_rate_among_answer_found", 0.0
        ),
        "alignment_bucket_counts": summary.get("alignment_bucket_counts", {}),
        "recommendation": summary.get("recommendation", {}),
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_jsonl(paths["rows"], rows)
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
        "# MP-DocVQA OCR and Page Alignment Inspection",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- source_run_id: `{summary.get('source_run_id')}`",
        f"- inspected_count: {summary.get('inspected_count', 0)}",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary.get('validation_subset_used_for_training')).lower()}`",
        "",
        "## Alignment Metrics",
        "",
        f"- answer_found_anywhere_rate: {summary.get('answer_found_anywhere_rate', 0.0)}",
        f"- answer_found_adjacent_page_rate: {summary.get('answer_found_adjacent_page_rate', 0.0)}",
        f"- retrieved_answer_page_hit_rate: {summary.get('retrieved_answer_page_hit_rate', 0.0)}",
        f"- selected_answer_page_hit_rate: {summary.get('selected_answer_page_hit_rate', 0.0)}",
        f"- citation_answer_page_hit_rate: {summary.get('citation_answer_page_hit_rate', 0.0)}",
        "",
        "## Buckets",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("alignment_bucket_counts") or {}).items())],
        "",
        "## Recommendation",
        "",
        f"- next_action: `{recommendation_payload.get('next_action')}`",
        f"- do_not_train_yet: `{str(recommendation_payload.get('do_not_train_yet')).lower()}`",
        f"- reason: {recommendation_payload.get('reason')}",
        "",
        "This inspection is diagnostic only. It does not call models, start training, or create training data.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files: list[dict[str, Any]] = []
    for artifact in artifact_paths:
        if not artifact.is_file():
            continue
        files.append(
            {
                "path": safe_relpath(artifact),
                "size_bytes": artifact.stat().st_size,
                "sha256": sha256_file(artifact),
            }
        )
    write_json(path, {"run_id": run_id, "script_version": SCRIPT_VERSION, "files": files})


def sync_outputs(sync_dir: Path, paths: dict[str, Path]) -> None:
    sync_dir.mkdir(parents=True, exist_ok=True)
    for key in ("result", "summary", "summary_md", "preview", "manifest"):
        if paths[key].is_file():
            shutil.copy2(paths[key], sync_dir / paths[key].name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect MP-DocVQA OCR text and page alignment for retrieval misses.")
    parser.add_argument("--run-dir", required=True, help="Query/block granularity inspection artifact directory.")
    parser.add_argument("--mpdocvqa-db-path", required=True, help="SQLite DB with MP-DocVQA EvidenceBlocks.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--sync-output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = inspect_mpdocvqa_ocr_page_alignment(
        run_dir=repo_path(args.run_dir) or Path(args.run_dir),
        mpdocvqa_db_path=repo_path(args.mpdocvqa_db_path) or Path(args.mpdocvqa_db_path),
        output_root=repo_path(args.output_dir) or Path(args.output_dir),
        run_id=args.run_id,
        sync_output_root=repo_path(args.sync_output_dir) if args.sync_output_dir else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

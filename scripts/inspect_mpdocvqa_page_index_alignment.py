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
from scripts.inspect_mpdocvqa_ocr_page_alignment import answer_hit_pages, document_pages
from scripts.inspect_mpdocvqa_retrieval import as_int_set, as_str_list, load_blocks


SCRIPT_VERSION = "mpdocvqa-page-index-alignment-inspect-v1"
EVALUATION_SCOPE = "mpdocvqa_page_index_alignment_inspection_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_page_index_alignment_inspect"
DEFAULT_SUBSET_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_val_subset"


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
    return f"mpdocvqa_page_index_alignment_inspect_{stamp}"


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


def sample_id(row: dict[str, Any]) -> str:
    return str(row.get("sample_id") or row.get("qid") or row.get("raw_question_id") or "")


def rows_by_sample_id(path: Path, *, id_getter=sample_id) -> dict[str, dict[str, Any]]:
    if not path.is_file():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        if not isinstance(row, dict):
            continue
        key = id_getter(row)
        if key and key not in rows:
            rows[key] = row
    return rows


def load_document_manifests(subset_root: Path) -> dict[str, dict[str, Any]]:
    documents_path = subset_root / "documents.jsonl"
    manifests: dict[str, dict[str, Any]] = {}
    if not documents_path.is_file():
        return manifests
    for row in read_jsonl(documents_path):
        if not isinstance(row, dict):
            continue
        doc_id = str(row.get("doc_id") or "")
        manifest_path = row.get("document_manifest")
        if not doc_id or not manifest_path:
            continue
        path = subset_root / str(manifest_path)
        if path.is_file():
            manifests[doc_id] = load_json(path)
    return manifests


def int_list(values: Any) -> list[int]:
    return sorted(as_int_set(values))


def first_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def manifest_gold_pages(row: dict[str, Any] | None) -> list[int]:
    pages: list[int] = []
    if not row:
        return pages
    for item in row.get("gold_evidence") or []:
        if not isinstance(item, dict):
            continue
        value = first_int(item.get("page"))
        if value is not None:
            pages.append(value)
    return sorted(set(pages))


def nearest_delta(reference_pages: list[int], observed_pages: list[int]) -> int | None:
    if not reference_pages or not observed_pages:
        return None
    candidates: list[tuple[int, int]] = []
    for observed in observed_pages:
        for reference in reference_pages:
            delta = observed - reference
            candidates.append((abs(delta), delta))
    candidates.sort(key=lambda item: (item[0], abs(item[1]), item[1]))
    return candidates[0][1]


def page_hit_with_shift(reference_pages: list[int], observed_pages: list[int], shift: int) -> bool:
    if not reference_pages or not observed_pages:
        return False
    shifted = {page + shift for page in reference_pages}
    return bool(shifted.intersection(set(observed_pages)))


def source_page_id_for_ordinal(document_manifest: dict[str, Any], page: int | None) -> str:
    if page is None:
        return ""
    for item in document_manifest.get("pages") or []:
        if not isinstance(item, dict):
            continue
        if first_int(item.get("page_ordinal")) == page:
            return str(item.get("page_id") or "")
    ordered = document_manifest.get("ordered_page_ids") or []
    if isinstance(ordered, list) and 1 <= page <= len(ordered):
        return str(ordered[page - 1] or "")
    return ""


def source_page_ids_for_ordinals(document_manifest: dict[str, Any], pages: list[int]) -> list[str]:
    return [value for value in (source_page_id_for_ordinal(document_manifest, page) for page in pages) if value]


def counter_to_dict(counter: Counter[Any]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter, key=lambda item: str(item))}


def numeric_counter_to_dict(counter: Counter[int]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter)}


def load_alignment_rows(run_dir: Path) -> tuple[list[dict[str, Any]], str, str]:
    path = run_dir / "rows.jsonl"
    if not path.is_file():
        return [], "missing", ""
    return [row for row in read_jsonl(path) if isinstance(row, dict)], "ocr_page_alignment_rows", safe_relpath(path)


def inspect_row(
    row: dict[str, Any],
    *,
    qa_by_id: dict[str, dict[str, Any]],
    manifest_by_id: dict[str, dict[str, Any]],
    sample_evidence_by_id: dict[str, dict[str, Any]],
    document_manifests_by_doc: dict[str, dict[str, Any]],
    blocks_by_doc: dict[str, dict[str, Any]],
    index: int,
) -> dict[str, Any]:
    sid = sample_id(row)
    qa = qa_by_id.get(sid, {})
    manifest = manifest_by_id.get(sid, {})
    sample_evidence = sample_evidence_by_id.get(sid, {})
    doc_id = str(row.get("doc_id") or sample_evidence.get("doc_id") or qa.get("doc_id") or "")
    document_manifest = document_manifests_by_doc.get(doc_id, {})
    ingested_doc_id = str(row.get("ingested_doc_id") or sample_evidence.get("ingested_doc_id") or "")
    block_by_id = blocks_by_doc.get(ingested_doc_id, {})
    alignment_gold_pages = int_list(row.get("gold_pages") or [])
    answers = as_str_list(row.get("answers") or qa.get("answers") or sample_evidence.get("answers") or [])
    observed_answer_pages = int_list(row.get("answer_hit_pages") or [])
    if not observed_answer_pages and block_by_id:
        observed_answer_pages = answer_hit_pages(block_by_id, answers)

    qa_answer_page_idx = first_int(qa.get("answer_page_idx"))
    qa_gold_ordinal = first_int(qa.get("gold_page_ordinal"))
    qa_gold_pages = [qa_gold_ordinal] if qa_gold_ordinal is not None else []
    final_manifest_pages = manifest_gold_pages(manifest)
    evidence_gold_pages = int_list(sample_evidence.get("gold_pages") or [])
    available_pages = sorted(document_pages(block_by_id)) if block_by_id else []

    answer_delta = nearest_delta(alignment_gold_pages, observed_answer_pages)
    manifest_vs_qa_delta = nearest_delta(qa_gold_pages, final_manifest_pages)
    evidence_vs_manifest_delta = nearest_delta(final_manifest_pages, evidence_gold_pages)
    qa_ordinal_minus_answer_idx = (
        qa_gold_ordinal - qa_answer_page_idx if qa_gold_ordinal is not None and qa_answer_page_idx is not None else None
    )
    if page_hit_with_shift(alignment_gold_pages, observed_answer_pages, 0):
        bucket = "answer_on_current_gold_page"
    elif page_hit_with_shift(alignment_gold_pages, observed_answer_pages, -1):
        bucket = "answer_on_gold_minus_one_page"
    elif page_hit_with_shift(alignment_gold_pages, observed_answer_pages, 1):
        bucket = "answer_on_gold_plus_one_page"
    elif observed_answer_pages:
        bucket = "answer_elsewhere_in_document"
    elif str(row.get("alignment_bucket") or "") == "gold_page_without_retrievable_blocks":
        bucket = "gold_page_without_retrievable_blocks"
    else:
        bucket = "answer_not_found_in_document_text"

    return {
        "source_row_index": index,
        "sample_id": sid,
        "doc_id": doc_id,
        "ingested_doc_id": ingested_doc_id,
        "source_document": str(row.get("source_document") or sample_evidence.get("source_document") or qa.get("source_doc_id") or ""),
        "question": str(row.get("question") or qa.get("question") or ""),
        "answers": answers,
        "source_alignment_bucket": str(row.get("alignment_bucket") or ""),
        "page_index_bucket": bucket,
        "qa_answer_page_idx": qa_answer_page_idx,
        "qa_gold_page_ordinal": qa_gold_ordinal,
        "qa_gold_page_id": str(qa.get("gold_page_id") or ""),
        "document_window_page_count": first_int(document_manifest.get("page_count")),
        "document_window_ordered_page_ids": [str(item) for item in document_manifest.get("ordered_page_ids") or []],
        "current_gold_source_page_ids": source_page_ids_for_ordinals(document_manifest, alignment_gold_pages),
        "answer_hit_source_page_ids": source_page_ids_for_ordinals(document_manifest, observed_answer_pages),
        "final_manifest_gold_pages": final_manifest_pages,
        "sample_evidence_gold_pages": evidence_gold_pages,
        "alignment_gold_pages": alignment_gold_pages,
        "answer_hit_pages": observed_answer_pages,
        "retrieved_pages": int_list(row.get("retrieved_pages") or []),
        "selected_pages": int_list(row.get("selected_pages") or []),
        "citation_pages": int_list(row.get("citation_pages") or []),
        "retrieved_answer_page_hit": bool(row.get("retrieved_answer_page_hit")),
        "selected_answer_page_hit": bool(row.get("selected_answer_page_hit")),
        "citation_answer_page_hit": bool(row.get("citation_answer_page_hit")),
        "available_page_min": min(available_pages) if available_pages else None,
        "available_page_max": max(available_pages) if available_pages else None,
        "available_page_count": len(available_pages),
        "qa_ordinal_minus_answer_idx": qa_ordinal_minus_answer_idx,
        "final_manifest_minus_qa_gold_page_delta": manifest_vs_qa_delta,
        "sample_evidence_minus_manifest_gold_page_delta": evidence_vs_manifest_delta,
        "answer_page_minus_alignment_gold_page_delta": answer_delta,
        "current_gold_page_answer_hit": page_hit_with_shift(alignment_gold_pages, observed_answer_pages, 0),
        "gold_minus_one_answer_hit": page_hit_with_shift(alignment_gold_pages, observed_answer_pages, -1),
        "gold_plus_one_answer_hit": page_hit_with_shift(alignment_gold_pages, observed_answer_pages, 1),
        "has_qa_record": bool(qa),
        "has_document_manifest": bool(document_manifest),
        "has_final_manifest_record": bool(manifest),
        "has_sample_evidence_record": bool(sample_evidence),
    }


def recommendation(
    *,
    dominant_shift: int | None,
    dominant_shift_rate: float,
    current_hit_rate: float,
    shifted_hit_rates: dict[str, float],
    manifest_consistent_rate: float,
    evidence_consistent_rate: float,
    qa_ordinal_consistent_rate: float,
) -> dict[str, Any]:
    if manifest_consistent_rate < 0.8 or evidence_consistent_rate < 0.8 or qa_ordinal_consistent_rate < 0.8:
        next_action = "inspect_mpdocvqa_manifest_and_evidence_page_mapping_before_retrieval_changes"
    elif dominant_shift in {-1, 1} and dominant_shift_rate >= 0.5:
        next_action = "manual_review_answer_text_hits_before_retrieval_changes"
    elif shifted_hit_rates.get("0", 0.0) < current_hit_rate:
        next_action = "inspect_mpdocvqa_page_index_summary_logic"
    else:
        next_action = "inspect_ocr_or_answer_text_matching_before_retrieval_changes"
    return {
        "next_action": next_action,
        "do_not_train_yet": True,
        "reason": "This audit treats MP-DocVQA pages as the current input document pages (1..N). It only recommends mapping repair when answer_page_idx, manifests, or EvidenceBlock evidence pages disagree; answer-text hits on adjacent pages require manual/OCR review before retrieval or training changes.",
    }


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    answer_delta_counts: Counter[int] = Counter(
        row["answer_page_minus_alignment_gold_page_delta"]
        for row in rows
        if row.get("answer_page_minus_alignment_gold_page_delta") is not None
    )
    manifest_delta_counts: Counter[int] = Counter(
        row["final_manifest_minus_qa_gold_page_delta"]
        for row in rows
        if row.get("final_manifest_minus_qa_gold_page_delta") is not None
    )
    evidence_delta_counts: Counter[int] = Counter(
        row["sample_evidence_minus_manifest_gold_page_delta"]
        for row in rows
        if row.get("sample_evidence_minus_manifest_gold_page_delta") is not None
    )
    qa_ordinal_counts: Counter[int] = Counter(
        row["qa_ordinal_minus_answer_idx"] for row in rows if row.get("qa_ordinal_minus_answer_idx") is not None
    )
    dominant_shift = answer_delta_counts.most_common(1)[0][0] if answer_delta_counts else None
    observed_shift_count = sum(answer_delta_counts.values())
    dominant_shift_rate = rate(answer_delta_counts.get(dominant_shift, 0) if dominant_shift is not None else 0, observed_shift_count)
    shifted_hit_rates = {
        str(shift): rate(sum(1 for row in rows if page_hit_with_shift(row["alignment_gold_pages"], row["answer_hit_pages"], shift)), total)
        for shift in (-2, -1, 0, 1, 2)
    }
    manifest_consistent_rate = rate(manifest_delta_counts.get(0, 0), sum(manifest_delta_counts.values()))
    evidence_consistent_rate = rate(evidence_delta_counts.get(0, 0), sum(evidence_delta_counts.values()))
    qa_ordinal_consistent_rate = rate(qa_ordinal_counts.get(1, 0), sum(qa_ordinal_counts.values()))
    return {
        "inspected_count": total,
        "answer_page_shift_observed_count": observed_shift_count,
        "dominant_answer_page_shift": dominant_shift,
        "dominant_answer_page_shift_rate": dominant_shift_rate,
        "qa_ordinal_minus_answer_idx_distribution": numeric_counter_to_dict(qa_ordinal_counts),
        "final_manifest_minus_qa_gold_page_delta_distribution": numeric_counter_to_dict(manifest_delta_counts),
        "sample_evidence_minus_manifest_gold_page_delta_distribution": numeric_counter_to_dict(evidence_delta_counts),
        "answer_page_minus_alignment_gold_page_delta_distribution": numeric_counter_to_dict(answer_delta_counts),
        "page_index_bucket_counts": counter_to_dict(Counter(row.get("page_index_bucket") for row in rows)),
        "rows_with_qa_record_count": sum(1 for row in rows if row.get("has_qa_record")),
        "rows_with_final_manifest_record_count": sum(1 for row in rows if row.get("has_final_manifest_record")),
        "rows_with_sample_evidence_record_count": sum(1 for row in rows if row.get("has_sample_evidence_record")),
        "current_gold_page_answer_hit_rate": shifted_hit_rates["0"],
        "shifted_gold_page_answer_hit_rates": shifted_hit_rates,
        "manifest_consistent_with_qa_gold_page_rate": manifest_consistent_rate,
        "sample_evidence_consistent_with_manifest_gold_page_rate": evidence_consistent_rate,
        "qa_gold_page_ordinal_consistent_with_answer_page_idx_rate": qa_ordinal_consistent_rate,
        "recommendation": recommendation(
            dominant_shift=dominant_shift,
            dominant_shift_rate=dominant_shift_rate,
            current_hit_rate=shifted_hit_rates["0"],
            shifted_hit_rates=shifted_hit_rates,
            manifest_consistent_rate=manifest_consistent_rate,
            evidence_consistent_rate=evidence_consistent_rate,
            qa_ordinal_consistent_rate=qa_ordinal_consistent_rate,
        ),
    }


def inspect_mpdocvqa_page_index_alignment(
    *,
    alignment_run_dir: Path,
    subset_root: Path,
    sample_evidence_manifest_path: Path,
    mpdocvqa_db_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    alignment_summary = load_json(alignment_run_dir / "summary.json")
    alignment_result = load_json(alignment_run_dir / "result.json")
    alignment_rows, rows_scope, rows_path = load_alignment_rows(alignment_run_dir)
    qa_path = subset_root / "qa.jsonl"
    manifest_path = subset_root / "sample_manifest.jsonl"
    missing = [
        safe_relpath(path)
        for path in (
            alignment_run_dir / "summary.json",
            alignment_run_dir / "result.json",
            qa_path,
            manifest_path,
            sample_evidence_manifest_path,
            mpdocvqa_db_path,
        )
        if not path.is_file()
    ]
    if rows_scope == "missing":
        missing.append("rows.jsonl")
    if missing:
        summary = {
            "command": "inspect_mpdocvqa_page_index_alignment",
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

    qa_by_id = rows_by_sample_id(qa_path, id_getter=lambda row: str(row.get("qid") or row.get("raw_question_id") or ""))
    manifest_by_id = rows_by_sample_id(manifest_path)
    sample_evidence_by_id = rows_by_sample_id(sample_evidence_manifest_path)
    document_manifests_by_doc = load_document_manifests(subset_root)
    blocks_by_doc, db_available = load_blocks(alignment_rows, mpdocvqa_db_path)
    inspected_rows = [
        inspect_row(
            row,
            qa_by_id=qa_by_id,
            manifest_by_id=manifest_by_id,
            sample_evidence_by_id=sample_evidence_by_id,
            document_manifests_by_doc=document_manifests_by_doc,
            blocks_by_doc=blocks_by_doc,
            index=index,
        )
        for index, row in enumerate(alignment_rows)
    ]
    metrics = summarize_rows(inspected_rows)
    source_run_id = str(alignment_summary.get("run_id") or alignment_result.get("run_id") or alignment_run_dir.name)
    summary = {
        "command": "inspect_mpdocvqa_page_index_alignment",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "source_run_id": source_run_id,
        "source_run_dir": safe_relpath(alignment_run_dir),
        "rows_scope": rows_scope,
        "rows_path": rows_path,
        "subset_root": safe_relpath(subset_root),
        "sample_evidence_manifest_path": safe_relpath(sample_evidence_manifest_path),
        "mpdocvqa_db_path": safe_relpath(mpdocvqa_db_path),
        "mpdocvqa_db_available": db_available,
        "used_qwen": bool(alignment_summary.get("used_qwen", True)),
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        **metrics,
    }
    return write_outputs(
        artifact_dir=artifact_dir,
        summary=summary,
        rows=inspected_rows,
        preview=inspected_rows[:16],
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
        "dominant_answer_page_shift": summary.get("dominant_answer_page_shift"),
        "dominant_answer_page_shift_rate": summary.get("dominant_answer_page_shift_rate", 0.0),
        "current_gold_page_answer_hit_rate": summary.get("current_gold_page_answer_hit_rate", 0.0),
        "shifted_gold_page_answer_hit_rates": summary.get("shifted_gold_page_answer_hit_rates", {}),
        "page_index_bucket_counts": summary.get("page_index_bucket_counts", {}),
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
        "# MP-DocVQA Page Index Alignment Inspection",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- source_run_id: `{summary.get('source_run_id')}`",
        f"- inspected_count: {summary.get('inspected_count', 0)}",
        f"- dominant_answer_page_shift: `{summary.get('dominant_answer_page_shift')}`",
        f"- dominant_answer_page_shift_rate: {summary.get('dominant_answer_page_shift_rate', 0.0)}",
        f"- current_gold_page_answer_hit_rate: {summary.get('current_gold_page_answer_hit_rate', 0.0)}",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary.get('validation_subset_used_for_training')).lower()}`",
        "",
        "## Shifted Gold-Page Hit Rates",
        "",
        *[f"- shift {key}: {value}" for key, value in sorted((summary.get("shifted_gold_page_answer_hit_rates") or {}).items())],
        "",
        "## Buckets",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("page_index_bucket_counts") or {}).items())],
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
        files.append({"path": safe_relpath(artifact), "size_bytes": artifact.stat().st_size, "sha256": sha256_file(artifact)})
    write_json(path, {"run_id": run_id, "script_version": SCRIPT_VERSION, "files": files})


def sync_outputs(sync_dir: Path, paths: dict[str, Path]) -> None:
    sync_dir.mkdir(parents=True, exist_ok=True)
    for key in ("result", "summary", "summary_md", "preview", "manifest"):
        if paths[key].is_file():
            shutil.copy2(paths[key], sync_dir / paths[key].name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect MP-DocVQA page-index alignment before retrieval changes.")
    parser.add_argument("--alignment-run-dir", required=True, help="OCR/page alignment inspection artifact directory.")
    parser.add_argument("--subset-root", default=str(DEFAULT_SUBSET_ROOT), help="Prepared MP-DocVQA subset root.")
    parser.add_argument("--sample-evidence-manifest", required=True, help="sample_evidence_manifest.jsonl from evidence materialization.")
    parser.add_argument("--mpdocvqa-db-path", required=True, help="SQLite DB with MP-DocVQA EvidenceBlocks.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--sync-output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = inspect_mpdocvqa_page_index_alignment(
        alignment_run_dir=repo_path(args.alignment_run_dir) or Path(args.alignment_run_dir),
        subset_root=repo_path(args.subset_root) or Path(args.subset_root),
        sample_evidence_manifest_path=repo_path(args.sample_evidence_manifest) or Path(args.sample_evidence_manifest),
        mpdocvqa_db_path=repo_path(args.mpdocvqa_db_path) or Path(args.mpdocvqa_db_path),
        output_root=repo_path(args.output_dir) or Path(args.output_dir),
        run_id=args.run_id,
        sync_output_root=repo_path(args.sync_output_dir) if args.sync_output_dir else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

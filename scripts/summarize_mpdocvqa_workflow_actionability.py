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


SCRIPT_VERSION = "mpdocvqa-workflow-actionability-v1"
EVALUATION_SCOPE = "mpdocvqa_workflow_actionability_summary_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_workflow_actionability"
RETRIEVAL_ACTIONABILITY_BUCKETS = {
    "context_or_citation_selection_review",
    "retrieval_or_duplicate_answer_review",
    "retrieval_gold_page_miss_unreviewed",
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
    return f"mpdocvqa_workflow_actionability_{stamp}"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [row for row in read_jsonl(path) if isinstance(row, dict)]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def manual_review_by_sample(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    review: dict[str, dict[str, Any]] = {}
    for row in rows:
        sample_id = str(row.get("sample_id") or "")
        if sample_id and sample_id not in review:
            review[sample_id] = row
    return review


def adjusted_bucket(row: dict[str, Any], review_by_sample: dict[str, dict[str, Any]]) -> str:
    bucket = str(row.get("bucket") or "")
    if bucket != "retrieval_gold_page_miss":
        return bucket
    sample_id = str(row.get("sample_id") or "")
    review = review_by_sample.get(sample_id) or {}
    return str(review.get("actionability_bucket") or "retrieval_gold_page_miss_unreviewed")


def summarize_row(row: dict[str, Any], review_by_sample: dict[str, dict[str, Any]]) -> dict[str, Any]:
    sample_id = str(row.get("sample_id") or "")
    review = review_by_sample.get(sample_id) or {}
    actionability = str(review.get("actionability_bucket") or "")
    return {
        "sample_id": sample_id,
        "doc_id": str(row.get("doc_id") or ""),
        "source_document": str(row.get("source_document") or ""),
        "bucket": str(row.get("bucket") or ""),
        "adjusted_bucket": adjusted_bucket(row, review_by_sample),
        "actionability_bucket": actionability,
        "review_bucket": str(review.get("review_bucket") or ""),
        "page_index_bucket": str(review.get("page_index_bucket") or ""),
        "question": str(row.get("question") or ""),
        "answers": row.get("answers") or [],
        "gold_pages": row.get("gold_pages") or [],
        "retrieved_pages": row.get("retrieved_pages") or [],
        "selected_pages": row.get("selected_pages") or [],
        "citation_pages": row.get("citation_pages") or [],
        "answer_hit_pages": review.get("answer_hit_pages") or [],
        "workflow_answer_page_hits": review.get("workflow_answer_page_hits") or {},
    }


def recommendation(adjusted_counts: Counter[str]) -> dict[str, Any]:
    if adjusted_counts.get("ocr_or_answer_alias_review", 0) and sum(
        adjusted_counts.get(bucket, 0) for bucket in RETRIEVAL_ACTIONABILITY_BUCKETS
    ):
        next_action = "inspect_ocr_alias_and_remaining_retrieval_rows_before_more_eval"
    elif adjusted_counts.get("ocr_or_answer_alias_review", 0):
        next_action = "inspect_ocr_or_answer_alias_rows_before_more_eval"
    elif sum(adjusted_counts.get(bucket, 0) for bucket in RETRIEVAL_ACTIONABILITY_BUCKETS):
        next_action = "inspect_remaining_retrieval_actionability_rows_before_training"
    elif adjusted_counts.get("answer_generation_or_metric_miss", 0):
        next_action = "review_mpdocvqa_answer_generation_or_metric_before_training"
    else:
        next_action = "continue_qwen_eval_before_training"
    return {
        "next_action": next_action,
        "do_not_train_yet": True,
        "reason": (
            "This summary overlays manual page-alignment actionability on existing MP-DocVQA "
            "full-workflow diagnostics. It does not call models, repair labels, create training "
            "data, or claim formal benchmark acceptance."
        ),
    }


def summarize_mpdocvqa_workflow_actionability(
    *,
    compare_run_dir: Path,
    manual_review_dir: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    compare_summary = load_json(compare_run_dir / "summary.json")
    manual_summary = load_json(manual_review_dir / "summary.json")
    compare_rows_path = compare_run_dir / "rows.jsonl"
    manual_rows_path = manual_review_dir / "manual_review.jsonl"
    missing = [
        safe_relpath(path)
        for path in (compare_run_dir / "summary.json", compare_rows_path, manual_review_dir / "summary.json", manual_rows_path)
        if not path.is_file()
    ]
    if missing:
        summary = {
            "command": "summarize_mpdocvqa_workflow_actionability",
            "status": "failed",
            "quality_status": "blocked",
            "run_id": run_id,
            "artifact_dir": safe_relpath(artifact_dir),
            "missing": missing,
            "used_qwen": False,
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
        return write_outputs(artifact_dir=artifact_dir, summary=summary, rows=[], preview=[], sync_output_root=sync_output_root)

    compare_rows = load_jsonl(compare_rows_path)
    manual_rows = load_jsonl(manual_rows_path)
    review_by_sample = manual_review_by_sample(manual_rows)
    rows = [summarize_row(row, review_by_sample) for row in compare_rows]
    bucket_counts = Counter(str(row.get("bucket") or "") for row in rows)
    adjusted_counts = Counter(str(row.get("adjusted_bucket") or "") for row in rows)
    actionability_counts = Counter(str(row.get("actionability_bucket") or "") for row in rows if row.get("actionability_bucket"))
    retrieval_actionability_count = sum(adjusted_counts.get(bucket, 0) for bucket in RETRIEVAL_ACTIONABILITY_BUCKETS)
    reviewed_retrieval_miss_count = sum(
        1 for row in rows if row.get("bucket") == "retrieval_gold_page_miss" and row.get("actionability_bucket")
    )
    summary = {
        "command": "summarize_mpdocvqa_workflow_actionability",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "compare_run_dir": safe_relpath(compare_run_dir),
        "manual_review_dir": safe_relpath(manual_review_dir),
        "source_compare_run_id": compare_summary.get("run_id") or compare_run_dir.name,
        "source_manual_review_run_id": manual_summary.get("run_id") or manual_review_dir.name,
        "evaluated_count": len(rows),
        "reviewed_retrieval_miss_count": reviewed_retrieval_miss_count,
        "original_bucket_counts": dict(sorted(bucket_counts.items())),
        "adjusted_bucket_counts": dict(sorted(adjusted_counts.items())),
        "manual_actionability_bucket_counts": manual_summary.get("actionability_bucket_counts") or dict(sorted(actionability_counts.items())),
        "gold_page_alignment_review_not_retrieval_defect_count": adjusted_counts.get(
            "gold_page_alignment_review_not_retrieval_defect", 0
        ),
        "ocr_or_answer_alias_review_count": adjusted_counts.get("ocr_or_answer_alias_review", 0),
        "actionable_retrieval_issue_count": retrieval_actionability_count,
        "answer_generation_or_metric_miss_count": adjusted_counts.get("answer_generation_or_metric_miss", 0),
        "task_type_not_local_fact_qa_count": adjusted_counts.get("task_type_not_local_fact_qa", 0),
        "adjusted_retrieval_actionability_rate": rate(retrieval_actionability_count, len(rows)),
        "used_qwen": bool(compare_summary.get("used_qwen", True)),
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "recommendation": recommendation(adjusted_counts),
    }
    preview = [row for row in rows if row.get("adjusted_bucket") != "passed"][:16]
    return write_outputs(artifact_dir=artifact_dir, summary=summary, rows=rows, preview=preview, sync_output_root=sync_output_root)


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
    if sync_output_root is not None:
        summary["sync_bundle_path"] = safe_relpath(sync_output_root / str(summary["run_id"]))
    result = {
        "command": summary["command"],
        "status": summary["status"],
        "run_id": summary["run_id"],
        "artifact_dir": summary["artifact_dir"],
        "quality_status": summary["quality_status"],
        "evaluated_count": summary.get("evaluated_count", 0),
        "original_bucket_counts": summary.get("original_bucket_counts", {}),
        "adjusted_bucket_counts": summary.get("adjusted_bucket_counts", {}),
        "manual_actionability_bucket_counts": summary.get("manual_actionability_bucket_counts", {}),
        "actionable_retrieval_issue_count": summary.get("actionable_retrieval_issue_count", 0),
        "recommendation": summary.get("recommendation", {}),
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    if sync_output_root is not None:
        result["sync_bundle_path"] = summary["sync_bundle_path"]
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_jsonl(paths["rows"], rows)
    write_json(paths["preview"], preview)
    write_json(paths["result"], result)
    write_manifest(
        paths["manifest"],
        run_id=str(summary["run_id"]),
        artifact_paths=[path for key, path in paths.items() if key != "manifest"],
    )
    if sync_output_root is not None:
        sync_outputs(sync_output_root / str(summary["run_id"]), paths)
    return {**result, **summary, "artifact_paths": [safe_relpath(path) for path in paths.values()]}


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    recommendation_payload = summary.get("recommendation") or {}
    lines = [
        "# MP-DocVQA Workflow Actionability Summary",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- evaluated_count: {summary.get('evaluated_count', 0)}",
        f"- reviewed_retrieval_miss_count: {summary.get('reviewed_retrieval_miss_count', 0)}",
        f"- actionable_retrieval_issue_count: {summary.get('actionable_retrieval_issue_count', 0)}",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary.get('validation_subset_used_for_training')).lower()}`",
        "",
        "## Original Buckets",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("original_bucket_counts") or {}).items())],
        "",
        "## Adjusted Buckets",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("adjusted_bucket_counts") or {}).items())],
        "",
        "## Recommendation",
        "",
        f"- next_action: `{recommendation_payload.get('next_action')}`",
        f"- do_not_train_yet: `{str(recommendation_payload.get('do_not_train_yet')).lower()}`",
        f"- reason: {recommendation_payload.get('reason')}",
        "",
        "This summary is diagnostic only. It does not call models, start training, repair labels, or claim benchmark acceptance.",
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
    parser = argparse.ArgumentParser(description="Summarize MP-DocVQA full-workflow actionability after manual review.")
    parser.add_argument("--compare-run-dir", required=True, help="Full-workflow comparison artifact directory.")
    parser.add_argument("--manual-review-dir", required=True, help="Page-alignment manual-review artifact directory.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--sync-output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = summarize_mpdocvqa_workflow_actionability(
        compare_run_dir=repo_path(args.compare_run_dir) or Path(args.compare_run_dir),
        manual_review_dir=repo_path(args.manual_review_dir) or Path(args.manual_review_dir),
        output_root=repo_path(args.output_dir) or Path(args.output_dir),
        run_id=args.run_id,
        sync_output_root=repo_path(args.sync_output_dir) if args.sync_output_dir else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

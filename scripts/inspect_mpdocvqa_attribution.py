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

from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl


SCRIPT_VERSION = "mpdocvqa-attribution-inspect-v1"
EVALUATION_SCOPE = "mpdocvqa_answer_policy_attribution_inspection_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_attribution_inspect"


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
    return f"mpdocvqa_attribution_inspect_{stamp}"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_rows(run_dir: Path) -> tuple[list[dict[str, Any]], str, str]:
    results_path = run_dir / "results.jsonl"
    if results_path.is_file():
        return [row for row in read_jsonl(results_path) if isinstance(row, dict)], "full_results", safe_relpath(results_path)
    failures_path = run_dir / "failures_sample.jsonl"
    if failures_path.is_file():
        return [row for row in read_jsonl(failures_path) if isinstance(row, dict)], "failure_sample_only", safe_relpath(failures_path)
    return [], "missing", ""


def as_int_set(values: Any) -> set[int]:
    pages: set[int] = set()
    if not isinstance(values, list):
        values = [values]
    for value in values:
        try:
            pages.add(int(value))
        except (TypeError, ValueError):
            continue
    return pages


def as_str_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        values = [values] if values not in (None, "") else []
    return [str(item) for item in values if str(item or "").strip()]


def block_page_map_from_db(rows: list[dict[str, Any]], db_path: Path | None) -> tuple[dict[str, int], bool]:
    if db_path is None or not db_path.is_file():
        return {}, False
    doc_ids = sorted({str(row.get("ingested_doc_id") or "") for row in rows if str(row.get("ingested_doc_id") or "")})
    pages: dict[str, int] = {}
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        for doc_id in doc_ids:
            for block in repository.load_evidence_blocks(doc_id, include_page_blocks=True):
                page = block.location.page if block.location.page is not None else block.page_id
                if page is not None:
                    pages[block.block_id] = int(page)
    finally:
        conn.close()
    return pages, True


def pages_for_block_ids(block_ids: Any, block_pages: dict[str, int]) -> set[int]:
    pages: set[int] = set()
    for block_id in as_str_list(block_ids):
        page = block_pages.get(block_id)
        if page is not None:
            pages.add(page)
    return pages


def citation_pages(row: dict[str, Any], block_pages: dict[str, int]) -> set[int]:
    pages = as_int_set(row.get("citation_pages") or [])
    pages.update(pages_for_block_ids(row.get("citation_block_ids") or [], block_pages))
    return pages


def compact_answer(row: dict[str, Any]) -> str:
    if row.get("prediction_answer") is not None:
        return str(row.get("prediction_answer") or "")
    compact = row.get("final_answer_compact") if isinstance(row.get("final_answer_compact"), dict) else {}
    return str(compact.get("answer") or "")


def classify_mp_row(
    row: dict[str, Any],
    *,
    gold_pages: set[int],
    retrieved_pages: set[int],
    selected_pages: set[int],
    cited_pages: set[int],
    db_available: bool,
) -> str:
    if not gold_pages:
        return "gold_page_missing"
    answer_hit = bool(row.get("answer_hit"))
    citation_hit = bool(row.get("citation_page_hit")) or bool(gold_pages.intersection(cited_pages))
    if row.get("pass_fail") == "passed":
        return "passed"
    if not db_available:
        if not citation_hit:
            return "citation_page_miss_without_db_context"
        if not answer_hit:
            return "answer_generation_or_metric_miss"
        return "other_failure_without_db_context"
    if not gold_pages.intersection(retrieved_pages):
        return "retrieval_gold_page_miss"
    if selected_pages and not gold_pages.intersection(selected_pages):
        return "selected_context_gold_page_miss"
    if not citation_hit:
        if not as_str_list(row.get("citation_block_ids") or []):
            return "empty_citation"
        return "citation_selection_page_miss"
    if not answer_hit:
        return "answer_generation_or_metric_miss"
    return "other_failure"


def compact_mp_row(row: dict[str, Any], block_pages: dict[str, int], db_available: bool, source_row_index: int) -> dict[str, Any]:
    gold_pages = as_int_set(row.get("gold_pages") or [])
    retrieved_pages = pages_for_block_ids(row.get("retrieved_block_ids") or [], block_pages)
    selected_pages = pages_for_block_ids(row.get("selected_block_ids") or [], block_pages)
    cited_pages = citation_pages(row, block_pages)
    bucket = classify_mp_row(
        row,
        gold_pages=gold_pages,
        retrieved_pages=retrieved_pages,
        selected_pages=selected_pages,
        cited_pages=cited_pages,
        db_available=db_available,
    )
    return {
        "source_row_index": source_row_index,
        "sample_id": row.get("sample_id"),
        "dataset": row.get("dataset"),
        "bucket": bucket,
        "pass_fail": row.get("pass_fail"),
        "failure_reasons": row.get("failure_reasons") or [],
        "question": row.get("question"),
        "answers": row.get("answers") or [],
        "prediction_answer": compact_answer(row),
        "answer_hit": bool(row.get("answer_hit")),
        "citation_page_hit": bool(row.get("citation_page_hit")) or bool(gold_pages.intersection(cited_pages)),
        "gold_pages": sorted(gold_pages),
        "retrieved_pages": sorted(retrieved_pages),
        "selected_pages": sorted(selected_pages),
        "citation_pages": sorted(cited_pages),
        "retrieved_gold_page_hit": bool(gold_pages and retrieved_pages and gold_pages.intersection(retrieved_pages)),
        "selected_gold_page_hit": bool(gold_pages and selected_pages and gold_pages.intersection(selected_pages)),
        "citation_gold_page_hit": bool(gold_pages and cited_pages and gold_pages.intersection(cited_pages)),
        "retrieved_block_ids": as_str_list(row.get("retrieved_block_ids") or [])[:12],
        "selected_block_ids": as_str_list(row.get("selected_block_ids") or [])[:12],
        "citation_block_ids": as_str_list(row.get("citation_block_ids") or [])[:12],
        "raw_model_output_preview": str(row.get("raw_model_output_preview") or "")[:500],
    }


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def recommendation(bucket_counts: Counter[str]) -> dict[str, Any]:
    if bucket_counts.get("retrieval_gold_page_miss", 0) > 0:
        next_action = "inspect_mpdocvqa_retrieval_before_training"
    elif bucket_counts.get("selected_context_gold_page_miss", 0) > 0 or bucket_counts.get("citation_selection_page_miss", 0) > 0:
        next_action = "inspect_mpdocvqa_context_or_citation_selection_before_training"
    elif bucket_counts.get("answer_generation_or_metric_miss", 0) > 0:
        next_action = "review_mpdocvqa_answer_generation_or_metric_before_training"
    else:
        next_action = "continue_qwen_eval_before_training"
    return {
        "next_action": next_action,
        "do_not_train_yet": True,
        "reason": "This inspection separates generic MP-DocVQA retrieval, context selection, citation, and answer-quality signals without using validation rows for training.",
    }


def inspect_mpdocvqa_attribution(
    *,
    run_dir: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    mpdocvqa_db_path: Path | None = None,
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary_json = load_json(run_dir / "summary.json")
    result_json = load_json(run_dir / "result.json")
    rows, rows_scope, rows_path = load_rows(run_dir)
    missing = [safe_relpath(path) for path in [run_dir / "summary.json", run_dir / "result.json"] if not path.is_file()]
    if rows_scope == "missing":
        missing.append("results.jsonl_or_failures_sample.jsonl")
    if missing:
        payload = {
            "command": "inspect_mpdocvqa_attribution",
            "status": "failed",
            "quality_status": "blocked",
            "run_id": run_id,
            "artifact_dir": safe_relpath(artifact_dir),
            "missing": missing,
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
        return write_outputs(artifact_dir=artifact_dir, summary=payload, inspected_rows=[], preview=[], sync_output_root=sync_output_root)

    mp_rows = [row for row in rows if str(row.get("dataset") or "") in {"mp_docvqa", "mpdocvqa"} and row.get("answer_evaluated")]
    block_pages, db_available = block_page_map_from_db(mp_rows, mpdocvqa_db_path)
    inspected_rows = [compact_mp_row(row, block_pages, db_available, index) for index, row in enumerate(mp_rows)]
    buckets = Counter(str(row.get("bucket") or "") for row in inspected_rows)
    failure_reasons = Counter(reason for row in inspected_rows for reason in row.get("failure_reasons") or [])
    source_run_id = str(summary_json.get("run_id") or result_json.get("run_id") or run_dir.name)
    mp_count = len(inspected_rows)
    answer_hit_count = sum(1 for row in inspected_rows if row.get("answer_hit"))
    citation_hit_count = sum(1 for row in inspected_rows if row.get("citation_page_hit"))
    retrieved_hit_count = sum(1 for row in inspected_rows if row.get("retrieved_gold_page_hit"))
    selected_hit_count = sum(1 for row in inspected_rows if row.get("selected_gold_page_hit"))
    both_hit_count = sum(1 for row in inspected_rows if row.get("answer_hit") and row.get("citation_page_hit"))
    summary = {
        "command": "inspect_mpdocvqa_attribution",
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
        "used_qwen": bool(summary_json.get("used_qwen", result_json.get("used_qwen", False))),
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "mpdocvqa_db_path": safe_relpath(mpdocvqa_db_path) if mpdocvqa_db_path is not None else "",
        "mpdocvqa_db_available": db_available,
        "case_count": summary_json.get("case_count"),
        "evaluated_count": summary_json.get("evaluated_count"),
        "mpdocvqa_evaluated_count": mp_count,
        "mpdocvqa_passed_count": sum(1 for row in inspected_rows if row.get("pass_fail") == "passed"),
        "mpdocvqa_failed_count": sum(1 for row in inspected_rows if row.get("pass_fail") == "failed"),
        "mpdocvqa_answer_hit_count": answer_hit_count,
        "mpdocvqa_answer_hit_rate": rate(answer_hit_count, mp_count),
        "mpdocvqa_citation_page_hit_count": citation_hit_count,
        "mpdocvqa_citation_page_hit_rate": rate(citation_hit_count, mp_count),
        "mpdocvqa_answer_and_citation_hit_count": both_hit_count,
        "mpdocvqa_answer_and_citation_hit_rate": rate(both_hit_count, mp_count),
        "retrieved_gold_page_hit_count": retrieved_hit_count,
        "retrieved_gold_page_hit_rate": rate(retrieved_hit_count, mp_count),
        "selected_gold_page_hit_count": selected_hit_count,
        "selected_gold_page_hit_rate": rate(selected_hit_count, mp_count),
        "answer_hit_citation_page_miss_count": sum(
            1 for row in inspected_rows if row.get("answer_hit") and not row.get("citation_page_hit")
        ),
        "answer_miss_citation_page_hit_count": sum(
            1 for row in inspected_rows if not row.get("answer_hit") and row.get("citation_page_hit")
        ),
        "empty_citation_count": sum(1 for row in inspected_rows if not row.get("citation_block_ids")),
        "bucket_counts": dict(sorted(buckets.items())),
        "failure_reason_distribution": dict(sorted(failure_reasons.items())),
        "recommendation": recommendation(buckets),
    }
    return write_outputs(
        artifact_dir=artifact_dir,
        summary=summary,
        inspected_rows=inspected_rows,
        preview=[row for row in inspected_rows if row.get("bucket") != "passed"][:12],
        sync_output_root=sync_output_root,
    )


def write_outputs(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
    inspected_rows: list[dict[str, Any]],
    preview: list[dict[str, Any]],
    sync_output_root: Path | None,
) -> dict[str, Any]:
    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "rows": artifact_dir / "mpdocvqa_attribution_rows.jsonl",
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
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "mpdocvqa_evaluated_count": summary.get("mpdocvqa_evaluated_count", 0),
        "mpdocvqa_answer_hit_rate": summary.get("mpdocvqa_answer_hit_rate", 0.0),
        "mpdocvqa_citation_page_hit_rate": summary.get("mpdocvqa_citation_page_hit_rate", 0.0),
        "retrieved_gold_page_hit_rate": summary.get("retrieved_gold_page_hit_rate", 0.0),
        "bucket_counts": summary.get("bucket_counts", {}),
        "recommendation": summary.get("recommendation", {}),
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_jsonl(paths["rows"], inspected_rows)
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


def sync_outputs(sync_dir: Path, paths: dict[str, Path]) -> str:
    sync_dir.mkdir(parents=True, exist_ok=True)
    for key in ("result", "summary", "summary_md", "preview", "manifest"):
        if paths[key].is_file():
            shutil.copy2(paths[key], sync_dir / paths[key].name)
    return safe_relpath(sync_dir)


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files: list[dict[str, Any]] = []
    for artifact in artifact_paths:
        if not artifact.is_file():
            continue
        data = artifact.read_bytes()
        files.append(
            {
                "path": safe_relpath(artifact),
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    write_json(path, {"run_id": run_id, "script_version": SCRIPT_VERSION, "files": files})


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    recommendation_payload = summary.get("recommendation") or {}
    lines = [
        "# MP-DocVQA Attribution Inspection",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- source_run_id: `{summary.get('source_run_id')}`",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary.get('validation_subset_used_for_training')).lower()}`",
        f"- mpdocvqa_db_available: `{str(summary.get('mpdocvqa_db_available')).lower()}`",
        "",
        "## Metrics",
        "",
        f"- mpdocvqa_evaluated_count: {summary.get('mpdocvqa_evaluated_count', 0)}",
        f"- mpdocvqa_answer_hit_rate: {summary.get('mpdocvqa_answer_hit_rate', 0.0)}",
        f"- mpdocvqa_citation_page_hit_rate: {summary.get('mpdocvqa_citation_page_hit_rate', 0.0)}",
        f"- retrieved_gold_page_hit_rate: {summary.get('retrieved_gold_page_hit_rate', 0.0)}",
        f"- selected_gold_page_hit_rate: {summary.get('selected_gold_page_hit_rate', 0.0)}",
        "",
        "## Buckets",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("bucket_counts") or {}).items())],
        "",
        "## Recommendation",
        "",
        f"- next_action: `{recommendation_payload.get('next_action')}`",
        f"- do_not_train_yet: `{str(recommendation_payload.get('do_not_train_yet')).lower()}`",
        f"- reason: {recommendation_payload.get('reason')}",
        "",
        "This inspection is diagnostic only. It does not run Qwen, start SFT, start GRPO, or tune against individual validation examples.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect MP-DocVQA attribution signals in an AnswerPolicy baseline run.")
    parser.add_argument("--run-dir", required=True, help="AnswerPolicy baseline artifact directory.")
    parser.add_argument("--mpdocvqa-db-path", help="Optional SQLite DB with MP-DocVQA EvidenceBlocks.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--sync-output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = inspect_mpdocvqa_attribution(
        run_dir=repo_path(args.run_dir) or Path(args.run_dir),
        output_root=repo_path(args.output_dir) or Path(args.output_dir),
        run_id=args.run_id,
        mpdocvqa_db_path=repo_path(args.mpdocvqa_db_path) if args.mpdocvqa_db_path else None,
        sync_output_root=repo_path(args.sync_output_dir) if args.sync_output_dir else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

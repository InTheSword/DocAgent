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


SCRIPT_VERSION = "mpdocvqa-full-workflow-compare-v1"
EVALUATION_SCOPE = "mpdocvqa_cli_full_workflow_compare_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_full_workflow_compare"


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
    return f"mpdocvqa_full_workflow_compare_{stamp}"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [row for row in read_jsonl(path) if isinstance(row, dict)]


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def count_bool(rows: list[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if bool(row.get(key)))


def run_identity(run_dir: Path, summary: dict[str, Any], result: dict[str, Any]) -> str:
    return str(summary.get("run_id") or result.get("run_id") or run_dir.name)


def compact_row(row: dict[str, Any], *, source_run_id: str, source_run_dir: Path, source_row_index: int) -> dict[str, Any]:
    return {
        "source_run_id": source_run_id,
        "source_run_dir": safe_relpath(source_run_dir),
        "source_row_index": source_row_index,
        "sample_id": str(row.get("sample_id") or ""),
        "doc_id": str(row.get("doc_id") or ""),
        "ingested_doc_id": str(row.get("ingested_doc_id") or ""),
        "source_document": str(row.get("source_document") or ""),
        "bucket": str(row.get("bucket") or ""),
        "pass_fail": str(row.get("pass_fail") or ""),
        "question": str(row.get("question") or ""),
        "answers": row.get("answers") or [],
        "gold_pages": row.get("gold_pages") or [],
        "task_type": str(row.get("task_type") or ""),
        "answer_hit": bool(row.get("answer_hit")),
        "retrieved_gold_page_hit": bool(row.get("retrieved_gold_page_hit")),
        "selected_gold_page_hit": bool(row.get("selected_gold_page_hit")),
        "citation_page_hit": bool(row.get("citation_page_hit")),
        "retrieved_gold_page_rank": row.get("retrieved_gold_page_rank"),
        "retrieved_pages": row.get("retrieved_pages") or [],
        "selected_pages": row.get("selected_pages") or [],
        "citation_pages": row.get("citation_pages") or [],
        "retrieval_candidate_count": int(row.get("retrieval_candidate_count") or 0),
        "citation_count": int(row.get("citation_count") or 0),
        "full_model_path": bool(row.get("full_model_path")),
        "used_llm_router": bool(row.get("used_llm_router")),
        "used_llm_query_rewriter": bool(row.get("used_llm_query_rewriter")),
        "used_qwen_answer_policy": bool(row.get("used_qwen_answer_policy")),
        "used_dense_retrieval": bool(row.get("used_dense_retrieval")),
        "used_reranker": bool(row.get("used_reranker")),
        "retriever_mode": str(row.get("retriever_mode") or ""),
    }


def summarize_run(run_dir: Path) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    summary = load_json(run_dir / "summary.json")
    result = load_json(run_dir / "result.json")
    rows = load_jsonl_rows(run_dir / "results.jsonl")
    missing = [
        safe_relpath(path)
        for path in (run_dir / "summary.json", run_dir / "result.json", run_dir / "results.jsonl")
        if not path.is_file()
    ]
    run_id = run_identity(run_dir, summary, result)
    compact_rows = [
        compact_row(row, source_run_id=run_id, source_run_dir=run_dir, source_row_index=index)
        for index, row in enumerate(rows)
    ]
    bucket_counts = Counter(str(row.get("bucket") or "") for row in compact_rows)
    evaluated = len(compact_rows)
    local_fact_rows = [row for row in compact_rows if row.get("task_type") == "local_fact_qa"]
    run_summary = {
        "source_run_id": run_id,
        "source_run_dir": safe_relpath(run_dir),
        "source_status": summary.get("status") or result.get("status") or "",
        "evaluated_count": evaluated,
        "cli_success_count": int(summary.get("cli_success_count") or 0),
        "cli_success_rate": float(summary.get("cli_success_rate") or rate(int(summary.get("cli_success_count") or 0), evaluated)),
        "local_fact_qa_count": len(local_fact_rows),
        "used_qwen_answer_policy_count": count_bool(compact_rows, "used_qwen_answer_policy"),
        "used_dense_retrieval_count": count_bool(compact_rows, "used_dense_retrieval"),
        "used_reranker_count": count_bool(compact_rows, "used_reranker"),
        "used_llm_query_rewriter_count": count_bool(compact_rows, "used_llm_query_rewriter"),
        "retrieved_gold_page_hit_count": count_bool(compact_rows, "retrieved_gold_page_hit"),
        "retrieved_gold_page_hit_rate": rate(count_bool(compact_rows, "retrieved_gold_page_hit"), evaluated),
        "selected_gold_page_hit_count": count_bool(compact_rows, "selected_gold_page_hit"),
        "selected_gold_page_hit_rate": rate(count_bool(compact_rows, "selected_gold_page_hit"), evaluated),
        "citation_page_hit_count": count_bool(compact_rows, "citation_page_hit"),
        "citation_page_hit_rate": rate(count_bool(compact_rows, "citation_page_hit"), evaluated),
        "answer_hit_count": count_bool(compact_rows, "answer_hit"),
        "answer_hit_rate": rate(count_bool(compact_rows, "answer_hit"), evaluated),
        "bucket_counts": dict(sorted(bucket_counts.items())),
    }
    return run_summary, compact_rows, missing


def recommendation(bucket_counts: Counter[str], run_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    cli_or_component_issue = any(
        run.get("cli_success_count", 0) != run.get("evaluated_count", 0)
        or run.get("used_qwen_answer_policy_count", 0) < run.get("local_fact_qa_count", 0)
        or run.get("used_dense_retrieval_count", 0) < run.get("local_fact_qa_count", 0)
        or run.get("used_reranker_count", 0) < run.get("local_fact_qa_count", 0)
        for run in run_summaries
    )
    if cli_or_component_issue:
        next_action = "inspect_cli_component_usage_before_more_eval"
    elif bucket_counts.get("retrieval_gold_page_miss", 0):
        next_action = "inspect_retrieval_query_or_block_granularity_before_training"
    elif bucket_counts.get("selected_context_gold_page_miss", 0):
        next_action = "inspect_context_selection_before_training"
    elif bucket_counts.get("citation_selection_page_miss", 0):
        next_action = "inspect_citation_selection_before_training"
    elif bucket_counts.get("answer_generation_or_metric_miss", 0):
        next_action = "review_mpdocvqa_answer_generation_or_metric_before_training"
    else:
        next_action = "continue_qwen_eval_before_training"
    return {
        "next_action": next_action,
        "do_not_train_yet": True,
        "reason": "This comparison reads existing MP-DocVQA full-workflow diagnostic artifacts only; it does not call Qwen, create training data, or claim benchmark acceptance.",
    }


def compare_mpdocvqa_full_workflow_runs(
    *,
    run_dirs: list[Path],
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    run_summaries: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for run_dir in run_dirs:
        summary, compact_rows, run_missing = summarize_run(run_dir.resolve())
        run_summaries.append(summary)
        rows.extend(compact_rows)
        missing.extend(run_missing)

    if missing:
        summary = {
            "command": "compare_mpdocvqa_full_workflow_runs",
            "status": "failed",
            "quality_status": "blocked",
            "run_id": run_id,
            "artifact_dir": safe_relpath(artifact_dir),
            "missing": missing,
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
        return write_outputs(artifact_dir=artifact_dir, summary=summary, run_summaries=run_summaries, rows=[], preview=[], sync_output_root=sync_output_root)

    bucket_counts = Counter(str(row.get("bucket") or "") for row in rows)
    evaluated = len(rows)
    unique_sample_ids = {str(row.get("sample_id") or "") for row in rows if str(row.get("sample_id") or "")}
    duplicate_sample_count = evaluated - len(unique_sample_ids)
    summary = {
        "command": "compare_mpdocvqa_full_workflow_runs",
        "status": "success" if evaluated else "failed",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "source_run_count": len(run_summaries),
        "source_runs": run_summaries,
        "evaluated_count": evaluated,
        "unique_sample_count": len(unique_sample_ids),
        "duplicate_sample_count": duplicate_sample_count,
        "cli_success_count": sum(int(run.get("cli_success_count") or 0) for run in run_summaries),
        "cli_success_rate": rate(sum(int(run.get("cli_success_count") or 0) for run in run_summaries), evaluated),
        "local_fact_qa_count": sum(int(run.get("local_fact_qa_count") or 0) for run in run_summaries),
        "used_qwen_answer_policy_count": count_bool(rows, "used_qwen_answer_policy"),
        "used_dense_retrieval_count": count_bool(rows, "used_dense_retrieval"),
        "used_reranker_count": count_bool(rows, "used_reranker"),
        "used_llm_query_rewriter_count": count_bool(rows, "used_llm_query_rewriter"),
        "retrieved_gold_page_hit_count": count_bool(rows, "retrieved_gold_page_hit"),
        "retrieved_gold_page_hit_rate": rate(count_bool(rows, "retrieved_gold_page_hit"), evaluated),
        "selected_gold_page_hit_count": count_bool(rows, "selected_gold_page_hit"),
        "selected_gold_page_hit_rate": rate(count_bool(rows, "selected_gold_page_hit"), evaluated),
        "citation_page_hit_count": count_bool(rows, "citation_page_hit"),
        "citation_page_hit_rate": rate(count_bool(rows, "citation_page_hit"), evaluated),
        "answer_hit_count": count_bool(rows, "answer_hit"),
        "answer_hit_rate": rate(count_bool(rows, "answer_hit"), evaluated),
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "used_qwen": True,
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "recommendation": recommendation(bucket_counts, run_summaries),
    }
    preview = [row for row in rows if row.get("bucket") != "passed"][:16]
    return write_outputs(
        artifact_dir=artifact_dir,
        summary=summary,
        run_summaries=run_summaries,
        rows=rows,
        preview=preview,
        sync_output_root=sync_output_root,
    )


def write_outputs(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
    run_summaries: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    preview: list[dict[str, Any]],
    sync_output_root: Path | None,
) -> dict[str, Any]:
    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "run_summaries": artifact_dir / "run_summaries.json",
        "rows": artifact_dir / "rows.jsonl",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }
    summary.update(
        {
            "summary_path": safe_relpath(paths["summary"]),
            "summary_markdown_path": safe_relpath(paths["summary_md"]),
            "run_summaries_path": safe_relpath(paths["run_summaries"]),
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
        "source_run_count": summary.get("source_run_count", 0),
        "evaluated_count": summary.get("evaluated_count", 0),
        "cli_success_rate": summary.get("cli_success_rate", 0.0),
        "retrieved_gold_page_hit_rate": summary.get("retrieved_gold_page_hit_rate", 0.0),
        "citation_page_hit_rate": summary.get("citation_page_hit_rate", 0.0),
        "answer_hit_rate": summary.get("answer_hit_rate", 0.0),
        "bucket_counts": summary.get("bucket_counts", {}),
        "recommendation": summary.get("recommendation", {}),
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_json(paths["run_summaries"], run_summaries)
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
        "# MP-DocVQA Full Workflow Run Comparison",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- source_run_count: {summary.get('source_run_count', 0)}",
        f"- evaluated_count: {summary.get('evaluated_count', 0)}",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary.get('validation_subset_used_for_training')).lower()}`",
        "",
        "## Aggregate Metrics",
        "",
        f"- cli_success_rate: {summary.get('cli_success_rate', 0.0)}",
        f"- retrieved_gold_page_hit_rate: {summary.get('retrieved_gold_page_hit_rate', 0.0)}",
        f"- selected_gold_page_hit_rate: {summary.get('selected_gold_page_hit_rate', 0.0)}",
        f"- citation_page_hit_rate: {summary.get('citation_page_hit_rate', 0.0)}",
        f"- answer_hit_rate: {summary.get('answer_hit_rate', 0.0)}",
        "",
        "## Buckets",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("bucket_counts") or {}).items())],
        "",
        "## Source Runs",
        "",
        *[
            f"- `{run.get('source_run_id')}`: evaluated={run.get('evaluated_count')}, retrieval={run.get('retrieved_gold_page_hit_rate')}, citation={run.get('citation_page_hit_rate')}, answer={run.get('answer_hit_rate')}"
            for run in summary.get("source_runs") or []
        ],
        "",
        "## Recommendation",
        "",
        f"- next_action: `{recommendation_payload.get('next_action')}`",
        f"- do_not_train_yet: `{str(recommendation_payload.get('do_not_train_yet')).lower()}`",
        f"- reason: {recommendation_payload.get('reason')}",
        "",
        "This comparison is diagnostic only. It does not call Qwen, start training, or create training data.",
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
    for key in ("result", "summary", "summary_md", "preview", "manifest", "run_summaries"):
        if paths[key].is_file():
            shutil.copy2(paths[key], sync_dir / paths[key].name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare MP-DocVQA CLI full-workflow diagnostic runs.")
    parser.add_argument("--run-dir", action="append", required=True, help="Diagnostic run directory. Repeat for multiple runs.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--sync-output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = compare_mpdocvqa_full_workflow_runs(
        run_dirs=[repo_path(path) or Path(path) for path in args.run_dir],
        output_root=repo_path(args.output_dir) or Path(args.output_dir),
        run_id=args.run_id,
        sync_output_root=repo_path(args.sync_output_dir) if args.sync_output_dir else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

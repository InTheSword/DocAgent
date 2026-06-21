from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from docagent.retrieval.candidate_answer_extraction import (
    bucket_candidate_answer_failures,
    build_candidate_answer_boards,
    build_topk_candidate_answer_boards,
    candidate_answer_artifact_has_gold_leakage,
    estimate_bucket_transitions,
    summarize_candidate_answer_coverage,
)
from docagent.utils.jsonl import read_jsonl, write_jsonl


A1_REFINED_BASELINE = {
    "candidate_answer_coverage_all": 0.5222,
    "candidate_answer_coverage_top1": 0.2222,
    "candidate_answer_coverage_top5": 0.3778,
    "candidate_answer_coverage_top20": 0.5000,
    "mean_candidate_answer_count": 105.2889,
    "mean_unique_candidate_answer_count": 52.2333,
    "mean_numeric_distractor_count": 73.7444,
    "bucket_D": 21,
    "bucket_F": 29,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Phase 4D-A candidate answer coverage.")
    parser.add_argument("--candidate-evidence", required=True, type=Path)
    parser.add_argument("--qa-jsonl", required=True, type=Path)
    parser.add_argument("--answer-results", type=Path)
    parser.add_argument("--page-retrieval-results", type=Path)
    parser.add_argument("--candidate-packing-metrics", type=Path)
    parser.add_argument("--phase4c-summary", type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def run_phase4d_candidate_answer_coverage(args: argparse.Namespace) -> dict[str, Any]:
    candidate_records = read_jsonl(args.candidate_evidence)
    qa_records = read_jsonl(args.qa_jsonl)
    answer_results = _read_optional_jsonl(args.answer_results)
    page_retrieval_rows = _read_optional_jsonl(args.page_retrieval_results)
    candidate_packing_metrics = _read_optional_json(args.candidate_packing_metrics)
    phase4c_summary = _read_optional_json(args.phase4c_summary)

    run_dir = args.output_root / args.run_id
    if run_dir.exists() and any(run_dir.iterdir()) and not args.force:
        raise FileExistsError(f"Output directory exists; pass --force to overwrite: {run_dir}")
    run_dir.mkdir(parents=True, exist_ok=True)

    top_k = max(1, int(args.top_k))
    answer_boards = build_candidate_answer_boards(candidate_records, top_k=top_k)
    topk_answer_boards = build_topk_candidate_answer_boards(answer_boards, top_k=top_k)
    no_gold_leakage = not candidate_answer_artifact_has_gold_leakage(answer_boards)
    metrics = summarize_candidate_answer_coverage(
        candidate_records=candidate_records,
        answer_boards=answer_boards,
        topk_answer_boards=topk_answer_boards,
        qa_records=qa_records,
    )
    buckets = bucket_candidate_answer_failures(
        candidate_records=candidate_records,
        answer_boards=answer_boards,
        qa_records=qa_records,
        page_retrieval_rows=page_retrieval_rows,
        answer_results=answer_results,
    )
    transition_estimate = estimate_bucket_transitions(buckets)
    refinement_comparison = _build_refinement_comparison(metrics, buckets)

    paths = {
        "candidate_answers": run_dir / "candidate_answers.jsonl",
        "candidate_answers_preview": run_dir / "candidate_answers_preview.json",
        "candidate_answers_topk": run_dir / "candidate_answers_topk.jsonl",
        "candidate_answers_topk_preview": run_dir / "candidate_answers_topk_preview.json",
        "candidate_answer_coverage_metrics": run_dir / "candidate_answer_coverage_metrics.json",
        "candidate_answer_error_buckets": run_dir / "candidate_answer_error_buckets.json",
        "bucket_transition_estimate": run_dir / "bucket_transition_estimate.json",
        "refinement_comparison": run_dir / "refinement_comparison.json",
        "summary": run_dir / "summary.json",
        "summary_md": run_dir / "summary.md",
    }
    write_jsonl(paths["candidate_answers"], answer_boards)
    _write_json(paths["candidate_answers_preview"], {"records": [_preview_board(board) for board in answer_boards[:3]]})
    write_jsonl(paths["candidate_answers_topk"], topk_answer_boards)
    _write_json(paths["candidate_answers_topk_preview"], {"records": [_preview_board(board) for board in topk_answer_boards[:3]]})
    _write_json(paths["candidate_answer_coverage_metrics"], metrics)
    _write_json(paths["candidate_answer_error_buckets"], buckets)
    _write_json(paths["bucket_transition_estimate"], transition_estimate)
    _write_json(paths["refinement_comparison"], refinement_comparison)

    summary = {
        "phase": "Phase 4D-A",
        "task": "candidate_answer_coverage_audit",
        "status": "success",
        "input_candidate_evidence": _path_for_summary(args.candidate_evidence),
        "input_qa_jsonl": _path_for_summary(args.qa_jsonl),
        "input_answer_results": _optional_path_for_summary(args.answer_results),
        "input_page_retrieval_results": _optional_path_for_summary(args.page_retrieval_results),
        "input_candidate_packing_metrics": _optional_path_for_summary(args.candidate_packing_metrics),
        "input_phase4c_summary": _optional_path_for_summary(args.phase4c_summary),
        "does_not_modify_reader": True,
        "does_not_run_answer_policy": True,
        "does_not_train": True,
        "top_k": top_k,
        "no_gold_leakage_in_candidate_answers": no_gold_leakage,
        "artifact_paths": {key: _relative_to(paths[key], run_dir) for key in paths},
        "metrics": {
            "sample_count": metrics["sample_count"],
            "candidate_span_answer_coverage": metrics["candidate_span_answer_coverage"],
            "candidate_answer_coverage": metrics["candidate_answer_coverage"],
            "candidate_answer_coverage_all": metrics["candidate_answer_coverage_all"],
            "candidate_answer_coverage_top1": metrics["candidate_answer_coverage_top1"],
            "candidate_answer_coverage_top3": metrics["candidate_answer_coverage_top3"],
            "candidate_answer_coverage_top5": metrics["candidate_answer_coverage_top5"],
            "candidate_answer_coverage_top10": metrics["candidate_answer_coverage_top10"],
            "candidate_answer_coverage_top20": metrics["candidate_answer_coverage_top20"],
            "mean_ranked_candidate_answer_count": metrics["mean_ranked_candidate_answer_count"],
            "mean_topk_unique_candidate_answer_count": metrics["mean_topk_unique_candidate_answer_count"],
            "mean_topk_numeric_candidate_count": metrics["mean_topk_numeric_candidate_count"],
            "mean_topk_same_type_distractor_count": metrics["mean_topk_same_type_distractor_count"],
            "topk_retention_ratio": metrics["topk_retention_ratio"],
            "topk_numeric_ratio": metrics["topk_numeric_ratio"],
            "no_candidate_answer_count": metrics["no_candidate_answer_count"],
            "candidate_answer_no_gold_leakage": metrics["candidate_answer_no_gold_leakage"],
        },
        "error_buckets": {
            "answer_results_status": buckets["answer_results_status"],
            "bucket_counts": buckets["bucket_counts"],
            "bucket_summary": buckets["bucket_summary"],
        },
        "phase4c_context": {
            "candidate_packing_metrics_status": "available" if candidate_packing_metrics is not None else "unavailable",
            "phase4c_summary_status": "available" if phase4c_summary is not None else "unavailable",
            "candidate_packing_sample_count": (candidate_packing_metrics or {}).get("sample_count"),
            "phase4c_evidence_packing_mode": (phase4c_summary or {}).get("evidence_packing_mode"),
            "phase4c_fixed_evidence_hash": (phase4c_summary or {}).get("fixed_evidence_hash"),
        },
    }
    _write_json(paths["summary"], summary)
    paths["summary_md"].write_text(_summary_markdown(summary), encoding="utf-8")
    return summary


def _read_optional_jsonl(path: Path | None) -> list[dict[str, Any]] | None:
    if path is None or not path.exists():
        return None
    return read_jsonl(path)


def _read_optional_json(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _build_refinement_comparison(metrics: dict[str, Any], buckets: dict[str, Any]) -> dict[str, Any]:
    current = {
        "candidate_answer_coverage_all": metrics.get("candidate_answer_coverage_all"),
        "candidate_answer_coverage_top1": metrics.get("candidate_answer_coverage_top1"),
        "candidate_answer_coverage_top5": metrics.get("candidate_answer_coverage_top5"),
        "candidate_answer_coverage_top20": metrics.get("candidate_answer_coverage_top20"),
        "mean_candidate_answer_count": metrics.get("mean_candidate_answer_count"),
        "mean_unique_candidate_answer_count": metrics.get("mean_unique_candidate_answer_count"),
        "mean_numeric_distractor_count": metrics.get("mean_numeric_distractor_count"),
        "bucket_D": (buckets.get("bucket_counts") or {}).get("D"),
        "bucket_F": (buckets.get("bucket_counts") or {}).get("F"),
    }
    deltas = {
        key: (current[key] - A1_REFINED_BASELINE[key])
        for key in A1_REFINED_BASELINE
        if isinstance(current.get(key), (int, float))
    }
    return {
        "baseline_name": "Phase 4D-A.1 refined server audit",
        "baseline": A1_REFINED_BASELINE,
        "current": current,
        "delta_vs_baseline": deltas,
        "interpretation_hint": "Positive coverage deltas are improvements; negative count/distractor deltas indicate less candidate noise.",
    }


def _preview_board(board: dict[str, Any]) -> dict[str, Any]:
    preview = {
        "qid": board.get("qid"),
        "doc_id": board.get("doc_id"),
        "question": board.get("question"),
        "question_hints": board.get("question_hints") or {},
        "candidate_answers": [],
        "answer_board_stats": board.get("answer_board_stats") or {},
    }
    for answer in (board.get("candidate_answers") or [])[:5]:
        item = dict(answer)
        item["evidence_text"] = _truncate(str(item.get("evidence_text") or ""), limit=220)
        preview["candidate_answers"].append(item)
    return preview


def _truncate(text: str, *, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _path_for_summary(path: Path) -> str:
    return _relative_to(path, Path.cwd())


def _optional_path_for_summary(path: Path | None) -> str | None:
    if path is None:
        return None
    return _path_for_summary(path)


def _relative_to(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _summary_markdown(summary: dict[str, Any]) -> str:
    metrics = summary["metrics"]
    bucket_counts = summary["error_buckets"]["bucket_counts"]
    return "\n".join(
        [
            "# Phase 4D-A Candidate Answer Coverage Audit",
            "",
            f"- status: {summary['status']}",
            f"- sample_count: {metrics['sample_count']}",
            f"- candidate_span_answer_coverage: {metrics['candidate_span_answer_coverage']:.4f}",
            f"- candidate_answer_coverage: {metrics['candidate_answer_coverage']:.4f}",
            f"- candidate_answer_coverage_top20: {metrics['candidate_answer_coverage_top20']:.4f}",
            f"- no_gold_leakage_in_candidate_answers: {summary['no_gold_leakage_in_candidate_answers']}",
            f"- top_k: {summary['top_k']}",
            f"- answer_results_status: {summary['error_buckets']['answer_results_status']}",
            f"- bucket_counts: {json.dumps(bucket_counts, sort_keys=True)}",
            "",
            "This audit does not modify Reader prompts, run AnswerPolicy, train models, or change retrieval.",
            "",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    summary = run_phase4d_candidate_answer_coverage(args)
    print(json.dumps({"status": summary["status"], "summary": summary["artifact_paths"]["summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

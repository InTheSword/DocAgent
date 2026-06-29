from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl


SCRIPT_VERSION = "answer-policy-baseline-review-v1"
EVALUATION_SCOPE = "answer_policy_baseline_review_not_formal_benchmark"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "answer_policy_baseline_review"


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
    return f"answer_policy_baseline_review_{stamp}"


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
    return [], "summary_only", ""


def _metrics(summary: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    result_metrics = result.get("metrics") if isinstance(result.get("metrics"), dict) else {}
    return {
        "case_count": _number(summary, result_metrics, "case_count"),
        "evaluated_count": _number(summary, result_metrics, "evaluated_count"),
        "passed_count": _number(summary, result_metrics, "passed_count"),
        "failed_count": _number(summary, result_metrics, "failed_count"),
        "skipped_count": _number(summary, result_metrics, "skipped_count"),
        "pass_rate": _number(summary, result_metrics, "pass_rate"),
        "tool_success_rate": _number(summary, result_metrics, "tool_success_rate"),
        "format_valid_rate": _number(summary, result_metrics, "format_valid_rate"),
        "location_valid_rate": _number(summary, result_metrics, "location_valid_rate"),
        "answer_hit_rate": _number(summary, result_metrics, "answer_hit_rate"),
        "citation_block_hit_rate": _number(summary, result_metrics, "citation_block_hit_rate"),
    }


def _number(primary: dict[str, Any], secondary: dict[str, Any], key: str) -> int | float:
    value = primary.get(key, secondary.get(key, 0))
    return value if isinstance(value, (int, float)) else 0


def _rate(value: Any) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def analyze_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    failure_reasons = Counter(reason for row in rows for reason in row.get("failure_reasons") or [])
    failure_stages = Counter(str(row.get("failure_stage") or "") for row in rows if row.get("failure_stage"))
    modes = Counter(str(row.get("evaluation_mode") or "") for row in rows if row.get("evaluation_mode"))
    parse_fail_count = 0
    repaired_parse_fail_count = 0
    unrepaired_parse_fail_count = 0
    invalid_citation_id_count = 0
    empty_citation_count = 0
    answer_miss_count = 0
    tool_failure_count = 0
    review_samples: list[dict[str, Any]] = []
    for row in rows:
        parse_result = row.get("parse_result") if isinstance(row.get("parse_result"), dict) else {}
        if parse_result and (parse_result.get("raw_json_ok") is False or parse_result.get("schema_ok") is False):
            parse_fail_count += 1
            if row.get("format_valid") is True:
                repaired_parse_fail_count += 1
            else:
                unrepaired_parse_fail_count += 1
        compact = row.get("final_answer_compact") if isinstance(row.get("final_answer_compact"), dict) else {}
        validation = compact.get("citation_validation") if isinstance(compact.get("citation_validation"), dict) else {}
        invalid_citation_id_count += len(validation.get("invalid_block_ids") or [])
        if row.get("citation_evaluated") and not row.get("citation_block_ids"):
            empty_citation_count += 1
        if "answer_miss" in (row.get("failure_reasons") or []):
            answer_miss_count += 1
        if row.get("tool_executed") and row.get("tool_status") not in {"", "success"}:
            tool_failure_count += 1
        if row.get("pass_fail") == "failed" and len(review_samples) < 10:
            review_samples.append(_review_sample(row))
    return {
        "row_count": len(rows),
        "failure_reason_distribution": dict(sorted(failure_reasons.items())),
        "failure_stage_distribution": dict(sorted(failure_stages.items())),
        "evaluation_mode_distribution": dict(sorted(modes.items())),
        "parse_fail_count_in_rows": parse_fail_count,
        "repaired_parse_fail_count_in_rows": repaired_parse_fail_count,
        "unrepaired_parse_fail_count_in_rows": unrepaired_parse_fail_count,
        "invalid_citation_id_count_in_rows": invalid_citation_id_count,
        "empty_citation_count_in_rows": empty_citation_count,
        "answer_miss_count_in_rows": answer_miss_count,
        "tool_failure_count_in_rows": tool_failure_count,
        "review_samples": review_samples,
    }


def _review_sample(row: dict[str, Any]) -> dict[str, Any]:
    compact = row.get("final_answer_compact") if isinstance(row.get("final_answer_compact"), dict) else {}
    return {
        "sample_id": row.get("sample_id"),
        "dataset": row.get("dataset"),
        "evaluation_mode": row.get("evaluation_mode"),
        "failure_stage": row.get("failure_stage"),
        "failure_reasons": row.get("failure_reasons") or [],
        "expected_tools": row.get("expected_tools") or [],
        "prediction_answer": row.get("prediction_answer") or compact.get("answer") or "",
        "answers": row.get("answers") or [],
        "citation_block_ids": row.get("citation_block_ids") or compact.get("citation_block_ids") or [],
        "tool_status": row.get("tool_status"),
        "raw_model_output_preview": row.get("raw_model_output_preview") or "",
    }


def training_gate(summary: dict[str, Any], result: dict[str, Any], row_analysis: dict[str, Any]) -> dict[str, Any]:
    metrics = _metrics(summary, result)
    used_qwen = bool(summary.get("used_qwen", result.get("used_qwen", False)))
    evaluated = int(metrics["evaluated_count"])
    reasons: list[str] = []
    baseline_status = str(summary.get("status") or result.get("status") or "success")
    if baseline_status != "success":
        reasons.append(f"baseline_status_{baseline_status}")
        return _gate("blocked_baseline_not_success", "blocked", "defer_until_successful_baseline", reasons)
    if not used_qwen:
        reasons.append("real_qwen_baseline_missing")
        return _gate("needs_real_qwen_baseline", "not_started", "defer_until_real_qwen_run", reasons)
    if evaluated <= 0:
        reasons.append("no_evaluated_cases")
        return _gate("blocked_no_evaluated_cases", "blocked", "defer_until_evaluated_cases_exist", reasons)
    if _rate(metrics["format_valid_rate"]) < 0.95:
        reasons.append("format_valid_rate_below_0.95")
        return _gate("prompt_or_parser_repair_before_training", "not_ready", "fix_output_format_or_parser_before_sft", reasons)
    if row_analysis.get("unrepaired_parse_fail_count_in_rows", row_analysis["parse_fail_count_in_rows"]) > 0:
        reasons.append("raw_json_or_schema_failures_present")
        return _gate("prompt_or_parser_repair_before_training", "not_ready", "fix_output_format_or_parser_before_sft", reasons)
    if row_analysis["parse_fail_count_in_rows"] > 0:
        reasons.append("raw_json_or_schema_failures_repaired_by_canonicalization")
    if _rate(metrics["citation_block_hit_rate"]) < 0.80:
        reasons.append("citation_block_hit_rate_below_0.80")
        return _gate("citation_contract_repair_before_training", "not_ready", "fix_citation_selection_before_sft", reasons)
    citation_miss_count = int((row_analysis.get("failure_reason_distribution") or {}).get("citation_block_miss") or 0)
    if row_analysis["invalid_citation_id_count_in_rows"] > 0 and (
        citation_miss_count > 0 or row_analysis["empty_citation_count_in_rows"] > 0
    ):
        reasons.append("invalid_model_selected_citation_ids_present")
        return _gate("citation_contract_repair_before_training", "not_ready", "fix_citation_allowlist_use_before_sft", reasons)
    if row_analysis["invalid_citation_id_count_in_rows"] > 0:
        reasons.append("invalid_model_selected_citation_ids_filtered_by_allowlist")
    if _rate(metrics["answer_hit_rate"]) < 0.50:
        reasons.append("answer_hit_rate_below_0.50")
        return _gate("sft_data_design_candidate", "candidate", "design_sft_data_from_failures_and_evidence_packs", reasons)
    if _rate(metrics["pass_rate"]) < 0.70:
        reasons.append("pass_rate_below_0.70")
        return _gate("sft_data_design_candidate", "candidate", "inspect_answer_and_attribution_failures_before_sft", reasons)
    reasons.append("baseline_contract_stable_enough_for_larger_qwen_eval")
    return _gate("continue_qwen_eval_before_training", "defer", "run_larger_real_qwen_baseline_or_manual_review", reasons)


def _gate(recommendation: str, sft_gate: str, next_action: str, reasons: list[str]) -> dict[str, Any]:
    return {
        "recommendation": recommendation,
        "sft_gate": sft_gate,
        "grpo_gate": "defer_until_sft_result",
        "next_action": next_action,
        "reasons": reasons,
        "quality_status": "diagnostic_only",
        "formal_benchmark_acceptance": False,
    }


def review_answer_policy_baseline(
    *,
    run_dir: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    summary = load_json(run_dir / "summary.json")
    result = load_json(run_dir / "result.json")
    rows, sample_scope, rows_path = load_rows(run_dir)
    source_run_id = str(summary.get("run_id") or result.get("run_id") or run_dir.name)
    if run_id:
        review_run_id = run_id
    elif source_run_id:
        review_run_id = f"review_{source_run_id}"
    else:
        review_run_id = now_run_id()
    artifact_dir = output_root / review_run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if not summary and not result and sample_scope == "summary_only":
        review = missing_artifacts_review(run_dir=run_dir, artifact_dir=artifact_dir, review_run_id=review_run_id, source_run_id=source_run_id)
        write_json(artifact_dir / "review.json", review)
        write_review_markdown(artifact_dir / "review.md", review)
        return {
            **review,
            "artifact_paths": [review["review_path"], review["review_markdown_path"]],
        }
    row_analysis = analyze_rows(rows)
    gate = training_gate(summary, result, row_analysis)
    metrics = _metrics(summary, result)
    review = {
        "command": "review_answer_policy_baseline",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "source_run_id": source_run_id,
        "source_run_dir": safe_relpath(run_dir),
        "sample_scope": sample_scope,
        "rows_path": rows_path,
        "run_id": review_run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "used_qwen": bool(summary.get("used_qwen", result.get("used_qwen", False))),
        "answer_policy_mode": summary.get("answer_policy_mode", result.get("answer_policy_mode", "")),
        "metrics": metrics,
        "summary_failure_reason_distribution": summary.get("failure_reason_distribution") or {},
        "summary_failure_stage_distribution": summary.get("failure_stage_distribution") or {},
        "row_analysis": row_analysis,
        "training_gate": gate,
        "review_path": safe_relpath(artifact_dir / "review.json"),
        "review_markdown_path": safe_relpath(artifact_dir / "review.md"),
    }
    write_json(artifact_dir / "review.json", review)
    write_review_markdown(artifact_dir / "review.md", review)
    return {
        **review,
        "artifact_paths": [review["review_path"], review["review_markdown_path"]],
    }


def missing_artifacts_review(*, run_dir: Path, artifact_dir: Path, review_run_id: str, source_run_id: str) -> dict[str, Any]:
    gate = _gate(
        "blocked_missing_baseline_artifacts",
        "blocked",
        "point_run_dir_to_full_baseline_artifacts_or_sync_bundle",
        ["missing_summary_json_result_json_and_rows"],
    )
    return {
        "command": "review_answer_policy_baseline",
        "status": "failed",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "blocked",
        "source_run_id": source_run_id,
        "source_run_dir": safe_relpath(run_dir),
        "sample_scope": "missing",
        "rows_path": "",
        "run_id": review_run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "used_qwen": False,
        "answer_policy_mode": "",
        "metrics": {},
        "summary_failure_reason_distribution": {},
        "summary_failure_stage_distribution": {},
        "row_analysis": analyze_rows([]),
        "training_gate": gate,
        "error": {
            "type": "missing_baseline_artifacts",
            "message": "Expected summary.json/result.json plus results.jsonl or failures_sample.jsonl in the run directory.",
        },
        "review_path": safe_relpath(artifact_dir / "review.json"),
        "review_markdown_path": safe_relpath(artifact_dir / "review.md"),
    }


def write_review_markdown(path: Path, review: dict[str, Any]) -> None:
    metrics = review.get("metrics") or {}
    gate = review.get("training_gate") or {}
    row_analysis = review.get("row_analysis") or {}
    lines = [
        "# AnswerPolicy Baseline Review",
        "",
        f"- source_run_id: `{review.get('source_run_id')}`",
        f"- sample_scope: `{review.get('sample_scope')}`",
        f"- used_qwen: `{str(review.get('used_qwen')).lower()}`",
        f"- answer_policy_mode: `{review.get('answer_policy_mode')}`",
        f"- recommendation: `{gate.get('recommendation')}`",
        f"- sft_gate: `{gate.get('sft_gate')}`",
        f"- grpo_gate: `{gate.get('grpo_gate')}`",
        f"- next_action: `{gate.get('next_action')}`",
        "",
        "## Metrics",
        "",
        f"- evaluated_count: {metrics.get('evaluated_count')}",
        f"- pass_rate: {metrics.get('pass_rate')}",
        f"- format_valid_rate: {metrics.get('format_valid_rate')}",
        f"- answer_hit_rate: {metrics.get('answer_hit_rate')}",
        f"- citation_block_hit_rate: {metrics.get('citation_block_hit_rate')}",
        f"- tool_success_rate: {metrics.get('tool_success_rate')}",
        "",
        "## Reasons",
        "",
        *[f"- {reason}" for reason in gate.get("reasons") or ["none"]],
        "",
        "## Failure Stages",
        "",
        *markdown_distribution(row_analysis.get("failure_stage_distribution") or review.get("summary_failure_stage_distribution") or {}),
        "",
        "## Review Samples",
        "",
    ]
    samples = row_analysis.get("review_samples") or []
    if not samples:
        lines.append("- none")
    for sample in samples[:10]:
        lines.extend(
            [
                f"- {sample.get('dataset')}:{sample.get('sample_id')} "
                f"stage={sample.get('failure_stage')} reasons={','.join(sample.get('failure_reasons') or [])}",
            ]
        )
    lines.extend(
        [
            "",
            "This review is diagnostic only. It does not mark benchmark acceptance, start SFT, or start GRPO.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def markdown_distribution(distribution: dict[str, Any]) -> list[str]:
    if not distribution:
        return ["- none"]
    return [f"- {key}: {value}" for key, value in sorted(distribution.items())]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review AnswerPolicy baseline artifacts and produce a diagnostic training gate.")
    parser.add_argument("--run-dir", required=True, help="AnswerPolicy baseline artifact directory or compact sync bundle.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = review_answer_policy_baseline(
        run_dir=repo_path(args.run_dir) or Path(args.run_dir),
        output_root=repo_path(args.output_dir) or DEFAULT_OUTPUT_ROOT,
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

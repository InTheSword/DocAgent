from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl


SCRIPT_VERSION = "answer-policy-sft-candidate-review-v1"
EVALUATION_SCOPE = "answer_policy_sft_candidate_review_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "answer_policy_candidate_review"


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
    return f"answer_policy_sft_candidate_review_{stamp}"


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_baseline_rows(run_dir: Path) -> tuple[list[dict[str, Any]], str, str]:
    results_path = run_dir / "results.jsonl"
    if results_path.is_file():
        return read_jsonl(results_path), "full_results", safe_relpath(results_path)
    failures_path = run_dir / "failures_sample.jsonl"
    if failures_path.is_file():
        return read_jsonl(failures_path), "failure_sample_only", safe_relpath(failures_path)
    return [], "missing", ""


def parse_assistant_target(record: dict[str, Any]) -> dict[str, Any]:
    messages = record.get("messages")
    if not isinstance(messages, list) or not messages:
        return {}
    last = messages[-1]
    if not isinstance(last, dict):
        return {}
    content = str(last.get("content") or "")
    try:
        parsed = json.loads(content)
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def source_sample_id(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return str(metadata.get("source_sample_id") or "")


def expected_tools_key(row: dict[str, Any]) -> str:
    tools = [str(item) for item in row.get("expected_tools") or []]
    return "+".join(tools) if tools else "<none>"


def tool_expected(values: list[Any]) -> bool:
    tools = {str(item) for item in values or []}
    return bool(tools.intersection({"table_lookup", "simple_calculation"}))


def build_failure_preview(rows: list[dict[str, Any]], candidate_by_sample: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for row in rows[:12]:
        sample_id = str(row.get("sample_id") or "")
        compact = row.get("final_answer_compact") if isinstance(row.get("final_answer_compact"), dict) else {}
        preview.append(
            {
                "sample_id": sample_id,
                "question": row.get("question"),
                "answers": row.get("answers"),
                "prediction_answer": row.get("prediction_answer"),
                "expected_answer_type": row.get("expected_answer_type"),
                "expected_tools": row.get("expected_tools") or [],
                "evaluation_mode": row.get("evaluation_mode"),
                "failure_reasons": row.get("failure_reasons") or [],
                "tool_status": row.get("tool_status"),
                "tool_answer": row.get("tool_answer"),
                "tool_citation_block_ids": row.get("tool_citation_block_ids") or [],
                "citation_block_ids": row.get("citation_block_ids") or [],
                "citation_validation": compact.get("citation_validation") if isinstance(compact, dict) else {},
                "candidate_record_available": sample_id in candidate_by_sample,
                "raw_model_output_preview": str(row.get("raw_model_output_preview") or "")[:500],
            }
        )
    return preview


def build_candidate_preview(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    preview: list[dict[str, Any]] = []
    for record in records[:12]:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        messages = record.get("messages") if isinstance(record.get("messages"), list) else []
        assistant_target = parse_assistant_target(record)
        user_text = ""
        if len(messages) >= 2 and isinstance(messages[1], dict):
            user_text = str(messages[1].get("content") or "")
        preview.append(
            {
                "record_id": record.get("id"),
                "source_sample_id": metadata.get("source_sample_id"),
                "dataset": metadata.get("dataset"),
                "evaluation_mode": metadata.get("evaluation_mode"),
                "failure_reasons": metadata.get("failure_reasons") or [],
                "expected_tools": metadata.get("expected_tools") or [],
                "prediction_answer": metadata.get("prediction_answer") or "",
                "gold_block_ids": metadata.get("gold_block_ids") or [],
                "tool_results_attached": metadata.get("tool_results_attached"),
                "selected_block_ids": metadata.get("selected_block_ids") or [],
                "dropped_block_ids": metadata.get("dropped_block_ids") or [],
                "assistant_target": {
                    "answer": assistant_target.get("answer"),
                    "reasoning_summary": assistant_target.get("reasoning_summary"),
                    "citation_block_ids": assistant_target.get("citation_block_ids") or [],
                    "evidence_used": assistant_target.get("evidence_used") or [],
                },
                "prompt_version": record.get("prompt_version"),
                "user_prompt_sha256": sha256_text(user_text) if user_text else "",
                "user_prompt_chars": len(user_text),
            }
        )
    return preview


def build_manual_review_rows(rows: list[dict[str, Any]], candidate_by_sample: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    manual_rows: list[dict[str, Any]] = []
    for row in rows:
        sample_id = str(row.get("sample_id") or "")
        record = candidate_by_sample.get(sample_id)
        metadata = record.get("metadata") if isinstance(record, dict) and isinstance(record.get("metadata"), dict) else {}
        manual_rows.append(
            {
                "sample_id": sample_id,
                "question": row.get("question"),
                "answers": row.get("answers"),
                "prediction_answer": row.get("prediction_answer"),
                "expected_answer_type": row.get("expected_answer_type"),
                "expected_tools": row.get("expected_tools") or [],
                "evaluation_mode": row.get("evaluation_mode"),
                "tool_status": row.get("tool_status"),
                "tool_answer": row.get("tool_answer"),
                "candidate_record_available": record is not None,
                "candidate_tool_results_attached": metadata.get("tool_results_attached"),
                "review_needed": "check_gold_answer_evidence_and_metric_normalization",
            }
        )
    return manual_rows


def candidate_quality_flags(records: list[dict[str, Any]], failed_without_candidate: list[str]) -> dict[str, Any]:
    missing_answer: list[str] = []
    missing_citation: list[str] = []
    tool_expected_without_tool_results: list[str] = []
    prompt_version_missing: list[str] = []
    for record in records:
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        sample_id = str(metadata.get("source_sample_id") or "")
        assistant_target = parse_assistant_target(record)
        if not str(assistant_target.get("answer") or "").strip():
            missing_answer.append(sample_id)
        if not assistant_target.get("citation_block_ids"):
            missing_citation.append(sample_id)
        if tool_expected(metadata.get("expected_tools") or []) and int(metadata.get("tool_results_attached") or 0) <= 0:
            tool_expected_without_tool_results.append(sample_id)
        if not record.get("prompt_version"):
            prompt_version_missing.append(sample_id)
    return {
        "candidate_missing_answer_count": len(missing_answer),
        "candidate_missing_answer_sample_ids": sorted(missing_answer),
        "candidate_missing_citation_count": len(missing_citation),
        "candidate_missing_citation_sample_ids": sorted(missing_citation),
        "tool_expected_without_tool_results_count": len(tool_expected_without_tool_results),
        "tool_expected_without_tool_results_sample_ids": sorted(tool_expected_without_tool_results),
        "prompt_version_missing_count": len(prompt_version_missing),
        "prompt_version_missing_sample_ids": sorted(prompt_version_missing),
        "failed_without_candidate_count": len(failed_without_candidate),
        "failed_without_candidate_sample_ids": sorted(failed_without_candidate),
    }


def recommendation(flags: dict[str, Any], record_count: int) -> dict[str, Any]:
    if record_count <= 0:
        return {
            "next_action": "blocked_no_sft_candidate_records",
            "do_not_train_yet": True,
            "reason": "No SFT candidate records were available for review.",
        }
    blocking_keys = [
        "candidate_missing_answer_count",
        "candidate_missing_citation_count",
        "tool_expected_without_tool_results_count",
        "prompt_version_missing_count",
    ]
    if any(int(flags.get(key) or 0) > 0 for key in blocking_keys):
        return {
            "next_action": "repair_sft_candidate_records_before_training",
            "do_not_train_yet": True,
            "reason": "Candidate records have missing target fields or missing tool context.",
        }
    return {
        "next_action": "manual_review_sft_candidates_before_training",
        "do_not_train_yet": True,
        "reason": "Candidate records exist, but answer misses must be checked for gold-answer/evidence quality, tool failure, and metric-normalization issues before training.",
    }


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files: list[dict[str, Any]] = []
    for artifact in artifact_paths:
        if not artifact.is_file():
            continue
        files.append({"path": safe_relpath(artifact), "size_bytes": artifact.stat().st_size})
    write_json(path, {"run_id": run_id, "script_version": SCRIPT_VERSION, "files": files})


def review_answer_policy_sft_candidates(
    *,
    baseline_run_dir: Path,
    candidate_run_dir: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    baseline_summary = load_json(baseline_run_dir / "summary.json")
    candidate_summary = load_json(candidate_run_dir / "summary.json")
    rows, rows_scope, rows_path = load_baseline_rows(baseline_run_dir)
    records_path = candidate_run_dir / "sft_candidates.jsonl"
    records = read_jsonl(records_path) if records_path.is_file() else []

    required = [baseline_run_dir / "summary.json", candidate_run_dir / "summary.json", records_path]
    missing = [safe_relpath(path) for path in required if not path.is_file()]
    if missing:
        summary = {
            "command": "review_answer_policy_sft_candidates",
            "status": "failed",
            "quality_status": "blocked",
            "run_id": run_id,
            "artifact_dir": safe_relpath(artifact_dir),
            "missing": missing,
            "used_training": False,
            "formal_benchmark_acceptance": False,
        }
        return write_outputs(artifact_dir=artifact_dir, summary=summary, failure_preview=[], candidate_preview=[], manual_review=[])

    failed_rows = [row for row in rows if row.get("dataset") == "tatqa" and row.get("pass_fail") == "failed"]
    answer_miss_rows = [row for row in failed_rows if "answer_miss" in (row.get("failure_reasons") or [])]
    candidate_by_sample = {source_sample_id(record): record for record in records if source_sample_id(record)}
    failed_ids = {str(row.get("sample_id") or "") for row in failed_rows}
    candidate_ids = set(candidate_by_sample)
    failed_without_candidate = sorted(failed_ids - candidate_ids)
    candidate_without_failed = sorted(candidate_ids - failed_ids)
    flags = candidate_quality_flags(records, failed_without_candidate)

    summary = {
        "command": "review_answer_policy_sft_candidates",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "baseline_run_id": baseline_summary.get("run_id"),
        "baseline_run_dir": safe_relpath(baseline_run_dir),
        "candidate_run_id": candidate_summary.get("run_id"),
        "candidate_run_dir": safe_relpath(candidate_run_dir),
        "rows_scope": rows_scope,
        "rows_path": rows_path,
        "baseline_metrics": {
            "case_count": baseline_summary.get("case_count"),
            "evaluated_count": baseline_summary.get("evaluated_count"),
            "pass_rate": baseline_summary.get("pass_rate"),
            "answer_hit_rate": baseline_summary.get("answer_hit_rate"),
            "citation_block_hit_rate": baseline_summary.get("citation_block_hit_rate"),
            "format_valid_rate": baseline_summary.get("format_valid_rate"),
            "failure_reason_distribution": baseline_summary.get("failure_reason_distribution"),
        },
        "candidate_summary": {
            "run_id": candidate_summary.get("run_id"),
            "record_count": candidate_summary.get("record_count", len(records)),
            "skip_reason_distribution": candidate_summary.get("skip_reason_distribution") or {},
            "candidate_failure_reason_distribution": candidate_summary.get("candidate_failure_reason_distribution") or {},
            "records_path": candidate_summary.get("records_path") or safe_relpath(records_path),
        },
        "failure_analysis": {
            "failed_tatqa_count": len(failed_rows),
            "answer_miss_count": len(answer_miss_rows),
            "failure_by_evaluation_mode": dict(Counter(str(row.get("evaluation_mode") or "") for row in failed_rows)),
            "failure_by_expected_answer_type": dict(Counter(str(row.get("expected_answer_type") or "") for row in failed_rows)),
            "failure_by_expected_tools": dict(Counter(expected_tools_key(row) for row in failed_rows)),
            "failure_by_tool_status": dict(Counter(str(row.get("tool_status") or "") for row in failed_rows)),
            "failed_sample_ids": sorted(failed_ids),
        },
        "candidate_alignment": {
            "candidate_record_count": len(records),
            "candidate_sample_ids": sorted(candidate_ids),
            "failed_without_candidate": failed_without_candidate,
            "candidate_without_failed": candidate_without_failed,
        },
        "candidate_quality_flags": flags,
        "recommendation": recommendation(flags, len(records)),
        "used_training": False,
        "formal_benchmark_acceptance": False,
    }
    return write_outputs(
        artifact_dir=artifact_dir,
        summary=summary,
        failure_preview=build_failure_preview(answer_miss_rows, candidate_by_sample),
        candidate_preview=build_candidate_preview(records),
        manual_review=build_manual_review_rows(answer_miss_rows, candidate_by_sample),
    )


def write_outputs(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
    failure_preview: list[dict[str, Any]],
    candidate_preview: list[dict[str, Any]],
    manual_review: list[dict[str, Any]],
) -> dict[str, Any]:
    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "failure_preview": artifact_dir / "failure_preview.json",
        "candidate_preview": artifact_dir / "candidate_preview.json",
        "manual_review": artifact_dir / "manual_review.jsonl",
        "manifest": artifact_dir / "manifest.json",
    }
    summary.update(
        {
            "summary_path": safe_relpath(paths["summary"]),
            "summary_markdown_path": safe_relpath(paths["summary_md"]),
            "failure_preview_path": safe_relpath(paths["failure_preview"]),
            "candidate_preview_path": safe_relpath(paths["candidate_preview"]),
            "manual_review_path": safe_relpath(paths["manual_review"]),
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
        "recommendation": summary.get("recommendation") or {},
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_json(paths["failure_preview"], failure_preview)
    write_json(paths["candidate_preview"], candidate_preview)
    write_jsonl(paths["manual_review"], manual_review)
    write_json(paths["result"], result)
    write_manifest(paths["manifest"], run_id=str(summary["run_id"]), artifact_paths=list(paths.values()))
    return {**result, **summary, "artifact_paths": [safe_relpath(path) for path in paths.values()]}


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    metrics = summary.get("baseline_metrics") or {}
    alignment = summary.get("candidate_alignment") or {}
    flags = summary.get("candidate_quality_flags") or {}
    recommendation_payload = summary.get("recommendation") or {}
    lines = [
        "# AnswerPolicy SFT Candidate Review",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- baseline_run_id: `{summary.get('baseline_run_id')}`",
        f"- candidate_run_id: `{summary.get('candidate_run_id')}`",
        f"- evaluated_count: {metrics.get('evaluated_count')}",
        f"- pass_rate: {metrics.get('pass_rate')}",
        f"- answer_hit_rate: {metrics.get('answer_hit_rate')}",
        f"- citation_block_hit_rate: {metrics.get('citation_block_hit_rate')}",
        f"- candidate_record_count: {alignment.get('candidate_record_count')}",
        f"- failed_without_candidate: {', '.join(alignment.get('failed_without_candidate') or []) or 'none'}",
        f"- candidate_without_failed: {', '.join(alignment.get('candidate_without_failed') or []) or 'none'}",
        "",
        "## Quality Flags",
        "",
        *[f"- {key}: {value}" for key, value in sorted(flags.items()) if key.endswith("_count")],
        "",
        "## Recommendation",
        "",
        f"- next_action: `{recommendation_payload.get('next_action')}`",
        f"- do_not_train_yet: `{str(recommendation_payload.get('do_not_train_yet')).lower()}`",
        f"- reason: {recommendation_payload.get('reason')}",
        "",
        "This review is diagnostic only. It does not start SFT, start GRPO, or claim benchmark acceptance.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review AnswerPolicy SFT candidate artifacts before any training.")
    parser.add_argument("--baseline-run-dir", required=True)
    parser.add_argument("--candidate-run-dir", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = review_answer_policy_sft_candidates(
        baseline_run_dir=repo_path(args.baseline_run_dir) or Path(args.baseline_run_dir),
        candidate_run_dir=repo_path(args.candidate_run_dir) or Path(args.candidate_run_dir),
        output_root=repo_path(args.output_dir) or DEFAULT_OUTPUT_ROOT,
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

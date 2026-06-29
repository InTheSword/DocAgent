from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl


SCRIPT_VERSION = "answer-policy-answer-miss-review-v1"
EVALUATION_SCOPE = "answer_policy_answer_miss_review_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "answer_policy_answer_miss_review"


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
    return f"answer_policy_answer_miss_review_{stamp}"


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


def normalize_answer_hint(value: Any) -> str:
    text = "" if value is None else str(value)
    text = text.lower().replace(",", "")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.%()-]+", " ", text)).strip()


def answer_overlap_hint(prediction: Any, answers: Any) -> bool:
    normalized_prediction = normalize_answer_hint(prediction)
    if not normalized_prediction:
        return False
    answer_values = answers if isinstance(answers, list) else [answers]
    for answer in answer_values:
        normalized_answer = normalize_answer_hint(answer)
        if normalized_answer and (normalized_answer in normalized_prediction or normalized_prediction in normalized_answer):
            return True
    return False


def final_answer(row: dict[str, Any]) -> str:
    if row.get("prediction_answer") is not None:
        return str(row.get("prediction_answer") or "")
    compact = row.get("final_answer_compact") if isinstance(row.get("final_answer_compact"), dict) else {}
    return str(compact.get("answer") or "")


def parse_failed(row: dict[str, Any]) -> bool:
    parse_result = row.get("parse_result") if isinstance(row.get("parse_result"), dict) else {}
    return bool(parse_result) and (parse_result.get("raw_json_ok") is False or parse_result.get("schema_ok") is False)


def classify_answer_miss(row: dict[str, Any]) -> str:
    expected_tools = [str(item) for item in row.get("expected_tools") or []]
    tool_status = str(row.get("tool_status") or "not_run")
    evaluation_mode = str(row.get("evaluation_mode") or "")
    if parse_failed(row) and row.get("format_valid") is True:
        return "repaired_parse_plus_answer_miss"
    if answer_overlap_hint(final_answer(row), row.get("answers") or []):
        return "answer_granularity_or_metric_review"
    if "simple_calculation" in expected_tools and tool_status == "success":
        return "calculation_reasoning_or_operand_review"
    if "table_lookup" in expected_tools and tool_status == "success":
        return "table_selection_or_column_review"
    if evaluation_mode == "answer_policy_generation" or tool_status == "not_run":
        return "model_extractive_precision_review"
    if tool_status not in {"", "success", "not_run"}:
        return "tool_execution_review"
    return "general_answer_miss_review"


def expected_tools_key(row: dict[str, Any]) -> str:
    tools = [str(item) for item in row.get("expected_tools") or []]
    return "+".join(tools) if tools else "none"


def compact_row(row: dict[str, Any], bucket: str) -> dict[str, Any]:
    return {
        "sample_id": row.get("sample_id"),
        "dataset": row.get("dataset"),
        "bucket": bucket,
        "evaluation_mode": row.get("evaluation_mode"),
        "expected_tools": row.get("expected_tools") or [],
        "tool_status": row.get("tool_status") or "not_run",
        "question": row.get("question"),
        "answers": row.get("answers") or [],
        "prediction_answer": final_answer(row),
        "format_valid": row.get("format_valid"),
        "citation_block_hit": row.get("citation_block_hit"),
        "citation_block_ids": row.get("citation_block_ids") or [],
        "failure_reasons": row.get("failure_reasons") or [],
    }


def recommendation(bucket_counts: dict[str, int]) -> dict[str, Any]:
    tool_count = sum(
        int(bucket_counts.get(key, 0))
        for key in ["calculation_reasoning_or_operand_review", "table_selection_or_column_review", "tool_execution_review"]
    )
    metric_count = int(bucket_counts.get("answer_granularity_or_metric_review", 0))
    generation_count = int(bucket_counts.get("model_extractive_precision_review", 0)) + int(
        bucket_counts.get("repaired_parse_plus_answer_miss", 0)
    )
    if tool_count > 0:
        next_action = "inspect_generic_tool_outputs_before_training"
    elif metric_count > 0:
        next_action = "inspect_metric_normalization_before_training"
    elif generation_count > 0:
        next_action = "continue_qwen_eval_or_prompt_review_before_training"
    else:
        next_action = "continue_qwen_eval_before_training"
    return {
        "next_action": next_action,
        "do_not_train_yet": True,
        "reason": "Use these buckets to choose generic tool, prompt, or metric work before any SFT/GRPO decision; do not tune against individual validation examples.",
    }


def review_answer_policy_answer_misses(
    *,
    run_dir: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary = load_json(run_dir / "summary.json")
    result = load_json(run_dir / "result.json")
    rows, rows_scope, rows_path = load_rows(run_dir)
    missing = [safe_relpath(path) for path in [run_dir / "summary.json", run_dir / "result.json"] if not path.is_file()]
    if rows_scope == "missing":
        missing.append("results.jsonl_or_failures_sample.jsonl")
    if missing:
        payload = {
            "command": "review_answer_policy_answer_misses",
            "status": "failed",
            "quality_status": "blocked",
            "run_id": run_id,
            "artifact_dir": safe_relpath(artifact_dir),
            "missing": missing,
            "used_training": False,
            "formal_benchmark_acceptance": False,
        }
        return write_outputs(artifact_dir=artifact_dir, summary=payload, miss_rows=[], preview=[])

    miss_rows = [row for row in rows if "answer_miss" in (row.get("failure_reasons") or [])]
    reviewed_rows = [{**compact_row(row, classify_answer_miss(row)), "source_row_index": index} for index, row in enumerate(miss_rows)]
    bucket_counts = Counter(str(row.get("bucket") or "") for row in reviewed_rows)
    evaluation_mode_counts = Counter(str(row.get("evaluation_mode") or "") for row in reviewed_rows)
    expected_tools_counts = Counter(expected_tools_key(row) for row in miss_rows)
    tool_status_counts = Counter(str(row.get("tool_status") or "not_run") for row in reviewed_rows)
    source_run_id = str(summary.get("run_id") or result.get("run_id") or run_dir.name)
    payload = {
        "command": "review_answer_policy_answer_misses",
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
        "used_qwen": bool(summary.get("used_qwen", result.get("used_qwen", False))),
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "case_count": summary.get("case_count"),
        "evaluated_count": summary.get("evaluated_count"),
        "pass_rate": summary.get("pass_rate"),
        "answer_hit_rate": summary.get("answer_hit_rate"),
        "citation_block_hit_rate": summary.get("citation_block_hit_rate"),
        "answer_miss_count": len(miss_rows),
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "evaluation_mode_counts": dict(sorted(evaluation_mode_counts.items())),
        "expected_tools_counts": dict(sorted(expected_tools_counts.items())),
        "tool_status_counts": dict(sorted(tool_status_counts.items())),
        "recommendation": recommendation(dict(bucket_counts)),
    }
    return write_outputs(artifact_dir=artifact_dir, summary=payload, miss_rows=reviewed_rows, preview=reviewed_rows[:12])


def write_outputs(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
    miss_rows: list[dict[str, Any]],
    preview: list[dict[str, Any]],
) -> dict[str, Any]:
    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "answer_miss_rows": artifact_dir / "answer_miss_rows.jsonl",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }
    summary.update(
        {
            "summary_path": safe_relpath(paths["summary"]),
            "summary_markdown_path": safe_relpath(paths["summary_md"]),
            "answer_miss_rows_path": safe_relpath(paths["answer_miss_rows"]),
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
        "answer_miss_count": summary.get("answer_miss_count", 0),
        "bucket_counts": summary.get("bucket_counts", {}),
        "recommendation": summary.get("recommendation", {}),
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_jsonl(paths["answer_miss_rows"], miss_rows)
    write_json(paths["preview"], preview)
    write_json(paths["result"], result)
    write_manifest(paths["manifest"], run_id=str(summary["run_id"]), artifact_paths=list(paths.values()))
    return {**result, **summary, "artifact_paths": [safe_relpath(path) for path in paths.values()]}


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
        "# AnswerPolicy Answer-Miss Review",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- source_run_id: `{summary.get('source_run_id')}`",
        f"- answer_miss_count: {summary.get('answer_miss_count', 0)}",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary.get('formal_benchmark_acceptance')).lower()}`",
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
        "This review is diagnostic only. It does not create training data, start SFT, start GRPO, or tune against individual validation examples.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Review AnswerPolicy answer_miss rows from a baseline artifact directory.")
    parser.add_argument("--run-dir", required=True, help="AnswerPolicy baseline artifact directory.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = review_answer_policy_answer_misses(
        run_dir=repo_path(args.run_dir) or Path(args.run_dir),
        output_root=repo_path(args.output_dir) or DEFAULT_OUTPUT_ROOT,
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

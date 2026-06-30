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


SCRIPT_VERSION = "answer-policy-tool-output-inspect-v1"
EVALUATION_SCOPE = "answer_policy_generic_tool_output_inspection_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "answer_policy_tool_output_inspect"
TABLE_TOOL_NAMES = {"table_lookup", "simple_calculation"}


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
    return f"answer_policy_tool_output_inspect_{stamp}"


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


def answer_overlap_hint(value: Any, answers: Any) -> bool:
    normalized_value = normalize_answer_hint(value)
    if not normalized_value:
        return False
    answer_values = answers if isinstance(answers, list) else [answers]
    for answer in answer_values:
        normalized_answer = normalize_answer_hint(answer)
        if normalized_answer and (normalized_answer in normalized_value or normalized_value in normalized_answer):
            return True
    return False


def expected_tools(row: dict[str, Any]) -> list[str]:
    return [str(item) for item in row.get("expected_tools") or []]


def expected_tools_key(row: dict[str, Any]) -> str:
    tools = expected_tools(row)
    return "+".join(tools) if tools else "none"


def expects_table_tool(row: dict[str, Any]) -> bool:
    return bool(TABLE_TOOL_NAMES.intersection(expected_tools(row)))


def first_tool_result(row: dict[str, Any]) -> dict[str, Any]:
    compact = row.get("tool_results_compact")
    if isinstance(compact, list):
        for item in compact:
            if isinstance(item, dict):
                return item
    return {}


def tool_answer(row: dict[str, Any]) -> str:
    direct = row.get("tool_answer")
    if direct not in (None, ""):
        return str(direct)
    compact = first_tool_result(row)
    return str(compact.get("answer") or "")


def prediction_answer(row: dict[str, Any]) -> str:
    if row.get("prediction_answer") is not None:
        return str(row.get("prediction_answer") or "")
    compact = row.get("final_answer_compact") if isinstance(row.get("final_answer_compact"), dict) else {}
    return str(compact.get("answer") or "")


def tool_status(row: dict[str, Any]) -> str:
    if row.get("tool_status") not in (None, ""):
        return str(row.get("tool_status"))
    compact = first_tool_result(row)
    return str(compact.get("status") or "not_run")


def tool_structured_result(row: dict[str, Any]) -> dict[str, Any]:
    compact = first_tool_result(row)
    structured = compact.get("structured_result") if isinstance(compact.get("structured_result"), dict) else {}
    return structured


def tool_operation(row: dict[str, Any]) -> str:
    structured = tool_structured_result(row)
    if structured.get("operation"):
        return str(structured.get("operation"))
    compact = first_tool_result(row)
    if compact.get("tool"):
        return str(compact.get("tool"))
    if "simple_calculation" in expected_tools(row):
        return "simple_calculation"
    if "table_lookup" in expected_tools(row):
        return "table_lookup"
    return ""


def tool_error_type(row: dict[str, Any]) -> str:
    compact = first_tool_result(row)
    error = compact.get("error") if isinstance(compact.get("error"), dict) else {}
    return str(row.get("tool_error_type") or error.get("type") or "")


def tool_warnings(row: dict[str, Any]) -> list[str]:
    compact = first_tool_result(row)
    warnings: list[Any] = []
    if isinstance(compact.get("warnings"), list):
        warnings.extend(compact.get("warnings") or [])
    if isinstance(row.get("tool_warnings"), list):
        warnings.extend(row.get("tool_warnings") or [])
    return sorted({str(item) for item in warnings if str(item)})


def tool_citation_block_ids(row: dict[str, Any]) -> list[str]:
    ids = [str(item) for item in row.get("tool_citation_block_ids") or [] if item]
    compact = first_tool_result(row)
    for citation in compact.get("citations") or []:
        if isinstance(citation, dict) and citation.get("block_id"):
            ids.append(str(citation["block_id"]))
    return sorted(set(ids))


def selected_table_summary(row: dict[str, Any]) -> dict[str, Any]:
    structured = tool_structured_result(row)
    selected = structured.get("selected_table") if isinstance(structured.get("selected_table"), dict) else {}
    return {
        key: selected.get(key)
        for key in ("doc_id", "page", "block_id", "block_type", "caption", "header", "row_count")
        if selected.get(key) not in (None, "", [], {})
    }


def selected_value_summary(row: dict[str, Any]) -> dict[str, Any]:
    structured = tool_structured_result(row)
    selected = structured.get("selected_value") if isinstance(structured.get("selected_value"), dict) else {}
    return {
        key: selected.get(key)
        for key in ("value", "raw_value", "column", "row_label")
        if selected.get(key) not in (None, "", [], {})
    }


def calculation_summary(row: dict[str, Any]) -> dict[str, Any]:
    structured = tool_structured_result(row)
    calculation = structured.get("calculation") if isinstance(structured.get("calculation"), dict) else {}
    inputs = structured.get("inputs") if isinstance(structured.get("inputs"), list) else []
    return {
        key: value
        for key, value in {
            "operation": calculation.get("operation"),
            "expression": calculation.get("expression"),
            "result_text": calculation.get("result_text"),
            "input_count": len(inputs),
            "input_labels": [str(item.get("label")) for item in inputs if isinstance(item, dict) and item.get("label")],
            "input_columns": [str(item.get("column")) for item in inputs if isinstance(item, dict) and item.get("column")],
        }.items()
        if value not in (None, "", [], {})
    }


def inspect_bucket(row: dict[str, Any]) -> str:
    status = tool_status(row)
    tool_text = tool_answer(row)
    prediction_hits = answer_overlap_hint(prediction_answer(row), row.get("answers") or [])
    tool_hits = answer_overlap_hint(tool_text, row.get("answers") or [])
    if not expects_table_tool(row):
        return "non_table_tool_answer_miss_excluded"
    if prediction_hits:
        return "metric_or_answer_granularity_review"
    if status == "not_run":
        return "tool_expected_but_not_run"
    if status != "success":
        return "tool_execution_or_unsupported"
    if not tool_text or not first_tool_result(row):
        return "tool_result_missing_or_empty"
    if tool_hits:
        return "model_did_not_use_correct_tool_output"
    if "simple_calculation" in expected_tools(row):
        return "generic_calculation_operand_or_operation_review"
    if "table_lookup" in expected_tools(row):
        return "generic_table_selection_or_column_review"
    return "generic_tool_output_review"


def compact_inspection_row(row: dict[str, Any], bucket: str) -> dict[str, Any]:
    answers = row.get("answers") or []
    return {
        "sample_id": row.get("sample_id"),
        "dataset": row.get("dataset"),
        "bucket": bucket,
        "question": row.get("question"),
        "answers": answers,
        "prediction_answer": prediction_answer(row),
        "tool_answer": tool_answer(row),
        "prediction_hits_gold_hint": answer_overlap_hint(prediction_answer(row), answers),
        "tool_hits_gold_hint": answer_overlap_hint(tool_answer(row), answers),
        "expected_answer_type": row.get("expected_answer_type"),
        "expected_tools": expected_tools(row),
        "evaluation_mode": row.get("evaluation_mode"),
        "tool_status": tool_status(row),
        "tool_operation": tool_operation(row),
        "tool_error_type": tool_error_type(row),
        "tool_warnings": tool_warnings(row),
        "tool_citation_block_ids": tool_citation_block_ids(row),
        "final_citation_block_ids": row.get("citation_block_ids") or [],
        "selected_table": selected_table_summary(row),
        "selected_value": selected_value_summary(row),
        "calculation": calculation_summary(row),
        "failure_reasons": row.get("failure_reasons") or [],
    }


def recommendation(summary: dict[str, Any]) -> dict[str, Any]:
    bucket_counts = summary.get("bucket_counts") or {}
    if int(bucket_counts.get("tool_execution_or_unsupported") or 0) or int(
        bucket_counts.get("tool_result_missing_or_empty") or 0
    ):
        next_action = "fix_generic_tool_execution_or_contract_before_training"
    elif int(bucket_counts.get("generic_calculation_operand_or_operation_review") or 0) or int(
        bucket_counts.get("generic_table_selection_or_column_review") or 0
    ):
        next_action = "inspect_generic_table_or_calculation_tool_outputs_before_training"
    elif int(bucket_counts.get("model_did_not_use_correct_tool_output") or 0):
        next_action = "inspect_answer_policy_tool_use_prompt_before_training"
    elif int(bucket_counts.get("metric_or_answer_granularity_review") or 0):
        next_action = "inspect_metric_normalization_before_training"
    else:
        next_action = "continue_qwen_eval_or_separate_training_data_design_review"
    return {
        "next_action": next_action,
        "do_not_train_yet": True,
        "reason": "Inspect generic tool-output, prompt-use, and metric issues before any SFT/GRPO decision. This script does not tune against validation examples or create training data.",
    }


def inspect_answer_policy_tool_outputs(
    *,
    run_dir: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
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
            "command": "inspect_answer_policy_tool_outputs",
            "status": "failed",
            "quality_status": "blocked",
            "run_id": run_id,
            "artifact_dir": safe_relpath(artifact_dir),
            "missing": missing,
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
        return write_outputs(artifact_dir=artifact_dir, summary=payload, inspected_rows=[], preview=[])

    answer_miss_rows = [row for row in rows if "answer_miss" in (row.get("failure_reasons") or [])]
    inspected_rows = [
        {**compact_inspection_row(row, inspect_bucket(row)), "source_row_index": index}
        for index, row in enumerate(answer_miss_rows)
        if expects_table_tool(row)
    ]
    all_buckets = Counter(inspect_bucket(row) for row in answer_miss_rows)
    inspected_buckets = Counter(str(row.get("bucket") or "") for row in inspected_rows)
    status_counts = Counter(str(row.get("tool_status") or "not_run") for row in inspected_rows)
    expected_counts = Counter(expected_tools_key(row) for row in inspected_rows)
    operation_counts = Counter(str(row.get("tool_operation") or "") for row in inspected_rows if row.get("tool_operation"))
    warning_counts = Counter(warning for row in inspected_rows for warning in row.get("tool_warnings") or [])
    error_type_counts = Counter(str(row.get("tool_error_type") or "") for row in inspected_rows if row.get("tool_error_type"))
    source_run_id = str(summary_json.get("run_id") or result_json.get("run_id") or run_dir.name)
    summary = {
        "command": "inspect_answer_policy_tool_outputs",
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
        "case_count": summary_json.get("case_count"),
        "evaluated_count": summary_json.get("evaluated_count"),
        "answer_miss_count": len(answer_miss_rows),
        "tool_expected_answer_miss_count": len(inspected_rows),
        "non_tool_answer_miss_count": len(answer_miss_rows) - len(inspected_rows),
        "bucket_counts": dict(sorted(inspected_buckets.items())),
        "all_answer_miss_bucket_counts": dict(sorted(all_buckets.items())),
        "expected_tools_counts": dict(sorted(expected_counts.items())),
        "tool_status_counts": dict(sorted(status_counts.items())),
        "tool_operation_counts": dict(sorted(operation_counts.items())),
        "tool_warning_counts": dict(sorted(warning_counts.items())),
        "tool_error_type_counts": dict(sorted(error_type_counts.items())),
        "tool_answer_gold_hit_hint_count": sum(1 for row in inspected_rows if row.get("tool_hits_gold_hint")),
        "tool_answer_gold_miss_hint_count": sum(1 for row in inspected_rows if not row.get("tool_hits_gold_hint")),
        "prediction_gold_overlap_hint_count": sum(1 for row in inspected_rows if row.get("prediction_hits_gold_hint")),
        "model_did_not_use_correct_tool_output_count": int(inspected_buckets.get("model_did_not_use_correct_tool_output") or 0),
        "generic_tool_output_review_count": int(
            inspected_buckets.get("generic_calculation_operand_or_operation_review") or 0
        )
        + int(inspected_buckets.get("generic_table_selection_or_column_review") or 0),
    }
    summary["recommendation"] = recommendation(summary)
    return write_outputs(artifact_dir=artifact_dir, summary=summary, inspected_rows=inspected_rows, preview=inspected_rows[:12])


def write_outputs(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
    inspected_rows: list[dict[str, Any]],
    preview: list[dict[str, Any]],
) -> dict[str, Any]:
    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "tool_output_rows": artifact_dir / "tool_output_rows.jsonl",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }
    summary.update(
        {
            "summary_path": safe_relpath(paths["summary"]),
            "summary_markdown_path": safe_relpath(paths["summary_md"]),
            "tool_output_rows_path": safe_relpath(paths["tool_output_rows"]),
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
        "answer_miss_count": summary.get("answer_miss_count", 0),
        "tool_expected_answer_miss_count": summary.get("tool_expected_answer_miss_count", 0),
        "bucket_counts": summary.get("bucket_counts", {}),
        "recommendation": summary.get("recommendation", {}),
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_jsonl(paths["tool_output_rows"], inspected_rows)
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
        "# AnswerPolicy Tool-Output Inspection",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- source_run_id: `{summary.get('source_run_id')}`",
        f"- answer_miss_count: {summary.get('answer_miss_count', 0)}",
        f"- tool_expected_answer_miss_count: {summary.get('tool_expected_answer_miss_count', 0)}",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary.get('formal_benchmark_acceptance')).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary.get('validation_subset_used_for_training')).lower()}`",
        "",
        "## Tool Buckets",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("bucket_counts") or {}).items())],
        "",
        "## Tool Status",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("tool_status_counts") or {}).items())],
        "",
        "## Recommendation",
        "",
        f"- next_action: `{recommendation_payload.get('next_action')}`",
        f"- do_not_train_yet: `{str(recommendation_payload.get('do_not_train_yet')).lower()}`",
        f"- reason: {recommendation_payload.get('reason')}",
        "",
        "This inspection is diagnostic only. It does not create training data, start SFT, start GRPO, or tune against individual validation examples.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect generic tool-output patterns in AnswerPolicy answer_miss rows.")
    parser.add_argument("--run-dir", required=True, help="AnswerPolicy baseline artifact directory.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = inspect_answer_policy_tool_outputs(
        run_dir=repo_path(args.run_dir) or Path(args.run_dir),
        output_root=repo_path(args.output_dir) or DEFAULT_OUTPUT_ROOT,
        run_id=args.run_id,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

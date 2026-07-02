from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "final_delivery_benchmark_gate_review"


def _now_run_id() -> str:
    return "final_delivery_benchmark_gate_review_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_summary_markdown(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Final Delivery Benchmark Gate Review",
        "",
        f"- status: `{result.get('status')}`",
        f"- gate_status: `{result.get('gate_status')}`",
        f"- run_id: `{result.get('run_id')}`",
        f"- formal_benchmark_acceptance: `{str(result.get('formal_benchmark_acceptance')).lower()}`",
        f"- validation_subset_used_for_training: `{str(result.get('validation_subset_used_for_training')).lower()}`",
        f"- used_training: `{str(result.get('used_training')).lower()}`",
        "",
        "## Steps",
        "",
    ]
    for name, status in result.get("step_statuses", {}).items():
        lines.append(f"- {name}: `{status}`")
    step_metrics = result.get("step_metrics") if isinstance(result.get("step_metrics"), dict) else {}
    if step_metrics:
        lines.extend(["", "## Step Metrics", ""])
        for name, metrics in step_metrics.items():
            if not isinstance(metrics, dict) or not metrics:
                continue
            compact = ", ".join(f"{key}={value}" for key, value in metrics.items() if not isinstance(value, dict))
            lines.append(f"- {name}: {compact or 'structured metrics only'}")
            bucket_counts = metrics.get("bucket_counts")
            if isinstance(bucket_counts, dict) and bucket_counts:
                lines.append(f"  - bucket_counts: `{json.dumps(bucket_counts, ensure_ascii=False)}`")
    lines.extend(
        [
            "",
            "## Manifest Checks",
            "",
            f"- local_manifest: `{(result.get('local_manifest') or {}).get('status')}`",
            f"- sync_manifest: `{(result.get('sync_manifest') or {}).get('status') if result.get('sync_manifest') is not None else 'not_checked'}`",
            "",
            "## Next Action",
            "",
            str(result.get("next_action") or ""),
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_manifest_entry(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def verify_manifest(manifest_path: Path) -> dict[str, Any]:
    if not manifest_path.is_file():
        return {
            "status": "failed",
            "manifest_path": safe_relpath(manifest_path),
            "checked_count": 0,
            "failures": [{"type": "missing_manifest", "path": safe_relpath(manifest_path)}],
        }
    manifest = read_json(manifest_path)
    failures: list[dict[str, Any]] = []
    checked_count = 0
    for item in manifest.get("files", []):
        path_text = str(item.get("path", ""))
        artifact_path = resolve_manifest_entry(path_text)
        if artifact_path.name == "manifest.json":
            failures.append({"type": "manifest_self_hash_present", "path": path_text})
            continue
        if not artifact_path.is_file():
            failures.append({"type": "missing_artifact", "path": path_text})
            continue
        checked_count += 1
        expected_size = item.get("byte_size")
        actual_size = artifact_path.stat().st_size
        if expected_size != actual_size:
            failures.append({"type": "byte_size_mismatch", "path": path_text, "expected": expected_size, "actual": actual_size})
        expected_sha = item.get("sha256")
        actual_sha = sha256_file(artifact_path)
        if expected_sha != actual_sha:
            failures.append({"type": "sha256_mismatch", "path": path_text, "expected": expected_sha, "actual": actual_sha})
    return {
        "status": "success" if not failures else "failed",
        "manifest_path": safe_relpath(manifest_path),
        "checked_count": checked_count,
        "failure_count": len(failures),
        "failures": failures,
    }


def _step_metrics(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    metrics_by_step: dict[str, dict[str, Any]] = {}
    for step in summary.get("steps", []):
        if not isinstance(step, dict):
            continue
        name = str(step.get("name") or "")
        if not name:
            continue
        metrics = step.get("metrics")
        metrics_by_step[name] = metrics if isinstance(metrics, dict) else {}
    return metrics_by_step


def _step_artifact_refs(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    for step in summary.get("steps", []):
        if not isinstance(step, dict):
            continue
        name = str(step.get("name") or "")
        if not name:
            continue
        refs[name] = {
            "parsed_command": step.get("parsed_command"),
            "parsed_status": step.get("parsed_status"),
            "returncode": step.get("returncode"),
            "parse_error": step.get("parse_error"),
            "artifact_paths": step.get("artifact_paths") if isinstance(step.get("artifact_paths"), list) else [],
            "sync_bundle_path": step.get("sync_bundle_path"),
        }
    return refs


def _metric_number(metrics: dict[str, Any], key: str) -> float | None:
    value = metrics.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _component_usage_review(mpdocvqa_metrics: dict[str, Any]) -> dict[str, Any]:
    local_fact_count = _metric_number(mpdocvqa_metrics, "local_fact_qa_count")
    evaluated_count = _metric_number(mpdocvqa_metrics, "evaluated_count")
    bucket_counts = mpdocvqa_metrics.get("bucket_counts") if isinstance(mpdocvqa_metrics.get("bucket_counts"), dict) else {}
    non_local_fact_count = _metric_number(bucket_counts, "task_type_not_local_fact_qa")
    if local_fact_count is not None:
        expected_count = local_fact_count
        expected_count_source = "local_fact_qa_count"
    elif evaluated_count is not None and non_local_fact_count is not None:
        expected_count = max(0.0, evaluated_count - non_local_fact_count)
        expected_count_source = "evaluated_count_minus_task_type_not_local_fact_qa"
    else:
        expected_count = evaluated_count
        expected_count_source = "evaluated_count"
    component_keys = {
        "qwen_answer_policy": "used_qwen_answer_policy_count",
        "dense_retrieval": "used_dense_retrieval_count",
        "reranker": "used_reranker_count",
        "llm_query_rewriter": "used_llm_query_rewriter_count",
    }
    component_counts: dict[str, Any] = {}
    incomplete: list[str] = []
    missing: list[str] = []
    for label, metric_key in component_keys.items():
        count = _metric_number(mpdocvqa_metrics, metric_key)
        component_counts[label] = count
        if count is None:
            missing.append(label)
        if expected_count is not None and count is not None and count < expected_count:
            incomplete.append(label)
    cli_success_rate = _metric_number(mpdocvqa_metrics, "cli_success_rate")
    return {
        "expected_component_count": expected_count,
        "expected_component_count_source": expected_count_source,
        "component_counts": component_counts,
        "missing_component_metrics": missing,
        "incomplete_components": incomplete,
        "cli_success_rate": cli_success_rate,
        "cli_success_complete": cli_success_rate is None or cli_success_rate >= 1.0,
        "full_component_metrics_present": not missing,
    }


def _metric_review(summary: dict[str, Any], failures: list[str]) -> dict[str, Any]:
    step_metrics = _step_metrics(summary)
    answer_metrics = step_metrics.get("answer_policy_baseline", {})
    mpdocvqa_metrics = step_metrics.get("mpdocvqa_full_workflow", {})
    component_review = _component_usage_review(mpdocvqa_metrics)
    answer_hit_rate = _metric_number(answer_metrics, "answer_hit_rate")
    mpdocvqa_answer_hit_rate = _metric_number(mpdocvqa_metrics, "answer_hit_rate")
    mpdocvqa_retrieval_hit_rate = _metric_number(mpdocvqa_metrics, "retrieved_gold_page_hit_rate")
    metric_gaps: list[str] = []
    for name in ("answer_policy_baseline", "mpdocvqa_full_workflow"):
        if name in {str(step.get("name") or "") for step in summary.get("steps", []) if isinstance(step, dict)} and not step_metrics.get(name):
            metric_gaps.append(name)
    if mpdocvqa_metrics and component_review["missing_component_metrics"]:
        metric_gaps.append("mpdocvqa_full_workflow_component_usage")
    if failures:
        next_action = "fix_gate_artifact_contract_or_rerun_gate"
    elif component_review["missing_component_metrics"]:
        next_action = "rerun_gate_with_component_metric_contract_before_benchmark"
    elif component_review["incomplete_components"] or not component_review["cli_success_complete"]:
        next_action = "inspect_full_workflow_component_usage_before_benchmark"
    elif metric_gaps:
        next_action = "review_raw_step_artifacts_or_rerun_gate_with_metric_contract"
    else:
        next_action = "review_answer_quality_metrics_before_formal_benchmark_or_training"
    return {
        "answer_policy": {
            "evaluated_count": answer_metrics.get("evaluated_count"),
            "pass_rate": answer_metrics.get("pass_rate"),
            "answer_hit_rate": answer_hit_rate,
            "citation_block_hit_rate": answer_metrics.get("citation_block_hit_rate"),
            "format_valid_rate": answer_metrics.get("format_valid_rate"),
            "failure_reason_distribution": answer_metrics.get("failure_reason_distribution", {}),
        },
        "mpdocvqa_full_workflow": {
            "evaluated_count": mpdocvqa_metrics.get("evaluated_count"),
            "cli_success_rate": mpdocvqa_metrics.get("cli_success_rate"),
            "retrieved_gold_page_hit_rate": mpdocvqa_retrieval_hit_rate,
            "citation_page_hit_rate": mpdocvqa_metrics.get("citation_page_hit_rate"),
            "answer_hit_rate": mpdocvqa_answer_hit_rate,
            "bucket_counts": mpdocvqa_metrics.get("bucket_counts", {}),
            "component_usage": component_review,
        },
        "metric_gaps": metric_gaps,
        "recommendation": {
            "next_action": next_action,
            "do_not_train_yet": True,
            "reason": (
                "This review reads final-delivery gate artifacts only. It checks child-step metrics, "
                "workflow component-use signals, and safety flags before any formal benchmark or training decision."
            ),
        },
    }


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files = []
    for artifact in artifact_paths:
        if artifact.is_file():
            files.append({"path": safe_relpath(artifact), "byte_size": artifact.stat().st_size, "sha256": sha256_file(artifact)})
    write_json(
        path,
        {
            "run_id": run_id,
            "script_version": "final-delivery-benchmark-gate-inspector-v1",
            "files": files,
        },
    )


def inspect_gate(run_dir: Path, *, sync_bundle_dir: Path | None = None) -> dict[str, Any]:
    summary_path = run_dir / "summary.json"
    result_path = run_dir / "result.json"
    manifest_path = run_dir / "manifest.json"
    missing = [safe_relpath(path) for path in [summary_path, result_path, manifest_path] if not path.is_file()]
    summary = read_json(summary_path) if summary_path.is_file() else {}
    result = read_json(result_path) if result_path.is_file() else {}
    local_manifest = verify_manifest(manifest_path)

    resolved_sync_dir = sync_bundle_dir
    if resolved_sync_dir is None and isinstance(summary.get("sync_bundle_path"), str) and summary["sync_bundle_path"]:
        resolved_sync_dir = repo_path(summary["sync_bundle_path"])
    sync_manifest = None
    if resolved_sync_dir is not None:
        sync_manifest = verify_manifest(resolved_sync_dir / "manifest.json")

    step_statuses = {str(step.get("name", "")): step.get("status") for step in summary.get("steps", [])}
    safety_flags = {
        "formal_benchmark_acceptance": summary.get("formal_benchmark_acceptance"),
        "validation_subset_used_for_training": summary.get("validation_subset_used_for_training"),
        "used_training": summary.get("used_training"),
        "used_vlm": summary.get("used_vlm"),
    }
    failures: list[str] = []
    if missing:
        failures.append("missing_required_artifacts")
    if summary.get("status") != result.get("status"):
        failures.append("summary_result_status_mismatch")
    if local_manifest["status"] != "success":
        failures.append("local_manifest_failed")
    if sync_manifest is not None and sync_manifest["status"] != "success":
        failures.append("sync_manifest_failed")
    if safety_flags["formal_benchmark_acceptance"] is not False:
        failures.append("formal_benchmark_acceptance_not_false")
    if safety_flags["validation_subset_used_for_training"] is not False:
        failures.append("validation_subset_used_for_training_not_false")
    if safety_flags["used_training"] is not False:
        failures.append("used_training_not_false")

    step_metrics = _step_metrics(summary)
    step_artifact_refs = _step_artifact_refs(summary)
    metric_review = _metric_review(summary, failures)
    next_action = metric_review["recommendation"]["next_action"] if not failures else "fix_gate_artifact_contract_or_rerun_gate"

    return {
        "command": "inspect_final_delivery_benchmark_gate",
        "status": "success" if not failures else "failed",
        "quality_status": "artifact_review_only",
        "run_dir": safe_relpath(run_dir),
        "gate_status": summary.get("status"),
        "run_id": summary.get("run_id") or result.get("run_id"),
        "step_statuses": step_statuses,
        "step_metrics": step_metrics,
        "step_artifact_refs": step_artifact_refs,
        "metric_review": metric_review,
        "successful_step_count": summary.get("successful_step_count"),
        "step_count": summary.get("step_count"),
        "used_qwen": summary.get("used_qwen"),
        **safety_flags,
        "formal_benchmark_acceptance_reviewed": safety_flags["formal_benchmark_acceptance"] is False,
        "validation_subset_used_for_training_reviewed": safety_flags["validation_subset_used_for_training"] is False,
        "used_training_reviewed": safety_flags["used_training"] is False,
        "local_manifest": local_manifest,
        "sync_manifest": sync_manifest,
        "missing": missing,
        "failures": failures,
        "next_action": next_action,
        "used_vlm": summary.get("used_vlm"),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect final-delivery benchmark gate artifacts without rerunning models.")
    parser.add_argument("--run-dir", required=True, help="Gate artifact directory containing result.json, summary.json, and manifest.json.")
    parser.add_argument("--sync-bundle-dir", help="Optional sync bundle directory to verify instead of the summary-declared sync path.")
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run_id = args.run_id or _now_run_id()
    output_dir = (repo_path(args.output_dir) or Path(args.output_dir)) / run_id
    run_dir = repo_path(args.run_dir) or Path(args.run_dir)
    sync_bundle_dir = repo_path(args.sync_bundle_dir) if args.sync_bundle_dir else None
    result = inspect_gate(run_dir, sync_bundle_dir=sync_bundle_dir)
    result["artifact_dir"] = safe_relpath(output_dir)
    result_path = output_dir / "result.json"
    summary_path = output_dir / "summary.json"
    summary_markdown_path = output_dir / "summary.md"
    manifest_path = output_dir / "manifest.json"
    write_json(result_path, result)
    write_json(summary_path, result)
    write_summary_markdown(summary_markdown_path, result)
    write_manifest(manifest_path, run_id=str(result.get("run_id") or run_id), artifact_paths=[result_path, summary_path, summary_markdown_path])
    result["artifact_paths"] = [safe_relpath(path) for path in [result_path, summary_path, summary_markdown_path, manifest_path]]
    write_json(result_path, result)
    write_json(summary_path, result)
    write_summary_markdown(summary_markdown_path, result)
    write_manifest(manifest_path, run_id=str(result.get("run_id") or run_id), artifact_paths=[result_path, summary_path, summary_markdown_path])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

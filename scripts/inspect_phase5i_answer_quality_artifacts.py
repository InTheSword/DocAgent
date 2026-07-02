from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "phase5i_answer_quality_review"
REQUIRED_ARTIFACTS = {
    "phase5i_cases.jsonl",
    "phase5i_results.jsonl",
    "phase5i_summary.json",
    "preview.json",
    "manual_review.md",
    "metrics.json",
    "predictions.jsonl",
    "case_reports.jsonl",
    "failure_analysis.md",
    "acceptance_report.json",
    "training_candidates_raw.jsonl",
}


def _now_run_id() -> str:
    return "phase5i_answer_quality_review_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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
            "failure_count": 1,
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
        "manifest": manifest,
    }


def _line_count(path: Path) -> int:
    if not path.is_file():
        return 0
    return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())


def _empty_or_missing(path: Path) -> bool:
    return not path.is_file() or not path.read_text(encoding="utf-8").strip()


def _artifact_names(manifest_review: dict[str, Any]) -> set[str]:
    manifest = manifest_review.get("manifest") if isinstance(manifest_review.get("manifest"), dict) else {}
    names = set()
    for item in manifest.get("files", []):
        if isinstance(item, dict):
            names.add(Path(str(item.get("path") or "")).name)
    return names


def _safe_flag(value: Any) -> bool:
    return value is False


def inspect_phase5i_answer_quality_run(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "manifest.json"
    manifest_review = verify_manifest(manifest_path)
    summary_path = run_dir / "phase5i_summary.json"
    metrics_path = run_dir / "metrics.json"
    acceptance_path = run_dir / "acceptance_report.json"
    training_candidates_path = run_dir / "training_candidates_raw.jsonl"

    missing_artifacts = sorted(REQUIRED_ARTIFACTS - _artifact_names(manifest_review))
    summary = read_json(summary_path) if summary_path.is_file() else {}
    metrics = read_json(metrics_path) if metrics_path.is_file() else {}
    acceptance = read_json(acceptance_path) if acceptance_path.is_file() else {}

    failures: list[str] = []
    if manifest_review["status"] != "success":
        failures.append("manifest_failed")
    if missing_artifacts:
        failures.append("required_artifacts_missing_from_manifest")
    if not _safe_flag(summary.get("formal_benchmark_acceptance")):
        failures.append("summary_formal_benchmark_acceptance_not_false")
    if not _safe_flag(summary.get("validation_subset_used_for_training")):
        failures.append("summary_validation_subset_used_for_training_not_false")
    if not _safe_flag(summary.get("used_training")):
        failures.append("summary_used_training_not_false")
    if not _safe_flag(acceptance.get("formal_benchmark_acceptance")):
        failures.append("acceptance_formal_benchmark_acceptance_not_false")
    if not _safe_flag(acceptance.get("validation_subset_used_for_training")):
        failures.append("acceptance_validation_subset_used_for_training_not_false")
    if not _empty_or_missing(training_candidates_path):
        failures.append("training_candidates_raw_not_empty")
    if summary.get("run_id") and acceptance.get("run_id") and summary.get("run_id") != acceptance.get("run_id"):
        failures.append("summary_acceptance_run_id_mismatch")
    if summary.get("run_id") and metrics.get("run_id") and summary.get("run_id") != metrics.get("run_id"):
        failures.append("summary_metrics_run_id_mismatch")
    if summary.get("final_answer_quality_evaluated") != metrics.get("final_answer_quality_evaluated"):
        failures.append("summary_metrics_final_answer_quality_flag_mismatch")

    final_answer_evaluated = bool(summary.get("final_answer_quality_evaluated"))
    next_action = (
        "fix_phase5i_answer_quality_artifact_contract"
        if failures
        else "review_answer_quality_metrics_before_formal_benchmark_or_training"
        if final_answer_evaluated
        else "run_phase5ib_server_answer_quality_probe_when_ready"
    )
    return {
        "command": "inspect_phase5i_answer_quality_artifacts",
        "status": "success" if not failures else "failed",
        "quality_status": "artifact_review_only",
        "run_dir": safe_relpath(run_dir),
        "run_id": summary.get("run_id") or acceptance.get("run_id") or metrics.get("run_id"),
        "evaluation_scope": summary.get("evaluation_scope") or metrics.get("evaluation_scope"),
        "final_answer_quality_evaluated": summary.get("final_answer_quality_evaluated"),
        "case_count": summary.get("case_count"),
        "passed_count": summary.get("passed_count"),
        "failed_count": summary.get("failed_count"),
        "metrics": {
            "final_answer_evaluated_count": metrics.get("final_answer_evaluated_count"),
            "answer_correct_rate": metrics.get("answer_correct_rate"),
            "format_valid_rate": metrics.get("format_valid_rate"),
            "citation_valid_rate": metrics.get("citation_valid_rate"),
            "location_valid_rate": metrics.get("location_valid_rate"),
        },
        "artifact_counts": {
            "prediction_count": _line_count(run_dir / "predictions.jsonl"),
            "case_report_count": _line_count(run_dir / "case_reports.jsonl"),
            "training_candidate_raw_count": _line_count(training_candidates_path),
        },
        "formal_benchmark_acceptance": summary.get("formal_benchmark_acceptance"),
        "validation_subset_used_for_training": summary.get("validation_subset_used_for_training"),
        "used_training": summary.get("used_training"),
        "used_vlm": summary.get("used_vlm"),
        "manifest_review": {k: v for k, v in manifest_review.items() if k != "manifest"},
        "missing_artifacts": missing_artifacts,
        "failures": failures,
        "next_action": next_action,
        "recommendation": {
            "next_action": next_action,
            "do_not_train_yet": True,
            "reason": (
                "This review validates Phase 5I-B answer-quality artifacts, manifest hashes, "
                "and safety flags only. It does not call models, create training data, or claim formal benchmark acceptance."
            ),
        },
    }


def write_summary_markdown(path: Path, result: dict[str, Any]) -> None:
    lines = [
        "# Phase 5I-B Answer Quality Artifact Review",
        "",
        f"- status: `{result.get('status')}`",
        f"- run_id: `{result.get('run_id')}`",
        f"- evaluation_scope: `{result.get('evaluation_scope')}`",
        f"- final_answer_quality_evaluated: `{str(result.get('final_answer_quality_evaluated')).lower()}`",
        f"- formal_benchmark_acceptance: `{str(result.get('formal_benchmark_acceptance')).lower()}`",
        f"- validation_subset_used_for_training: `{str(result.get('validation_subset_used_for_training')).lower()}`",
        f"- used_training: `{str(result.get('used_training')).lower()}`",
        "",
        "## Metrics",
        "",
    ]
    for key, value in (result.get("metrics") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "## Manifest",
            "",
            f"- status: `{(result.get('manifest_review') or {}).get('status')}`",
            f"- checked_count: `{(result.get('manifest_review') or {}).get('checked_count')}`",
            "",
            "## Next Action",
            "",
            str(result.get("next_action") or ""),
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files = []
    for artifact_path in artifact_paths:
        if artifact_path.is_file():
            files.append({"path": safe_relpath(artifact_path), "byte_size": artifact_path.stat().st_size, "sha256": sha256_file(artifact_path)})
    write_json(path, {"run_id": run_id, "script_version": "phase5i-answer-quality-artifact-inspector-v1", "files": files})


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Phase 5I-B answer-quality artifacts without rerunning models.")
    parser.add_argument("--run-dir", required=True, help="Phase 5I-B artifact directory containing phase5i_summary.json and manifest.json.")
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    run_dir = repo_path(args.run_dir) or Path(args.run_dir)
    result = inspect_phase5i_answer_quality_run(run_dir)
    run_id = args.run_id or f"{result.get('run_id') or _now_run_id()}_review"
    artifact_dir = (repo_path(args.output_dir) or Path(args.output_dir)) / run_id
    result_path = artifact_dir / "result.json"
    summary_path = artifact_dir / "summary.json"
    summary_md_path = artifact_dir / "summary.md"
    manifest_path = artifact_dir / "manifest.json"
    result["artifact_dir"] = safe_relpath(artifact_dir)
    result["artifact_paths"] = [safe_relpath(result_path), safe_relpath(summary_path), safe_relpath(summary_md_path), safe_relpath(manifest_path)]
    write_json(result_path, result)
    write_json(summary_path, result)
    write_summary_markdown(summary_md_path, result)
    write_manifest(manifest_path, run_id=run_id, artifact_paths=[result_path, summary_path, summary_md_path])
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

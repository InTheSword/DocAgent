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

    return {
        "command": "inspect_final_delivery_benchmark_gate",
        "status": "success" if not failures else "failed",
        "quality_status": "artifact_review_only",
        "run_dir": safe_relpath(run_dir),
        "gate_status": summary.get("status"),
        "run_id": summary.get("run_id") or result.get("run_id"),
        "step_statuses": step_statuses,
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
        "next_action": "review_gate_step_outputs_or_update_delivery_status" if not failures else "fix_gate_artifact_contract_or_rerun_gate",
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
    write_json(result_path, result)
    write_json(summary_path, result)
    result["artifact_paths"] = [safe_relpath(result_path), safe_relpath(summary_path)]
    write_json(result_path, result)
    write_json(summary_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

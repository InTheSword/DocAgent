from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl


SCRIPT_VERSION = "answer-policy-v3-checkpoint-compare-v1"
EVALUATION_SCOPE = "answer_policy_v3_checkpoint_compare_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training_eval" / "answer_policy_v3_checkpoint_compare"
METRIC_KEYS = [
    "json_valid_rate",
    "schema_valid_rate",
    "answer_exact_rate",
    "support_status_match_rate",
    "supporting_refs_subset_rate",
    "positive_ref_hit_rate",
    "insufficient_ref_empty_rate",
    "thinking_rate",
]


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


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def artifact_entry(path: Path) -> dict[str, Any]:
    return {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def run_summary(run_dir: Path, *, label: str) -> dict[str, Any]:
    summary = load_json(run_dir / "summary.json")
    metrics = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else {}
    return {
        "label": label,
        "run_id": str(summary.get("run_id") or run_dir.name),
        "source_run_dir": safe_relpath(run_dir),
        "status": summary.get("status"),
        "model_mode": summary.get("model_mode"),
        "sft_input": summary.get("sft_input"),
        "adapter_path": summary.get("adapter_path"),
        "metrics": {key: metrics.get(key) for key in [*METRIC_KEYS, "evaluated_count", "schema_error_counts"]},
        "generation": summary.get("generation") or {},
        "used_qwen": bool(summary.get("used_qwen")),
        "used_training": bool(summary.get("used_training")),
        "formal_benchmark_acceptance": bool(summary.get("formal_benchmark_acceptance")),
        "validation_subset_used_for_training": bool(summary.get("validation_subset_used_for_training")),
    }


def required_missing(run_dir: Path) -> list[str]:
    return [safe_relpath(path) for path in (run_dir / "summary.json", run_dir / "rows.jsonl") if not path.is_file()]


def load_rows(run_dir: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(read_jsonl(run_dir / "rows.jsonl") if (run_dir / "rows.jsonl").is_file() else []):
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or f"row_{index}")
        rows[row_id] = row
    return rows


def load_metadata_rows(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    rows: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(path):
        if not isinstance(row, dict):
            continue
        row_id = str(row.get("id") or "")
        if row_id:
            rows[row_id] = row
    return rows


def metric_bool(row: dict[str, Any], key: str) -> bool:
    metrics = row.get("metrics") if isinstance(row.get("metrics"), dict) else {}
    return bool(metrics.get(key))


def movement(base: dict[str, Any], candidate: dict[str, Any]) -> str:
    base_ok = metric_bool(base, "answer_exact")
    candidate_ok = metric_bool(candidate, "answer_exact")
    if base_ok and candidate_ok:
        return "both_answer_exact"
    if base_ok and not candidate_ok:
        return "candidate_regressed"
    if not base_ok and candidate_ok:
        return "candidate_improved"
    return "both_answer_miss"


def compare_rows(
    base_rows: dict[str, dict[str, Any]],
    candidate_rows: dict[str, dict[str, Any]],
    metadata_rows: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_id in sorted(set(base_rows) | set(candidate_rows)):
        base = base_rows.get(row_id, {})
        candidate = candidate_rows.get(row_id, {})
        meta = metadata_rows.get(row_id, {})
        rows.append(
            {
                "id": row_id,
                "source": meta.get("source") or base.get("source") or candidate.get("source"),
                "bucket": meta.get("bucket"),
                "category": meta.get("category"),
                "target_kinds": meta.get("target_kinds") or [],
                "movement": movement(base, candidate),
                "base_answer_exact": metric_bool(base, "answer_exact"),
                "candidate_answer_exact": metric_bool(candidate, "answer_exact"),
                "base_schema_ok": metric_bool(base, "schema_ok"),
                "candidate_schema_ok": metric_bool(candidate, "schema_ok"),
                "base_positive_ref_hit": metric_bool(base, "positive_ref_hit"),
                "candidate_positive_ref_hit": metric_bool(candidate, "positive_ref_hit"),
                "base_prediction": base.get("prediction"),
                "candidate_prediction": candidate.get("prediction"),
                "target": candidate.get("target") or base.get("target"),
            }
        )
    return rows


def rate(count: int, total: int) -> float:
    return round(count / total, 6) if total else 0.0


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    movement_counts = Counter(str(row.get("movement") or "") for row in rows)
    return {
        "row_count": total,
        "movement_counts": dict(sorted(movement_counts.items())),
        "candidate_improved_count": int(movement_counts.get("candidate_improved", 0)),
        "candidate_regressed_count": int(movement_counts.get("candidate_regressed", 0)),
        "both_answer_exact_count": int(movement_counts.get("both_answer_exact", 0)),
        "both_answer_miss_count": int(movement_counts.get("both_answer_miss", 0)),
        "base_answer_exact_rate": rate(sum(bool(row.get("base_answer_exact")) for row in rows), total),
        "candidate_answer_exact_rate": rate(sum(bool(row.get("candidate_answer_exact")) for row in rows), total),
    }


def breakdown_by_category(rows: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row.get("category") or "unknown")].append(row)
    return {category: summarize_rows(items) for category, items in sorted(groups.items())}


def metric_deltas(base: dict[str, Any], candidate: dict[str, Any]) -> dict[str, float | None]:
    base_metrics = base.get("metrics") or {}
    candidate_metrics = candidate.get("metrics") or {}
    deltas: dict[str, float | None] = {}
    for key in METRIC_KEYS:
        base_value = base_metrics.get(key)
        candidate_value = candidate_metrics.get(key)
        if isinstance(base_value, (int, float)) and isinstance(candidate_value, (int, float)):
            deltas[key] = round(float(candidate_value) - float(base_value), 6)
        else:
            deltas[key] = None
    return deltas


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    row_summary = summary.get("row_summary") or {}
    deltas = summary.get("metric_deltas") or {}
    lines = [
        "# AnswerPolicy v3 Checkpoint Compare",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- row_count: `{row_summary.get('row_count', 0)}`",
        f"- candidate_improved_count: `{row_summary.get('candidate_improved_count', 0)}`",
        f"- candidate_regressed_count: `{row_summary.get('candidate_regressed_count', 0)}`",
        f"- answer_exact_delta: `{deltas.get('answer_exact_rate')}`",
        f"- schema_valid_delta: `{deltas.get('schema_valid_rate')}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary['validation_subset_used_for_training']).lower()}`",
    ]
    if summary.get("missing"):
        lines.extend(["", "## Missing"])
        lines.extend(f"- `{item}`" for item in summary["missing"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync_bundle(artifact_dir: Path, sync_output_dir: Path, run_id: str, paths: list[Path]) -> Path:
    bundle = sync_output_dir / run_id
    bundle.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if path.is_file():
            shutil.copy2(path, bundle / path.name)
    return bundle


def compare_checkpoint_evals(
    *,
    base_run_dir: str | Path,
    candidate_run_dir: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_checkpoint_compare",
    base_label: str = "base",
    candidate_label: str = "candidate",
    metadata_rows_path: str | Path | None = None,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    base_dir = repo_path(base_run_dir)
    candidate_dir = repo_path(candidate_run_dir)
    metadata_path = repo_path(metadata_rows_path)
    assert base_dir is not None
    assert candidate_dir is not None
    artifact_dir = repo_path(output_root) / run_id  # type: ignore[operator]
    artifact_dir.mkdir(parents=True, exist_ok=True)

    result_path = artifact_dir / "result.json"
    summary_path = artifact_dir / "summary.json"
    summary_md_path = artifact_dir / "summary.md"
    rows_path = artifact_dir / "rows.jsonl"
    run_summaries_path = artifact_dir / "run_summaries.json"
    preview_path = artifact_dir / "preview.json"
    manifest_path = artifact_dir / "manifest.json"

    missing = [*required_missing(base_dir), *required_missing(candidate_dir)]
    if metadata_path is not None and not metadata_path.is_file():
        missing.append(safe_relpath(metadata_path))

    base = run_summary(base_dir, label=base_label)
    candidate = run_summary(candidate_dir, label=candidate_label)
    rows: list[dict[str, Any]] = []
    if not missing:
        rows = compare_rows(load_rows(base_dir), load_rows(candidate_dir), load_metadata_rows(metadata_path))
    status = "blocked" if missing else "success"
    row_summary = summarize_rows(rows)
    summary = {
        "command": "compare_answer_policy_v3_checkpoint_evals",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "base": base,
        "candidate": candidate,
        "metric_deltas": metric_deltas(base, candidate),
        "row_summary": row_summary,
        "category_breakdown": breakdown_by_category(rows),
        "metadata_rows_path": safe_relpath(metadata_path) if metadata_path is not None else "",
        "missing": missing,
        "used_qwen": bool(base.get("used_qwen") or candidate.get("used_qwen")),
        "used_training": False,
        "training_started": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "recommendation": {
            "next_action": "use_fixed_evidence_delta_as_training_objective_signal_not_deployment_gate",
            "do_not_train_yet": True,
            "reason": (
                "This comparison reads existing AnswerPolicy v3 checkpoint eval artifacts only. "
                "It does not call models, start training, use validation data, or claim benchmark acceptance."
            ),
        },
    }

    write_jsonl(rows_path, rows)
    write_json(run_summaries_path, {"base": base, "candidate": candidate})
    write_json(preview_path, {"rows": rows[:10]})
    write_json(summary_path, summary)
    write_json(result_path, summary)
    write_summary_markdown(summary_md_path, summary)
    artifacts = [result_path, summary_path, summary_md_path, rows_path, run_summaries_path, preview_path]
    manifest = {
        "status": status,
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "artifacts": [artifact_entry(path) for path in artifacts if path.is_file()],
        "used_qwen": summary["used_qwen"],
        "used_training": False,
        "training_started": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    write_json(manifest_path, manifest)
    summary["manifest_path"] = safe_relpath(manifest_path)
    summary["artifact_paths"] = [safe_relpath(path) for path in [*artifacts, manifest_path] if path.is_file()]
    if sync_output_dir:
        bundle = sync_bundle(artifact_dir, repo_path(sync_output_dir), run_id, [result_path, summary_path, summary_md_path, preview_path, manifest_path])
        summary["sync_bundle_path"] = safe_relpath(bundle)
    write_json(summary_path, summary)
    write_json(result_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare existing AnswerPolicy v3 checkpoint diagnostic artifacts.")
    parser.add_argument("--base-run-dir", required=True)
    parser.add_argument("--candidate-run-dir", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_checkpoint_compare")
    parser.add_argument("--base-label", default="base")
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--metadata-rows-path")
    parser.add_argument("--sync-output-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = compare_checkpoint_evals(
            base_run_dir=args.base_run_dir,
            candidate_run_dir=args.candidate_run_dir,
            output_root=args.output_root,
            run_id=args.run_id,
            base_label=args.base_label,
            candidate_label=args.candidate_label,
            metadata_rows_path=args.metadata_rows_path,
            sync_output_dir=args.sync_output_dir,
        )
    except Exception as exc:
        result = {
            "command": "compare_answer_policy_v3_checkpoint_evals",
            "status": "failed",
            "exception": f"{type(exc).__name__}: {exc}",
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

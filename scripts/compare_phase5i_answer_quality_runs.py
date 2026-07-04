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


SCRIPT_VERSION = "phase5i-answer-quality-compare-v1"
EVALUATION_SCOPE = "phase5i_answer_quality_run_compare_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "phase5i_answer_quality_compare"


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
    return f"phase5i_answer_quality_compare_{stamp}"


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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def compact_text(value: Any, *, limit: int = 320) -> str:
    text = str(value or "")
    return text if len(text) <= limit else f"{text[:limit]}...<truncated>"


def case_id_for(row: dict[str, Any], index: int) -> str:
    return str(row.get("case_id") or row.get("sample_id") or row.get("id") or f"row_{index}")


def passed(row: dict[str, Any]) -> bool:
    if "passed" in row:
        return bool(row.get("passed"))
    value = str(row.get("pass_fail") or row.get("status") or "").casefold()
    return value in {"passed", "pass", "success"}


def failure_reasons(row: dict[str, Any]) -> list[str]:
    value = row.get("failure_reasons")
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value:
        return [value]
    distribution = row.get("failure_reason_distribution")
    if isinstance(distribution, dict):
        return [str(key) for key, count in distribution.items() if count]
    return []


def answer_preview(row: dict[str, Any]) -> str:
    for key in ("answer_preview", "prediction_answer", "final_answer", "answer"):
        if row.get(key):
            return compact_text(row.get(key))
    return ""


def citation_pages(row: dict[str, Any]) -> list[Any]:
    for key in ("citation_pages", "citation_page_ids", "citation_page_numbers"):
        value = row.get(key)
        if isinstance(value, list):
            return value
    return []


def index_case_reports(run_dir: Path) -> dict[str, dict[str, Any]]:
    rows = load_jsonl_rows(run_dir / "case_reports.jsonl")
    return {case_id_for(row, index): row for index, row in enumerate(rows)}


def short_run_summary(run_dir: Path, *, label: str) -> dict[str, Any]:
    summary = load_json(run_dir / "phase5i_summary.json")
    metrics = load_json(run_dir / "metrics.json")
    return {
        "label": label,
        "run_id": summary.get("run_id") or run_dir.name,
        "source_run_dir": safe_relpath(run_dir),
        "status": summary.get("status"),
        "answer_policy_mode": summary.get("answer_policy_mode"),
        "answer_output_contract": summary.get("answer_output_contract"),
        "case_count": int(summary.get("case_count") or 0),
        "passed_count": int(summary.get("passed_count") or 0),
        "failed_count": int(summary.get("failed_count") or 0),
        "json_valid_count": int(summary.get("json_valid_count") or 0),
        "citation_page_hit_count": int(summary.get("citation_page_hit_count") or 0),
        "answer_keyword_hit_count": int(summary.get("answer_keyword_hit_count") or 0),
        "evidence_keyword_hit_count": int(summary.get("evidence_keyword_hit_count") or 0),
        "used_qwen_answer_policy_count": int(summary.get("used_qwen_answer_policy_count") or 0),
        "used_llm_query_rewriter_count": int(summary.get("used_llm_query_rewriter_count") or 0),
        "failure_reason_distribution": summary.get("failure_reason_distribution") or {},
        "metrics": {
            "answer_correct_rate": metrics.get("answer_correct_rate"),
            "format_valid_rate": metrics.get("format_valid_rate"),
            "citation_valid_rate": metrics.get("citation_valid_rate"),
            "location_valid_rate": metrics.get("location_valid_rate"),
        },
        "used_training": bool(summary.get("used_training")),
        "formal_benchmark_acceptance": bool(summary.get("formal_benchmark_acceptance")),
        "validation_subset_used_for_training": bool(summary.get("validation_subset_used_for_training")),
    }


def required_missing(run_dir: Path) -> list[str]:
    return [
        safe_relpath(path)
        for path in (run_dir / "phase5i_summary.json", run_dir / "metrics.json", run_dir / "case_reports.jsonl")
        if not path.is_file()
    ]


def compare_rows(base_reports: dict[str, dict[str, Any]], candidate_reports: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_id in sorted(set(base_reports) | set(candidate_reports)):
        base = base_reports.get(case_id, {})
        candidate = candidate_reports.get(case_id, {})
        base_passed = passed(base)
        candidate_passed = passed(candidate)
        if base_passed and candidate_passed:
            change = "both_passed"
        elif base_passed and not candidate_passed:
            change = "candidate_regressed"
        elif not base_passed and candidate_passed:
            change = "candidate_improved"
        else:
            change = "both_failed"
        rows.append(
            {
                "case_id": case_id,
                "base_passed": base_passed,
                "candidate_passed": candidate_passed,
                "change": change,
                "base_failure_reasons": failure_reasons(base),
                "candidate_failure_reasons": failure_reasons(candidate),
                "base_answer_preview": answer_preview(base),
                "candidate_answer_preview": answer_preview(candidate),
                "base_citation_pages": citation_pages(base),
                "candidate_citation_pages": citation_pages(candidate),
            }
        )
    return rows


def interpretation(base: dict[str, Any], candidate: dict[str, Any], changes: Counter[str]) -> dict[str, Any]:
    base_passed = int(base.get("passed_count") or 0)
    candidate_passed = int(candidate.get("passed_count") or 0)
    if candidate_passed > base_passed:
        result = "candidate_outperformed_base_on_clean_contract"
        next_action = "candidate_merits_broader_clean_or_heldout_evaluation_before_promotion"
    elif candidate_passed < base_passed:
        result = "candidate_underperformed_base_on_clean_contract"
        next_action = "do_not_promote_candidate_from_this_signal; inspect_candidate_failure_pattern_or_keep_base"
    else:
        result = "candidate_matched_base_on_clean_contract"
        next_action = "do_not_promote_candidate_without_additional_broader_evidence"
    return {
        "contract_result": result,
        "case_change_counts": dict(changes),
        "next_action": next_action,
        "boundary": (
            "This compares existing Phase 5I answer-quality artifacts only. "
            "It does not call models, create training data, measure retrieval improvement, "
            "claim formal benchmark acceptance, or judge whether the training objective improved. "
            "Training effectiveness must be judged with train-only heldout/fixed-evidence "
            "v3 objective metrics; real workflow diagnostics mainly check execution continuity "
            "and deployment regression risk."
        ),
    }


def promotion_gate(base: dict[str, Any], candidate: dict[str, Any], changes: Counter[str]) -> dict[str, Any]:
    """Conservative default-deployment guard for a checkpoint.

    This comparison is intentionally not a training-effectiveness judgement.
    It can only block default deployment or mark a candidate as worth broader
    clean/heldout evaluation.
    """
    reasons: list[str] = []
    base_passed = int(base.get("passed_count") or 0)
    candidate_passed = int(candidate.get("passed_count") or 0)
    if int(changes.get("candidate_regressed") or 0):
        reasons.append("candidate_regressed_cases_present")
    if candidate_passed < base_passed:
        reasons.append("candidate_passed_count_below_base")

    base_metrics = base.get("metrics") or {}
    candidate_metrics = candidate.get("metrics") or {}
    for key in ("format_valid_rate", "citation_valid_rate", "location_valid_rate"):
        base_value = base_metrics.get(key)
        candidate_value = candidate_metrics.get(key)
        if isinstance(base_value, (int, float)) and isinstance(candidate_value, (int, float)) and candidate_value < base_value:
            reasons.append(f"candidate_{key}_below_base")

    if reasons:
        decision = "blocked"
        broader_eval_recommended = False
        next_action = "keep_current_baseline_or_inspect_candidate_failures"
    elif candidate_passed > base_passed:
        decision = "requires_broader_eval"
        broader_eval_recommended = True
        next_action = "run_broader_clean_or_train_heldout_evaluation_before_default_promotion"
    else:
        decision = "hold"
        broader_eval_recommended = False
        next_action = "keep_current_baseline_until_candidate_shows_broader_benefit"

    return {
        "gate_scope": "default_checkpoint_deployment_guard",
        "decision": decision,
        "candidate_promotable_from_this_artifact": False,
        "training_effectiveness_judged": False,
        "broader_eval_recommended": broader_eval_recommended,
        "reasons": reasons,
        "next_action": next_action,
        "training_effectiveness_boundary": (
            "Use train-only heldout or fixed-evidence v3 objective metrics "
            "(schema, support_status, supporting_refs, positive-ref hit, insufficient behavior) "
            "to judge training-target improvement. Do not treat real workflow answer-hit "
            "rate as a standalone training-effectiveness metric."
        ),
    }


def write_outputs(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    sync_output_root: Path | None,
) -> dict[str, Any]:
    result_path = artifact_dir / "result.json"
    summary_path = artifact_dir / "summary.json"
    summary_md_path = artifact_dir / "summary.md"
    rows_path = artifact_dir / "rows.jsonl"
    preview_path = artifact_dir / "preview.json"
    manifest_path = artifact_dir / "manifest.json"

    write_json(result_path, summary)
    write_json(summary_path, summary)
    summary_md_path.write_text(summary_markdown(summary), encoding="utf-8")
    write_jsonl(rows_path, rows)
    write_json(preview_path, {"rows": rows[:20]})

    artifact_paths = [result_path, summary_path, summary_md_path, rows_path, preview_path]
    manifest = {
        "status": summary.get("status"),
        "run_id": summary.get("run_id"),
        "script_version": SCRIPT_VERSION,
        "artifact_count": len(artifact_paths),
        "artifacts": [
            {"path": safe_relpath(path), "size_bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in artifact_paths
        ],
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    write_json(manifest_path, manifest)
    summary["artifact_paths"] = [safe_relpath(path) for path in [*artifact_paths, manifest_path]]
    summary["manifest_path"] = safe_relpath(manifest_path)
    if sync_output_root is not None:
        sync_dir = sync_output_root / str(summary.get("run_id"))
        sync_dir.mkdir(parents=True, exist_ok=True)
        for path in [result_path, summary_path, summary_md_path, rows_path, preview_path, manifest_path]:
            shutil.copy2(path, sync_dir / path.name)
        summary["sync_bundle_path"] = safe_relpath(sync_dir)
    write_json(result_path, summary)
    write_json(summary_path, summary)
    return summary


def summary_markdown(summary: dict[str, Any]) -> str:
    base = summary.get("base") or {}
    candidate = summary.get("candidate") or {}
    interpretation_data = summary.get("interpretation") or {}
    promotion = summary.get("promotion_gate") or {}
    return "\n".join(
        [
            "# Phase 5I Answer-Quality Run Compare",
            "",
            f"- status: {summary.get('status')}",
            f"- base: {base.get('label')} passed {base.get('passed_count')}/{base.get('case_count')}",
            f"- candidate: {candidate.get('label')} passed {candidate.get('passed_count')}/{candidate.get('case_count')}",
            f"- contract_result: {interpretation_data.get('contract_result')}",
            f"- case_change_counts: {json.dumps(summary.get('case_change_counts') or {}, ensure_ascii=False)}",
            f"- promotion_gate: {promotion.get('decision')} ({promotion.get('gate_scope')})",
            "",
            "This artifact is diagnostic-only and does not call models or create training data. "
            "It is a deployment/regression guard, not a standalone judgement of SFT/RL training effectiveness.",
            "",
        ]
    )


def compare_phase5i_answer_quality_runs(
    *,
    base_run_dir: Path,
    candidate_run_dir: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    base_label: str = "base",
    candidate_label: str = "candidate",
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    base_run_dir = base_run_dir.resolve()
    candidate_run_dir = candidate_run_dir.resolve()
    missing = [*required_missing(base_run_dir), *required_missing(candidate_run_dir)]
    if missing:
        summary = {
            "command": "compare_phase5i_answer_quality_runs",
            "status": "failed",
            "script_version": SCRIPT_VERSION,
            "evaluation_scope": EVALUATION_SCOPE,
            "run_id": run_id,
            "artifact_dir": safe_relpath(artifact_dir),
            "missing": missing,
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
        return write_outputs(artifact_dir=artifact_dir, summary=summary, rows=[], sync_output_root=sync_output_root)

    base = short_run_summary(base_run_dir, label=base_label)
    candidate = short_run_summary(candidate_run_dir, label=candidate_label)
    rows = compare_rows(index_case_reports(base_run_dir), index_case_reports(candidate_run_dir))
    changes = Counter(str(row.get("change") or "") for row in rows)
    summary = {
        "command": "compare_phase5i_answer_quality_runs",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "base": base,
        "candidate": candidate,
        "case_count": len(rows),
        "case_change_counts": dict(sorted(changes.items())),
        "interpretation": interpretation(base, candidate, changes),
        "promotion_gate": promotion_gate(base, candidate, changes),
        "used_qwen": True,
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    return write_outputs(artifact_dir=artifact_dir, summary=summary, rows=rows, sync_output_root=sync_output_root)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compare two Phase 5I answer-quality artifact runs.")
    parser.add_argument("--base-run-dir", required=True, type=Path)
    parser.add_argument("--candidate-run-dir", required=True, type=Path)
    parser.add_argument("--base-label", default="base")
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--sync-output-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = compare_phase5i_answer_quality_runs(
        base_run_dir=repo_path(args.base_run_dir) or args.base_run_dir,
        candidate_run_dir=repo_path(args.candidate_run_dir) or args.candidate_run_dir,
        output_root=repo_path(args.output_dir) or args.output_dir,
        run_id=args.run_id,
        base_label=args.base_label,
        candidate_label=args.candidate_label,
        sync_output_root=repo_path(args.sync_output_dir) if args.sync_output_dir else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.rewards.combined import docqa_v3_reward_breakdown
from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.answer_contract import normalize_supporting_refs, validate_model_output_v3
from scripts.run_answer_policy_v3_sft_warmup import (
    assistant_target,
    extract_allowed_refs,
    safe_relpath,
    sha256_file,
    validate_sft_record,
    validation_path_markers,
)


SCRIPT_VERSION = "answer-policy-v3-reward-calibration-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training_prep" / "answer_policy_v3_reward_calibration"


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact_entry(path: Path) -> dict[str, Any]:
    return {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def first_allowed_non_positive(allowed_refs: set[str], positive_refs: set[str]) -> str:
    for ref in sorted(allowed_refs):
        if ref not in positive_refs:
            return ref
    return "E999"


def first_allowed_ref(allowed_refs: set[str]) -> str:
    return sorted(allowed_refs)[0] if allowed_refs else "E1"


def make_variants(record: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    target = assistant_target(record) or {}
    allowed_refs = extract_allowed_refs(record)
    positive_refs = set(normalize_supporting_refs(target))
    status = str(target.get("support_status") or "")
    variants: list[tuple[str, dict[str, Any]]] = [("gold_target", dict(target))]
    if status == "supported":
        variants.extend(
            [
                (
                    "wrong_answer_same_refs",
                    {
                        **target,
                        "answer": "Unsupported answer.",
                        "reasoning_summary": "This answer is intentionally incorrect for calibration.",
                    },
                ),
                (
                    "wrong_ref_same_answer",
                    {
                        **target,
                        "supporting_refs": [first_allowed_non_positive(allowed_refs, positive_refs)],
                        "reasoning_summary": "This uses an intentionally wrong supporting ref.",
                    },
                ),
                (
                    "insufficient_instead_of_supported",
                    {
                        "answer": "Insufficient evidence.",
                        "supporting_refs": [],
                        "support_status": "insufficient",
                        "reasoning_summary": "This incorrectly refuses a supported example.",
                    },
                ),
            ]
        )
    else:
        variants.extend(
            [
                (
                    "fabricated_supported",
                    {
                        "answer": "Unsupported answer.",
                        "supporting_refs": [first_allowed_ref(allowed_refs)],
                        "support_status": "supported",
                        "reasoning_summary": "This fabricates support for an insufficient example.",
                    },
                ),
                (
                    "fabricated_answer_with_insufficient_status",
                    {
                        "answer": "Unsupported answer.",
                        "supporting_refs": [],
                        "support_status": "insufficient",
                        "reasoning_summary": "This has the right status but a non-refusal answer.",
                    },
                ),
            ]
        )
    invalid = dict(target)
    invalid.pop("supporting_refs", None)
    variants.append(("invalid_schema_missing_refs", invalid))
    return variants


def score_variant(record: dict[str, Any], variant_name: str, prediction: dict[str, Any]) -> dict[str, Any]:
    target = assistant_target(record) or {}
    allowed_refs = extract_allowed_refs(record)
    positive_refs = normalize_supporting_refs(target)
    insufficient_expected = str(target.get("support_status") or "") == "insufficient"
    schema_ok, schema_error = validate_model_output_v3(prediction, allowed_refs=allowed_refs)
    reward = docqa_v3_reward_breakdown(
        prediction,
        str(target.get("answer") or ""),
        positive_refs=positive_refs,
        insufficient_expected=insufficient_expected,
    )
    return {
        "variant": variant_name,
        "schema_ok": schema_ok,
        "schema_error": schema_error,
        "reward": reward["reward"],
        "reward_components": reward,
        "prediction": prediction,
    }


def load_records(paths: list[Path], *, limit: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    audit = {
        "input_paths": [safe_relpath(path) for path in paths],
        "input_record_counts": {},
        "valid_record_count": 0,
        "invalid_reason_counts": {},
    }
    invalid = Counter()
    for path in paths:
        source_rows = read_jsonl(path)
        audit["input_record_counts"][safe_relpath(path)] = len(source_rows)
        for row in source_rows:
            ok, reason = validate_sft_record(row)
            if ok:
                rows.append(row)
            else:
                invalid[reason] += 1
    if limit > 0:
        rows = rows[:limit]
    audit["valid_record_count"] = len(rows)
    audit["invalid_reason_counts"] = dict(sorted(invalid.items()))
    return rows, audit


def summarize_rows(rows: list[dict[str, Any]], *, max_negative_reward: float, min_target_reward: float) -> dict[str, Any]:
    variant_scores: dict[str, list[float]] = defaultdict(list)
    status_counts = Counter()
    for row in rows:
        target = row.get("target") or {}
        status_counts[str(target.get("support_status") or "")] += 1
        for variant in row.get("variants") or []:
            variant_scores[str(variant["variant"])].append(float(variant["reward"]))
    variant_summary = {
        name: {
            "count": len(values),
            "mean": sum(values) / len(values) if values else 0.0,
            "min": min(values) if values else 0.0,
            "max": max(values) if values else 0.0,
        }
        for name, values in sorted(variant_scores.items())
    }
    target_stats = variant_summary.get("gold_target", {"min": 0.0, "mean": 0.0, "max": 0.0})
    negative_max = max(
        (stats["max"] for name, stats in variant_summary.items() if name != "gold_target"),
        default=0.0,
    )
    calibration_passed = target_stats["min"] >= min_target_reward and negative_max <= max_negative_reward
    return {
        "calibrated_record_count": len(rows),
        "target_support_status_counts": dict(sorted(status_counts.items())),
        "variant_summary": variant_summary,
        "target_reward_min": target_stats["min"],
        "target_reward_mean": target_stats["mean"],
        "negative_reward_max": negative_max,
        "min_target_reward": min_target_reward,
        "max_negative_reward": max_negative_reward,
        "reward_calibration_status": "passed" if calibration_passed else "review_needed",
    }


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# AnswerPolicy v3 Reward Calibration",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- calibrated_record_count: `{summary['metrics'].get('calibrated_record_count', 0)}`",
        f"- reward_calibration_status: `{summary['metrics'].get('reward_calibration_status', '')}`",
        f"- target_reward_min: `{summary['metrics'].get('target_reward_min', 0.0)}`",
        f"- negative_reward_max: `{summary['metrics'].get('negative_reward_max', 0.0)}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
    ]
    lines.extend(["", "## Variants"])
    for name, stats in (summary["metrics"].get("variant_summary") or {}).items():
        lines.append(f"- {name}: mean `{stats['mean']}`, min `{stats['min']}`, max `{stats['max']}`")
    if summary.get("block_reasons"):
        lines.extend(["", "## Block Reasons"])
        lines.extend(f"- `{reason}`" for reason in summary["block_reasons"])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync_bundle(artifact_dir: Path, sync_output_dir: Path, run_id: str, paths: list[Path]) -> Path:
    bundle = sync_output_dir / run_id
    bundle.mkdir(parents=True, exist_ok=True)
    for path in paths:
        if path.is_file():
            shutil.copy2(path, bundle / path.name)
    return bundle


def run_calibration(
    *,
    sft_inputs: list[str | Path],
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_reward_calibration",
    limit: int = 128,
    min_target_reward: float = 0.95,
    max_negative_reward: float = 0.85,
    allow_validation_like_input: bool = False,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    rows_path = artifact_dir / "rows.jsonl"
    summary_path = artifact_dir / "summary.json"
    summary_md_path = artifact_dir / "summary.md"
    result_path = artifact_dir / "result.json"
    preview_path = artifact_dir / "preview.json"
    manifest_path = artifact_dir / "manifest.json"

    input_paths = [repo_path(path) for path in sft_inputs]
    block_reasons: list[str] = []
    for path in input_paths:
        if not path.is_file():
            block_reasons.append(f"missing_sft_input:{safe_relpath(path)}")
        if not allow_validation_like_input:
            markers = validation_path_markers(path)
            if markers:
                block_reasons.append(f"validation_like_input_path:{safe_relpath(path)}:{','.join(markers)}")
    if not input_paths:
        block_reasons.append("no_sft_inputs")

    records: list[dict[str, Any]] = []
    audit: dict[str, Any] = {}
    if not block_reasons:
        records, audit = load_records(input_paths, limit=limit)
        if not records:
            block_reasons.append("no_valid_sft_records")

    rows: list[dict[str, Any]] = []
    if not block_reasons:
        for record in records:
            target = assistant_target(record) or {}
            rows.append(
                {
                    "id": record.get("id"),
                    "source": record.get("source"),
                    "target": target,
                    "allowed_refs": sorted(extract_allowed_refs(record)),
                    "variants": [
                        score_variant(record, variant_name, prediction)
                        for variant_name, prediction in make_variants(record)
                    ],
                }
            )

    metrics = summarize_rows(rows, max_negative_reward=max_negative_reward, min_target_reward=min_target_reward)
    status = "blocked" if block_reasons else "success"
    recommendation = {
        "next_action": "reward_calibration_ready_for_best_of_n_or_dpo_design"
        if metrics.get("reward_calibration_status") == "passed"
        else "inspect_answer_policy_v3_reward_components_before_rl",
        "do_not_train_yet": True,
        "reason": (
            "This calibration reads train-only v3 SFT records and scores deterministic target/negative variants. "
            "It does not call models, start training, create validation-derived records, or approve GRPO."
        ),
    }
    write_jsonl(rows_path, rows)
    write_json(preview_path, {"rows": rows[:5]})
    summary = {
        "command": "calibrate_answer_policy_v3_rewards",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "sft_inputs": [safe_relpath(path) for path in input_paths],
        "audit": audit,
        "metrics": metrics,
        "block_reasons": block_reasons,
        "recommendation": recommendation,
        "used_training": False,
        "training_started": False,
        "used_qwen": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    write_json(summary_path, summary)
    write_json(result_path, summary)
    write_summary_markdown(summary_md_path, summary)
    artifacts = [rows_path, preview_path, result_path, summary_path, summary_md_path]
    manifest = {
        "status": status,
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "artifacts": [artifact_entry(path) for path in artifacts if path.is_file()],
        "used_training": False,
        "training_started": False,
        "used_qwen": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    write_json(manifest_path, manifest)
    summary["artifact_paths"] = [safe_relpath(path) for path in [*artifacts, manifest_path] if path.is_file()]
    summary["manifest_path"] = safe_relpath(manifest_path)
    if sync_output_dir:
        bundle = sync_bundle(artifact_dir, repo_path(sync_output_dir), run_id, [result_path, summary_path, summary_md_path, preview_path, manifest_path])
        summary["sync_bundle_path"] = safe_relpath(bundle)
    write_json(summary_path, summary)
    write_json(result_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calibrate deterministic reward components for AnswerPolicy v3 SFT records.")
    parser.add_argument("--sft-input", action="append", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_reward_calibration")
    parser.add_argument("--limit", type=int, default=128)
    parser.add_argument("--min-target-reward", type=float, default=0.95)
    parser.add_argument("--max-negative-reward", type=float, default=0.85)
    parser.add_argument("--allow-validation-like-input", action="store_true")
    parser.add_argument("--sync-output-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = run_calibration(
            sft_inputs=args.sft_input,
            output_root=args.output_root,
            run_id=args.run_id,
            limit=args.limit,
            min_target_reward=args.min_target_reward,
            max_negative_reward=args.max_negative_reward,
            allow_validation_like_input=bool(args.allow_validation_like_input),
            sync_output_dir=args.sync_output_dir,
        )
    except Exception as exc:
        result = {
            "command": "calibrate_answer_policy_v3_rewards",
            "status": "failed",
            "exception": f"{type(exc).__name__}: {exc}",
            "used_training": False,
            "training_started": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

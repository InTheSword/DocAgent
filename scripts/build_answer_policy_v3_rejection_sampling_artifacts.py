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
from scripts.calibrate_answer_policy_v3_rewards import make_variants
from scripts.eval_answer_policy_v3_sft_checkpoint import decode_first_json_object
from scripts.run_answer_policy_v3_sft_warmup import (
    assistant_target,
    extract_allowed_refs,
    safe_relpath,
    sha256_file,
    validate_sft_record,
    validation_path_markers,
)


SCRIPT_VERSION = "answer-policy-v3-rejection-sampling-artifacts-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training_prep" / "answer_policy_v3_rejection_sampling"
TRAINING_READY_CANDIDATE_SOURCES = {"candidate_input", "model_generation"}


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact_entry(path: Path) -> dict[str, Any]:
    return {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def load_sft_records(paths: list[Path], *, limit: int, offset: int = 0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    invalid = Counter()
    duplicate_count = 0
    seen: set[str] = set()
    audit = {
        "input_paths": [safe_relpath(path) for path in paths],
        "input_record_counts": {},
        "valid_record_count": 0,
        "duplicate_record_count": 0,
        "invalid_reason_counts": {},
        "offset": offset,
        "limit": limit,
    }
    for path in paths:
        source_rows = read_jsonl(path)
        audit["input_record_counts"][safe_relpath(path)] = len(source_rows)
        for row in source_rows:
            ok, reason = validate_sft_record(row)
            if not ok:
                invalid[reason] += 1
                continue
            record_id = str(row.get("id") or "")
            if record_id in seen:
                duplicate_count += 1
                continue
            seen.add(record_id)
            records.append(row)
    if offset > 0:
        records = records[offset:]
    if limit > 0:
        records = records[:limit]
    audit["valid_record_count"] = len(records)
    audit["duplicate_record_count"] = duplicate_count
    audit["invalid_reason_counts"] = dict(sorted(invalid.items()))
    return records, audit


def record_map(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(record.get("id") or ""): record for record in records if str(record.get("id") or "")}


def load_candidate_inputs(paths: list[Path], records_by_id: dict[str, dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    missing_record_count = 0
    parsed_count = 0
    no_prediction_count = 0
    audit = {
        "candidate_input_paths": [safe_relpath(path) for path in paths],
        "candidate_input_row_counts": {},
    }
    for path in paths:
        rows = read_jsonl(path)
        audit["candidate_input_row_counts"][safe_relpath(path)] = len(rows)
        for row_index, row in enumerate(rows):
            record_id = str(row.get("id") or row.get("record_id") or "")
            if record_id not in records_by_id:
                missing_record_count += 1
                continue
            raw_candidates = row.get("candidates") if isinstance(row.get("candidates"), list) else [row]
            for candidate_index, item in enumerate(raw_candidates):
                if not isinstance(item, dict):
                    no_prediction_count += 1
                    continue
                prediction = item.get("prediction") or item.get("model_output")
                raw_text = str(item.get("raw_text") or item.get("text") or row.get("raw_text") or "")
                if not isinstance(prediction, dict) and raw_text:
                    prediction = decode_first_json_object(raw_text)
                if not isinstance(prediction, dict):
                    no_prediction_count += 1
                    prediction = {}
                parsed_count += 1
                candidate_source = str(item.get("candidate_source") or item.get("source") or "candidate_input")
                candidates[record_id].append(
                    {
                        "candidate_id": str(item.get("candidate_id") or f"{path.name}:{row_index}:{candidate_index}"),
                        "candidate_source": candidate_source,
                        "prediction": prediction,
                        "raw_text_preview": raw_text[:500],
                    }
                )
    audit.update(
        {
            "parsed_candidate_count": parsed_count,
            "missing_record_candidate_count": missing_record_count,
            "no_prediction_candidate_count": no_prediction_count,
        }
    )
    return candidates, audit


def calibration_candidates(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "candidate_id": name,
            "candidate_source": "calibration_variant",
            "prediction": prediction,
            "raw_text_preview": "",
        }
        for name, prediction in make_variants(record)
    ]


def score_candidate(record: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    target = assistant_target(record) or {}
    allowed_refs = extract_allowed_refs(record)
    positive_refs = normalize_supporting_refs(target)
    insufficient_expected = str(target.get("support_status") or "") == "insufficient"
    prediction = candidate.get("prediction") if isinstance(candidate.get("prediction"), dict) else {}
    schema_ok, schema_error = validate_model_output_v3(prediction, allowed_refs=allowed_refs)
    reward = docqa_v3_reward_breakdown(
        prediction,
        str(target.get("answer") or ""),
        positive_refs=positive_refs,
        insufficient_expected=insufficient_expected,
    )
    return {
        "candidate_id": candidate.get("candidate_id"),
        "candidate_source": candidate.get("candidate_source"),
        "prediction": prediction,
        "raw_text_preview": candidate.get("raw_text_preview") or "",
        "schema_ok": schema_ok,
        "schema_error": schema_error,
        "reward": float(reward["reward"]),
        "reward_components": reward,
    }


def rank_candidates(record: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = [score_candidate(record, candidate) for candidate in candidates]
    scored.sort(key=lambda item: (item["reward"], bool(item["schema_ok"]), str(item.get("candidate_id") or "")), reverse=True)
    for index, item in enumerate(scored, start=1):
        item["rank"] = index
    return scored


def prompt_messages(record: dict[str, Any]) -> list[dict[str, Any]]:
    messages = record.get("messages") if isinstance(record.get("messages"), list) else []
    return [dict(message) for message in messages[:-1]]


def assistant_message(prediction: dict[str, Any]) -> dict[str, str]:
    return {"role": "assistant", "content": json.dumps(prediction, ensure_ascii=False)}


def readiness_reasons(
    *,
    best: dict[str, Any] | None,
    source_mode: str,
    min_chosen_reward: float,
    candidate_count: int,
) -> list[str]:
    reasons: list[str] = []
    if best is None:
        reasons.append("no_candidates")
        return reasons
    if best.get("candidate_source") not in TRAINING_READY_CANDIDATE_SOURCES:
        reasons.append("synthetic_candidate_source")
    if not best.get("schema_ok"):
        reasons.append("chosen_schema_invalid")
    if float(best.get("reward") or 0.0) < min_chosen_reward:
        reasons.append("chosen_reward_below_threshold")
    if source_mode == "calibration_variants":
        reasons.append("calibration_variants_are_not_training_data")
    if candidate_count < 1:
        reasons.append("no_candidates")
    return reasons


def build_rows(
    records: list[dict[str, Any]],
    candidates_by_id: dict[str, list[dict[str, Any]]],
    *,
    source_mode: str,
    min_chosen_reward: float,
    min_margin: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    ranked_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    preference_rows: list[dict[str, Any]] = []
    rejection_sft_rows: list[dict[str, Any]] = []
    for record in records:
        record_id = str(record.get("id") or "")
        candidates = list(candidates_by_id.get(record_id, []))
        ranked = rank_candidates(record, candidates)
        target = assistant_target(record) or {}
        ranked_rows.append(
            {
                "id": record_id,
                "source": record.get("source"),
                "target": target,
                "candidate_count": len(ranked),
                "candidates": ranked,
            }
        )
        best = ranked[0] if ranked else None
        reasons = readiness_reasons(
            best=best,
            source_mode=source_mode,
            min_chosen_reward=min_chosen_reward,
            candidate_count=len(ranked),
        )
        training_ready = not reasons
        selected_rows.append(
            {
                "id": record_id,
                "source": record.get("source"),
                "chosen_candidate": best,
                "training_ready": training_ready,
                "not_training_ready_reasons": reasons,
            }
        )
        if training_ready and best is not None:
            rejection_sft_rows.append(
                {
                    "id": record_id,
                    "source": record.get("source"),
                    "messages": [*prompt_messages(record), assistant_message(best["prediction"])],
                    "metadata": {
                        "source_artifact": "answer_policy_v3_rejection_sampling",
                        "candidate_id": best.get("candidate_id"),
                        "reward": best.get("reward"),
                    },
                }
            )
        if len(ranked) >= 2 and best is not None:
            rejected = ranked[-1]
            margin = float(best.get("reward") or 0.0) - float(rejected.get("reward") or 0.0)
            pair_reasons = list(reasons)
            if margin < min_margin:
                pair_reasons.append("reward_margin_below_threshold")
            pair_ready = not pair_reasons
            preference_rows.append(
                {
                    "id": record_id,
                    "source": record.get("source"),
                    "prompt_messages": prompt_messages(record),
                    "chosen": best,
                    "rejected": rejected,
                    "reward_margin": margin,
                    "training_ready": pair_ready,
                    "not_training_ready_reasons": pair_reasons,
                }
            )
    return ranked_rows, selected_rows, preference_rows, rejection_sft_rows


def summarize(
    *,
    ranked_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    preference_rows: list[dict[str, Any]],
    rejection_sft_rows: list[dict[str, Any]],
    source_mode: str,
) -> dict[str, Any]:
    candidate_sources = Counter()
    candidate_count = 0
    for row in ranked_rows:
        for candidate in row.get("candidates") or []:
            candidate_count += 1
            candidate_sources[str(candidate.get("candidate_source") or "")] += 1
    reason_counts = Counter()
    for row in selected_rows:
        for reason in row.get("not_training_ready_reasons") or []:
            reason_counts[str(reason)] += 1
    pair_reason_counts = Counter()
    for row in preference_rows:
        for reason in row.get("not_training_ready_reasons") or []:
            pair_reason_counts[str(reason)] += 1
    return {
        "source_mode": source_mode,
        "record_count": len(ranked_rows),
        "candidate_count": candidate_count,
        "candidate_source_counts": dict(sorted(candidate_sources.items())),
        "selected_count": len(selected_rows),
        "training_ready_selected_count": sum(1 for row in selected_rows if row.get("training_ready")),
        "preference_pair_count": len(preference_rows),
        "training_ready_preference_pair_count": sum(1 for row in preference_rows if row.get("training_ready")),
        "rejection_sft_record_count": len(rejection_sft_rows),
        "selected_not_ready_reason_counts": dict(sorted(reason_counts.items())),
        "pair_not_ready_reason_counts": dict(sorted(pair_reason_counts.items())),
    }


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    metrics = summary.get("metrics") or {}
    lines = [
        "# AnswerPolicy v3 Rejection Sampling Artifacts",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- source_mode: `{metrics.get('source_mode', '')}`",
        f"- record_count: `{metrics.get('record_count', 0)}`",
        f"- candidate_count: `{metrics.get('candidate_count', 0)}`",
        f"- training_ready_selected_count: `{metrics.get('training_ready_selected_count', 0)}`",
        f"- training_ready_preference_pair_count: `{metrics.get('training_ready_preference_pair_count', 0)}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
    ]
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


def build_rejection_sampling_artifacts(
    *,
    sft_inputs: list[str | Path],
    candidate_inputs: list[str | Path] | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_rejection_sampling",
    limit: int = 128,
    offset: int = 0,
    min_chosen_reward: float = 0.95,
    min_margin: float = 0.2,
    use_calibration_variants: bool = False,
    allow_validation_like_input: bool = False,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    ranked_path = artifact_dir / "ranked_candidates.jsonl"
    selected_path = artifact_dir / "selected_candidates.jsonl"
    preference_path = artifact_dir / "preference_pairs.jsonl"
    rejection_sft_path = artifact_dir / "rejection_sft_candidates.jsonl"
    summary_path = artifact_dir / "summary.json"
    summary_md_path = artifact_dir / "summary.md"
    result_path = artifact_dir / "result.json"
    preview_path = artifact_dir / "preview.json"
    manifest_path = artifact_dir / "manifest.json"

    input_paths = [repo_path(path) for path in sft_inputs]
    candidate_paths = [repo_path(path) for path in (candidate_inputs or [])]
    block_reasons: list[str] = []
    for path in [*input_paths, *candidate_paths]:
        if not path.is_file():
            block_reasons.append(f"missing_input:{safe_relpath(path)}")
        if not allow_validation_like_input:
            markers = validation_path_markers(path)
            if markers:
                block_reasons.append(f"validation_like_input_path:{safe_relpath(path)}:{','.join(markers)}")
    if not input_paths:
        block_reasons.append("no_sft_inputs")
    if not candidate_paths and not use_calibration_variants:
        block_reasons.append("no_candidate_inputs")
    if offset < 0:
        block_reasons.append("offset_must_be_non_negative")

    records: list[dict[str, Any]] = []
    sft_audit: dict[str, Any] = {}
    candidate_audit: dict[str, Any] = {}
    source_mode = "candidate_input" if candidate_paths else "calibration_variants"
    candidates_by_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
    if not block_reasons:
        records, sft_audit = load_sft_records(input_paths, limit=limit, offset=offset)
        if not records:
            block_reasons.append("no_valid_sft_records")
        records_by_id = record_map(records)
        if candidate_paths:
            candidates_by_id, candidate_audit = load_candidate_inputs(candidate_paths, records_by_id)
        if use_calibration_variants:
            source_mode = "candidate_input+calibration_variants" if candidate_paths else "calibration_variants"
            for record in records:
                candidates_by_id[str(record.get("id") or "")].extend(calibration_candidates(record))

    ranked_rows: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    preference_rows: list[dict[str, Any]] = []
    rejection_sft_rows: list[dict[str, Any]] = []
    if not block_reasons:
        ranked_rows, selected_rows, preference_rows, rejection_sft_rows = build_rows(
            records,
            candidates_by_id,
            source_mode=source_mode,
            min_chosen_reward=min_chosen_reward,
            min_margin=min_margin,
        )

    status = "blocked" if block_reasons else "success"
    metrics = summarize(
        ranked_rows=ranked_rows,
        selected_rows=selected_rows,
        preference_rows=preference_rows,
        rejection_sft_rows=rejection_sft_rows,
        source_mode=source_mode,
    )
    recommendation = {
        "next_action": "inspect_rejection_sampling_artifacts_before_dpo_or_sft_distillation"
        if metrics.get("training_ready_selected_count", 0) or metrics.get("training_ready_preference_pair_count", 0)
        else "collect_real_model_candidate_generations_for_rejection_sampling",
        "do_not_train_yet": True,
        "reason": (
            "This script ranks AnswerPolicy v3 candidates and writes best-of-N/preference artifacts. "
            "It does not call models, start training, create validation-derived records, or approve GRPO."
        ),
    }
    write_jsonl(ranked_path, ranked_rows)
    write_jsonl(selected_path, selected_rows)
    write_jsonl(preference_path, preference_rows)
    write_jsonl(rejection_sft_path, rejection_sft_rows)
    write_json(preview_path, {"ranked_rows": ranked_rows[:3], "selected_rows": selected_rows[:3], "preference_rows": preference_rows[:3]})
    summary = {
        "command": "build_answer_policy_v3_rejection_sampling_artifacts",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "sft_inputs": [safe_relpath(path) for path in input_paths],
        "candidate_inputs": [safe_relpath(path) for path in candidate_paths],
        "use_calibration_variants": use_calibration_variants,
        "offset": offset,
        "min_chosen_reward": min_chosen_reward,
        "min_margin": min_margin,
        "sft_audit": sft_audit,
        "candidate_audit": candidate_audit,
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
    artifacts = [ranked_path, selected_path, preference_path, rejection_sft_path, preview_path, result_path, summary_path, summary_md_path]
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
    parser = argparse.ArgumentParser(description="Build AnswerPolicy v3 best-of-N and rejection-sampling artifacts.")
    parser.add_argument("--sft-input", action="append", required=True)
    parser.add_argument("--candidate-input", action="append")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_rejection_sampling")
    parser.add_argument("--limit", type=int, default=128)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--min-chosen-reward", type=float, default=0.95)
    parser.add_argument("--min-margin", type=float, default=0.2)
    parser.add_argument("--use-calibration-variants", action="store_true")
    parser.add_argument("--allow-validation-like-input", action="store_true")
    parser.add_argument("--sync-output-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = build_rejection_sampling_artifacts(
            sft_inputs=args.sft_input,
            candidate_inputs=args.candidate_input,
            output_root=args.output_root,
            run_id=args.run_id,
            limit=args.limit,
            offset=args.offset,
            min_chosen_reward=args.min_chosen_reward,
            min_margin=args.min_margin,
            use_calibration_variants=bool(args.use_calibration_variants),
            allow_validation_like_input=bool(args.allow_validation_like_input),
            sync_output_dir=args.sync_output_dir,
        )
    except Exception as exc:
        result = {
            "command": "build_answer_policy_v3_rejection_sampling_artifacts",
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

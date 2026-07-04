from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_answer_policy_v3_sft_warmup import (
    safe_relpath,
    sha256_file,
    validate_sft_record,
    validation_path_markers,
)


SCRIPT_VERSION = "answer-policy-v3-mixed-sft-pack-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training_prep" / "answer_policy_v3_mixed_sft"


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact_entry(path: Path) -> dict[str, Any]:
    return {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def record_key(record: dict[str, Any]) -> str:
    if record.get("id"):
        return str(record["id"])
    text = json.dumps(record.get("messages") or record, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_category(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = read_jsonl(path)
    valid: list[dict[str, Any]] = []
    invalid = Counter()
    seen: set[str] = set()
    duplicate_count = 0
    for row in rows:
        ok, reason = validate_sft_record(row)
        if not ok:
            invalid[reason] += 1
            continue
        key = record_key(row)
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        valid.append(row)
    return valid, {
        "path": safe_relpath(path),
        "input_record_count": len(rows),
        "valid_record_count": len(valid),
        "duplicate_record_count": duplicate_count,
        "invalid_reason_counts": dict(sorted(invalid.items())),
    }


def quota_counts(total: int, ratios: dict[str, float]) -> dict[str, int]:
    normalized = {key: max(0.0, float(value)) for key, value in ratios.items()}
    ratio_sum = sum(normalized.values())
    if ratio_sum <= 0:
        raise ValueError("at least one ratio must be positive")
    raw = {key: total * value / ratio_sum for key, value in normalized.items()}
    quotas = {key: int(math.floor(value)) for key, value in raw.items()}
    remainder = total - sum(quotas.values())
    for key, _ in sorted(raw.items(), key=lambda item: (item[1] - math.floor(item[1]), item[0]), reverse=True):
        if remainder <= 0:
            break
        quotas[key] += 1
        remainder -= 1
    return quotas


def interleave(groups: dict[str, list[dict[str, Any]]], order: list[str]) -> list[dict[str, Any]]:
    mixed: list[dict[str, Any]] = []
    max_len = max((len(groups.get(name, [])) for name in order), default=0)
    for index in range(max_len):
        for name in order:
            group = groups.get(name, [])
            if index < len(group):
                mixed.append(group[index])
    return mixed


def select_mixed_records(
    categories: dict[str, list[dict[str, Any]]],
    *,
    target_records: int,
    ratios: dict[str, float],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    quotas = quota_counts(target_records, ratios)
    selected_by_category: dict[str, list[dict[str, Any]]] = {}
    remaining_by_category: dict[str, list[dict[str, Any]]] = {}
    shortage_counts: dict[str, int] = {}
    for name, records in categories.items():
        quota = quotas.get(name, 0)
        selected_by_category[name] = list(records[:quota])
        remaining_by_category[name] = list(records[quota:])
        if len(records) < quota:
            shortage_counts[name] = quota - len(records)

    selected_count = sum(len(records) for records in selected_by_category.values())
    fill_needed = max(0, target_records - selected_count)
    fill_counts = Counter()
    order = sorted(categories)
    while fill_needed > 0:
        progressed = False
        for name in order:
            remaining = remaining_by_category.get(name, [])
            if not remaining:
                continue
            selected_by_category[name].append(remaining.pop(0))
            fill_counts[name] += 1
            fill_needed -= 1
            progressed = True
            if fill_needed <= 0:
                break
        if not progressed:
            break

    selected = interleave(selected_by_category, order)
    actual_counts = Counter(str(record.get("source") or "unknown") for record in selected)
    category_counts = {name: len(records) for name, records in selected_by_category.items()}
    return selected, {
        "target_records": target_records,
        "ratios": ratios,
        "initial_quotas": quotas,
        "available_counts": {name: len(records) for name, records in categories.items()},
        "shortage_counts": dict(sorted(shortage_counts.items())),
        "backfill_counts": dict(sorted(fill_counts.items())),
        "selected_category_counts": dict(sorted(category_counts.items())),
        "selected_source_counts": dict(sorted(actual_counts.items())),
        "selected_record_count": len(selected),
        "unfilled_count": max(0, target_records - len(selected)),
    }


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# AnswerPolicy v3 Mixed SFT Pack",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- selected_record_count: `{summary['selected_record_count']}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary['validation_subset_used_for_training']).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
    ]
    plan = summary.get("selection_plan") or {}
    if plan:
        lines.extend(["", "## Selection"])
        for key in ("initial_quotas", "available_counts", "shortage_counts", "backfill_counts", "selected_category_counts", "unfilled_count"):
            lines.append(f"- {key}: `{json.dumps(plan.get(key, {}), ensure_ascii=False, sort_keys=True)}`")
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


def build_mixed_pack(
    *,
    tatqa_sft: str | Path | None = None,
    mpdocvqa_sft: str | Path | None = None,
    insufficient_sft: str | Path | None = None,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_mixed_sft",
    target_records: int = 128,
    tatqa_ratio: float = 0.4,
    mpdocvqa_ratio: float = 0.5,
    insufficient_ratio: float = 0.1,
    allow_validation_like_input: bool = False,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    sft_path = artifact_dir / "sft_train.jsonl"
    summary_path = artifact_dir / "summary.json"
    summary_md_path = artifact_dir / "summary.md"
    preview_path = artifact_dir / "preview.json"
    manifest_path = artifact_dir / "manifest.json"
    source_audit_path = artifact_dir / "source_audit.json"

    source_paths = {
        "mpdocvqa": repo_path(mpdocvqa_sft) if mpdocvqa_sft else None,
        "tatqa": repo_path(tatqa_sft) if tatqa_sft else None,
        "insufficient": repo_path(insufficient_sft) if insufficient_sft else None,
    }
    block_reasons: list[str] = []
    for name, path in source_paths.items():
        if path is None:
            continue
        if not path.is_file():
            block_reasons.append(f"missing_{name}_sft:{safe_relpath(path)}")
        if not allow_validation_like_input:
            markers = validation_path_markers(path)
            if markers:
                block_reasons.append(f"validation_like_input_path:{safe_relpath(path)}:{','.join(markers)}")
    if all(path is None for path in source_paths.values()):
        block_reasons.append("no_sft_inputs")

    categories: dict[str, list[dict[str, Any]]] = {}
    source_audit: dict[str, Any] = {}
    if not block_reasons:
        for name, path in source_paths.items():
            if path is None:
                categories[name] = []
                source_audit[name] = {"path": "", "input_record_count": 0, "valid_record_count": 0}
                continue
            records, audit = load_category(path)
            categories[name] = records
            source_audit[name] = audit

    selected: list[dict[str, Any]] = []
    selection_plan: dict[str, Any] = {}
    if not block_reasons:
        selected, selection_plan = select_mixed_records(
            categories,
            target_records=target_records,
            ratios={"mpdocvqa": mpdocvqa_ratio, "tatqa": tatqa_ratio, "insufficient": insufficient_ratio},
        )
        if not selected:
            block_reasons.append("no_valid_sft_records")

    status = "blocked" if block_reasons else "success"
    if status == "blocked":
        selected = []
    write_jsonl(sft_path, selected)
    write_json(source_audit_path, source_audit)
    write_json(preview_path, {"records": selected[:5]})
    summary = {
        "command": "build_answer_policy_v3_mixed_sft_pack",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "sft_train_path": safe_relpath(sft_path),
        "selected_record_count": len(selected),
        "target_records": target_records,
        "selection_plan": selection_plan,
        "source_audit": source_audit,
        "block_reasons": block_reasons,
        "used_training": False,
        "training_started": False,
        "used_qwen": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    write_json(summary_path, summary)
    write_summary_markdown(summary_md_path, summary)
    artifact_paths = [sft_path, source_audit_path, preview_path, summary_path, summary_md_path]
    manifest = {
        "status": status,
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "artifacts": [artifact_entry(path) for path in artifact_paths if path.is_file()],
        "used_training": False,
        "training_started": False,
        "used_qwen": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    write_json(manifest_path, manifest)
    summary["artifact_paths"] = [safe_relpath(path) for path in [*artifact_paths, manifest_path] if path.is_file()]
    summary["manifest_path"] = safe_relpath(manifest_path)
    if sync_output_dir:
        bundle = sync_bundle(
            artifact_dir,
            repo_path(sync_output_dir),
            run_id,
            [summary_path, summary_md_path, preview_path, source_audit_path, manifest_path],
        )
        summary["sync_bundle_path"] = safe_relpath(bundle)
    write_json(summary_path, summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a train-only mixed AnswerPolicy v3 SFT pack.")
    parser.add_argument("--tatqa-sft")
    parser.add_argument("--mpdocvqa-sft")
    parser.add_argument("--insufficient-sft")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_mixed_sft")
    parser.add_argument("--target-records", type=int, default=128)
    parser.add_argument("--tatqa-ratio", type=float, default=0.4)
    parser.add_argument("--mpdocvqa-ratio", type=float, default=0.5)
    parser.add_argument("--insufficient-ratio", type=float, default=0.1)
    parser.add_argument("--allow-validation-like-input", action="store_true")
    parser.add_argument("--sync-output-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = build_mixed_pack(
            tatqa_sft=args.tatqa_sft,
            mpdocvqa_sft=args.mpdocvqa_sft,
            insufficient_sft=args.insufficient_sft,
            output_root=args.output_root,
            run_id=args.run_id,
            target_records=args.target_records,
            tatqa_ratio=args.tatqa_ratio,
            mpdocvqa_ratio=args.mpdocvqa_ratio,
            insufficient_ratio=args.insufficient_ratio,
            allow_validation_like_input=bool(args.allow_validation_like_input),
            sync_output_dir=args.sync_output_dir,
        )
    except Exception as exc:
        result = {
            "command": "build_answer_policy_v3_mixed_sft_pack",
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

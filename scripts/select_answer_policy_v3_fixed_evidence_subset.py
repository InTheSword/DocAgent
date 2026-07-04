from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_answer_policy_v3_sft_warmup import (
    assistant_target,
    safe_relpath,
    sha256_file,
    validate_sft_record,
    validation_path_markers,
)


SCRIPT_VERSION = "answer-policy-v3-fixed-evidence-subset-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training_eval" / "answer_policy_v3_fixed_evidence_subset"


REF_KIND_RE = re.compile(r"^\[(E\d+)\]\s+kind=([A-Za-z0-9_:-]+)", re.MULTILINE)


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact_entry(path: Path) -> dict[str, Any]:
    return {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def user_prompt(record: dict[str, Any]) -> str:
    messages = record.get("messages") if isinstance(record.get("messages"), list) else []
    return "\n".join(str(message.get("content") or "") for message in messages if message.get("role") == "user")


def prompt_ref_kinds(record: dict[str, Any]) -> dict[str, str]:
    return {ref: kind for ref, kind in REF_KIND_RE.findall(user_prompt(record))}


def target_refs(record: dict[str, Any]) -> list[str]:
    target = assistant_target(record) or {}
    refs = target.get("supporting_refs")
    if not isinstance(refs, list):
        return []
    return [str(ref) for ref in refs if isinstance(ref, str)]


def support_status(record: dict[str, Any]) -> str:
    target = assistant_target(record) or {}
    return str(target.get("support_status") or "")


def record_bucket(record: dict[str, Any]) -> str:
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    return str(metadata.get("bucket") or record.get("bucket") or "")


def source_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(record.get("source") or "unknown") for record in records).items()))


def count_key(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(sorted(Counter(str(row.get(key) or "") for row in rows).items()))


def target_kind_list(record: dict[str, Any]) -> list[str]:
    kinds = prompt_ref_kinds(record)
    return [kinds.get(ref, "unknown") for ref in target_refs(record)]


def classify_record(record: dict[str, Any]) -> str:
    status = support_status(record)
    if status == "insufficient":
        return "insufficient"
    kinds = set(target_kind_list(record))
    if "calculation_result" in kinds:
        return "calculation_supported"
    if "table" in kinds:
        return "table_value_supported"
    if kinds:
        return "non_table_supported"
    return "supported_without_target_refs"


def inspect_record(record: dict[str, Any]) -> dict[str, Any]:
    kinds = target_kind_list(record)
    return {
        "id": str(record.get("id") or ""),
        "source": str(record.get("source") or ""),
        "bucket": record_bucket(record),
        "support_status": support_status(record),
        "target_refs": target_refs(record),
        "target_kinds": kinds,
        "category": classify_record(record),
    }


def select_records(
    records: list[dict[str, Any]],
    *,
    include_kinds: set[str],
    include_statuses: set[str],
    include_categories: set[str],
    max_records: int,
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    selected: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    not_selected = Counter()
    for record in records:
        row = inspect_record(record)
        row_kinds = set(row["target_kinds"])
        kind_ok = not include_kinds or bool(row_kinds & include_kinds)
        status_ok = not include_statuses or row["support_status"] in include_statuses
        category_ok = not include_categories or row["category"] in include_categories
        if kind_ok and status_ok and category_ok:
            selected.append(record)
            row["selected"] = True
        else:
            if not kind_ok:
                not_selected["target_kind_not_included"] += 1
            if not status_ok:
                not_selected["support_status_not_included"] += 1
            if not category_ok:
                not_selected["category_not_included"] += 1
            row["selected"] = False
        audit_rows.append(row)
    if max_records > 0 and len(selected) > max_records:
        rng = random.Random(seed)
        selected = list(selected)
        rng.shuffle(selected)
        selected = selected[:max_records]
    return selected, audit_rows, dict(sorted(not_selected.items()))


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# AnswerPolicy v3 Fixed-Evidence Subset",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- valid_record_count: `{summary['valid_record_count']}`",
        f"- selected_record_count: `{summary['selected_record_count']}`",
        f"- include_kinds: `{', '.join(summary['include_kinds']) or '(any)'}`",
        f"- include_statuses: `{', '.join(summary['include_statuses']) or '(any)'}`",
        f"- include_categories: `{', '.join(summary['include_categories']) or '(any)'}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary['validation_subset_used_for_training']).lower()}`",
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


def build_fixed_evidence_subset(
    *,
    sft_inputs: list[str | Path],
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_fixed_evidence_subset",
    include_kinds: list[str] | None = None,
    include_statuses: list[str] | None = None,
    include_categories: list[str] | None = None,
    max_records: int = 0,
    seed: int = 17,
    allow_validation_like_input: bool = False,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    eval_path = artifact_dir / "eval_records.jsonl"
    rows_path = artifact_dir / "rows.jsonl"
    summary_path = artifact_dir / "summary.json"
    result_path = artifact_dir / "result.json"
    summary_md_path = artifact_dir / "summary.md"
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
    if max_records < 0:
        block_reasons.append("max_records_must_be_non_negative")

    input_record_count = 0
    valid_records: list[dict[str, Any]] = []
    invalid_reasons = Counter()
    if not block_reasons:
        for path in input_paths:
            rows = read_jsonl(path)
            input_record_count += len(rows)
            for row in rows:
                ok, reason = validate_sft_record(row)
                if ok:
                    valid_records.append(row)
                else:
                    invalid_reasons[reason] += 1

    selected: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    not_selected_reason_counts: dict[str, int] = {}
    if not block_reasons:
        selected, audit_rows, not_selected_reason_counts = select_records(
            valid_records,
            include_kinds=set(include_kinds or []),
            include_statuses=set(include_statuses or []),
            include_categories=set(include_categories or []),
            max_records=max_records,
            seed=seed,
        )
        if not selected:
            block_reasons.append("no_records_selected")

    status = "blocked" if block_reasons else "success"
    write_jsonl(eval_path, selected)
    write_jsonl(rows_path, audit_rows)
    write_json(preview_path, {"selected": selected[:3], "rows": audit_rows[:10]})

    selected_rows = [inspect_record(record) for record in selected]
    target_kind_counts = Counter(kind for row in selected_rows for kind in row["target_kinds"])
    summary = {
        "command": "select_answer_policy_v3_fixed_evidence_subset",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "sft_inputs": [safe_relpath(path) for path in input_paths],
        "include_kinds": sorted(include_kinds or []),
        "include_statuses": sorted(include_statuses or []),
        "include_categories": sorted(include_categories or []),
        "max_records": max_records,
        "seed": seed,
        "input_record_count": input_record_count,
        "valid_record_count": len(valid_records),
        "invalid_reason_counts": dict(sorted(invalid_reasons.items())),
        "selected_record_count": len(selected),
        "source_counts": source_counts(selected),
        "bucket_counts": count_key(selected_rows, "bucket"),
        "support_status_counts": count_key(selected_rows, "support_status"),
        "category_counts": count_key(selected_rows, "category"),
        "target_kind_counts": dict(sorted(target_kind_counts.items())),
        "not_selected_reason_counts": not_selected_reason_counts,
        "block_reasons": block_reasons,
        "eval_records_path": safe_relpath(eval_path),
        "rows_path": safe_relpath(rows_path),
        "used_qwen": False,
        "used_training": False,
        "training_started": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    write_json(summary_path, summary)
    write_json(result_path, summary)
    write_summary_markdown(summary_md_path, summary)
    artifacts = [eval_path, rows_path, result_path, summary_path, summary_md_path, preview_path]
    manifest = {
        "status": status,
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "artifacts": [artifact_entry(path) for path in artifacts if path.is_file()],
        "used_qwen": False,
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
    parser = argparse.ArgumentParser(description="Select train-only AnswerPolicy v3 fixed-evidence diagnostic subsets.")
    parser.add_argument("--sft-input", action="append", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_fixed_evidence_subset")
    parser.add_argument("--include-kind", action="append")
    parser.add_argument("--include-status", action="append")
    parser.add_argument("--include-category", action="append", default=[])
    parser.add_argument("--max-records", type=int, default=0, help="0 means keep every selected record.")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--allow-validation-like-input", action="store_true")
    parser.add_argument("--sync-output-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = build_fixed_evidence_subset(
            sft_inputs=args.sft_input,
            output_root=args.output_root,
            run_id=args.run_id,
            include_kinds=args.include_kind or ["table", "calculation_result"],
            include_statuses=args.include_status or ["supported"],
            include_categories=args.include_category,
            max_records=args.max_records,
            seed=args.seed,
            allow_validation_like_input=bool(args.allow_validation_like_input),
            sync_output_dir=args.sync_output_dir,
        )
    except Exception as exc:
        result = {
            "command": "select_answer_policy_v3_fixed_evidence_subset",
            "status": "failed",
            "exception": repr(exc),
            "used_qwen": False,
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

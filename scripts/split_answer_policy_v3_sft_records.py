from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import write_jsonl
from scripts.run_answer_policy_v3_sft_warmup import (
    load_valid_records,
    safe_relpath,
    sha256_file,
    validation_path_markers,
)


SCRIPT_VERSION = "answer-policy-v3-sft-split-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training_prep" / "answer_policy_v3_sft_split"


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def artifact_entry(path: Path) -> dict[str, Any]:
    return {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def source_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(str(record.get("source") or "unknown") for record in records).items()))


def id_list(records: list[dict[str, Any]]) -> list[str]:
    return [str(record.get("id") or "") for record in records]


def split_records(
    records: list[dict[str, Any]],
    *,
    train_count: int,
    heldout_count: int,
    seed: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    shuffled = list(records)
    random.Random(seed).shuffle(shuffled)
    heldout = shuffled[: max(0, heldout_count)]
    remaining = shuffled[max(0, heldout_count) :]
    train = remaining if train_count <= 0 else remaining[:train_count]
    excluded = [] if train_count <= 0 else remaining[train_count:]
    return train, heldout, excluded


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# AnswerPolicy v3 SFT Split",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- valid_record_count: `{summary['valid_record_count']}`",
        f"- train_record_count: `{summary['train_record_count']}`",
        f"- heldout_record_count: `{summary['heldout_record_count']}`",
        f"- overlap_count: `{summary['overlap_count']}`",
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


def run_split(
    *,
    sft_inputs: list[str | Path],
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_sft_split",
    train_count: int = 0,
    heldout_count: int = 16,
    seed: int = 17,
    allow_validation_like_input: bool = False,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    train_path = artifact_dir / "train_sft.jsonl"
    heldout_path = artifact_dir / "heldout_eval.jsonl"
    excluded_path = artifact_dir / "excluded.jsonl"
    result_path = artifact_dir / "result.json"
    summary_path = artifact_dir / "summary.json"
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
    if heldout_count < 0:
        block_reasons.append("heldout_count_must_be_non_negative")
    if train_count < 0:
        block_reasons.append("train_count_must_be_non_negative")

    audit: dict[str, Any] = {}
    valid_records: list[dict[str, Any]] = []
    train_records: list[dict[str, Any]] = []
    heldout_records: list[dict[str, Any]] = []
    excluded_records: list[dict[str, Any]] = []
    if not block_reasons:
        valid_records, audit = load_valid_records(input_paths)
        if len(valid_records) <= heldout_count:
            block_reasons.append("not_enough_records_for_heldout")
        else:
            train_records, heldout_records, excluded_records = split_records(
                valid_records,
                train_count=train_count,
                heldout_count=heldout_count,
                seed=seed,
            )
            if not train_records:
                block_reasons.append("no_train_records_after_split")
            if not heldout_records:
                block_reasons.append("no_heldout_records_after_split")

    train_ids = set(id_list(train_records))
    heldout_ids = set(id_list(heldout_records))
    overlap = sorted(train_ids & heldout_ids)
    if overlap:
        block_reasons.append("train_heldout_id_overlap")

    status = "blocked" if block_reasons else "success"
    write_jsonl(train_path, train_records)
    write_jsonl(heldout_path, heldout_records)
    write_jsonl(excluded_path, excluded_records)
    write_json(
        preview_path,
        {
            "train": train_records[:3],
            "heldout": heldout_records[:3],
            "excluded": excluded_records[:3],
        },
    )

    summary = {
        "command": "split_answer_policy_v3_sft_records",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "sft_inputs": [safe_relpath(path) for path in input_paths],
        "seed": seed,
        "requested_train_count": train_count,
        "requested_heldout_count": heldout_count,
        "valid_record_count": len(valid_records),
        "train_record_count": len(train_records),
        "heldout_record_count": len(heldout_records),
        "excluded_record_count": len(excluded_records),
        "overlap_count": len(overlap),
        "overlap_ids": overlap,
        "source_counts": {
            "all_valid": source_counts(valid_records),
            "train": source_counts(train_records),
            "heldout": source_counts(heldout_records),
            "excluded": source_counts(excluded_records),
        },
        "audit": audit,
        "block_reasons": block_reasons,
        "train_sft_path": safe_relpath(train_path),
        "heldout_eval_path": safe_relpath(heldout_path),
        "excluded_path": safe_relpath(excluded_path),
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
    artifacts = [train_path, heldout_path, excluded_path, preview_path, result_path, summary_path, summary_md_path]
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
    parser = argparse.ArgumentParser(description="Split train-only AnswerPolicy v3 SFT records into train and heldout diagnostic files.")
    parser.add_argument("--sft-input", action="append", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_sft_split")
    parser.add_argument("--train-count", type=int, default=0, help="0 means use all records remaining after heldout.")
    parser.add_argument("--heldout-count", type=int, default=16)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--allow-validation-like-input", action="store_true")
    parser.add_argument("--sync-output-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    try:
        result = run_split(
            sft_inputs=args.sft_input,
            output_root=args.output_root,
            run_id=args.run_id,
            train_count=args.train_count,
            heldout_count=args.heldout_count,
            seed=args.seed,
            allow_validation_like_input=bool(args.allow_validation_like_input),
            sync_output_dir=args.sync_output_dir,
        )
    except Exception as exc:
        result = {
            "command": "split_answer_policy_v3_sft_records",
            "status": "failed",
            "exception": f"{type(exc).__name__}: {exc}",
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

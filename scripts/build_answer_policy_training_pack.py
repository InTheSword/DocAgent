from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(SCRIPT_DIR))

from docagent.schemas import DocAgentSample
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.audit_training_data import compact_report, summarize
from scripts.build_grpo_dataset import build_grpo_record
from scripts.build_sft_dataset import build_sft_record


SCRIPT_VERSION = "answer-policy-training-pack-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "training_prep" / "answer_policy_training_pack"
VALID_TRAIN_SPLITS = {"train", "training"}
VALIDATION_PATH_MARKERS = {"dev", "val", "valid", "validation", "test", "final_eval"}


def _resolve(path: str | Path) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else ROOT / candidate


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_entry(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _input_path_markers(path: Path) -> list[str]:
    markers: list[str] = []
    for part in path.parts:
        normalized = part.lower().replace("-", "_")
        if normalized in VALIDATION_PATH_MARKERS:
            markers.append(part)
    return markers


def _sample_split_counts(samples: list[DocAgentSample]) -> dict[str, int]:
    counts = Counter(str(sample.split or "unknown") for sample in samples)
    return dict(sorted(counts.items()))


def _source_counts(samples: list[DocAgentSample]) -> dict[str, int]:
    counts = Counter(str(sample.source or "unknown") for sample in samples)
    return dict(sorted(counts.items()))


def _answer_type_counts(samples: list[DocAgentSample]) -> dict[str, int]:
    counts = Counter(str(sample.answer_type or "unknown") for sample in samples)
    return dict(sorted(counts.items()))


def _load_samples(input_path: Path) -> list[DocAgentSample]:
    return [DocAgentSample.from_dict(record) for record in read_jsonl(input_path)]


def _safety_block_reasons(
    *,
    input_path: Path,
    samples: list[DocAgentSample],
    allow_non_train_source: bool,
) -> list[str]:
    if allow_non_train_source:
        return []

    reasons: list[str] = []
    invalid_splits = sorted({str(sample.split or "unknown") for sample in samples if str(sample.split or "").lower() not in VALID_TRAIN_SPLITS})
    if invalid_splits:
        reasons.append(f"non_train_sample_splits:{','.join(invalid_splits)}")

    path_markers = _input_path_markers(input_path)
    if path_markers:
        reasons.append(f"validation_like_input_path:{','.join(path_markers)}")

    return reasons


def _markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# AnswerPolicy Training Pack",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- input: `{summary['input_path']}`",
        f"- sample_count: `{summary['sample_count']}`",
        f"- verifiable_sample_count: `{summary['verifiable_sample_count']}`",
        f"- sft_record_count: `{summary['sft_record_count']}`",
        f"- grpo_record_count: `{summary['grpo_record_count']}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary['validation_subset_used_for_training']).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
    ]
    if summary.get("block_reasons"):
        lines.extend(["", "## Block Reasons"])
        lines.extend(f"- `{reason}`" for reason in summary["block_reasons"])
    lines.extend(["", "## Splits"])
    lines.extend(f"- {key}: {value}" for key, value in summary.get("split_counts", {}).items())
    lines.extend(["", "## Sources"])
    lines.extend(f"- {key}: {value}" for key, value in summary.get("source_counts", {}).items())
    lines.extend(["", "## Answer Types"])
    lines.extend(f"- {key}: {value}" for key, value in summary.get("answer_type_counts", {}).items())
    lines.extend(
        [
            "",
            "This pack prepares training-format artifacts only. It does not start SFT/GRPO, load models, call Qwen, or claim benchmark acceptance.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_answer_policy_training_pack(
    *,
    input_path: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_training_pack",
    max_evidence_blocks: int = 5,
    max_block_chars: int = 1200,
    preserve_evidence_order: bool = False,
    max_audit_evidence_chars: int = 300,
    allow_non_train_source: bool = False,
) -> dict[str, Any]:
    resolved_input = _resolve(input_path)
    resolved_output_root = _resolve(output_root)
    artifact_dir = resolved_output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    samples = _load_samples(resolved_input)
    verifiable_samples = [sample for sample in samples if sample.verifiable]
    block_reasons = _safety_block_reasons(
        input_path=resolved_input,
        samples=verifiable_samples,
        allow_non_train_source=allow_non_train_source,
    )

    paths = {
        "sft": artifact_dir / "sft_train.jsonl",
        "grpo": artifact_dir / "grpo_train.jsonl",
        "sft_audit": artifact_dir / "sft_audit.json",
        "grpo_audit": artifact_dir / "grpo_audit.json",
        "preview": artifact_dir / "preview.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "manifest": artifact_dir / "manifest.json",
    }

    sft_records: list[dict[str, Any]] = []
    grpo_records: list[dict[str, Any]] = []
    sft_audit: dict[str, Any] = {}
    grpo_audit: dict[str, Any] = {}
    status = "success"

    if block_reasons:
        status = "blocked"
        write_jsonl(paths["sft"], [])
        write_jsonl(paths["grpo"], [])
        _write_json(paths["sft_audit"], {"status": "blocked", "block_reasons": block_reasons})
        _write_json(paths["grpo_audit"], {"status": "blocked", "block_reasons": block_reasons})
    else:
        sft_records = [
            build_sft_record(
                sample,
                max_evidence_blocks=max_evidence_blocks,
                max_block_chars=max_block_chars,
                gold_first=not preserve_evidence_order,
            )
            for sample in verifiable_samples
        ]
        grpo_records = [
            build_grpo_record(
                sample,
                max_evidence_blocks=max_evidence_blocks,
                max_block_chars=max_block_chars,
                gold_first=not preserve_evidence_order,
            )
            for sample in verifiable_samples
            if sample.answer_type in {"extractive", "numeric", "boolean", "choice", "visual"}
        ]
        write_jsonl(paths["sft"], sft_records)
        write_jsonl(paths["grpo"], grpo_records)
        sft_audit = compact_report(summarize(sft_records, max_audit_evidence_chars))
        grpo_audit = compact_report(summarize(grpo_records, max_audit_evidence_chars))
        _write_json(paths["sft_audit"], sft_audit)
        _write_json(paths["grpo_audit"], grpo_audit)

    preview = {
        "sft": sft_records[:2],
        "grpo": grpo_records[:2],
    }
    _write_json(paths["preview"], preview)

    summary = {
        "command": "build_answer_policy_training_pack",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": str(artifact_dir.relative_to(ROOT)) if artifact_dir.is_relative_to(ROOT) else str(artifact_dir),
        "input_path": str(resolved_input.relative_to(ROOT)) if resolved_input.is_relative_to(ROOT) else str(resolved_input),
        "sample_count": len(samples),
        "verifiable_sample_count": len(verifiable_samples),
        "sft_record_count": len(sft_records),
        "grpo_record_count": len(grpo_records),
        "split_counts": _sample_split_counts(samples),
        "source_counts": _source_counts(samples),
        "answer_type_counts": _answer_type_counts(samples),
        "block_reasons": block_reasons,
        "used_training": False,
        "training_started": False,
        "used_qwen": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "allow_non_train_source": allow_non_train_source,
        "sft_audit": sft_audit,
        "grpo_audit": grpo_audit,
    }
    artifact_paths = [paths[key] for key in ("sft", "grpo", "sft_audit", "grpo_audit", "preview", "summary", "summary_md")]
    summary["manifest_path"] = str(paths["manifest"].relative_to(ROOT)) if paths["manifest"].is_relative_to(ROOT) else str(paths["manifest"])
    summary["artifact_paths"] = [
        str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        for path in [*artifact_paths, paths["manifest"]]
    ]
    _write_json(paths["summary"], summary)
    paths["summary_md"].write_text(_markdown_summary(summary), encoding="utf-8")

    manifest = {
        "status": status,
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "artifact_count": len(artifact_paths),
        "artifacts": [_artifact_entry(path) for path in artifact_paths],
        "used_training": False,
        "training_started": False,
        "validation_subset_used_for_training": False,
        "formal_benchmark_acceptance": False,
    }
    _write_json(paths["manifest"], manifest)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Build audited SFT/GRPO training-format artifacts from train-role DocAgent samples.")
    parser.add_argument("--input", required=True)
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_training_pack")
    parser.add_argument("--max-evidence-blocks", type=int, default=5)
    parser.add_argument("--max-block-chars", type=int, default=1200)
    parser.add_argument("--preserve-evidence-order", action="store_true")
    parser.add_argument("--max-audit-evidence-chars", type=int, default=300)
    parser.add_argument(
        "--allow-non-train-source",
        action="store_true",
        help="Allow non-train splits or validation-like input paths. Use only for controlled local fixtures.",
    )
    args = parser.parse_args()

    result = build_answer_policy_training_pack(
        input_path=args.input,
        output_root=args.output_root,
        run_id=args.run_id,
        max_evidence_blocks=args.max_evidence_blocks,
        max_block_chars=args.max_block_chars,
        preserve_evidence_order=args.preserve_evidence_order,
        max_audit_evidence_chars=args.max_audit_evidence_chars,
        allow_non_train_source=args.allow_non_train_source,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

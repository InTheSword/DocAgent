from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import write_jsonl
from scripts.build_mpdocvqa_raw_documents import (
    AuditResult,
    BuildError,
    WindowRecord,
    audit_parquet,
    build_outputs,
    normalize_input_parquets,
    repo_path,
    stable_key,
)


COMMAND = "build_phase4b_expanded_sample"
PHASE = "Phase 4B"
GATE = "Gate 4A"
DEFAULT_OUTPUT_ROOT = "outputs/phase4/mpdocvqa_raw_gate4_expanded"
DEFAULT_BASELINE_DOC_IDS = [
    "hqvw0217__bc714cf4181a5632",
    "rzbj0037__e09400dd12a9c549",
    "jrcy0227__558596710c584b02",
]


@dataclass(frozen=True)
class SelectedWindow:
    window: WindowRecord
    reason: str
    baseline: bool


class ExpandedSampleError(RuntimeError):
    pass


def _page_bucket(page_count: int) -> str:
    if page_count <= 1:
        return "pages_1"
    if page_count <= 5:
        return "pages_2_5"
    if page_count < 10:
        return "pages_6_9"
    return "pages_10_plus"


def _primary_shard(window: WindowRecord) -> str:
    return sorted(window.source_shards)[0] if window.source_shards else "unknown"


def _is_preferred_new_shard(window: WindowRecord) -> bool:
    return any(not shard.startswith("val-00001") for shard in window.source_shards)


def _qa_count(window: WindowRecord) -> int:
    return len(window.qa_rows)


def _selection_manifest_record(selected: SelectedWindow) -> dict[str, Any]:
    window = selected.window
    rows = sorted(window.qa_rows, key=lambda item: (item.source_shard, item.row_index if item.row_index is not None else -1, item.qid))
    row_indices = sorted({row.row_index for row in rows if row.row_index is not None})
    answer_page_idx = [row.answer_page_idx for row in rows]
    return {
        "shard_name": _primary_shard(window),
        "source_shards": sorted(window.source_shards),
        "row_index": row_indices[0] if row_indices else None,
        "row_indices": row_indices,
        "source_doc_id": window.source_doc_id,
        "doc_id": window.doc_id,
        "window_signature": window.window_signature,
        "ordered_page_ids": list(window.page_ids),
        "page_count": window.page_count,
        "qa_count": len(rows),
        "question_ids": [row.qid for row in rows],
        "answer_page_idx": answer_page_idx,
        "selection_reason": selected.reason,
        "baseline_window": selected.baseline,
    }


def _selection_summary(
    *,
    selected: list[SelectedWindow],
    audit: AuditResult,
    skipped: Counter[str],
    target_qa_count: int,
    min_qa_count: int,
    max_qa_count: int,
) -> dict[str, Any]:
    source_counts = Counter(item.window.source_doc_id for item in selected)
    shard_distribution: Counter[str] = Counter()
    for item in selected:
        shard_distribution.update(item.window.source_shards)
    page_count_distribution = Counter(str(item.window.page_count) for item in selected)
    bucket_distribution = Counter(_page_bucket(item.window.page_count) for item in selected)
    qa_count = sum(_qa_count(item.window) for item in selected)
    warnings = []
    if qa_count < min_qa_count:
        warnings.append("selected_qa_count_below_minimum")
    if qa_count > max_qa_count:
        warnings.append("selected_qa_count_above_maximum")
    return {
        "status": "success",
        "phase": PHASE,
        "gate": GATE,
        "selected_window_count": len(selected),
        "selected_qa_count": qa_count,
        "target_qa_count": target_qa_count,
        "min_qa_count": min_qa_count,
        "max_qa_count": max_qa_count,
        "page_count_distribution": dict(sorted(page_count_distribution.items())),
        "page_bucket_distribution": dict(sorted(bucket_distribution.items())),
        "shard_distribution": dict(sorted(shard_distribution.items())),
        "repeated_source_doc_id_count": sum(1 for count in source_counts.values() if count > 1),
        "skipped_reason_distribution": dict(sorted(skipped.items())),
        "baseline_windows_count": sum(1 for item in selected if item.baseline),
        "newly_selected_windows_count": sum(1 for item in selected if not item.baseline),
        "valid_window_count": len(audit.valid_windows),
        "invalid_window_count": len(audit.invalid_windows),
        "warnings": warnings,
    }


def select_expanded_windows(
    audit: AuditResult,
    *,
    baseline_doc_ids: list[str],
    target_qa_count: int,
    min_qa_count: int,
    max_qa_count: int,
    seed: str,
) -> tuple[list[SelectedWindow], Counter[str]]:
    selected: list[SelectedWindow] = []
    selected_ids: set[str] = set()
    skipped: Counter[str] = Counter()

    for doc_id in baseline_doc_ids:
        window = audit.valid_windows.get(doc_id)
        if window is None:
            skipped["baseline_window_missing"] += 1
            continue
        selected.append(SelectedWindow(window=window, reason="baseline_verified", baseline=True))
        selected_ids.add(doc_id)

    candidates = [window for window in audit.valid_windows.values() if window.doc_id not in selected_ids]
    candidates.sort(key=lambda window: (0 if _is_preferred_new_shard(window) else 1, stable_key(seed, window.doc_id), window.doc_id))

    bucket_counts = Counter(_page_bucket(item.window.page_count) for item in selected)
    selected_qa_count = sum(_qa_count(item.window) for item in selected)
    while candidates and selected_qa_count < target_qa_count:
        viable = [
            window
            for window in candidates
            if selected_qa_count + _qa_count(window) <= max_qa_count
        ]
        if not viable:
            skipped["would_exceed_max_qa_count"] += len(candidates)
            break
        best = sorted(
            viable,
            key=lambda window: (
                bucket_counts[_page_bucket(window.page_count)],
                0 if _is_preferred_new_shard(window) else 1,
                stable_key(seed, window.doc_id),
                window.doc_id,
            ),
        )[0]
        bucket = _page_bucket(best.page_count)
        selected.append(
            SelectedWindow(
                window=best,
                reason=f"expanded_{bucket}_{'newer_shard' if _is_preferred_new_shard(best) else 'available_shard'}",
                baseline=False,
            )
        )
        selected_ids.add(best.doc_id)
        selected_qa_count += _qa_count(best)
        bucket_counts[bucket] += 1
        candidates = [window for window in candidates if window.doc_id != best.doc_id]

    skipped["not_selected_after_target"] += len(candidates)
    if selected_qa_count < min_qa_count:
        skipped["below_min_qa_count"] += 1
    return selected, skipped


def _prepare_output_root(path: Path, *, overwrite: bool, validate_only: bool) -> None:
    if path.exists() and not overwrite:
        raise ExpandedSampleError(f"output root already exists: {path}")
    if path.exists() and overwrite:
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)
    if validate_only:
        return


def run_expanded_sample(args: argparse.Namespace) -> dict[str, Any]:
    parquet_paths = normalize_input_parquets(args.input_parquet)
    output_root = repo_path(args.output_root)
    audit = audit_parquet(parquet_paths)
    selected, skipped = select_expanded_windows(
        audit,
        baseline_doc_ids=args.baseline_doc_id,
        target_qa_count=args.target_qa_count,
        min_qa_count=args.min_qa_count,
        max_qa_count=args.max_qa_count,
        seed=str(args.seed),
    )
    if not selected:
        raise ExpandedSampleError("no document windows selected")

    manifest_rows = [_selection_manifest_record(item) for item in selected]
    summary = _selection_summary(
        selected=selected,
        audit=audit,
        skipped=skipped,
        target_qa_count=args.target_qa_count,
        min_qa_count=args.min_qa_count,
        max_qa_count=args.max_qa_count,
    )

    _prepare_output_root(output_root, overwrite=bool(args.overwrite), validate_only=bool(args.validate_only))
    write_jsonl(output_root / "expanded_sample_manifest.jsonl", manifest_rows)
    (output_root / "selection_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    build_payload: dict[str, Any] | None = None
    if not args.validate_only:
        build_payload = build_outputs(
            audit=audit,
            input_parquets=parquet_paths,
            output_root=output_root,
            sample_documents=len(selected),
            seed=str(args.seed),
            requested_doc_ids=[item.window.doc_id for item in selected],
            validate_only=False,
            overwrite=True,
        )
        write_jsonl(output_root / "expanded_sample_manifest.jsonl", manifest_rows)
        (output_root / "selection_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {
        "command": COMMAND,
        "status": "success",
        "phase": PHASE,
        "gate": GATE,
        "validate_only": bool(args.validate_only),
        "artifact_paths": [
            "expanded_sample_manifest.jsonl",
            "selection_summary.json",
        ],
        "selection_summary": summary,
        "build_metrics": None if build_payload is None else build_payload.get("metrics"),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Phase 4B Gate 4 expanded MP-DocVQA sample.")
    parser.add_argument("--input-parquet", nargs="+", required=True)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--baseline-doc-id", action="append", default=list(DEFAULT_BASELINE_DOC_IDS))
    parser.add_argument("--target-qa-count", type=int, default=90)
    parser.add_argument("--min-qa-count", type=int, default=80)
    parser.add_argument("--max-qa-count", type=int, default=100)
    parser.add_argument("--seed", default="phase4b-gate4")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    exit_code = 0
    try:
        payload = run_expanded_sample(args)
    except Exception as exc:
        exit_code = 1
        payload = {
            "command": COMMAND,
            "status": "failed",
            "exit_code": 1,
            "exception": f"{type(exc).__name__}: {exc}",
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

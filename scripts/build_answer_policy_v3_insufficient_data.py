from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.parser.parse_tatqa import convert_tatqa_question
from docagent.utils.jsonl import write_jsonl
from scripts.build_answer_policy_v3_training_data import (
    DEFAULT_OUTPUT_ROOT,
    SCRIPT_VERSION as V3_DATA_SCRIPT_VERSION,
    TRAIN_SPLITS,
    answer_text,
    answer_values,
    artifact_paths,
    build_insufficient_record,
    build_sft_record,
    candidate_from_block,
    load_json_list,
    ref_map_entry,
    repo_path,
    safe_relpath,
    sha256_file,
    text_contains_answer,
    validation_path_markers,
    write_json,
    write_empty_artifacts,
)


SCRIPT_VERSION = "answer-policy-v3-insufficient-data-v1"


def _candidate_board(
    context: dict[str, Any],
    *,
    split: str,
    max_candidates: int,
    max_candidate_chars: int,
) -> dict[str, Any] | None:
    questions = [item for item in context.get("questions") or [] if isinstance(item, dict)]
    if not questions:
        return None
    try:
        sample = convert_tatqa_question(context, questions[0], split=split)
    except Exception:
        return None
    candidates = [
        candidate_from_block(f"E{index}", block, max_chars=max_candidate_chars)
        for index, block in enumerate(sample.evidence[:max_candidates], start=1)
    ]
    if not candidates:
        return None
    return {
        "doc_id": sample.doc_id,
        "candidates": candidates,
        "evidence_ref_map": {item["ref"]: ref_map_entry(item) for item in candidates},
    }


def _board_lacks_answers(board: dict[str, Any], answers: list[str]) -> bool:
    text = "\n".join(str(item.get("display_text") or "") for item in board.get("candidates") or [])
    return not any(text_contains_answer(text, answer) for answer in answers)


def _find_decoy_board(
    boards: list[dict[str, Any]],
    *,
    source_doc_id: str,
    answers: list[str],
    start_index: int,
) -> dict[str, Any] | None:
    if not boards:
        return None
    for offset in range(len(boards)):
        board = boards[(start_index + offset) % len(boards)]
        if str(board.get("doc_id") or "") == source_doc_id:
            continue
        if _board_lacks_answers(board, answers):
            return board
    return None


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# AnswerPolicy v3 Insufficient Evidence Data",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- insufficient_record_count: `{summary['insufficient_record_count']}`",
        f"- sft_record_count: `{summary['sft_record_count']}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary['validation_subset_used_for_training']).lower()}`",
    ]
    if summary.get("block_reasons"):
        lines.extend(["", "## Block Reasons"])
        lines.extend(f"- `{reason}`" for reason in summary["block_reasons"])
    lines.extend(["", "## Buckets"])
    for bucket, count in (summary.get("bucket_counts") or {}).items():
        lines.append(f"- {bucket}: {count}")
    lines.extend(
        [
            "",
            "Records are generated only from train-split TAT-QA source questions and decoy evidence boards whose candidate text does not contain the gold answer string.",
            "This is data preparation only. It does not call Qwen, run SFT/GRPO, use VLM, or claim benchmark acceptance.",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_artifacts(
    paths: dict[str, Path],
    *,
    records: list[dict[str, Any]],
    sft_records: list[dict[str, Any]],
    alignment_failed: list[dict[str, Any]],
    unsupported: list[dict[str, Any]],
    summary: dict[str, Any],
    sync_output_dir: Path | None,
) -> dict[str, Any]:
    write_jsonl(paths["aligned"], records)
    write_jsonl(paths["sft"], sft_records)
    write_jsonl(paths["alignment_failed"], alignment_failed)
    write_jsonl(paths["needs_tool_planning"], [])
    write_jsonl(paths["insufficient"], records)
    write_jsonl(paths["unsupported"], unsupported)
    write_json(paths["preview"], {"insufficient": records[:3], "sft": sft_records[:2], "alignment_failed": alignment_failed[:3]})

    artifact_keys = ("aligned", "sft", "alignment_failed", "needs_tool_planning", "insufficient", "unsupported", "preview", "summary", "summary_md")
    artifact_list = [paths[key] for key in artifact_keys]
    summary["artifact_paths"] = [safe_relpath(path) for path in [*artifact_list, paths["manifest"]]]
    write_json(paths["summary"], summary)
    paths["summary_md"].write_text(_summary_markdown(summary), encoding="utf-8")

    manifest_artifacts = [
        {"path": safe_relpath(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
        for path in artifact_list
        if path.exists()
    ]
    manifest = {
        "status": summary["status"],
        "run_id": summary["run_id"],
        "script_version": SCRIPT_VERSION,
        "depends_on": [V3_DATA_SCRIPT_VERSION],
        "artifact_count": len(manifest_artifacts),
        "artifacts": manifest_artifacts,
        "used_training": False,
        "training_started": False,
        "used_qwen": False,
        "used_vlm": False,
        "validation_subset_used_for_training": False,
        "formal_benchmark_acceptance": False,
    }
    write_json(paths["manifest"], manifest)
    if sync_output_dir is not None:
        bundle = sync_output_dir / summary["run_id"]
        bundle.mkdir(parents=True, exist_ok=True)
        for path in (paths["summary"], paths["summary_md"], paths["preview"], paths["manifest"]):
            if path.is_file():
                shutil.copy2(path, bundle / path.name)
        summary["sync_bundle_path"] = safe_relpath(bundle)
        write_json(paths["summary"], summary)
    return summary


def build_tatqa_insufficient_data(
    *,
    tatqa_raw: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_tatqa_insufficient",
    split: str = "train",
    limit: int = 100,
    max_candidates: int = 8,
    max_candidate_chars: int = 900,
    allow_non_train_source: bool = False,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    raw_path = repo_path(tatqa_raw)
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths = artifact_paths(artifact_dir)

    block_reasons: list[str] = []
    if not allow_non_train_source:
        if split.lower() not in TRAIN_SPLITS:
            block_reasons.append(f"non_train_split:{split}")
        markers = validation_path_markers(raw_path)
        if markers:
            block_reasons.append(f"validation_like_input_path:{','.join(markers)}")
    if not raw_path.is_file():
        block_reasons.append(f"missing_tatqa_raw:{safe_relpath(raw_path)}")
    if block_reasons:
        write_empty_artifacts(paths)
        summary = _base_summary(
            status="blocked",
            run_id=run_id,
            artifact_dir=artifact_dir,
            raw_path=raw_path,
            split=split,
            limit=limit,
            block_reasons=block_reasons,
            records=[],
            scan_counts={},
            rejected_count=0,
        )
        return _write_artifacts(
            paths,
            records=[],
            sft_records=[],
            alignment_failed=[],
            unsupported=[],
            summary=summary,
            sync_output_dir=repo_path(sync_output_dir) if sync_output_dir else None,
        )

    contexts = load_json_list(raw_path)
    boards = [
        board
        for context in contexts
        if (board := _candidate_board(context, split=split, max_candidates=max_candidates, max_candidate_chars=max_candidate_chars)) is not None
    ]
    records: list[dict[str, Any]] = []
    alignment_failed: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    counts = Counter()
    raw_question_count = 0

    for context_index, context in enumerate(contexts):
        for question in context.get("questions") or []:
            if len(records) >= limit:
                break
            if not isinstance(question, dict):
                counts["unsupported_or_ambiguous"] += 1
                unsupported.append({"reason": "invalid_question_record"})
                continue
            raw_question_count += 1
            try:
                sample = convert_tatqa_question(context, question, split=split)
            except Exception as exc:
                counts["unsupported_or_ambiguous"] += 1
                unsupported.append({"reason": f"{type(exc).__name__}: {exc}", "question": question.get("question")})
                continue
            answers = answer_values(sample.answer)
            if not answers:
                counts["unsupported_or_ambiguous"] += 1
                unsupported.append({"reason": "missing_answer", "sample_id": sample.qid})
                continue
            decoy = _find_decoy_board(boards, source_doc_id=sample.doc_id, answers=answers, start_index=context_index + 1)
            if decoy is None:
                counts["alignment_failed"] += 1
                alignment_failed.append(
                    {
                        "sample_id": sample.qid,
                        "source": "tatqa",
                        "question": sample.question,
                        "answer": answer_text(sample.answer),
                        "reason": "no_decoy_board_without_gold_answer",
                    }
                )
                continue
            metadata = {
                "source_doc_id": sample.doc_id,
                "decoy_doc_id": str(decoy.get("doc_id") or ""),
                "split": sample.split,
                "source_question_uid": question.get("uid"),
                "answer_from": sample.metadata.get("answer_from"),
                "raw_answer_type": sample.metadata.get("raw_answer_type"),
                "negative_sampling": "different_doc_no_gold_answer_text_match",
            }
            record = build_insufficient_record(
                sample_id=f"{sample.qid}__insufficient",
                source="tatqa",
                question=sample.question,
                candidates=list(decoy["candidates"]),
                evidence_ref_map=dict(decoy["evidence_ref_map"]),
                metadata=metadata,
            )
            records.append(record)
            counts["insufficient_confirmed"] += 1
        if len(records) >= limit:
            break

    sft_records = [build_sft_record(record) for record in records]
    summary = _base_summary(
        status="success",
        run_id=run_id,
        artifact_dir=artifact_dir,
        raw_path=raw_path,
        split=split,
        limit=limit,
        block_reasons=[],
        records=records,
        scan_counts={**dict(sorted(counts.items())), "raw_question_count_scanned": raw_question_count, "candidate_board_count": len(boards)},
        rejected_count=len(alignment_failed) + len(unsupported),
    )
    return _write_artifacts(
        paths,
        records=records,
        sft_records=sft_records,
        alignment_failed=alignment_failed,
        unsupported=unsupported,
        summary=summary,
        sync_output_dir=repo_path(sync_output_dir) if sync_output_dir else None,
    )


def _base_summary(
    *,
    status: str,
    run_id: str,
    artifact_dir: Path,
    raw_path: Path,
    split: str,
    limit: int,
    block_reasons: list[str],
    records: list[dict[str, Any]],
    scan_counts: dict[str, int],
    rejected_count: int,
) -> dict[str, Any]:
    bucket_counts = Counter(record["bucket"] for record in records)
    return {
        "command": "build_answer_policy_v3_insufficient_data",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "source": "tatqa",
        "source_path": safe_relpath(raw_path),
        "tatqa_raw": safe_relpath(raw_path),
        "split": split,
        "limit": limit,
        "insufficient_record_count": len(records),
        "aligned_record_count": len(records),
        "sft_record_count": len(records),
        "rejected_record_count": rejected_count,
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "scan_counts": scan_counts,
        "block_reasons": block_reasons,
        "used_training": False,
        "training_started": False,
        "used_qwen": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build high-confidence AnswerPolicy v3 insufficient-evidence SFT data.")
    parser.add_argument("--source", choices=["tatqa"], default="tatqa")
    parser.add_argument("--tatqa-raw", default="data/benchmark/tatqa/tatqa_dataset_train.json")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id", default="answer_policy_v3_tatqa_insufficient")
    parser.add_argument("--split", default="train")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--max-candidate-chars", type=int, default=900)
    parser.add_argument("--allow-non-train-source", action="store_true")
    parser.add_argument("--sync-output-dir")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    result = build_tatqa_insufficient_data(
        tatqa_raw=args.tatqa_raw,
        output_root=args.output_root,
        run_id=args.run_id,
        split=args.split,
        limit=args.limit,
        max_candidates=args.max_candidates,
        max_candidate_chars=args.max_candidate_chars,
        allow_non_train_source=bool(args.allow_non_train_source),
        sync_output_dir=args.sync_output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

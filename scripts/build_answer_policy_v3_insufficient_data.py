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
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
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
    load_rows,
    load_json_list,
    mpdocvqa_candidate_blocks,
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


def _mpdocvqa_candidate_board(
    row: dict[str, Any],
    blocks: list[Any],
    *,
    max_candidates: int,
    max_candidate_chars: int,
) -> dict[str, Any] | None:
    gold_pages: list[int] = []
    for value in row.get("gold_pages") or []:
        try:
            gold_pages.append(int(value))
        except (TypeError, ValueError):
            continue
    candidates = [
        candidate_from_block(f"E{index}", block, max_chars=max_candidate_chars)
        for index, block in enumerate(mpdocvqa_candidate_blocks(blocks, gold_pages, max_candidates), start=1)
    ]
    if not candidates:
        return None
    return {
        "sample_id": str(row.get("sample_id") or ""),
        "doc_id": str(row.get("doc_id") or ""),
        "ingested_doc_id": str(row.get("ingested_doc_id") or ""),
        "source_document": str(row.get("source_document") or ""),
        "gold_pages": gold_pages,
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


def _find_mpdocvqa_decoy_board(
    boards: list[dict[str, Any]],
    *,
    source_doc_id: str,
    source_ingested_doc_id: str,
    answers: list[str],
    start_index: int,
) -> dict[str, Any] | None:
    if not boards:
        return None
    for offset in range(len(boards)):
        board = boards[(start_index + offset) % len(boards)]
        if str(board.get("doc_id") or "") == source_doc_id:
            continue
        if str(board.get("ingested_doc_id") or "") == source_ingested_doc_id:
            continue
        if _board_lacks_answers(board, answers):
            return board
    return None


def _summary_markdown(summary: dict[str, Any]) -> str:
    source_label = "TAT-QA" if summary.get("source") == "tatqa" else "MP-DocVQA"
    lines = [
        "# AnswerPolicy v3 Insufficient Evidence Data",
        "",
        f"- status: `{summary['status']}`",
        f"- run_id: `{summary['run_id']}`",
        f"- source: `{summary.get('source', '')}`",
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
            f"Records are generated only from train-split {source_label} source questions and decoy evidence boards whose candidate text does not contain the gold answer string.",
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
            source="tatqa",
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
        source="tatqa",
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


def build_mpdocvqa_insufficient_data(
    *,
    evidence_manifest: str | Path,
    db_path: str | Path,
    output_root: str | Path = DEFAULT_OUTPUT_ROOT,
    run_id: str = "answer_policy_v3_mpdocvqa_insufficient",
    split: str = "train",
    limit: int = 100,
    max_candidates: int = 8,
    max_candidate_chars: int = 900,
    allow_non_train_source: bool = False,
    sync_output_dir: str | Path | None = None,
) -> dict[str, Any]:
    manifest_path = repo_path(evidence_manifest)
    sqlite_path = repo_path(db_path)
    artifact_dir = repo_path(output_root) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    paths = artifact_paths(artifact_dir)

    block_reasons: list[str] = []
    if not allow_non_train_source:
        if split.lower() not in TRAIN_SPLITS:
            block_reasons.append(f"non_train_split:{split}")
        markers = [*validation_path_markers(manifest_path), *validation_path_markers(sqlite_path)]
        if markers:
            block_reasons.append(f"validation_like_input_path:{','.join(dict.fromkeys(markers))}")
    if not manifest_path.is_file():
        block_reasons.append(f"missing_evidence_manifest:{safe_relpath(manifest_path)}")
    if not sqlite_path.is_file():
        block_reasons.append(f"missing_db_path:{safe_relpath(sqlite_path)}")
    if block_reasons:
        write_empty_artifacts(paths)
        summary = _base_summary(
            status="blocked",
            run_id=run_id,
            artifact_dir=artifact_dir,
            raw_path=manifest_path,
            split=split,
            limit=limit,
            block_reasons=block_reasons,
            records=[],
            scan_counts={},
            rejected_count=0,
            source="mp_docvqa",
            db_path=sqlite_path,
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

    rows = load_rows(manifest_path)
    row_splits = sorted({str(row.get("split") or "") for row in rows if row.get("split")})
    if not allow_non_train_source and any(row_split.lower() not in TRAIN_SPLITS for row_split in row_splits):
        block_reasons.append(f"non_train_manifest_splits:{','.join(row_splits)}")
    if block_reasons:
        write_empty_artifacts(paths)
        summary = _base_summary(
            status="blocked",
            run_id=run_id,
            artifact_dir=artifact_dir,
            raw_path=manifest_path,
            split=split,
            limit=limit,
            block_reasons=block_reasons,
            records=[],
            scan_counts={"manifest_row_count": len(rows)},
            rejected_count=0,
            source="mp_docvqa",
            db_path=sqlite_path,
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

    records: list[dict[str, Any]] = []
    alignment_failed: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    counts = Counter()
    blocks_by_doc: dict[str, list[Any]] = {}
    boards: list[dict[str, Any]] = []

    conn = connect(sqlite_path)
    try:
        repository = DocumentRepository(conn)
        for row in rows:
            if not row.get("evidence_ready"):
                continue
            doc_id = str(row.get("ingested_doc_id") or "")
            if not doc_id:
                continue
            if doc_id not in blocks_by_doc:
                blocks_by_doc[doc_id] = repository.load_evidence_blocks(doc_id, include_page_blocks=True)
            board = _mpdocvqa_candidate_board(
                row,
                blocks_by_doc.get(doc_id, []),
                max_candidates=max_candidates,
                max_candidate_chars=max_candidate_chars,
            )
            if board is not None:
                boards.append(board)

        for row_index, row in enumerate(rows):
            if len(records) >= limit:
                break
            sample_id = str(row.get("sample_id") or "")
            answers = answer_values(row.get("answers"))
            if not answers:
                counts["unsupported_or_ambiguous"] += 1
                unsupported.append({"reason": "missing_answer", "sample_id": sample_id})
                continue
            if not row.get("evidence_ready"):
                counts["alignment_failed"] += 1
                alignment_failed.append({"reason": "evidence_not_ready", "sample_id": sample_id})
                continue
            source_doc_id = str(row.get("doc_id") or "")
            source_ingested_doc_id = str(row.get("ingested_doc_id") or "")
            if not source_doc_id or not source_ingested_doc_id:
                counts["alignment_failed"] += 1
                alignment_failed.append({"reason": "missing_source_doc_id", "sample_id": sample_id})
                continue
            decoy = _find_mpdocvqa_decoy_board(
                boards,
                source_doc_id=source_doc_id,
                source_ingested_doc_id=source_ingested_doc_id,
                answers=answers,
                start_index=row_index + 1,
            )
            if decoy is None:
                counts["alignment_failed"] += 1
                alignment_failed.append(
                    {
                        "sample_id": sample_id,
                        "source": "mp_docvqa",
                        "question": row.get("question"),
                        "answers": answers,
                        "reason": "no_decoy_board_without_gold_answer",
                    }
                )
                continue
            metadata = {
                "source_sample_id": sample_id,
                "source_doc_id": source_doc_id,
                "source_ingested_doc_id": source_ingested_doc_id,
                "source_document": str(row.get("source_document") or ""),
                "decoy_sample_id": str(decoy.get("sample_id") or ""),
                "decoy_doc_id": str(decoy.get("doc_id") or ""),
                "decoy_ingested_doc_id": str(decoy.get("ingested_doc_id") or ""),
                "decoy_source_document": str(decoy.get("source_document") or ""),
                "decoy_gold_pages": decoy.get("gold_pages") or [],
                "split": str(row.get("split") or split),
                "gold_pages": row.get("gold_pages") or [],
                "negative_sampling": "different_window_no_gold_answer_text_match",
            }
            record = build_insufficient_record(
                sample_id=f"{sample_id}__insufficient",
                source="mp_docvqa",
                question=str(row.get("question") or ""),
                candidates=list(decoy["candidates"]),
                evidence_ref_map=dict(decoy["evidence_ref_map"]),
                metadata=metadata,
            )
            records.append(record)
            counts["insufficient_confirmed"] += 1
    finally:
        conn.close()

    sft_records = [build_sft_record(record) for record in records]
    summary = _base_summary(
        status="success",
        run_id=run_id,
        artifact_dir=artifact_dir,
        raw_path=manifest_path,
        split=split,
        limit=limit,
        block_reasons=[],
        records=records,
        scan_counts={**dict(sorted(counts.items())), "manifest_row_count": len(rows), "candidate_board_count": len(boards)},
        rejected_count=len(alignment_failed) + len(unsupported),
        source="mp_docvqa",
        db_path=sqlite_path,
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
    source: str,
    db_path: Path | None = None,
) -> dict[str, Any]:
    bucket_counts = Counter(record["bucket"] for record in records)
    summary = {
        "command": "build_answer_policy_v3_insufficient_data",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "source": source,
        "source_path": safe_relpath(raw_path),
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
    if source == "tatqa":
        summary["tatqa_raw"] = safe_relpath(raw_path)
    if source == "mp_docvqa":
        summary["mpdocvqa_evidence_manifest"] = safe_relpath(raw_path)
        summary["mpdocvqa_db_path"] = safe_relpath(db_path) if db_path is not None else ""
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build high-confidence AnswerPolicy v3 insufficient-evidence SFT data.")
    parser.add_argument("--source", choices=["tatqa", "mpdocvqa"], default="tatqa")
    parser.add_argument("--tatqa-raw", default="data/benchmark/tatqa/tatqa_dataset_train.json")
    parser.add_argument("--mpdocvqa-evidence-manifest")
    parser.add_argument("--mpdocvqa-db-path")
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
    if args.source == "mpdocvqa":
        if not args.mpdocvqa_evidence_manifest or not args.mpdocvqa_db_path:
            result = {
                "command": "build_answer_policy_v3_insufficient_data",
                "status": "blocked",
                "block_reasons": ["mpdocvqa_requires_evidence_manifest_and_db_path"],
                "used_training": False,
                "training_started": False,
                "formal_benchmark_acceptance": False,
                "validation_subset_used_for_training": False,
            }
        else:
            result = build_mpdocvqa_insufficient_data(
                evidence_manifest=args.mpdocvqa_evidence_manifest,
                db_path=args.mpdocvqa_db_path,
                output_root=args.output_root,
                run_id=args.run_id,
                split=args.split,
                limit=args.limit,
                max_candidates=args.max_candidates,
                max_candidate_chars=args.max_candidate_chars,
                allow_non_train_source=bool(args.allow_non_train_source),
                sync_output_dir=args.sync_output_dir,
            )
    else:
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

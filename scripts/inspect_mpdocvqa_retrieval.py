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

from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_final_eval_subset import normalize_text


SCRIPT_VERSION = "mpdocvqa-retrieval-inspect-v1"
EVALUATION_SCOPE = "mpdocvqa_retrieval_inspection_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_retrieval_inspect"


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
    return f"mpdocvqa_retrieval_inspect_{stamp}"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_rows(run_dir: Path) -> tuple[list[dict[str, Any]], str, str]:
    for filename, scope in (
        ("results.jsonl", "answer_policy_results"),
        ("mpdocvqa_attribution_rows.jsonl", "attribution_rows"),
        ("failures_sample.jsonl", "failure_sample_only"),
    ):
        path = run_dir / filename
        if path.is_file():
            return [row for row in read_jsonl(path) if isinstance(row, dict)], scope, safe_relpath(path)
    return [], "missing", ""


def as_str_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        values = [values] if values not in (None, "") else []
    return [str(item) for item in values if str(item or "").strip()]


def as_int_set(values: Any) -> set[int]:
    if not isinstance(values, list):
        values = [values] if values not in (None, "") else []
    pages: set[int] = set()
    for value in values:
        try:
            pages.add(int(value))
        except (TypeError, ValueError):
            continue
    return pages


def block_page(block: Any) -> int | None:
    if block is None:
        return None
    if getattr(block, "page_id", None) is not None:
        return int(block.page_id)
    location = getattr(block, "location", None)
    if location is not None and getattr(location, "page", None) is not None:
        return int(location.page)
    return None


def block_retrieval_text(block: Any) -> str:
    if block is None:
        return ""
    return str(getattr(block, "retrieval_text", "") or "").strip()


def load_blocks(rows: list[dict[str, Any]], db_path: Path | None) -> tuple[dict[str, dict[str, Any]], bool]:
    if db_path is None or not db_path.is_file():
        return {}, False
    doc_ids = sorted({str(row.get("ingested_doc_id") or "") for row in rows if str(row.get("ingested_doc_id") or "")})
    blocks_by_doc: dict[str, dict[str, Any]] = {}
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        for doc_id in doc_ids:
            blocks_by_doc[doc_id] = {
                block.block_id: block for block in repository.load_evidence_blocks(doc_id, include_page_blocks=True)
            }
    finally:
        conn.close()
    return blocks_by_doc, True


def pages_for_block_ids(block_ids: Any, block_by_id: dict[str, Any]) -> list[int]:
    pages: list[int] = []
    for block_id in as_str_list(block_ids):
        page = block_page(block_by_id.get(block_id))
        if page is not None:
            pages.append(page)
    return pages


def first_gold_page_rank(block_ids: Any, block_by_id: dict[str, Any], gold_pages: set[int]) -> int | None:
    if not gold_pages:
        return None
    for index, block_id in enumerate(as_str_list(block_ids), start=1):
        page = block_page(block_by_id.get(block_id))
        if page in gold_pages:
            return index
    return None


def citation_pages(row: dict[str, Any], block_by_id: dict[str, Any]) -> set[int]:
    pages = as_int_set(row.get("citation_pages") or [])
    pages.update(pages_for_block_ids(row.get("citation_block_ids") or [], block_by_id))
    return pages


def answer_text_hit(gold_page_text: str, answers: list[str]) -> bool:
    normalized = normalize_text(gold_page_text)
    return any(answer and normalize_text(answer) in normalized for answer in answers)


def row_bucket(
    *,
    row: dict[str, Any],
    db_available: bool,
    ingested_doc_id: str,
    gold_pages: set[int],
    gold_page_block_count: int,
    gold_retrievable_block_count: int,
    retrieved_pages: set[int],
    selected_pages: set[int],
    cited_pages: set[int],
) -> str:
    if row.get("pass_fail") == "passed":
        return "passed"
    if not gold_pages:
        return "gold_page_missing"
    if not db_available:
        return "evidence_db_missing"
    if not ingested_doc_id:
        return "ingested_doc_id_missing"
    if gold_page_block_count == 0:
        return "gold_page_blocks_missing"
    if gold_retrievable_block_count == 0:
        return "gold_page_without_retrievable_blocks"
    if not as_str_list(row.get("retrieved_block_ids") or []):
        return "retrieved_blocks_empty"
    if not gold_pages.intersection(retrieved_pages):
        return "retrieval_gold_page_miss"
    if selected_pages and not gold_pages.intersection(selected_pages):
        return "selected_context_gold_page_miss"
    if cited_pages and not gold_pages.intersection(cited_pages):
        return "citation_selection_page_miss"
    if not bool(row.get("answer_hit")):
        return "answer_generation_or_metric_miss"
    return "other_failure"


def compact_row(row: dict[str, Any], blocks_by_doc: dict[str, dict[str, Any]], db_available: bool, source_row_index: int) -> dict[str, Any]:
    ingested_doc_id = str(row.get("ingested_doc_id") or "")
    block_by_id = blocks_by_doc.get(ingested_doc_id, {})
    gold_pages = as_int_set(row.get("gold_pages") or [])
    answers = as_str_list(row.get("answers") or [])
    gold_blocks = [block for block in block_by_id.values() if block_page(block) in gold_pages]
    gold_child_blocks = [block for block in gold_blocks if getattr(block, "block_type", "") != "page"]
    gold_retrievable_blocks = [block for block in gold_child_blocks if block_retrieval_text(block)]
    gold_page_text = "\n".join(block_retrieval_text(block) for block in gold_blocks if block_retrieval_text(block))
    retrieved_pages = set(pages_for_block_ids(row.get("retrieved_block_ids") or [], block_by_id))
    selected_pages = set(pages_for_block_ids(row.get("selected_block_ids") or [], block_by_id))
    cited_pages = citation_pages(row, block_by_id)
    bucket = row_bucket(
        row=row,
        db_available=db_available,
        ingested_doc_id=ingested_doc_id,
        gold_pages=gold_pages,
        gold_page_block_count=len(gold_blocks),
        gold_retrievable_block_count=len(gold_retrievable_blocks),
        retrieved_pages=retrieved_pages,
        selected_pages=selected_pages,
        cited_pages=cited_pages,
    )
    return {
        "source_row_index": source_row_index,
        "sample_id": row.get("sample_id"),
        "dataset": row.get("dataset"),
        "doc_id": row.get("doc_id"),
        "ingested_doc_id": ingested_doc_id,
        "bucket": bucket,
        "pass_fail": row.get("pass_fail"),
        "question": row.get("question"),
        "answers": answers,
        "answer_hit": bool(row.get("answer_hit")),
        "gold_pages": sorted(gold_pages),
        "gold_page_block_count": len(gold_blocks),
        "gold_page_child_block_count": len(gold_child_blocks),
        "gold_page_retrievable_block_count": len(gold_retrievable_blocks),
        "gold_page_has_retrievable_blocks": bool(gold_retrievable_blocks),
        "gold_page_answer_text_hit": answer_text_hit(gold_page_text, answers),
        "retrieved_pages": sorted(retrieved_pages),
        "selected_pages": sorted(selected_pages),
        "citation_pages": sorted(cited_pages),
        "retrieved_gold_page_hit": bool(gold_pages and gold_pages.intersection(retrieved_pages)),
        "selected_gold_page_hit": bool(gold_pages and selected_pages and gold_pages.intersection(selected_pages)),
        "citation_gold_page_hit": bool(gold_pages and cited_pages and gold_pages.intersection(cited_pages)),
        "retrieved_gold_page_rank": first_gold_page_rank(row.get("retrieved_block_ids") or [], block_by_id, gold_pages),
        "selected_gold_page_rank": first_gold_page_rank(row.get("selected_block_ids") or [], block_by_id, gold_pages),
        "citation_gold_page_rank": first_gold_page_rank(row.get("citation_block_ids") or [], block_by_id, gold_pages),
        "retrieved_block_count": len(as_str_list(row.get("retrieved_block_ids") or [])),
        "selected_block_count": len(as_str_list(row.get("selected_block_ids") or [])),
        "citation_block_count": len(as_str_list(row.get("citation_block_ids") or [])),
        "retrieved_block_ids": as_str_list(row.get("retrieved_block_ids") or [])[:12],
        "selected_block_ids": as_str_list(row.get("selected_block_ids") or [])[:12],
        "citation_block_ids": as_str_list(row.get("citation_block_ids") or [])[:12],
        "failure_reasons": row.get("failure_reasons") or [],
    }


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def rank_hit(rows: list[dict[str, Any]], k: int) -> int:
    count = 0
    for row in rows:
        rank = row.get("retrieved_gold_page_rank")
        if isinstance(rank, int) and rank <= k:
            count += 1
    return count


def recommendation(bucket_counts: Counter[str]) -> dict[str, Any]:
    if bucket_counts.get("gold_page_blocks_missing", 0) or bucket_counts.get("gold_page_without_retrievable_blocks", 0):
        next_action = "inspect_mineru_evidence_mapping_or_block_text_before_training"
    elif bucket_counts.get("retrieval_gold_page_miss", 0) or bucket_counts.get("retrieved_blocks_empty", 0):
        next_action = "inspect_retrieval_query_or_block_granularity_before_training"
    elif bucket_counts.get("selected_context_gold_page_miss", 0):
        next_action = "inspect_context_selection_before_training"
    elif bucket_counts.get("citation_selection_page_miss", 0):
        next_action = "inspect_citation_selection_before_training"
    elif bucket_counts.get("answer_generation_or_metric_miss", 0):
        next_action = "review_mpdocvqa_answer_generation_or_metric_before_training"
    else:
        next_action = "continue_qwen_eval_before_training"
    return {
        "next_action": next_action,
        "do_not_train_yet": True,
        "reason": "This retrieval inspection uses existing MP-DocVQA validation artifacts only for diagnostic buckets; it does not create training data or tune against individual examples.",
    }


def inspect_mpdocvqa_retrieval(
    *,
    run_dir: Path,
    mpdocvqa_db_path: Path | None,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary_json = load_json(run_dir / "summary.json")
    result_json = load_json(run_dir / "result.json")
    rows, rows_scope, rows_path = load_rows(run_dir)
    missing = [safe_relpath(path) for path in [run_dir / "summary.json", run_dir / "result.json"] if not path.is_file()]
    if rows_scope == "missing":
        missing.append("results.jsonl_or_mpdocvqa_attribution_rows.jsonl_or_failures_sample.jsonl")
    if missing:
        payload = {
            "command": "inspect_mpdocvqa_retrieval",
            "status": "failed",
            "quality_status": "blocked",
            "run_id": run_id,
            "artifact_dir": safe_relpath(artifact_dir),
            "missing": missing,
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
        return write_outputs(artifact_dir=artifact_dir, summary=payload, inspected_rows=[], preview=[], sync_output_root=sync_output_root)

    mp_rows = [
        row
        for row in rows
        if str(row.get("dataset") or "") in {"mp_docvqa", "mpdocvqa"} and row.get("answer_evaluated")
    ]
    blocks_by_doc, db_available = load_blocks(mp_rows, mpdocvqa_db_path)
    inspected_rows = [compact_row(row, blocks_by_doc, db_available, index) for index, row in enumerate(mp_rows)]
    bucket_counts = Counter(str(row.get("bucket") or "") for row in inspected_rows)
    failure_reasons = Counter(reason for row in inspected_rows for reason in row.get("failure_reasons") or [])
    total = len(inspected_rows)
    retrieved_hits = sum(1 for row in inspected_rows if row.get("retrieved_gold_page_hit"))
    selected_hits = sum(1 for row in inspected_rows if row.get("selected_gold_page_hit"))
    citation_hits = sum(1 for row in inspected_rows if row.get("citation_gold_page_hit"))
    retrievable_gold_pages = sum(1 for row in inspected_rows if row.get("gold_page_has_retrievable_blocks"))
    answer_text_hits = sum(1 for row in inspected_rows if row.get("gold_page_answer_text_hit"))
    source_run_id = str(summary_json.get("run_id") or result_json.get("run_id") or run_dir.name)
    summary = {
        "command": "inspect_mpdocvqa_retrieval",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "source_run_id": source_run_id,
        "source_run_dir": safe_relpath(run_dir),
        "rows_scope": rows_scope,
        "rows_path": rows_path,
        "mpdocvqa_db_path": safe_relpath(mpdocvqa_db_path) if mpdocvqa_db_path is not None else "",
        "mpdocvqa_db_available": db_available,
        "used_qwen": bool(summary_json.get("used_qwen", result_json.get("used_qwen", False))),
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "case_count": summary_json.get("case_count"),
        "evaluated_count": summary_json.get("evaluated_count"),
        "mpdocvqa_evaluated_count": total,
        "retrieved_gold_page_hit_count": retrieved_hits,
        "retrieved_gold_page_hit_rate": rate(retrieved_hits, total),
        "selected_gold_page_hit_count": selected_hits,
        "selected_gold_page_hit_rate": rate(selected_hits, total),
        "citation_gold_page_hit_count": citation_hits,
        "citation_gold_page_hit_rate": rate(citation_hits, total),
        "gold_page_has_retrievable_blocks_count": retrievable_gold_pages,
        "gold_page_has_retrievable_blocks_rate": rate(retrievable_gold_pages, total),
        "gold_page_answer_text_hit_count": answer_text_hits,
        "gold_page_answer_text_hit_rate": rate(answer_text_hits, total),
        "retrieval_recall_at_1": rate(rank_hit(inspected_rows, 1), total),
        "retrieval_recall_at_3": rate(rank_hit(inspected_rows, 3), total),
        "retrieval_recall_at_5": rate(rank_hit(inspected_rows, 5), total),
        "retrieved_blocks_empty_count": sum(1 for row in inspected_rows if row.get("retrieved_block_count") == 0),
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "failure_reason_distribution": dict(sorted(failure_reasons.items())),
        "recommendation": recommendation(bucket_counts),
    }
    preview = [row for row in inspected_rows if row.get("bucket") not in {"passed"}][:12]
    return write_outputs(artifact_dir=artifact_dir, summary=summary, inspected_rows=inspected_rows, preview=preview, sync_output_root=sync_output_root)


def write_outputs(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
    inspected_rows: list[dict[str, Any]],
    preview: list[dict[str, Any]],
    sync_output_root: Path | None,
) -> dict[str, Any]:
    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "rows": artifact_dir / "mpdocvqa_retrieval_rows.jsonl",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }
    summary.update(
        {
            "summary_path": safe_relpath(paths["summary"]),
            "summary_markdown_path": safe_relpath(paths["summary_md"]),
            "rows_path": safe_relpath(paths["rows"]),
            "preview_path": safe_relpath(paths["preview"]),
            "manifest_path": safe_relpath(paths["manifest"]),
        }
    )
    result = {
        "command": summary["command"],
        "status": summary["status"],
        "run_id": summary["run_id"],
        "artifact_dir": summary["artifact_dir"],
        "quality_status": summary["quality_status"],
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "mpdocvqa_evaluated_count": summary.get("mpdocvqa_evaluated_count", 0),
        "retrieved_gold_page_hit_rate": summary.get("retrieved_gold_page_hit_rate", 0.0),
        "gold_page_has_retrievable_blocks_rate": summary.get("gold_page_has_retrievable_blocks_rate", 0.0),
        "retrieval_recall_at_5": summary.get("retrieval_recall_at_5", 0.0),
        "bucket_counts": summary.get("bucket_counts", {}),
        "recommendation": summary.get("recommendation", {}),
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_jsonl(paths["rows"], inspected_rows)
    write_json(paths["preview"], preview)
    write_json(paths["result"], result)
    write_manifest(paths["manifest"], run_id=str(summary["run_id"]), artifact_paths=list(paths.values()))
    if sync_output_root is not None:
        sync_bundle_path = safe_relpath(sync_output_root / str(summary["run_id"]))
        summary["sync_bundle_path"] = sync_bundle_path
        result["sync_bundle_path"] = sync_bundle_path
        write_json(paths["summary"], summary)
        write_json(paths["result"], result)
        sync_outputs(sync_output_root / str(summary["run_id"]), paths)
    return {**result, **summary, "artifact_paths": [safe_relpath(path) for path in paths.values()]}


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files: list[dict[str, Any]] = []
    for artifact in artifact_paths:
        if not artifact.is_file():
            continue
        data = artifact.read_bytes()
        files.append(
            {
                "path": safe_relpath(artifact),
                "size_bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
    write_json(path, {"run_id": run_id, "script_version": SCRIPT_VERSION, "files": files})


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    recommendation_payload = summary.get("recommendation") or {}
    lines = [
        "# MP-DocVQA Retrieval Inspection",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- source_run_id: `{summary.get('source_run_id')}`",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary.get('validation_subset_used_for_training')).lower()}`",
        f"- mpdocvqa_db_available: `{str(summary.get('mpdocvqa_db_available')).lower()}`",
        "",
        "## Retrieval Metrics",
        "",
        f"- mpdocvqa_evaluated_count: {summary.get('mpdocvqa_evaluated_count', 0)}",
        f"- retrieved_gold_page_hit_rate: {summary.get('retrieved_gold_page_hit_rate', 0.0)}",
        f"- selected_gold_page_hit_rate: {summary.get('selected_gold_page_hit_rate', 0.0)}",
        f"- citation_gold_page_hit_rate: {summary.get('citation_gold_page_hit_rate', 0.0)}",
        f"- gold_page_has_retrievable_blocks_rate: {summary.get('gold_page_has_retrievable_blocks_rate', 0.0)}",
        f"- gold_page_answer_text_hit_rate: {summary.get('gold_page_answer_text_hit_rate', 0.0)}",
        f"- retrieval_recall_at_1: {summary.get('retrieval_recall_at_1', 0.0)}",
        f"- retrieval_recall_at_3: {summary.get('retrieval_recall_at_3', 0.0)}",
        f"- retrieval_recall_at_5: {summary.get('retrieval_recall_at_5', 0.0)}",
        "",
        "## Buckets",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("bucket_counts") or {}).items())],
        "",
        "## Recommendation",
        "",
        f"- next_action: `{recommendation_payload.get('next_action')}`",
        f"- do_not_train_yet: `{str(recommendation_payload.get('do_not_train_yet')).lower()}`",
        f"- reason: {recommendation_payload.get('reason')}",
        "",
        "This inspection is diagnostic only. It does not run Qwen, start SFT, start GRPO, or create training data.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def sync_outputs(sync_dir: Path, paths: dict[str, Path]) -> None:
    sync_dir.mkdir(parents=True, exist_ok=True)
    for key in ("result", "summary", "summary_md", "preview", "manifest"):
        if paths[key].is_file():
            shutil.copy2(paths[key], sync_dir / paths[key].name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect MP-DocVQA retrieval signals in an AnswerPolicy baseline run.")
    parser.add_argument("--run-dir", required=True, help="AnswerPolicy baseline or attribution artifact directory.")
    parser.add_argument("--mpdocvqa-db-path", required=True, help="SQLite DB with MP-DocVQA EvidenceBlocks.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--sync-output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = inspect_mpdocvqa_retrieval(
        run_dir=repo_path(args.run_dir) or Path(args.run_dir),
        mpdocvqa_db_path=repo_path(args.mpdocvqa_db_path) or Path(args.mpdocvqa_db_path),
        output_root=repo_path(args.output_dir) or Path(args.output_dir),
        run_id=args.run_id,
        sync_output_root=repo_path(args.sync_output_dir) if args.sync_output_dir else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.inspect_mpdocvqa_retrieval import (
    as_int_set,
    as_str_list,
    block_page,
    block_retrieval_text,
    load_blocks,
)
from scripts.run_final_eval_subset import normalize_text


SCRIPT_VERSION = "mpdocvqa-query-block-granularity-inspect-v1"
EVALUATION_SCOPE = "mpdocvqa_query_block_granularity_inspection_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_query_block_granularity_inspect"

STOPWORDS = {
    "the",
    "and",
    "for",
    "from",
    "with",
    "that",
    "this",
    "what",
    "which",
    "when",
    "where",
    "were",
    "was",
    "are",
    "how",
    "many",
    "much",
    "does",
    "did",
    "had",
    "has",
    "have",
    "into",
    "than",
    "their",
    "there",
}


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
    return f"mpdocvqa_query_block_granularity_inspect_{stamp}"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def load_rows(run_dir: Path) -> tuple[list[dict[str, Any]], str, str]:
    for filename, scope in (("rows.jsonl", "comparison_rows"), ("results.jsonl", "full_workflow_rows")):
        path = run_dir / filename
        if path.is_file():
            return [row for row in read_jsonl(path) if isinstance(row, dict)], scope, safe_relpath(path)
    return [], "missing", ""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def tokens(text: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9]+", text.lower()) if len(token) > 2 and token not in STOPWORDS}


def page_text(blocks: list[Any]) -> str:
    return "\n".join(block_retrieval_text(block) for block in blocks if block_retrieval_text(block))


def answer_text_hit(text: str, answers: list[str]) -> bool:
    normalized = normalize_text(text)
    return any(answer and normalize_text(answer) in normalized for answer in answers)


def page_blocks(block_by_id: dict[str, Any], pages: set[int]) -> list[Any]:
    return [block for block in block_by_id.values() if block_page(block) in pages]


def child_blocks(blocks: list[Any]) -> list[Any]:
    return [block for block in blocks if getattr(block, "block_type", "") != "page"]


def retrievable_blocks(blocks: list[Any]) -> list[Any]:
    return [block for block in blocks if block_retrieval_text(block)]


def token_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def overlap_count(question: str, text: str) -> int:
    return len(tokens(question).intersection(tokens(text)))


def first_page_text(block_by_id: dict[str, Any], pages: Any) -> str:
    page_numbers = as_int_set(pages)
    if not page_numbers:
        return ""
    first_page = {sorted(page_numbers)[0]}
    return page_text(page_blocks(block_by_id, first_page))


def diagnostic_bucket(
    *,
    row_bucket: str,
    db_available: bool,
    gold_pages: set[int],
    gold_block_count: int,
    gold_retrievable_block_count: int,
    gold_answer_hit: bool,
    gold_question_overlap: int,
) -> str:
    if row_bucket != "retrieval_gold_page_miss":
        return row_bucket or "not_retrieval_miss"
    if not db_available:
        return "evidence_db_missing"
    if not gold_pages:
        return "gold_page_missing"
    if gold_block_count == 0:
        return "gold_page_blocks_missing"
    if gold_retrievable_block_count == 0:
        return "gold_page_without_retrievable_blocks"
    if not gold_answer_hit:
        return "gold_page_answer_text_not_found"
    if gold_question_overlap == 0:
        return "query_answer_bridge_or_question_terms_absent"
    return "retrieval_ranker_or_block_scoring_miss"


def inspect_row(row: dict[str, Any], blocks_by_doc: dict[str, dict[str, Any]], db_available: bool, index: int) -> dict[str, Any]:
    ingested_doc_id = str(row.get("ingested_doc_id") or "")
    block_by_id = blocks_by_doc.get(ingested_doc_id, {})
    gold_pages = as_int_set(row.get("gold_pages") or [])
    retrieved_pages = as_int_set(row.get("retrieved_pages") or [])
    answers = as_str_list(row.get("answers") or [])
    question = str(row.get("question") or "")

    gold_blocks = page_blocks(block_by_id, gold_pages)
    gold_child_blocks = child_blocks(gold_blocks)
    gold_retrievable_blocks = retrievable_blocks(gold_child_blocks)
    gold_text = page_text(gold_blocks)
    first_retrieved_text = first_page_text(block_by_id, retrieved_pages)

    gold_answer_hit = answer_text_hit(gold_text, answers)
    retrieved_answer_hit = answer_text_hit(first_retrieved_text, answers)
    gold_question_overlap = overlap_count(question, gold_text)
    retrieved_question_overlap = overlap_count(question, first_retrieved_text)
    row_bucket = str(row.get("bucket") or "")
    bucket = diagnostic_bucket(
        row_bucket=row_bucket,
        db_available=db_available,
        gold_pages=gold_pages,
        gold_block_count=len(gold_blocks),
        gold_retrievable_block_count=len(gold_retrievable_blocks),
        gold_answer_hit=gold_answer_hit,
        gold_question_overlap=gold_question_overlap,
    )
    return {
        "source_row_index": index,
        "source_run_id": str(row.get("source_run_id") or ""),
        "sample_id": str(row.get("sample_id") or ""),
        "doc_id": str(row.get("doc_id") or ""),
        "ingested_doc_id": ingested_doc_id,
        "source_document": str(row.get("source_document") or ""),
        "row_bucket": row_bucket,
        "diagnostic_bucket": bucket,
        "question": question,
        "answers": answers,
        "task_type": str(row.get("task_type") or ""),
        "answer_hit": bool(row.get("answer_hit")),
        "retrieved_gold_page_hit": bool(row.get("retrieved_gold_page_hit")),
        "citation_page_hit": bool(row.get("citation_page_hit")),
        "gold_pages": sorted(gold_pages),
        "retrieved_pages": sorted(retrieved_pages),
        "selected_pages": row.get("selected_pages") or [],
        "citation_pages": row.get("citation_pages") or [],
        "gold_page_block_count": len(gold_blocks),
        "gold_page_child_block_count": len(gold_child_blocks),
        "gold_page_retrievable_block_count": len(gold_retrievable_blocks),
        "gold_page_token_count": token_count(gold_text),
        "gold_page_answer_text_hit": gold_answer_hit,
        "gold_page_question_token_overlap_count": gold_question_overlap,
        "first_retrieved_page_answer_text_hit": retrieved_answer_hit,
        "first_retrieved_page_question_token_overlap_count": retrieved_question_overlap,
        "gold_page_text_preview": gold_text[:400],
        "first_retrieved_page_text_preview": first_retrieved_text[:400],
    }


def recommendation(bucket_counts: Counter[str]) -> dict[str, Any]:
    if bucket_counts.get("evidence_db_missing", 0) or bucket_counts.get("gold_page_blocks_missing", 0):
        next_action = "inspect_mineru_evidence_mapping_before_training"
    elif bucket_counts.get("gold_page_without_retrievable_blocks", 0) or bucket_counts.get(
        "gold_page_answer_text_not_found", 0
    ):
        next_action = "inspect_ocr_or_gold_page_text_before_training"
    elif bucket_counts.get("query_answer_bridge_or_question_terms_absent", 0):
        next_action = "inspect_query_rewriter_for_answer_bridge_before_training"
    elif bucket_counts.get("retrieval_ranker_or_block_scoring_miss", 0):
        next_action = "inspect_retriever_block_scoring_or_page_context_before_training"
    else:
        next_action = "continue_qwen_eval_before_training"
    return {
        "next_action": next_action,
        "do_not_train_yet": True,
        "reason": "This inspection reads existing MP-DocVQA workflow artifacts and EvidenceBlocks only; it does not call models, create training data, or tune against validation examples.",
    }


def inspect_mpdocvqa_query_block_granularity(
    *,
    run_dir: Path,
    mpdocvqa_db_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    source_summary = load_json(run_dir / "summary.json")
    source_result = load_json(run_dir / "result.json")
    rows, rows_scope, rows_path = load_rows(run_dir)
    missing = [safe_relpath(path) for path in (run_dir / "summary.json", run_dir / "result.json") if not path.is_file()]
    if rows_scope == "missing":
        missing.append("rows.jsonl_or_results.jsonl")
    if not mpdocvqa_db_path.is_file():
        missing.append(safe_relpath(mpdocvqa_db_path))
    if missing:
        summary = {
            "command": "inspect_mpdocvqa_query_block_granularity",
            "status": "failed",
            "quality_status": "blocked",
            "run_id": run_id,
            "artifact_dir": safe_relpath(artifact_dir),
            "missing": missing,
            "used_training": False,
            "formal_benchmark_acceptance": False,
            "validation_subset_used_for_training": False,
        }
        return write_outputs(artifact_dir=artifact_dir, summary=summary, rows=[], preview=[], sync_output_root=sync_output_root)

    mp_rows = [row for row in rows if str(row.get("ingested_doc_id") or "")]
    blocks_by_doc, db_available = load_blocks(mp_rows, mpdocvqa_db_path)
    inspected_rows = [inspect_row(row, blocks_by_doc, db_available, index) for index, row in enumerate(mp_rows)]
    retrieval_miss_rows = [row for row in inspected_rows if row.get("row_bucket") == "retrieval_gold_page_miss"]
    bucket_counts = Counter(str(row.get("diagnostic_bucket") or "") for row in inspected_rows)
    retrieval_miss_bucket_counts = Counter(str(row.get("diagnostic_bucket") or "") for row in retrieval_miss_rows)
    source_run_id = str(source_summary.get("run_id") or source_result.get("run_id") or run_dir.name)
    summary = {
        "command": "inspect_mpdocvqa_query_block_granularity",
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
        "mpdocvqa_db_path": safe_relpath(mpdocvqa_db_path),
        "mpdocvqa_db_available": db_available,
        "evaluated_count": len(inspected_rows),
        "retrieval_miss_count": len(retrieval_miss_rows),
        "gold_page_answer_text_hit_count": sum(1 for row in retrieval_miss_rows if row.get("gold_page_answer_text_hit")),
        "gold_page_answer_text_hit_rate": rate(
            sum(1 for row in retrieval_miss_rows if row.get("gold_page_answer_text_hit")), len(retrieval_miss_rows)
        ),
        "gold_page_question_overlap_count": sum(
            1 for row in retrieval_miss_rows if int(row.get("gold_page_question_token_overlap_count") or 0) > 0
        ),
        "gold_page_question_overlap_rate": rate(
            sum(1 for row in retrieval_miss_rows if int(row.get("gold_page_question_token_overlap_count") or 0) > 0),
            len(retrieval_miss_rows),
        ),
        "diagnostic_bucket_counts": dict(sorted(bucket_counts.items())),
        "retrieval_miss_diagnostic_bucket_counts": dict(sorted(retrieval_miss_bucket_counts.items())),
        "used_qwen": bool(source_summary.get("used_qwen", True)),
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "recommendation": recommendation(retrieval_miss_bucket_counts),
    }
    preview = [row for row in inspected_rows if row.get("row_bucket") == "retrieval_gold_page_miss"][:16]
    return write_outputs(
        artifact_dir=artifact_dir,
        summary=summary,
        rows=inspected_rows,
        preview=preview,
        sync_output_root=sync_output_root,
    )


def write_outputs(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    preview: list[dict[str, Any]],
    sync_output_root: Path | None,
) -> dict[str, Any]:
    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "rows": artifact_dir / "rows.jsonl",
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
        "evaluated_count": summary.get("evaluated_count", 0),
        "retrieval_miss_count": summary.get("retrieval_miss_count", 0),
        "gold_page_answer_text_hit_rate": summary.get("gold_page_answer_text_hit_rate", 0.0),
        "gold_page_question_overlap_rate": summary.get("gold_page_question_overlap_rate", 0.0),
        "retrieval_miss_diagnostic_bucket_counts": summary.get("retrieval_miss_diagnostic_bucket_counts", {}),
        "recommendation": summary.get("recommendation", {}),
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_jsonl(paths["rows"], rows)
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


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    recommendation_payload = summary.get("recommendation") or {}
    lines = [
        "# MP-DocVQA Query and Block Granularity Inspection",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- source_run_id: `{summary.get('source_run_id')}`",
        f"- evaluated_count: {summary.get('evaluated_count', 0)}",
        f"- retrieval_miss_count: {summary.get('retrieval_miss_count', 0)}",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary.get('validation_subset_used_for_training')).lower()}`",
        "",
        "## Retrieval Miss Signals",
        "",
        f"- gold_page_answer_text_hit_rate: {summary.get('gold_page_answer_text_hit_rate', 0.0)}",
        f"- gold_page_question_overlap_rate: {summary.get('gold_page_question_overlap_rate', 0.0)}",
        "",
        "## Diagnostic Buckets",
        "",
        *[
            f"- {key}: {value}"
            for key, value in sorted((summary.get("retrieval_miss_diagnostic_bucket_counts") or {}).items())
        ],
        "",
        "## Recommendation",
        "",
        f"- next_action: `{recommendation_payload.get('next_action')}`",
        f"- do_not_train_yet: `{str(recommendation_payload.get('do_not_train_yet')).lower()}`",
        f"- reason: {recommendation_payload.get('reason')}",
        "",
        "This inspection is diagnostic only. It does not call models, start training, or create training data.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files: list[dict[str, Any]] = []
    for artifact in artifact_paths:
        if not artifact.is_file():
            continue
        files.append(
            {
                "path": safe_relpath(artifact),
                "size_bytes": artifact.stat().st_size,
                "sha256": sha256_file(artifact),
            }
        )
    write_json(path, {"run_id": run_id, "script_version": SCRIPT_VERSION, "files": files})


def sync_outputs(sync_dir: Path, paths: dict[str, Path]) -> None:
    sync_dir.mkdir(parents=True, exist_ok=True)
    for key in ("result", "summary", "summary_md", "preview", "manifest"):
        if paths[key].is_file():
            shutil.copy2(paths[key], sync_dir / paths[key].name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect MP-DocVQA query and block granularity signals.")
    parser.add_argument("--run-dir", required=True, help="Comparison or full-workflow diagnostic artifact directory.")
    parser.add_argument("--mpdocvqa-db-path", required=True, help="SQLite DB with MP-DocVQA EvidenceBlocks.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--sync-output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = inspect_mpdocvqa_query_block_granularity(
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

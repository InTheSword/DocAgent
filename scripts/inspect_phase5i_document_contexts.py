from __future__ import annotations

import argparse
import glob
import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from scripts.run_phase5i_answer_quality_benchmark import (
    DEFAULT_DB_PATH,
    DEFAULT_DOC_ID,
    GoldenCase,
    _document_context_status,
    _read_cases_jsonl,
    default_cases,
)


SCRIPT_VERSION = "phase5i-document-context-inventory-v1"
EVALUATION_SCOPE = "phase5i_document_context_inventory_not_model_eval"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "phase5i_document_context_inventory"


def _now_run_id() -> str:
    return "phase5i_document_context_inventory_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


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


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n",
        encoding="utf-8",
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, capture_output=True, timeout=10)
    except Exception:
        return ""
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _unique_paths(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def expand_db_paths(db_paths: list[str] | None, db_globs: list[str] | None) -> list[Path]:
    paths = [repo_path(path) for path in (db_paths or [])]
    globbed: list[Path] = []
    for pattern in db_globs or []:
        if Path(pattern).is_absolute():
            globbed.extend(Path(match) for match in glob.glob(pattern))
        else:
            globbed.extend(ROOT / match for match in glob.glob(pattern, root_dir=ROOT))
    if not paths and not globbed:
        paths = [DEFAULT_DB_PATH]
    return _unique_paths([path for path in [*paths, *globbed] if path is not None])


def list_candidate_doc_ids(
    db_path: Path,
    *,
    explicit_doc_ids: list[str] | None,
    max_documents: int,
    include_default_doc_id: bool,
) -> list[str]:
    doc_ids = [doc_id for doc_id in (explicit_doc_ids or []) if doc_id]
    if not doc_ids and db_path.is_file():
        conn = connect(db_path)
        try:
            repository = DocumentRepository(conn)
            doc_ids.extend(str(row.get("doc_id") or "") for row in repository.list_documents()[: max(0, max_documents)])
        finally:
            conn.close()
    if include_default_doc_id and not explicit_doc_ids and DEFAULT_DOC_ID not in doc_ids:
        doc_ids.insert(0, DEFAULT_DOC_ID)
    return [doc_id for doc_id in dict.fromkeys(doc_ids) if doc_id]


def load_cases(cases_jsonl: Path | None) -> list[GoldenCase]:
    return _read_cases_jsonl(cases_jsonl) if cases_jsonl is not None else default_cases()


def _contains(text: str, keyword: str) -> bool:
    return keyword.lower() in text.lower()


def _case_row(db_path: Path, doc_id: str, case: GoldenCase, retrievable_blocks: list[Any]) -> dict[str, Any]:
    texts = [str(block.retrieval_text or "") for block in retrievable_blocks]
    evidence_keyword_hits = {
        keyword: any(_contains(text, keyword) for text in texts)
        for keyword in case.expected_evidence_keywords
    }
    answer_keyword_hits = {
        keyword: any(_contains(text, keyword) for text in texts)
        for keyword in case.expected_answer_keywords
    }
    page_has_retrievable_block = (
        True
        if case.expected_page is None
        else any(block.page_id == case.expected_page and str(block.retrieval_text or "").strip() for block in retrievable_blocks)
    )
    evidence_keywords_all_hit = all(evidence_keyword_hits.values()) if evidence_keyword_hits else True
    return {
        "db_path": safe_relpath(db_path),
        "doc_id": doc_id,
        "case_id": case.case_id,
        "expected_task_type": case.expected_task_type,
        "expected_page": case.expected_page,
        "page_has_retrievable_block": page_has_retrievable_block,
        "evidence_keyword_hits": evidence_keyword_hits,
        "answer_keyword_hits": answer_keyword_hits,
        "evidence_keywords_all_hit": evidence_keywords_all_hit,
        "context_ready_for_case": bool(page_has_retrievable_block and evidence_keywords_all_hit),
    }


def inspect_document_context(db_path: Path, doc_id: str, cases: list[GoldenCase]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    context = _document_context_status(db_path, doc_id)
    row: dict[str, Any] = {
        "db_path": safe_relpath(db_path),
        "doc_id": doc_id,
        "ready": bool(context.get("ready")),
        "blocker_type": context.get("blocker_type") or "",
        "message": context.get("message") or "",
        "document": context.get("document") or {},
        "evidence_block_count": context.get("evidence_block_count", 0),
        "retrievable_evidence_block_count": context.get("retrievable_evidence_block_count", 0),
    }
    if not context.get("ready"):
        row["case_context_ready_count"] = 0
        row["case_context_ready_rate"] = 0.0
        return row, []

    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        blocks = repository.load_evidence_blocks(doc_id)
    finally:
        conn.close()

    retrievable_blocks = [block for block in blocks if str(block.retrieval_text or "").strip()]
    block_type_counts = Counter(block.block_type for block in blocks)
    retrievable_block_type_counts = Counter(block.block_type for block in retrievable_blocks)
    retrievable_pages = sorted({block.page_id for block in retrievable_blocks if block.page_id is not None})
    case_rows = [_case_row(db_path, doc_id, case, retrievable_blocks) for case in cases]
    case_ready_count = sum(1 for item in case_rows if item["context_ready_for_case"])
    row.update(
        {
            "block_type_counts": dict(sorted(block_type_counts.items())),
            "retrievable_block_type_counts": dict(sorted(retrievable_block_type_counts.items())),
            "retrievable_page_count": len(retrievable_pages),
            "retrievable_pages_sample": retrievable_pages[:20],
            "case_count": len(case_rows),
            "case_context_ready_count": case_ready_count,
            "case_context_ready_rate": round(case_ready_count / len(case_rows), 4) if case_rows else None,
            "retrieval_text_previews": [
                {
                    "block_id": block.block_id,
                    "page_id": block.page_id,
                    "block_type": block.block_type,
                    "text_preview": " ".join(str(block.retrieval_text or "").split())[:240],
                }
                for block in retrievable_blocks[:5]
            ],
        }
    )
    return row, case_rows


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files = []
    for artifact_path in artifact_paths:
        if artifact_path.name == "manifest.json" or not artifact_path.is_file():
            continue
        files.append(
            {
                "path": safe_relpath(artifact_path),
                "byte_size": artifact_path.stat().st_size,
                "sha256": sha256_file(artifact_path),
            }
        )
    write_json(
        path,
        {
            "run_id": run_id,
            "command": "inspect_phase5i_document_contexts",
            "script_version": SCRIPT_VERSION,
            "git_commit": git_commit(),
            "files": files,
        },
    )


def sync_artifacts(sync_output_dir: Path | None, run_id: str, artifact_paths: list[Path]) -> tuple[str | None, list[str]]:
    if sync_output_dir is None:
        return None, []
    sync_dir = sync_output_dir / run_id
    sync_dir.mkdir(parents=True, exist_ok=True)
    synced: list[str] = []
    for path in artifact_paths:
        if not path.is_file():
            continue
        target = sync_dir / path.name
        shutil.copy2(path, target)
        synced.append(safe_relpath(target))
    return safe_relpath(sync_dir), synced


def inspect_phase5i_document_contexts(
    *,
    run_id: str,
    output_root: Path,
    db_paths: list[Path],
    explicit_doc_ids: list[str] | None,
    cases: list[GoldenCase],
    max_documents: int,
    include_default_doc_id: bool,
    sync_output_dir: Path | None = None,
) -> dict[str, Any]:
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    document_rows: list[dict[str, Any]] = []
    case_rows: list[dict[str, Any]] = []
    for db_path in db_paths:
        doc_ids = list_candidate_doc_ids(
            db_path,
            explicit_doc_ids=explicit_doc_ids,
            max_documents=max_documents,
            include_default_doc_id=include_default_doc_id,
        )
        if not doc_ids:
            doc_ids = [DEFAULT_DOC_ID]
        for doc_id in doc_ids:
            document_row, document_case_rows = inspect_document_context(db_path, doc_id, cases)
            document_rows.append(document_row)
            case_rows.extend(document_case_rows)

    ready_rows = [row for row in document_rows if row.get("ready")]
    candidate_rows = [row for row in ready_rows if (row.get("case_context_ready_count") or 0) > 0]
    blocker_counts = Counter(str(row.get("blocker_type") or "ready") for row in document_rows)
    result = {
        "command": "inspect_phase5i_document_contexts",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "inventory_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "db_path_count": len(db_paths),
        "document_context_count": len(document_rows),
        "ready_document_count": len(ready_rows),
        "candidate_document_count": len(candidate_rows),
        "case_context_row_count": len(case_rows),
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "best_candidates": sorted(
            candidate_rows,
            key=lambda row: (row.get("case_context_ready_count") or 0, row.get("retrievable_evidence_block_count") or 0),
            reverse=True,
        )[:5],
        "used_qwen": False,
        "used_vlm": False,
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "recommendation": {
            "next_action": (
                "run_phase5ib_answer_quality_probe_with_selected_context"
                if candidate_rows
                else "materialize_or_select_valid_document_context_before_phase5ib_probe"
            ),
            "do_not_train_yet": True,
            "reason": (
                "This read-only inventory checks whether candidate db_path/doc_id pairs have persisted retrievable "
                "EvidenceBlocks before any Phase 5I-B model-backed answer-quality probe. It does not call models or create training data."
            ),
        },
    }

    result_path = artifact_dir / "result.json"
    summary_path = artifact_dir / "summary.json"
    summary_md_path = artifact_dir / "summary.md"
    documents_path = artifact_dir / "document_context_rows.jsonl"
    cases_path = artifact_dir / "case_context_rows.jsonl"
    preview_path = artifact_dir / "preview.json"
    manifest_path = artifact_dir / "manifest.json"
    artifact_paths = [result_path, summary_path, summary_md_path, documents_path, cases_path, preview_path, manifest_path]

    write_json(result_path, result)
    write_json(summary_path, result)
    write_jsonl(documents_path, document_rows)
    write_jsonl(cases_path, case_rows)
    write_json(
        preview_path,
        {
            "best_candidates": result["best_candidates"],
            "document_context_rows": document_rows[:10],
            "case_context_rows": case_rows[:20],
        },
    )
    summary_md_path.write_text(
        "\n".join(
            [
                "# Phase 5I-B Document Context Inventory",
                "",
                f"- status: {result['status']}",
                f"- ready_document_count: {result['ready_document_count']}",
                f"- candidate_document_count: {result['candidate_document_count']}",
                f"- blocker_counts: `{json.dumps(result['blocker_counts'], ensure_ascii=False)}`",
                f"- next_action: {result['recommendation']['next_action']}",
                "",
                "This inventory is read-only and does not call Qwen, BGE-M3, reranker, MinerU, VLM, or training.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    write_manifest(manifest_path, run_id=run_id, artifact_paths=artifact_paths)
    result.update(
        {
            "summary_path": safe_relpath(summary_path),
            "rows_path": safe_relpath(documents_path),
            "case_rows_path": safe_relpath(cases_path),
            "preview_path": safe_relpath(preview_path),
            "manifest_path": safe_relpath(manifest_path),
            "artifact_paths": [safe_relpath(path) for path in artifact_paths],
            "sync_bundle_path": None,
            "sync_artifact_paths": [],
        }
    )
    write_json(result_path, result)
    write_json(summary_path, result)
    write_json(
        preview_path,
        {
            "best_candidates": result["best_candidates"],
            "document_context_rows": document_rows[:10],
            "case_context_rows": case_rows[:20],
        },
    )
    write_manifest(manifest_path, run_id=run_id, artifact_paths=artifact_paths)
    if sync_output_dir is not None:
        sync_bundle_path, sync_artifact_paths = sync_artifacts(sync_output_dir, run_id, artifact_paths)
        result["sync_bundle_path"] = sync_bundle_path
        result["sync_artifact_paths"] = sync_artifact_paths
        write_json(result_path, result)
        write_json(summary_path, result)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Phase 5I-B candidate document contexts without calling models.")
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--db-path", action="append", help="SQLite database path. Can be repeated.")
    parser.add_argument("--db-glob", action="append", help="Repository-relative or absolute glob for SQLite database paths.")
    parser.add_argument("--doc-id", action="append", help="Document id to inspect. Can be repeated.")
    parser.add_argument("--cases-jsonl")
    parser.add_argument("--max-documents", type=int, default=20)
    parser.add_argument("--include-default-doc-id", dest="include_default_doc_id", action="store_true", default=True)
    parser.add_argument("--no-include-default-doc-id", dest="include_default_doc_id", action="store_false")
    parser.add_argument("--sync-output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    run_id = args.run_id or _now_run_id()
    cases_path = repo_path(args.cases_jsonl)
    output_root = repo_path(args.output_dir) or DEFAULT_OUTPUT_ROOT
    sync_output_dir = repo_path(args.sync_output_dir)
    result = inspect_phase5i_document_contexts(
        run_id=run_id,
        output_root=output_root,
        db_paths=expand_db_paths(args.db_path, args.db_glob),
        explicit_doc_ids=args.doc_id,
        cases=load_cases(cases_path),
        max_documents=args.max_documents,
        include_default_doc_id=args.include_default_doc_id,
        sync_output_dir=sync_output_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

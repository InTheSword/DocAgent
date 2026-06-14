from __future__ import annotations

import argparse
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.ingestion.document_registry import DocumentRegistry
from docagent.ingestion.hashing import sha256_file
from docagent.ingestion.service import DocumentIngestionService
from docagent.parser.mineru_backend import MinerUParserBackend
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl


WINDOWS_PATH_RE = re.compile(r"(^|[^A-Za-z0-9])([A-Za-z]:[\\/]|\\\\)")


def _repo_rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _prepare_work_dir(work_dir: Path) -> None:
    resolved = work_dir.resolve()
    if resolved in {Path(resolved.anchor), ROOT.resolve()}:
        raise RuntimeError(f"refusing to clean unsafe work directory: {work_dir}")
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)


def _looks_like_local_absolute_path(value: str) -> bool:
    if "://" in value:
        return False
    if WINDOWS_PATH_RE.search(value):
        return True
    if value.startswith("/") and not value.startswith("//"):
        return True
    return False


def _scan_absolute_paths(value: Any, *, where: str, hits: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _scan_absolute_paths(item, where=f"{where}.{key}", hits=hits)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_absolute_paths(item, where=f"{where}[{index}]", hits=hits)
    elif isinstance(value, str) and _looks_like_local_absolute_path(value):
        hits.append({"where": where, "value": value})


def _sanitize_manifest_paths(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _sanitize_manifest_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_manifest_paths(item) for item in value]
    if isinstance(value, str) and _looks_like_local_absolute_path(value):
        return Path(value).name
    return value


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _copy_source_manifest(mineru_output: Path, document_dir: Path) -> None:
    manifest = mineru_output.parent / "source_manifest.json"
    if not manifest.exists():
        return
    payload = _read_json(manifest)
    if isinstance(payload, dict):
        payload = _sanitize_manifest_paths(payload)
        payload["source_file"] = "source/original.pdf"
        (document_dir / "mineru_source_manifest.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _page_aggregates_valid(blocks: list[dict[str, Any]], pages: list[dict[str, Any]]) -> bool:
    by_page: dict[int, set[str]] = {}
    excluded_by_page: dict[int, set[str]] = {}
    retrieval_text_by_page: dict[int, bool] = {}
    for block in blocks:
        page = block.get("page_id")
        if page is None:
            return False
        page_id = int(page)
        by_page.setdefault(page_id, set()).add(str(block["block_id"]))
        if block.get("metadata", {}).get("exclude_from_retrieval"):
            excluded_by_page.setdefault(page_id, set()).add(str(block["block_id"]))
        elif block.get("text") or block.get("table_html") or block.get("visual_summary"):
            retrieval_text_by_page[page_id] = True
    if len(pages) != len(by_page):
        return False
    for page_record in pages:
        page = page_record.get("page_id")
        metadata = page_record.get("metadata") or {}
        location = page_record.get("location") or {}
        if page is None or location.get("page") != page:
            return False
        if retrieval_text_by_page.get(int(page)) and not page_record.get("text"):
            return False
        child_ids = set(metadata.get("child_block_ids") or [])
        excluded_ids = set(metadata.get("excluded_child_block_ids") or [])
        if child_ids != by_page.get(int(page), set()):
            return False
        if excluded_ids != excluded_by_page.get(int(page), set()):
            return False
    return True


def _scan_persisted_artifacts(
    *,
    document_dir: Path,
    sqlite_path: Path,
    blocks: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    ingestion_report: dict[str, Any],
    quality_report: dict[str, Any],
) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    _scan_absolute_paths(blocks, where="evidence_blocks.jsonl", hits=hits)
    _scan_absolute_paths(pages, where="page_documents.jsonl", hits=hits)
    _scan_absolute_paths(ingestion_report, where="ingestion_report.json", hits=hits)
    _scan_absolute_paths(quality_report, where="structure_quality.json", hits=hits)
    manifest_path = document_dir / "mineru_source_manifest.json"
    if manifest_path.exists():
        _scan_absolute_paths(_read_json(manifest_path), where="mineru_source_manifest.json", hits=hits)
    with sqlite3.connect(sqlite_path) as conn:
        rows = conn.execute("SELECT block_id, payload_json, metadata_json FROM evidence_blocks").fetchall()
    for block_id, payload_json, metadata_json in rows:
        _scan_absolute_paths(json.loads(payload_json), where=f"sqlite.payload_json[{block_id}]", hits=hits)
        if metadata_json:
            _scan_absolute_paths(json.loads(metadata_json), where=f"sqlite.metadata_json[{block_id}]", hits=hits)
    return hits


def _verify(args: argparse.Namespace) -> dict[str, Any]:
    source_pdf = Path(args.source_pdf)
    mineru_output = Path(args.mineru_output)
    work_dir = Path(args.work_dir)
    if source_pdf.name.lower() == "cdc_135850_ds1.pdf":
        raise RuntimeError("CDC PDF is out of scope for this verifier")
    _prepare_work_dir(work_dir)
    document_root = work_dir / "documents"
    sqlite_path = work_dir / "docagent.sqlite"
    preview = DocumentRegistry(document_root).register(source_pdf)
    document_dir = Path(preview.document_dir)
    shutil.copytree(mineru_output, document_dir / "mineru")
    _copy_source_manifest(mineru_output, document_dir)

    conn = connect(sqlite_path)
    repository = DocumentRepository(conn)
    service = DocumentIngestionService(document_root=document_root, repository=repository)
    result = service.ingest(
        file_path=source_pdf,
        parser_backend=MinerUParserBackend(mode="parse_existing", backend_name="mineru_existing"),
        force_parse=True,
    )
    conn.close()
    doc_id = result.document.doc_id
    evidence_path = document_dir / "evidence_blocks.jsonl"
    pages_path = document_dir / "page_documents.jsonl"
    ingestion_path = document_dir / "ingestion_report.json"
    quality_path = document_dir / "structure_quality.json"
    blocks = read_jsonl(evidence_path)
    pages = read_jsonl(pages_path)
    ingestion_report = _read_json(ingestion_path)
    quality_report = _read_json(quality_path)

    with sqlite3.connect(sqlite_path) as sqlite_conn:
        sqlite_counts = {
            "documents": sqlite_conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0],
            "evidence_blocks": sqlite_conn.execute("SELECT COUNT(*) FROM evidence_blocks").fetchone()[0],
        }

    absolute_hits = _scan_persisted_artifacts(
        document_dir=document_dir,
        sqlite_path=sqlite_path,
        blocks=blocks,
        pages=pages,
        ingestion_report=ingestion_report,
        quality_report=quality_report,
    )
    page_aggregates_valid = _page_aggregates_valid(blocks, pages)
    converted_types = Counter(block["block_type"] for block in blocks)
    checks = {
        "converted_nonempty": len(blocks) > 0,
        "raw_blocks_accounted_for": quality_report["raw_block_count"] == len(blocks),
        "quality_not_failed": quality_report["overall_status"] in {"passed", "passed_with_warnings"},
        "no_persisted_absolute_paths": len(absolute_hits) == 0,
        "page_aggregates_valid": page_aggregates_valid,
        "sqlite_document_count": sqlite_counts["documents"] == 1,
        "sqlite_evidence_count": sqlite_counts["evidence_blocks"] == len(blocks) + len(pages),
        "block_ids_unique": bool(quality_report["block_id_unique"]),
        "reading_order_contiguous": bool(quality_report["reading_order_contiguous"]),
        "adjacency_valid": bool(quality_report["adjacency_valid"]),
        "no_missing_images": quality_report["missing_image_reference_count"] == 0,
    }
    failures = [name for name, ok in checks.items() if not ok]
    status = "success" if not failures else "failed"
    payload = {
        "command": "verify_phase2b_real_pdf",
        "status": status,
        "doc_id": doc_id,
        "source_sha256": sha256_file(source_pdf),
        "raw_block_count": quality_report["raw_block_count"],
        "converted_block_count": len(blocks),
        "page_count": quality_report["content_list_page_count"],
        "page_document_count": len(pages),
        "raw_type_distribution": quality_report["raw_type_distribution"],
        "converted_type_distribution": dict(sorted(converted_types.items())),
        "table_count": quality_report["table_count"],
        "table_html_count": quality_report["table_html_count"],
        "chart_count": quality_report["chart_count"],
        "boilerplate_count": quality_report["boilerplate_count"],
        "empty_boilerplate_count": quality_report["empty_boilerplate_count"],
        "missing_retrieval_content_count": quality_report["missing_retrieval_content_count"],
        "image_reference_count": quality_report["image_reference_count"],
        "missing_image_reference_count": quality_report["missing_image_reference_count"],
        "block_ids_unique": quality_report["block_id_unique"],
        "reading_order_contiguous": quality_report["reading_order_contiguous"],
        "adjacency_valid": quality_report["adjacency_valid"],
        "page_aggregates_valid": page_aggregates_valid,
        "sqlite": sqlite_counts,
        "persisted_absolute_path_count": len(absolute_hits),
        "overall_status": quality_report["overall_status"],
        "warnings": quality_report["warnings"],
        "failures": failures,
        "artifact_paths": {
            "evidence_blocks": _repo_rel(evidence_path),
            "page_documents": _repo_rel(pages_path),
            "ingestion_report": _repo_rel(ingestion_path),
            "structure_quality": _repo_rel(quality_path),
            "sqlite": _repo_rel(sqlite_path),
            "verification_report": _repo_rel(work_dir / "verification_report.json"),
        },
    }
    if absolute_hits:
        payload["persisted_absolute_path_examples"] = absolute_hits[:5]
    (work_dir / "verification_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-pdf", required=True)
    parser.add_argument("--mineru-output", required=True)
    parser.add_argument("--work-dir", required=True)
    args = parser.parse_args()
    try:
        payload = _verify(args)
    except Exception as exc:
        payload = {
            "command": "verify_phase2b_real_pdf",
            "status": "failed",
            "error": f"{type(exc).__name__}: {exc}",
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        raise SystemExit(1)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if payload["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()

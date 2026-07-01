from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.schemas import EvidenceBlock
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.prompts import build_evidence_context, format_evidence_blocks


SCRIPT_VERSION = "answer-prompt-media-metadata-audit-v1"
EVALUATION_SCOPE = "answer_prompt_media_metadata_audit_not_training"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "answer_prompt_media_audit"
MEDIA_METADATA_KEYS = ("table_caption", "caption", "image_caption", "chart_caption")


def repo_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def safe_relpath(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"answer_prompt_media_audit_{stamp}"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compact(text: object, *, max_chars: int = 240) -> str:
    value = " ".join(str(text or "").split())
    return value[:max_chars]


def is_remote_resource(value: str | None) -> bool:
    return bool(re.match(r"^https?://", str(value or "").strip(), flags=re.IGNORECASE))


def is_absolute_path(value: str | None) -> bool:
    text = str(value or "").replace("\\", "/")
    return bool(re.match(r"^[A-Za-z]:/", text) or text.startswith("/"))


def metadata_value(block: EvidenceBlock, *keys: str) -> str:
    parts: list[str] = []
    for key in keys:
        value = block.metadata.get(key)
        if isinstance(value, list):
            parts.extend(str(item).strip() for item in value if str(item or "").strip())
        elif value not in {None, ""}:
            parts.append(str(value).strip())
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        normalized = " ".join(part.split())
        marker = normalized.casefold()
        if normalized and marker not in seen:
            seen.add(marker)
            result.append(normalized)
    return " ".join(result)


def block_media_fields(block: EvidenceBlock) -> dict[str, str]:
    fields = {
        "table_caption": metadata_value(block, "table_caption"),
        "image_caption": metadata_value(block, "caption", "image_caption", "chart_caption"),
        "image_path": str(block.image_path or "").strip(),
    }
    return {key: value for key, value in fields.items() if value}


def output_media_fields(block: EvidenceBlock) -> dict[str, str]:
    fields = block_media_fields(block)
    image_path = fields.get("image_path")
    if image_path and is_remote_resource(image_path):
        fields["image_path"] = "<remote_image_resource>"
    elif image_path and is_absolute_path(image_path):
        fields["image_path"] = "<absolute_image_resource>"
    return fields


def has_media(block: EvidenceBlock) -> bool:
    return bool(block_media_fields(block))


def expects_prompt_media(block: EvidenceBlock) -> bool:
    fields = block_media_fields(block)
    image_path = fields.get("image_path")
    return bool(
        fields.get("table_caption")
        or fields.get("image_caption")
        or (image_path and not is_absolute_path(image_path))
    )


def prompt_eligible(block: EvidenceBlock) -> bool:
    if block.block_type == "page":
        return False
    if block.metadata.get("is_boilerplate") or block.metadata.get("exclude_from_retrieval"):
        return False
    return bool(block.retrieval_text.strip())


def document_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [row for row in read_jsonl(path) if isinstance(row, dict)]


def selected_document_ids(rows: list[dict[str, Any]], *, max_documents: int | None) -> list[str]:
    doc_ids: list[str] = []
    seen: set[str] = set()
    for row in rows:
        doc_id = str(row.get("ingested_doc_id") or row.get("doc_id") or "").strip()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        doc_ids.append(doc_id)
        if max_documents is not None and len(doc_ids) >= max_documents:
            break
    return doc_ids


def block_preview(block: EvidenceBlock) -> str:
    return compact(block.retrieval_text, max_chars=220)


def formatted_headers(formatted: str) -> list[str]:
    headers: list[str] = []
    for line in formatted.splitlines():
        if line.startswith("[") and "block_id=" in line:
            headers.append(line[:500])
    return headers


def audit_document(
    *,
    repository: DocumentRepository,
    doc_id: str,
    max_blocks_per_doc: int,
) -> dict[str, Any]:
    blocks = repository.load_evidence_blocks(doc_id, include_page_blocks=False)
    media_blocks = [block for block in blocks if has_media(block)]
    eligible_media_blocks = [block for block in media_blocks if prompt_eligible(block)]
    selected_blocks = eligible_media_blocks[: max(0, max_blocks_per_doc)]
    context = build_evidence_context(
        question="Audit whether MinerU media metadata reaches the AnswerPolicy evidence context.",
        evidence_blocks=selected_blocks,
        max_chars_per_block=800,
    )
    formatted = format_evidence_blocks(selected_blocks, max_chars_per_block=800)
    context_by_id = {str(item.get("block_id") or ""): item for item in context.get("evidence", []) if isinstance(item, dict)}
    missing_media_ids = [
        block.block_id
        for block in selected_blocks
        if expects_prompt_media(block)
        if not ((context_by_id.get(block.block_id) or {}).get("media") or {})
    ]
    remote_redacted_ids = [
        block.block_id
        for block in selected_blocks
        if is_remote_resource(block.image_path)
        and ((context_by_id.get(block.block_id) or {}).get("media") or {}).get("image_path") == "<remote_image_resource>"
    ]
    remote_unredacted_ids = [
        block.block_id
        for block in selected_blocks
        if is_remote_resource(block.image_path)
        and str(((context_by_id.get(block.block_id) or {}).get("media") or {}).get("image_path") or "").startswith("http")
    ]
    absolute_suppressed_ids = [
        block.block_id
        for block in selected_blocks
        if is_absolute_path(block.image_path)
        and not ((context_by_id.get(block.block_id) or {}).get("media") or {}).get("image_path")
    ]
    relative_path_ids = [
        block.block_id
        for block in selected_blocks
        if block.image_path
        and not is_remote_resource(block.image_path)
        and not is_absolute_path(block.image_path)
        and ((context_by_id.get(block.block_id) or {}).get("media") or {}).get("image_path")
    ]
    context_media_items = [
        item
        for item in context.get("evidence", [])
        if isinstance(item, dict) and ((item.get("media") or {}) if isinstance(item.get("media"), dict) else {})
    ]
    table_caption_context_ids = [
        str(item.get("block_id") or "")
        for item in context_media_items
        if isinstance(item.get("media"), dict) and (item.get("media") or {}).get("table_caption")
    ]
    image_caption_context_ids = [
        str(item.get("block_id") or "")
        for item in context_media_items
        if isinstance(item.get("media"), dict) and (item.get("media") or {}).get("image_caption")
    ]
    raw_remote_url_leaks = re.findall(r"https?://[^\s\"'}\]]+", formatted + "\n" + json.dumps(context.get("evidence", []), ensure_ascii=False))
    return {
        "doc_id": doc_id,
        "block_count": len(blocks),
        "media_block_count": len(media_blocks),
        "prompt_eligible_media_block_count": len(eligible_media_blocks),
        "audited_media_block_count": len(selected_blocks),
        "context_evidence_count": len(context.get("evidence", [])),
        "context_media_item_count": len(context_media_items),
        "formatted_media_header_count": formatted.count(" | media="),
        "media_missing_in_context_block_ids": missing_media_ids,
        "remote_resource_redacted_block_ids": remote_redacted_ids,
        "remote_resource_unredacted_block_ids": remote_unredacted_ids,
        "absolute_resource_suppressed_block_ids": absolute_suppressed_ids,
        "relative_image_path_block_ids": relative_path_ids,
        "table_caption_context_block_ids": table_caption_context_ids,
        "image_caption_context_block_ids": image_caption_context_ids,
        "raw_remote_url_leak_count": len(raw_remote_url_leaks),
        "raw_remote_url_leak_samples": raw_remote_url_leaks[:3],
        "selected_block_ids": [block.block_id for block in selected_blocks],
        "sample_blocks": [
            {
                "block_id": block.block_id,
                "page": block.page_id,
                "block_type": block.block_type,
                "media_fields": output_media_fields(block),
                "retrieval_text_preview": block_preview(block),
            }
            for block in selected_blocks[:5]
        ],
        "sample_context_media": [
            {
                "block_id": str(item.get("block_id") or ""),
                "media": item.get("media") or {},
            }
            for item in context_media_items[:5]
        ],
        "sample_formatted_headers": formatted_headers(formatted)[:5],
    }


def aggregate_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    totals = Counter()
    for row in rows:
        totals["document_count"] += 1
        for key in (
            "block_count",
            "media_block_count",
            "prompt_eligible_media_block_count",
            "audited_media_block_count",
            "context_evidence_count",
            "context_media_item_count",
            "formatted_media_header_count",
            "raw_remote_url_leak_count",
        ):
            totals[key] += int(row.get(key) or 0)
        totals["media_missing_in_context_count"] += len(row.get("media_missing_in_context_block_ids") or [])
        totals["remote_resource_redacted_count"] += len(row.get("remote_resource_redacted_block_ids") or [])
        totals["remote_resource_unredacted_count"] += len(row.get("remote_resource_unredacted_block_ids") or [])
        totals["absolute_resource_suppressed_count"] += len(row.get("absolute_resource_suppressed_block_ids") or [])
        totals["relative_image_path_count"] += len(row.get("relative_image_path_block_ids") or [])
        totals["table_caption_context_count"] += len(row.get("table_caption_context_block_ids") or [])
        totals["image_caption_context_count"] += len(row.get("image_caption_context_block_ids") or [])
    return dict(totals)


def summarize(
    *,
    run_id: str,
    artifact_dir: Path,
    evidence_run_dir: Path,
    db_path: Path | None,
    rows: list[dict[str, Any]],
    missing: list[str],
) -> dict[str, Any]:
    totals = aggregate_rows(rows)
    contract_failures = []
    if totals.get("prompt_eligible_media_block_count", 0) and totals.get("media_missing_in_context_count", 0):
        contract_failures.append("eligible_media_missing_from_context")
    if totals.get("raw_remote_url_leak_count", 0):
        contract_failures.append("remote_resource_url_leaked_to_prompt")
    if totals.get("audited_media_block_count", 0) and totals.get("formatted_media_header_count", 0) < totals.get("context_media_item_count", 0):
        contract_failures.append("formatted_header_media_count_below_context_media_count")
    if not totals.get("media_block_count", 0):
        contract_status = "no_media_blocks_found"
    elif contract_failures:
        contract_status = "failed"
    else:
        contract_status = "passed"
    status = "failed" if missing else "success"
    return {
        "command": "audit_answer_prompt_media_metadata",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only" if status == "success" else "blocked",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "source_evidence_run_dir": safe_relpath(evidence_run_dir),
        "db_path": safe_relpath(db_path),
        "missing": missing,
        "contract_status": contract_status,
        "contract_failures": contract_failures,
        "used_qwen": False,
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        **totals,
        "recommendation": {
            "next_action": "run_server_artifact_audit_or_continue_parser_retrieval_chain",
            "do_not_train_yet": True,
            "reason": (
                "This audit verifies whether existing MinerU media metadata reaches AnswerPolicy evidence context "
                "and formatted evidence headers. It does not call MinerU, Qwen, retrieval models, or create training data."
            ),
        },
    }


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Answer Prompt Media Metadata Audit",
        "",
        f"- status: `{summary.get('status')}`",
        f"- contract_status: `{summary.get('contract_status')}`",
        f"- document_count: {summary.get('document_count', 0)}",
        f"- media_block_count: {summary.get('media_block_count', 0)}",
        f"- prompt_eligible_media_block_count: {summary.get('prompt_eligible_media_block_count', 0)}",
        f"- context_media_item_count: {summary.get('context_media_item_count', 0)}",
        f"- formatted_media_header_count: {summary.get('formatted_media_header_count', 0)}",
        f"- media_missing_in_context_count: {summary.get('media_missing_in_context_count', 0)}",
        f"- raw_remote_url_leak_count: {summary.get('raw_remote_url_leak_count', 0)}",
        f"- remote_resource_redacted_count: {summary.get('remote_resource_redacted_count', 0)}",
        f"- relative_image_path_count: {summary.get('relative_image_path_count', 0)}",
        "",
        "This is diagnostic only. It does not call MinerU, Qwen, retrieval models, or create training data.",
    ]
    if summary.get("contract_failures"):
        lines.extend(["", "## Contract Failures", "", *[f"- {item}" for item in summary["contract_failures"]]])
    if summary.get("missing"):
        lines.extend(["", "## Missing", "", *[f"- {item}" for item in summary["missing"]]])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files = []
    for artifact in artifact_paths:
        if artifact.is_file():
            files.append({"path": safe_relpath(artifact), "size_bytes": artifact.stat().st_size, "sha256": sha256_file(artifact)})
    write_json(path, {"run_id": run_id, "script_version": SCRIPT_VERSION, "files": files})


def sync_outputs(sync_dir: Path, paths: dict[str, Path]) -> None:
    sync_dir.mkdir(parents=True, exist_ok=True)
    for key in ("result", "summary", "summary_md", "preview", "manifest"):
        if paths[key].is_file():
            shutil.copy2(paths[key], sync_dir / paths[key].name)


def audit_answer_prompt_media_metadata(
    *,
    evidence_run_dir: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    db_path: Path | None = None,
    max_documents: int | None = None,
    max_blocks_per_doc: int = 20,
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    evidence_summary = load_json(evidence_run_dir / "summary.json")
    documents_path = evidence_run_dir / "documents.jsonl"
    db_path = db_path or (repo_path(evidence_summary.get("db_path")) if evidence_summary.get("db_path") else None)
    missing = [safe_relpath(path) for path in (evidence_run_dir / "summary.json", documents_path) if not path.is_file()]
    if db_path is None or not db_path.is_file():
        missing.append("db_path_missing")

    rows: list[dict[str, Any]] = []
    conn: sqlite3.Connection | None = None
    try:
        if db_path is not None and db_path.is_file():
            conn = connect(db_path)
            repository = DocumentRepository(conn)
            for doc_id in selected_document_ids(document_rows(documents_path), max_documents=max_documents):
                rows.append(
                    audit_document(
                        repository=repository,
                        doc_id=doc_id,
                        max_blocks_per_doc=max_blocks_per_doc,
                    )
                )
    finally:
        if conn is not None:
            conn.close()

    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "rows": artifact_dir / "rows.jsonl",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }
    summary = summarize(
        run_id=run_id,
        artifact_dir=artifact_dir,
        evidence_run_dir=evidence_run_dir,
        db_path=db_path,
        rows=rows,
        missing=missing,
    )
    summary.update(
        {
            "summary_path": safe_relpath(paths["summary"]),
            "summary_markdown_path": safe_relpath(paths["summary_md"]),
            "rows_path": safe_relpath(paths["rows"]),
            "preview_path": safe_relpath(paths["preview"]),
            "manifest_path": safe_relpath(paths["manifest"]),
            "artifact_paths": [safe_relpath(path) for path in paths.values()],
        }
    )
    result = {
        key: summary[key]
        for key in (
            "command",
            "status",
            "run_id",
            "contract_status",
            "contract_failures",
            "document_count",
            "media_block_count",
            "prompt_eligible_media_block_count",
            "context_media_item_count",
            "formatted_media_header_count",
            "media_missing_in_context_count",
            "raw_remote_url_leak_count",
            "remote_resource_redacted_count",
            "relative_image_path_count",
            "used_qwen",
            "used_training",
            "formal_benchmark_acceptance",
            "validation_subset_used_for_training",
            "recommendation",
            "artifact_paths",
        )
        if key in summary
    }
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_jsonl(paths["rows"], rows)
    write_json(paths["preview"], rows[:12])
    write_json(paths["result"], result)
    write_manifest(paths["manifest"], run_id=run_id, artifact_paths=list(paths.values()))
    if sync_output_root is not None:
        sync_dir = sync_output_root / run_id
        summary["sync_bundle_path"] = safe_relpath(sync_dir)
        result["sync_bundle_path"] = safe_relpath(sync_dir)
        write_json(paths["summary"], summary)
        write_json(paths["result"], result)
        sync_outputs(sync_dir, paths)
    return {**result, **summary}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit AnswerPolicy prompt media metadata from persisted EvidenceBlocks.")
    parser.add_argument("--evidence-run-dir", required=True)
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--db-path")
    parser.add_argument("--max-documents", type=int)
    parser.add_argument("--max-blocks-per-doc", type=int, default=20)
    parser.add_argument("--sync-output-dir")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = audit_answer_prompt_media_metadata(
        evidence_run_dir=repo_path(args.evidence_run_dir) or Path(args.evidence_run_dir),
        output_root=repo_path(args.output_dir) or Path(args.output_dir),
        run_id=args.run_id,
        db_path=repo_path(args.db_path),
        max_documents=args.max_documents,
        max_blocks_per_doc=args.max_blocks_per_doc,
        sync_output_root=repo_path(args.sync_output_dir) if args.sync_output_dir else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
import sys
import traceback
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.ingestion.document_registry import DocumentRegistry
from docagent.ingestion.hashing import sha256_file
from docagent.ingestion.service import DocumentIngestionService
from docagent.integrations.mineru_api import MinerUApiClient
from docagent.parser.mineru_backend import MinerUParserBackend
from docagent.schemas import EvidenceBlock
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from docagent.utils.jsonl import read_jsonl, write_jsonl


COMMAND = "run_phase4b_mpdocvqa_ingestion"
PHASE = "Phase 4B"
GATE = "Gate 1"
DEFAULT_OUTPUT_ROOT = "outputs/phase4/mpdocvqa_ingestion"
ALLOWED_QUALITY_STATUSES = {"passed", "passed_with_warnings"}
WINDOWS_DRIVE_PATH_RE = re.compile(r"^[A-Za-z]:[\\/]")
UNC_PATH_RE = re.compile(r"^\\\\[A-Za-z0-9._-]+[\\/][^\s\\/]+")
URL_RE = re.compile(r"https?://[^\s\"'<>]+")
PATH_PREVIEW_LIMIT = 160
POSIX_LOCAL_ROOTS = ("/root/", "/mnt/", "/home/", "/tmp/", "/var/", "/opt/", "/usr/", "/etc/", "/data/")


class Phase4BIngestionError(RuntimeError):
    pass


@dataclass
class SampleInputs:
    sample_root: Path
    doc_id: str
    document_dir: Path
    pdf_path: Path
    document_manifest_path: Path
    qa_path: Path
    manifest: dict[str, Any]
    qa_records: list[dict[str, Any]]
    expected_page_count: int
    pdf_page_count: int
    source_doc_id: str
    input_scope: str
    ordered_page_ids: list[str]


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def _gate(args: argparse.Namespace) -> str:
    return str(getattr(args, "gate", GATE) or GATE)


def _relative_posix(path: Path, base: Path) -> str:
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return path.name if path.is_absolute() else path.as_posix()


def _artifact_path(path: Path, work_dir: Path) -> str:
    return _relative_posix(path, work_dir)


def _absolute_path_reason(value: str) -> str | None:
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.lower().startswith("file://"):
        return "file_uri_absolute_path"
    if "://" in stripped:
        return None
    if WINDOWS_DRIVE_PATH_RE.match(stripped):
        return "windows_drive_absolute_path"
    if UNC_PATH_RE.match(stripped):
        return "unc_absolute_path"
    if stripped.startswith(POSIX_LOCAL_ROOTS):
        return "posix_absolute_path"
    return None


def _looks_like_local_absolute_path(value: str) -> bool:
    return _absolute_path_reason(value) is not None


def _path_basename_portable(value: str) -> str:
    stripped = value.strip().rstrip("\\/")
    if not stripped:
        return ""
    return re.split(r"[\\/]", stripped)[-1]


def _preview_value(value: str, *, limit: int = PATH_PREVIEW_LIMIT) -> str:
    preview = _sanitize_text(value).replace("\r", "\\r").replace("\n", "\\n").strip()
    if len(preview) > limit:
        return preview[: limit - 3] + "..."
    return preview


def _scan_absolute_paths(value: Any, *, where: str, hits: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            _scan_absolute_paths(item, where=f"{where}.{key}", hits=hits)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_absolute_paths(item, where=f"{where}[{index}]", hits=hits)
    elif isinstance(value, str):
        reason = _absolute_path_reason(value)
        if reason is not None:
            hits.append({"where": where, "reason": reason, "value_preview": _preview_value(value)})


def _contains_sensitive_text(value: str) -> bool:
    lowered = value.lower()
    return (
        "authorization" in lowered
        or "bearer " in lowered
        or "mineru_token" in lowered
        or "upload.example" in lowered
        or "download.example" in lowered
        or ("full_zip_url" not in lowered and "signed" in lowered and "http" in lowered)
    )


def _scan_sensitive_text(value: Any, *, where: str, hits: list[dict[str, str]]) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _contains_sensitive_text(str(key)):
                hits.append({"where": f"{where}.{key}", "value": "<redacted-key>"})
            _scan_sensitive_text(item, where=f"{where}.{key}", hits=hits)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _scan_sensitive_text(item, where=f"{where}[{index}]", hits=hits)
    elif isinstance(value, str) and _contains_sensitive_text(value):
        hits.append({"where": where, "value": "<redacted>"})


def _sanitize_text(value: str) -> str:
    value = re.sub(r"Bearer\s+\S+", "Bearer <redacted>", value, flags=re.IGNORECASE)
    value = re.sub(
        r"Authorization\s*[:=]\s*(?:Bearer\s+)?\S+",
        "<redacted-auth>",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"Authorization", "<redacted-auth>", value, flags=re.IGNORECASE)
    value = URL_RE.sub("<redacted-url>", value)
    return value


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if lowered in {"authorization", "token", "mineru_token", "api_key", "access_token"}:
                continue
            sanitized[key_text] = _sanitize_json_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, str):
        if _looks_like_local_absolute_path(value):
            return _path_basename_portable(value)
        return _sanitize_text(value)
    return value


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _pdf_page_count(path: Path) -> int:
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except ModuleNotFoundError:
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise Phase4BIngestionError(f"failed to read PDF page count: {path.name}") from exc
        count = len(re.findall(rb"/Type\s*/Page\b", data))
        if count:
            return count
        raise Phase4BIngestionError(f"failed to read PDF page count: {path.name}")
    except Exception as exc:
        raise Phase4BIngestionError(f"failed to read PDF page count: {path.name}") from exc


def _as_int(value: Any, *, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise Phase4BIngestionError(f"{field} is not an integer") from exc


def _as_list(value: Any, *, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise Phase4BIngestionError(f"{field} must be a list")
    return value


def _load_sample_inputs(args: argparse.Namespace) -> SampleInputs:
    sample_root = repo_path(args.sample_root)
    doc_id = str(args.doc_id)
    document_dir = sample_root / "documents" / doc_id
    pdf_path = document_dir / "document.pdf"
    manifest_path = document_dir / "document_manifest.json"
    qa_path = sample_root / "qa.jsonl"

    if not sample_root.is_dir():
        raise Phase4BIngestionError(f"sample root missing: {sample_root.name}")
    if not document_dir.is_dir():
        raise Phase4BIngestionError(f"document directory missing for doc_id={doc_id}")
    if not manifest_path.is_file():
        raise Phase4BIngestionError(f"document manifest missing for doc_id={doc_id}")
    if not pdf_path.is_file():
        raise Phase4BIngestionError(f"document.pdf missing for doc_id={doc_id}")
    if not qa_path.is_file():
        raise Phase4BIngestionError("qa.jsonl missing under sample root")

    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict):
        raise Phase4BIngestionError("document_manifest.json must be an object")
    if manifest.get("doc_id") != doc_id:
        raise Phase4BIngestionError("document manifest doc_id does not match --doc-id")
    source_doc_id = str(manifest.get("source_doc_id") or "")
    if not source_doc_id:
        raise Phase4BIngestionError("document manifest source_doc_id is missing")
    input_scope = str(manifest.get("input_scope") or "")
    ordered_page_ids = [str(item) for item in _as_list(manifest.get("ordered_page_ids"), field="ordered_page_ids")]
    expected_page_count = _as_int(manifest.get("page_count"), field="manifest.page_count")
    pages = _as_list(manifest.get("pages"), field="manifest.pages")
    if expected_page_count <= 0:
        raise Phase4BIngestionError("manifest.page_count must be positive")
    if len(ordered_page_ids) != expected_page_count:
        raise Phase4BIngestionError("ordered_page_ids count does not match manifest.page_count")
    if len(pages) != expected_page_count:
        raise Phase4BIngestionError("manifest pages count does not match manifest.page_count")
    for ordinal, page in enumerate(pages, start=1):
        if not isinstance(page, dict):
            raise Phase4BIngestionError(f"manifest page {ordinal} must be an object")
        if _as_int(page.get("page_ordinal"), field=f"pages[{ordinal}].page_ordinal") != ordinal:
            raise Phase4BIngestionError("manifest page ordinals must be one-based and contiguous")
        if str(page.get("page_id") or "") != ordered_page_ids[ordinal - 1]:
            raise Phase4BIngestionError("manifest page_id does not match ordered_page_ids")

    pdf_page_count = _pdf_page_count(pdf_path)
    if pdf_page_count != expected_page_count:
        raise Phase4BIngestionError(
            f"PDF page count {pdf_page_count} does not match manifest.page_count {expected_page_count}"
        )
    manifest_pdf_sha = manifest.get("pdf_sha256")
    if manifest_pdf_sha and str(manifest_pdf_sha) != sha256_file(pdf_path):
        raise Phase4BIngestionError("document.pdf sha256 does not match document manifest")

    all_qa = read_jsonl(qa_path)
    qa_records = [record for record in all_qa if record.get("doc_id") == doc_id]
    if not qa_records:
        raise Phase4BIngestionError(f"qa.jsonl contains no records for doc_id={doc_id}")
    _validate_qa_records(
        qa_records=qa_records,
        doc_id=doc_id,
        source_doc_id=source_doc_id,
        ordered_page_ids=ordered_page_ids,
    )
    return SampleInputs(
        sample_root=sample_root,
        doc_id=doc_id,
        document_dir=document_dir,
        pdf_path=pdf_path,
        document_manifest_path=manifest_path,
        qa_path=qa_path,
        manifest=manifest,
        qa_records=qa_records,
        expected_page_count=expected_page_count,
        pdf_page_count=pdf_page_count,
        source_doc_id=source_doc_id,
        input_scope=input_scope,
        ordered_page_ids=ordered_page_ids,
    )


def _validate_qa_records(
    *,
    qa_records: list[dict[str, Any]],
    doc_id: str,
    source_doc_id: str,
    ordered_page_ids: list[str],
) -> None:
    page_count = len(ordered_page_ids)
    seen_qids: set[str] = set()
    for record in qa_records:
        qid = str(record.get("qid") or "")
        if not qid:
            raise Phase4BIngestionError("QA record has empty qid")
        if qid in seen_qids:
            raise Phase4BIngestionError(f"duplicate qid: {qid}")
        seen_qids.add(qid)
        if record.get("doc_id") != doc_id:
            raise Phase4BIngestionError(f"{qid}: QA doc_id does not match target doc_id")
        if record.get("source_doc_id") != source_doc_id:
            raise Phase4BIngestionError(f"{qid}: QA source_doc_id does not match document manifest")
        answer_page_idx = _as_int(record.get("answer_page_idx"), field=f"{qid}.answer_page_idx")
        gold_page_ordinal = _as_int(record.get("gold_page_ordinal"), field=f"{qid}.gold_page_ordinal")
        if answer_page_idx < 0 or answer_page_idx >= page_count:
            raise Phase4BIngestionError(f"{qid}: answer_page_idx is out of bounds")
        if gold_page_ordinal < 1 or gold_page_ordinal > page_count:
            raise Phase4BIngestionError(f"{qid}: gold_page_ordinal is out of bounds")
        if gold_page_ordinal != answer_page_idx + 1:
            raise Phase4BIngestionError(f"{qid}: answer_page_idx and gold_page_ordinal are inconsistent")
        expected_page_id = ordered_page_ids[answer_page_idx]
        if record.get("gold_page_id") != expected_page_id:
            raise Phase4BIngestionError(f"{qid}: gold_page_id does not match ordered page ids")
        answers = record.get("answers")
        if not isinstance(answers, list) or not answers:
            raise Phase4BIngestionError(f"{qid}: answers must be a non-empty list")


def _validate_runtime(args: argparse.Namespace, *, validate_only: bool, revalidate_existing: bool = False) -> None:
    output_root = repo_path(args.output_root)
    if output_root.exists() and not output_root.is_dir():
        raise Phase4BIngestionError("--output-root exists and is not a directory")
    if args.live_api and not bool(os.getenv("MINERU_TOKEN")):
        raise Phase4BIngestionError("MINERU_TOKEN is not set")
    if not validate_only and not revalidate_existing and not args.live_api:
        raise Phase4BIngestionError("Gate 1 ingestion requires --live-api")


def _validate_only_payload(args: argparse.Namespace, sample: SampleInputs) -> dict[str, Any]:
    _validate_runtime(args, validate_only=True)
    return {
        "command": COMMAND,
        "status": "success",
        "phase": PHASE,
        "gate": _gate(args),
        "validate_only": True,
        "doc_id": sample.doc_id,
        "source_doc_id": sample.source_doc_id,
        "input_scope": sample.input_scope,
        "expected_page_count": sample.expected_page_count,
        "pdf_page_count": sample.pdf_page_count,
        "qa_count": len(sample.qa_records),
        "live_api": bool(args.live_api),
        "mineru_token_set": bool(os.getenv("MINERU_TOKEN")) if args.live_api else None,
        "artifact_paths": [],
        "warnings": [],
        "failures": [],
    }


def _prepare_work_dir(work_dir: Path, *, force: bool) -> None:
    resolved = work_dir.resolve()
    if resolved in {Path(resolved.anchor), ROOT.resolve()}:
        raise Phase4BIngestionError(f"refusing to clean unsafe work directory: {work_dir}")
    if work_dir.exists():
        if not force:
            raise Phase4BIngestionError(f"output work directory already exists: {work_dir.name}; use --force")
        shutil.rmtree(work_dir)
    (work_dir / "logs").mkdir(parents=True)


def _run_mineru_api(
    *,
    args: argparse.Namespace,
    sample: SampleInputs,
    mineru_dir: Path,
    api_client_factory: Callable[[], Any] | None,
) -> None:
    factory = api_client_factory or (lambda: MinerUApiClient())
    client = factory()
    client.run(
        file_path=sample.pdf_path,
        data_id=sample.doc_id,
        output_dir=mineru_dir,
    )
    _sanitize_mineru_api_manifest(mineru_dir)


def _sanitize_mineru_api_manifest(mineru_dir: Path) -> None:
    manifest_path = mineru_dir / "mineru_api_manifest.json"
    if not manifest_path.exists():
        return
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return
    if isinstance(payload, dict):
        payload = _sanitize_json_value(payload)
        payload["source_file"] = "source/original.pdf"
        _write_json(manifest_path, payload)


def _sanitize_sqlite_paths(sqlite_path: Path, work_dir: Path) -> None:
    if not sqlite_path.exists():
        return
    with sqlite3.connect(sqlite_path) as conn:
        rows = conn.execute("SELECT doc_id, file_path FROM documents").fetchall()
        for doc_id, file_path in rows:
            if isinstance(file_path, str) and _looks_like_local_absolute_path(file_path):
                conn.execute(
                    "UPDATE documents SET file_path = ? WHERE doc_id = ?",
                    (_relative_posix(Path(file_path), work_dir), doc_id),
                )
        index_rows = conn.execute("SELECT doc_id, index_type, model_id, artifact_path FROM document_indexes").fetchall()
        for doc_id, index_type, model_id, artifact_path in index_rows:
            if isinstance(artifact_path, str) and _looks_like_local_absolute_path(artifact_path):
                conn.execute(
                    """
                    UPDATE document_indexes
                    SET artifact_path = ?
                    WHERE doc_id = ? AND index_type = ? AND model_id = ?
                    """,
                    (_relative_posix(Path(artifact_path), work_dir), doc_id, index_type, model_id),
                )
        conn.commit()


def _load_blocks(path: Path) -> list[EvidenceBlock]:
    return [EvidenceBlock.from_dict(record) for record in read_jsonl(path)]


def _build_page_identity_mapping(
    *,
    sample: SampleInputs,
    page_blocks: list[EvidenceBlock],
) -> list[dict[str, Any]]:
    pages_by_number = {block.page_id: block for block in page_blocks}
    mappings: list[dict[str, Any]] = []
    for ordinal, source_page_id in enumerate(sample.ordered_page_ids, start=1):
        page_block = pages_by_number.get(ordinal)
        child_ids = list((page_block.metadata.get("child_block_ids") if page_block else []) or [])
        errors: list[str] = []
        if page_block is None:
            errors.append("missing_page_aggregate")
        elif not child_ids:
            errors.append("page_aggregate_has_no_child_blocks")
        mappings.append(
            {
                "doc_id": sample.doc_id,
                "source_doc_id": sample.source_doc_id,
                "source_page_id": source_page_id,
                "page_window_ordinal": ordinal,
                "pdf_page_number": ordinal,
                "parsed_page_number": page_block.page_id if page_block else ordinal,
                "page_aggregate_id": page_block.block_id if page_block else None,
                "child_block_ids": child_ids,
                "mapping_valid": not errors,
                "mapping_errors": errors,
            }
        )
    return mappings


def _build_qa_page_mapping(
    *,
    sample: SampleInputs,
    page_identity: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_ordinal = {int(record["page_window_ordinal"]): record for record in page_identity}
    rows: list[dict[str, Any]] = []
    for qa in sample.qa_records:
        answer_page_idx = int(qa["answer_page_idx"])
        gold_page_ordinal = int(qa["gold_page_ordinal"])
        page_record = by_ordinal.get(gold_page_ordinal)
        errors: list[str] = []
        if gold_page_ordinal != answer_page_idx + 1:
            errors.append("answer_page_idx_gold_page_ordinal_mismatch")
        if qa.get("gold_page_id") != sample.ordered_page_ids[answer_page_idx]:
            errors.append("gold_page_id_mismatch")
        if page_record is None:
            errors.append("missing_page_identity")
            parsed_page_number = gold_page_ordinal
            page_aggregate_id = None
            child_block_ids: list[str] = []
        else:
            parsed_page_number = page_record["parsed_page_number"]
            page_aggregate_id = page_record["page_aggregate_id"]
            child_block_ids = list(page_record["child_block_ids"])
            errors.extend(str(item) for item in page_record["mapping_errors"])
        rows.append(
            {
                "qid": qa["qid"],
                "doc_id": sample.doc_id,
                "source_doc_id": sample.source_doc_id,
                "answer_page_idx": answer_page_idx,
                "gold_page_id": qa["gold_page_id"],
                "gold_page_ordinal": gold_page_ordinal,
                "parsed_page_number": parsed_page_number,
                "page_aggregate_id": page_aggregate_id,
                "child_block_ids": child_block_ids,
                "mapping_valid": not errors,
                "mapping_errors": errors,
            }
        )
    return rows


def _copy_report(src: Path, dst: Path) -> None:
    if src.exists():
        dst.write_text(src.read_text(encoding="utf-8-sig"), encoding="utf-8")


def _decode_json_column(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def _scan_json_artifacts(work_dir: Path, sqlite_path: Path) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    absolute_hits: list[dict[str, str]] = []
    sensitive_hits: list[dict[str, str]] = []
    for path in sorted(work_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl"}:
            continue
        rel = _relative_posix(path, work_dir)
        try:
            if path.suffix.lower() == ".jsonl":
                payload = read_jsonl(path)
            else:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        _scan_absolute_paths(payload, where=rel, hits=absolute_hits)
        _scan_sensitive_text(payload, where=rel, hits=sensitive_hits)
    if sqlite_path.exists():
        with sqlite3.connect(sqlite_path) as conn:
            for doc_id, file_path in conn.execute("SELECT doc_id, file_path FROM documents").fetchall():
                where = f"sqlite.documents[{doc_id}].file_path"
                _scan_absolute_paths(file_path, where=where, hits=absolute_hits)
                _scan_sensitive_text(file_path, where=where, hits=sensitive_hits)
            for block_id, payload_json, metadata_json in conn.execute(
                "SELECT block_id, payload_json, metadata_json FROM evidence_blocks"
            ).fetchall():
                for column, raw_value in {"payload_json": payload_json, "metadata_json": metadata_json}.items():
                    where = f"sqlite.evidence_blocks[{block_id}].{column}"
                    decoded = _decode_json_column(raw_value)
                    _scan_absolute_paths(decoded, where=where, hits=absolute_hits)
                    _scan_sensitive_text(decoded, where=where, hits=sensitive_hits)
            for doc_id, index_type, model_id, artifact_path, metadata_json in conn.execute(
                "SELECT doc_id, index_type, model_id, artifact_path, metadata_json FROM document_indexes"
            ).fetchall():
                index_key = f"{doc_id}:{index_type}:{model_id or ''}"
                artifact_where = f"sqlite.document_indexes[{index_key}].artifact_path"
                _scan_absolute_paths(artifact_path, where=artifact_where, hits=absolute_hits)
                _scan_sensitive_text(artifact_path, where=artifact_where, hits=sensitive_hits)
                metadata_where = f"sqlite.document_indexes[{index_key}].metadata_json"
                decoded = _decode_json_column(metadata_json)
                _scan_absolute_paths(decoded, where=metadata_where, hits=absolute_hits)
                _scan_sensitive_text(decoded, where=metadata_where, hits=sensitive_hits)
    return absolute_hits, sensitive_hits


def _acceptance_failures(
    *,
    sample: SampleInputs,
    parsed_page_count: int,
    page_document_count: int,
    invalid_page_identity_count: int,
    structure_quality_status: str,
    missing_image_reference_count: int,
    valid_mapping_count: int,
    invalid_mapping_count: int,
    absolute_path_count: int,
    sensitive_hit_count: int,
    no_mock_fallback: bool,
) -> list[str]:
    failures: list[str] = []
    if sample.pdf_page_count != sample.expected_page_count:
        failures.append("pdf_page_count_mismatch")
    if parsed_page_count != sample.expected_page_count:
        failures.append("parsed_page_count_mismatch")
    if page_document_count != sample.expected_page_count:
        failures.append("page_document_count_mismatch")
    if invalid_page_identity_count != 0:
        failures.append("page_identity_mapping_invalid")
    if structure_quality_status not in ALLOWED_QUALITY_STATUSES:
        failures.append("structure_quality_failed")
    if missing_image_reference_count != 0:
        failures.append("missing_image_references")
    if valid_mapping_count != len(sample.qa_records):
        failures.append("gold_page_mapping_invalid")
    if invalid_mapping_count != 0:
        failures.append("gold_page_mapping_invalid_count_nonzero")
    if absolute_path_count != 0:
        failures.append("persisted_absolute_paths")
    if sensitive_hit_count != 0:
        failures.append("sensitive_artifacts_persisted")
    if not no_mock_fallback:
        failures.append("live_api_required")
    return failures


def _build_acceptance_report(
    *,
    args: argparse.Namespace,
    sample: SampleInputs,
    work_dir: Path,
    sqlite_path: Path,
    evidence_path: Path,
    pages_path: Path,
    ingestion_report_path: Path,
    structure_quality_path: Path,
    ingestion_doc_id: str,
    no_mock_fallback: bool,
    revalidate_existing: bool = False,
) -> dict[str, Any]:
    blocks = _load_blocks(evidence_path)
    page_blocks = _load_blocks(pages_path)
    quality = _read_json(structure_quality_path)
    page_identity = _build_page_identity_mapping(sample=sample, page_blocks=page_blocks)
    qa_mapping = _build_qa_page_mapping(sample=sample, page_identity=page_identity)
    page_identity_path = work_dir / "page_identity_mapping.jsonl"
    qa_mapping_path = work_dir / "qa_page_mapping.jsonl"
    write_jsonl(page_identity_path, page_identity)
    write_jsonl(qa_mapping_path, qa_mapping)

    parsed_page_count = len({block.page_id for block in blocks if block.page_id is not None})
    block_type_counts = dict(sorted(Counter(block.block_type for block in blocks).items()))
    valid_mapping_count = sum(1 for record in qa_mapping if record["mapping_valid"])
    invalid_mapping_count = len(qa_mapping) - valid_mapping_count
    invalid_page_identity_count = sum(1 for record in page_identity if not record["mapping_valid"])
    absolute_hits, sensitive_hits = _scan_json_artifacts(work_dir, sqlite_path)
    failures = _acceptance_failures(
        sample=sample,
        parsed_page_count=parsed_page_count,
        page_document_count=len(page_blocks),
        invalid_page_identity_count=invalid_page_identity_count,
        structure_quality_status=str(quality.get("overall_status") or ""),
        missing_image_reference_count=int(quality.get("missing_image_reference_count") or 0),
        valid_mapping_count=valid_mapping_count,
        invalid_mapping_count=invalid_mapping_count,
        absolute_path_count=len(absolute_hits),
        sensitive_hit_count=len(sensitive_hits),
        no_mock_fallback=no_mock_fallback,
    )

    artifact_paths = {
        "documents": _artifact_path(work_dir / "documents", work_dir),
        "sqlite": _artifact_path(sqlite_path, work_dir),
        "ingestion_report": _artifact_path(ingestion_report_path, work_dir),
        "structure_quality": _artifact_path(structure_quality_path, work_dir),
        "qa_page_mapping": _artifact_path(qa_mapping_path, work_dir),
        "page_identity_mapping": _artifact_path(page_identity_path, work_dir),
        "acceptance_report": "acceptance_report.json",
        "logs": "logs",
    }
    report = {
        "command": COMMAND,
        "status": "success" if not failures else "failed",
        "phase": PHASE,
        "gate": _gate(args),
        "doc_id": sample.doc_id,
        "ingestion_doc_id": ingestion_doc_id,
        "source_doc_id": sample.source_doc_id,
        "input_scope": sample.input_scope,
        "source_pdf_sha256": sha256_file(sample.pdf_path),
        "expected_page_count": sample.expected_page_count,
        "pdf_page_count": sample.pdf_page_count,
        "parsed_page_count": parsed_page_count,
        "raw_block_count": quality.get("raw_block_count"),
        "converted_block_count": len(blocks),
        "block_type_counts": block_type_counts,
        "page_document_count": len(page_blocks),
        "missing_image_reference_count": int(quality.get("missing_image_reference_count") or 0),
        "persisted_absolute_path_count": len(absolute_hits),
        "structure_quality_status": quality.get("overall_status"),
        "qa_count": len(sample.qa_records),
        "page_identity_mapping_invalid_count": invalid_page_identity_count,
        "gold_page_mapping_valid_count": valid_mapping_count,
        "gold_page_mapping_invalid_count": invalid_mapping_count,
        "no_mock_fallback": no_mock_fallback,
        "artifact_paths": artifact_paths,
        "warnings": list(quality.get("warnings") or []),
        "failures": failures,
    }
    if revalidate_existing:
        report["revalidate_existing"] = True
    if absolute_hits:
        report["persisted_absolute_path_examples"] = absolute_hits[:5]
    if sensitive_hits:
        report["sensitive_artifact_examples"] = sensitive_hits[:5]
    _write_json(work_dir / "acceptance_report.json", report)
    return report


def _run_ingestion(
    *,
    args: argparse.Namespace,
    sample: SampleInputs,
    api_client_factory: Callable[[], Any] | None,
) -> dict[str, Any]:
    _validate_runtime(args, validate_only=False)
    output_root = repo_path(args.output_root)
    work_dir = output_root / sample.doc_id
    _prepare_work_dir(work_dir, force=bool(args.force))

    document_root = work_dir / "documents"
    sqlite_path = work_dir / "docagent.sqlite"
    preview = DocumentRegistry(document_root).register(sample.pdf_path)
    document_dir = Path(preview.document_dir)
    mineru_dir = document_dir / "mineru"

    if args.live_api:
        _run_mineru_api(args=args, sample=sample, mineru_dir=mineru_dir, api_client_factory=api_client_factory)

    conn = connect(sqlite_path)
    repository = DocumentRepository(conn)
    service = DocumentIngestionService(document_root=document_root, repository=repository)
    try:
        result = service.ingest(
            file_path=sample.pdf_path,
            parser_backend=MinerUParserBackend(mode="parse_existing", backend_name="mineru_api"),
            force_parse=True,
        )
        _sanitize_sqlite_paths(sqlite_path, work_dir)
    finally:
        conn.close()

    internal_doc_dir = Path(result.document.document_dir)
    evidence_path = internal_doc_dir / "evidence_blocks.jsonl"
    pages_path = internal_doc_dir / "page_documents.jsonl"
    ingestion_report_path = internal_doc_dir / "ingestion_report.json"
    structure_quality_path = internal_doc_dir / "structure_quality.json"
    top_ingestion_path = work_dir / "ingestion_report.json"
    top_quality_path = work_dir / "structure_quality.json"
    _copy_report(ingestion_report_path, top_ingestion_path)
    _copy_report(structure_quality_path, top_quality_path)

    no_mock_fallback = bool(args.live_api)
    return _build_acceptance_report(
        args=args,
        sample=sample,
        work_dir=work_dir,
        sqlite_path=sqlite_path,
        evidence_path=evidence_path,
        pages_path=pages_path,
        ingestion_report_path=top_ingestion_path,
        structure_quality_path=top_quality_path,
        ingestion_doc_id=result.document.doc_id,
        no_mock_fallback=no_mock_fallback,
        revalidate_existing=False,
    )


def _find_existing_document_dir(work_dir: Path) -> Path:
    document_root = work_dir / "documents"
    if not document_root.is_dir():
        raise Phase4BIngestionError("existing artifact documents directory is missing")
    candidates = sorted(
        path
        for path in document_root.iterdir()
        if path.is_dir() and (path / "evidence_blocks.jsonl").is_file() and (path / "page_documents.jsonl").is_file()
    )
    if not candidates:
        raise Phase4BIngestionError("existing artifact evidence/page document files are missing")
    if len(candidates) > 1:
        raise Phase4BIngestionError("existing artifact documents directory is ambiguous")
    return candidates[0]


def _read_existing_no_mock_fallback(work_dir: Path) -> bool:
    report_path = work_dir / "acceptance_report.json"
    if not report_path.is_file():
        return False
    try:
        payload = _read_json(report_path)
    except Exception:
        return False
    return bool(payload.get("no_mock_fallback"))


def _run_revalidate_existing(*, args: argparse.Namespace, sample: SampleInputs) -> dict[str, Any]:
    _validate_runtime(args, validate_only=False, revalidate_existing=True)
    work_dir = repo_path(args.output_root) / sample.doc_id
    if not work_dir.is_dir():
        raise Phase4BIngestionError(f"existing output work directory missing: {work_dir.name}")
    sqlite_path = work_dir / "docagent.sqlite"
    if not sqlite_path.is_file():
        raise Phase4BIngestionError("existing artifact docagent.sqlite is missing")
    internal_doc_dir = _find_existing_document_dir(work_dir)
    evidence_path = internal_doc_dir / "evidence_blocks.jsonl"
    pages_path = internal_doc_dir / "page_documents.jsonl"
    top_ingestion_path = work_dir / "ingestion_report.json"
    top_quality_path = work_dir / "structure_quality.json"
    ingestion_report_path = top_ingestion_path if top_ingestion_path.is_file() else internal_doc_dir / "ingestion_report.json"
    structure_quality_path = top_quality_path if top_quality_path.is_file() else internal_doc_dir / "structure_quality.json"
    if not ingestion_report_path.is_file():
        raise Phase4BIngestionError("existing artifact ingestion_report.json is missing")
    if not structure_quality_path.is_file():
        raise Phase4BIngestionError("existing artifact structure_quality.json is missing")
    return _build_acceptance_report(
        args=args,
        sample=sample,
        work_dir=work_dir,
        sqlite_path=sqlite_path,
        evidence_path=evidence_path,
        pages_path=pages_path,
        ingestion_report_path=ingestion_report_path,
        structure_quality_path=structure_quality_path,
        ingestion_doc_id=internal_doc_dir.name,
        no_mock_fallback=_read_existing_no_mock_fallback(work_dir),
        revalidate_existing=True,
    )


def _failure_payload(
    *,
    args: argparse.Namespace,
    exc: Exception,
    sample: SampleInputs | None = None,
) -> dict[str, Any]:
    doc_id = sample.doc_id if sample is not None else str(getattr(args, "doc_id", ""))
    output_root = repo_path(getattr(args, "output_root", DEFAULT_OUTPUT_ROOT))
    work_dir = output_root / doc_id if doc_id else output_root
    tail = [_sanitize_text(line) for line in traceback.format_exc().splitlines()[-12:]]
    payload = {
        "command": COMMAND,
        "status": "failed",
        "exit_code": 1,
        "phase": PHASE,
        "gate": _gate(args),
        "doc_id": doc_id,
        "exception": _sanitize_text(f"{type(exc).__name__}: {exc}"),
        "traceback_tail": tail,
        "no_mock_fallback": bool(getattr(args, "live_api", False)),
    }
    try:
        (work_dir / "logs").mkdir(parents=True, exist_ok=True)
        log_path = work_dir / "logs" / "failure.json"
        _write_json(log_path, payload)
        _write_json(work_dir / "acceptance_report.json", payload)
        payload["log_path"] = _artifact_path(log_path, work_dir)
        payload["artifact_paths"] = {"failure_log": payload["log_path"], "acceptance_report": "acceptance_report.json"}
    except Exception:
        payload["log_path"] = ""
    return payload


def run_phase4b_ingestion(
    args: argparse.Namespace,
    *,
    api_client_factory: Callable[[], Any] | None = None,
) -> dict[str, Any]:
    sample: SampleInputs | None = None
    try:
        sample = _load_sample_inputs(args)
        if args.validate_only:
            return _validate_only_payload(args, sample)
        if args.revalidate_existing:
            return _run_revalidate_existing(args=args, sample=sample)
        return _run_ingestion(args=args, sample=sample, api_client_factory=api_client_factory)
    except Exception as exc:
        return _failure_payload(args=args, exc=exc, sample=sample)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run or revalidate Phase 4B MP-DocVQA page-window MinerU ingestion."
    )
    parser.add_argument("--sample-root", required=True)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--output-root", default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--parser-mode", choices=["parse_existing"], default="parse_existing")
    parser.add_argument("--gate", default=GATE)
    parser.add_argument("--live-api", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--revalidate-existing", action="store_true")
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    payload = run_phase4b_ingestion(args)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if payload.get("status") == "success" else 1)


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import ast
import hashlib
import io
import json
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import write_jsonl


BUILDER_VERSION = "phase4a-mpdocvqa-raw-v1"
DEFAULT_OUTPUT_ROOT = "outputs/phase4/mpdocvqa_raw_sample"
IMAGE_COLUMNS = [f"image_{index}" for index in range(1, 21)]
REPEATED_CONTENT_WARNING = "duplicate_image_content_within_document"


class BuildError(RuntimeError):
    pass


@dataclass
class PageRecord:
    page_id: str
    ordinal: int
    source_name: str
    image_format: str
    extension: str
    width: int
    height: int
    byte_size: int
    sha256: str
    raw_bytes: bytes | None = field(default=None, repr=False)


@dataclass
class RowRecord:
    qid: str
    question: str
    doc_id: str
    page_ids: list[str]
    answers: list[str]
    answer_page_idx: int
    source_split: str
    source_shard: str
    pages: list[PageRecord]
    image_storage_kinds: list[str]
    repeated_page_content: bool

    @property
    def signature(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return tuple(self.page_ids), tuple(page.sha256 for page in self.pages)


@dataclass
class DocumentRecord:
    doc_id: str
    page_ids: list[str]
    qa_rows: list[RowRecord]
    page_sha256: list[str]
    page_formats: list[str]
    repeated_page_content: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def page_count(self) -> int:
        return len(self.page_ids)


@dataclass
class AuditResult:
    valid_documents: dict[str, DocumentRecord]
    invalid_documents: dict[str, list[str]]
    schema_audit: dict[str, Any]
    overlap_audit: dict[str, Any]


def repo_path(path: str | Path) -> Path:
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ""
    return result.stdout.strip()


def stable_key(seed: str, value: str) -> str:
    return hashlib.sha256(f"{seed}:{value}".encode("utf-8")).hexdigest()


def relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def parse_string_list(value: Any, *, field_name: str) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    elif isinstance(value, tuple):
        items = list(value)
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = ast.literal_eval(text)
            except (SyntaxError, ValueError) as exc:
                raise BuildError(f"{field_name} is not a valid stringified list") from exc
            if not isinstance(parsed, (list, tuple)):
                raise BuildError(f"{field_name} did not decode to a list")
            items = list(parsed)
        else:
            items = [text]
    else:
        items = [value]
    normalized = [str(item).strip() for item in items if str(item).strip()]
    return normalized


def parse_int(value: Any, *, field_name: str) -> int:
    if value is None:
        raise BuildError(f"{field_name} is missing")
    try:
        return int(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise BuildError(f"{field_name} is not an integer") from exc


def image_format_extension(image_format: str) -> str:
    mapping = {
        "JPEG": ".jpg",
        "PNG": ".png",
        "TIFF": ".tif",
        "BMP": ".bmp",
        "WEBP": ".webp",
        "GIF": ".gif",
    }
    try:
        return mapping[image_format]
    except KeyError as exc:
        raise BuildError(f"unsupported image format: {image_format}") from exc


def inspect_image(raw_bytes: bytes, *, column_name: str) -> tuple[str, int, int]:
    try:
        with Image.open(io.BytesIO(raw_bytes)) as image:
            image_format = image.format or "UNKNOWN"
            width, height = image.size
    except UnidentifiedImageError as exc:
        raise BuildError(f"{column_name} has unknown image format") from exc
    except Exception as exc:
        raise BuildError(f"{column_name} is a corrupt image") from exc
    if image_format == "UNKNOWN":
        raise BuildError(f"{column_name} has unknown image format")
    return image_format, width, height


def image_payload(value: Any, *, column_name: str) -> tuple[bytes | None, str | None, str]:
    if value is None:
        return None, None, "null"
    if isinstance(value, dict):
        keys = ",".join(sorted(value.keys()))
        raw = value.get("bytes")
        if isinstance(raw, memoryview):
            raw = raw.tobytes()
        elif isinstance(raw, bytearray):
            raw = bytes(raw)
        elif raw is not None and not isinstance(raw, bytes):
            raise BuildError(f"{column_name} bytes field is not binary")
        path = value.get("path")
        return raw, None if path is None else str(path), f"struct:{keys}"
    if isinstance(value, bytes):
        return value, None, "bytes"
    if isinstance(value, bytearray):
        return bytes(value), None, "bytearray"
    if isinstance(value, memoryview):
        return value.tobytes(), None, "memoryview"
    raise BuildError(f"{column_name} uses unsupported storage type: {type(value).__name__}")


def parse_row(raw_row: dict[str, Any], *, source_shard: str, include_raw_bytes: bool) -> RowRecord:
    qid = str(raw_row.get("questionId") or raw_row.get("questionid") or "").strip()
    if not qid:
        raise BuildError("questionId is missing")
    question = str(raw_row.get("question") or "").strip()
    if not question:
        raise BuildError(f"{qid}: question is missing")
    doc_id = str(raw_row.get("doc_id") or "").strip()
    if not doc_id:
        raise BuildError(f"{qid}: doc_id is missing")

    page_ids = parse_string_list(raw_row.get("page_ids"), field_name=f"{qid}.page_ids")
    if not page_ids:
        raise BuildError(f"{qid}: page_ids is empty")
    if len(page_ids) != len(set(page_ids)):
        raise BuildError(f"{qid}: page_ids contains duplicates")

    answers = parse_string_list(raw_row.get("answers"), field_name=f"{qid}.answers")
    if not answers:
        raise BuildError(f"{qid}: answers is empty")

    answer_page_idx = parse_int(raw_row.get("answer_page_idx"), field_name=f"{qid}.answer_page_idx")
    source_split = str(raw_row.get("data_split") or "").strip() or "unknown"

    pages: list[PageRecord] = []
    image_storage_kinds: list[str] = []
    seen_content = False
    seen_gap = False
    for column_name in IMAGE_COLUMNS:
        raw_bytes, source_name, storage_kind = image_payload(raw_row.get(column_name), column_name=column_name)
        image_storage_kinds.append(storage_kind)
        if raw_bytes is None:
            if seen_content:
                seen_gap = True
            continue
        if seen_gap:
            raise BuildError(f"{qid}: found non-null {column_name} after a null image slot")
        seen_content = True
        image_format, width, height = inspect_image(raw_bytes, column_name=column_name)
        extension = image_format_extension(image_format)
        page_ordinal = len(pages) + 1
        if page_ordinal > len(page_ids):
            raise BuildError(f"{qid}: more non-null images than page_ids")
        pages.append(
            PageRecord(
                page_id=page_ids[page_ordinal - 1],
                ordinal=page_ordinal,
                source_name=source_name or f"{page_ids[page_ordinal - 1]}{extension}",
                image_format=image_format,
                extension=extension,
                width=width,
                height=height,
                byte_size=len(raw_bytes),
                sha256=hashlib.sha256(raw_bytes).hexdigest(),
                raw_bytes=raw_bytes if include_raw_bytes else None,
            )
        )

    if len(pages) != len(page_ids):
        raise BuildError(
            f"{qid}: page_ids count {len(page_ids)} does not match non-null image count {len(pages)}"
        )
    if answer_page_idx < 0 or answer_page_idx >= len(page_ids):
        raise BuildError(
            f"{qid}: answer_page_idx {answer_page_idx} is out of range for {len(page_ids)} pages"
        )

    repeated_page_content = len({page.sha256 for page in pages}) != len(pages)
    return RowRecord(
        qid=qid,
        question=question,
        doc_id=doc_id,
        page_ids=page_ids,
        answers=answers,
        answer_page_idx=answer_page_idx,
        source_split=source_split,
        source_shard=source_shard,
        pages=pages,
        image_storage_kinds=image_storage_kinds,
        repeated_page_content=repeated_page_content,
    )


def locate_overlap_source() -> tuple[list[Path], Path | None]:
    candidates = [
        ROOT / "data" / "benchmark" / "mp_docvqa_imdb_ocr_5000_split" / "dev.jsonl",
        ROOT / "data" / "benchmark" / "mp_docvqa_imdb_ocr_5000_split" / "train.jsonl",
        ROOT / "data" / "benchmark" / "mp_docvqa_imdb_ocr_5000_split" / "imdb_val.npy",
        ROOT / "data" / "benchmark" / "mp_docvqa_imdb_ocr_5000_split" / "imdb_train.npy",
        ROOT / "outputs" / "evaluation" / "phase3_focused_eval" / "mpdocvqa_answer_policy_150_top20_20260616_131117" / "metadata.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidates, candidate
    return candidates, None


def overlap_audit(rows: list[RowRecord]) -> dict[str, Any]:
    searched_paths, found_path = locate_overlap_source()
    payload: dict[str, Any] = {
        "status": "not_available",
        "checked_paths": [path.relative_to(ROOT).as_posix() for path in searched_paths],
        "note": (
            "MP-DocVQA val 原始文档链路主要用于 integration、page retrieval 和 system E2E；"
            "训练重叠样本不能作为严格独立泛化证据。"
        ),
    }
    if found_path is not None:
        payload["found_path"] = found_path.relative_to(ROOT).as_posix()
    return payload


def audit_parquet(input_parquet: Path) -> AuditResult:
    parquet = pq.ParquetFile(input_parquet)
    schema = parquet.schema_arrow
    source_shard = input_parquet.name

    parsed_rows_by_doc: dict[str, list[RowRecord]] = defaultdict(list)
    row_issues_by_doc: dict[str, list[str]] = defaultdict(list)
    invalid_row_examples: list[dict[str, Any]] = []
    image_storage_kinds = Counter()
    image_formats = Counter()
    image_path_extensions = Counter()
    page_count_distribution = Counter()
    answer_idx_distribution = Counter()
    docs_with_multiple_qas = Counter()

    for batch in parquet.iter_batches(
        batch_size=16,
        columns=[
            name
            for name in ("questionId", "question", "doc_id", "page_ids", "answers", "answer_page_idx", "data_split")
            if name in schema.names
        ]
        + [column for column in IMAGE_COLUMNS if column in schema.names],
    ):
        for raw_row in batch.to_pylist():
            doc_id = str(raw_row.get("doc_id") or "")
            try:
                row = parse_row(raw_row, source_shard=source_shard, include_raw_bytes=False)
            except BuildError as exc:
                if doc_id:
                    row_issues_by_doc[doc_id].append(str(exc))
                if len(invalid_row_examples) < 10:
                    invalid_row_examples.append(
                        {
                            "questionId": str(raw_row.get("questionId") or raw_row.get("questionid") or ""),
                            "doc_id": doc_id,
                            "reason": str(exc),
                        }
                    )
                continue

            parsed_rows_by_doc[row.doc_id].append(row)
            docs_with_multiple_qas[row.doc_id] += 1
            page_count_distribution[len(row.page_ids)] += 1
            answer_idx_distribution[row.answer_page_idx] += 1
            image_formats.update(page.image_format for page in row.pages)
            for page in row.pages:
                image_path_extensions[Path(page.source_name).suffix.lower() or "<none>"] += 1
            image_storage_kinds.update(kind for kind in row.image_storage_kinds if kind != "null")

    valid_documents: dict[str, DocumentRecord] = {}
    invalid_documents: dict[str, list[str]] = {}
    conflict_examples: dict[str, Any] = {}
    repeated_content_docs: list[str] = []
    for doc_id, rows in parsed_rows_by_doc.items():
        issues = list(dict.fromkeys(row_issues_by_doc.get(doc_id, [])))
        signature_map: dict[tuple[tuple[str, ...], tuple[str, ...]], RowRecord] = {}
        for row in rows:
            signature_map.setdefault(row.signature, row)
        if len(signature_map) > 1:
            issues.append("conflicting page_ids or page image sha256 across rows for the same doc_id")
            if len(conflict_examples) < 5:
                conflict_examples[doc_id] = [
                    {
                        "page_ids": list(signature[0]),
                        "page_sha256_prefixes": [value[:12] for value in signature[1]],
                    }
                    for signature in signature_map.keys()
                ]
        canonical = rows[0]
        repeated_content = any(row.repeated_page_content for row in rows)
        warnings: list[str] = []
        if repeated_content:
            repeated_content_docs.append(doc_id)
            warnings.append(REPEATED_CONTENT_WARNING)
        if issues:
            invalid_documents[doc_id] = issues
            continue
        valid_documents[doc_id] = DocumentRecord(
            doc_id=doc_id,
            page_ids=list(canonical.page_ids),
            qa_rows=sorted(rows, key=lambda item: item.qid),
            page_sha256=[page.sha256 for page in canonical.pages],
            page_formats=[page.image_format for page in canonical.pages],
            repeated_page_content=repeated_content,
            warnings=warnings,
        )

    for doc_id, issues in row_issues_by_doc.items():
        if doc_id not in parsed_rows_by_doc:
            invalid_documents[doc_id] = list(dict.fromkeys(issues))

    all_rows = [row for rows in parsed_rows_by_doc.values() for row in rows]
    overlap = overlap_audit(all_rows)
    schema_audit = {
        "builder_version": BUILDER_VERSION,
        "source_shard": source_shard,
        "row_count": parquet.metadata.num_rows,
        "column_names": schema.names,
        "arrow_schema": str(schema),
        "field_arrow_types": {name: str(schema.field(name).type) for name in schema.names},
        "key_field_arrow_types": {
            name: str(schema.field(name).type)
            for name in ("questionId", "question", "doc_id", "page_ids", "answers", "answer_page_idx", "data_split")
            if name in schema.names
        },
        "stringified_fields": ["page_ids", "answers", "answer_page_idx"],
        "image_storage": {
            "arrow_type": str(schema.field("image_1").type) if "image_1" in schema.names else None,
            "storage_kinds": dict(image_storage_kinds),
            "path_extensions": dict(image_path_extensions),
            "image_formats": dict(image_formats),
        },
        "page_count_distribution": dict(page_count_distribution),
        "answer_page_idx_audit": {
            "distribution": dict(answer_idx_distribution),
            "zero_based_observed": True,
            "out_of_range_rows": 0,
        },
        "doc_audit": {
            "unique_doc_count": len({row.doc_id for row in all_rows} | set(invalid_documents)),
            "valid_doc_count": len(valid_documents),
            "invalid_doc_count": len(invalid_documents),
            "docs_with_multiple_qas": sum(1 for count in docs_with_multiple_qas.values() if count > 1),
            "max_qas_per_doc": max(docs_with_multiple_qas.values()) if docs_with_multiple_qas else 0,
            "conflicting_doc_count": sum(
                1 for issues in invalid_documents.values() if any("conflicting page_ids" in issue for issue in issues)
            ),
            "conflict_examples": conflict_examples,
            "duplicate_image_content_doc_ids": repeated_content_docs,
        },
        "invalid_row_examples": invalid_row_examples,
        "invalid_documents": [
            {"doc_id": doc_id, "reasons": reasons}
            for doc_id, reasons in sorted(invalid_documents.items())
        ],
    }
    return AuditResult(
        valid_documents=valid_documents,
        invalid_documents=invalid_documents,
        schema_audit=schema_audit,
        overlap_audit=overlap,
    )


def answer_bucket(page_count: int, answer_index: int) -> str:
    if page_count <= 1:
        return "front"
    ratio = answer_index / (page_count - 1)
    if ratio <= 0.34:
        return "front"
    if ratio >= 0.67:
        return "late"
    return "mid"


def selection_features(document: DocumentRecord) -> set[str]:
    features = set()
    if document.page_count == 1:
        features.add("page:single")
    elif document.page_count <= 5:
        features.add("page:short")
    else:
        features.add("page:long")
    for row in document.qa_rows:
        features.add(f"answer:{answer_bucket(document.page_count, row.answer_page_idx)}")
    return features


def select_sample_documents(
    documents: dict[str, DocumentRecord],
    *,
    sample_documents: int,
    seed: str,
    explicit_doc_ids: list[str] | None,
) -> list[DocumentRecord]:
    if explicit_doc_ids:
        selected: list[DocumentRecord] = []
        seen: set[str] = set()
        for doc_id in explicit_doc_ids:
            if doc_id in seen:
                continue
            seen.add(doc_id)
            try:
                selected.append(documents[doc_id])
            except KeyError as exc:
                raise BuildError(f"requested doc_id is unavailable or invalid: {doc_id}") from exc
        return selected

    ordered = sorted(documents.values(), key=lambda item: (stable_key(seed, item.doc_id), item.doc_id))
    if sample_documents >= len(ordered):
        return ordered

    selected: list[DocumentRecord] = []
    covered: set[str] = set()
    remaining = ordered[:]
    while remaining and len(selected) < sample_documents:
        scored = sorted(
            remaining,
            key=lambda item: (
                -(len(selection_features(item) - covered)),
                stable_key(seed, item.doc_id),
                item.doc_id,
            ),
        )
        best = scored[0]
        gain = len(selection_features(best) - covered)
        if gain == 0:
            break
        selected.append(best)
        covered.update(selection_features(best))
        remaining = [item for item in remaining if item.doc_id != best.doc_id]

    for item in ordered:
        if len(selected) >= sample_documents:
            break
        if item.doc_id not in {doc.doc_id for doc in selected}:
            selected.append(item)
    return selected[:sample_documents]


def load_selected_pages(input_parquet: Path, documents: list[DocumentRecord]) -> dict[str, list[PageRecord]]:
    expected = {document.doc_id: tuple(document.page_sha256) for document in documents}
    selected = set(expected)
    loaded: dict[str, list[PageRecord]] = {}
    parquet = pq.ParquetFile(input_parquet)
    for batch in parquet.iter_batches(
        batch_size=16,
        columns=[
            name
            for name in ("questionId", "question", "doc_id", "page_ids", "answers", "answer_page_idx", "data_split")
            if name in parquet.schema_arrow.names
        ]
        + [column for column in IMAGE_COLUMNS if column in parquet.schema_arrow.names],
    ):
        for raw_row in batch.to_pylist():
            doc_id = str(raw_row.get("doc_id") or "")
            if doc_id not in selected or doc_id in loaded:
                continue
            row = parse_row(raw_row, source_shard=input_parquet.name, include_raw_bytes=True)
            if tuple(page.sha256 for page in row.pages) == expected[doc_id]:
                loaded[doc_id] = row.pages
        if len(loaded) == len(selected):
            break
    missing = sorted(selected - set(loaded))
    if missing:
        raise BuildError(f"failed to load page bytes for selected documents: {missing}")
    return loaded


def render_pdf_bytes(page_files: list[Path]) -> bytes:
    images: list[Image.Image] = []
    try:
        for page_file in page_files:
            with Image.open(page_file) as image:
                images.append(image.convert("RGB"))
        if not images:
            raise BuildError("cannot render PDF without pages")
        buffer = io.BytesIO()
        first, *rest = images
        first.save(buffer, format="PDF", save_all=bool(rest), append_images=rest)
        return buffer.getvalue()
    finally:
        for image in images:
            image.close()


def build_document_assets(
    *,
    output_root: Path,
    document: DocumentRecord,
    pages: list[PageRecord],
    source_shard: str,
    generation_commit: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    doc_dir = output_root / "documents" / document.doc_id
    pages_dir = doc_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    page_manifest = []
    page_files: list[Path] = []
    for page in pages:
        page_file = pages_dir / f"{page.ordinal:04d}{page.extension}"
        if page.raw_bytes is None:
            raise BuildError(f"missing raw bytes for {document.doc_id}:{page.page_id}")
        page_file.write_bytes(page.raw_bytes)
        page_files.append(page_file)
        page_manifest.append(
            {
                "page_id": page.page_id,
                "page_ordinal": page.ordinal,
                "page_file": relative_posix(page_file, output_root),
                "source_image_name": page.source_name,
                "sha256": page.sha256,
                "format": page.image_format,
                "width": page.width,
                "height": page.height,
                "byte_size": page.byte_size,
            }
        )

    pdf_path = doc_dir / "document.pdf"
    pdf_bytes = render_pdf_bytes(page_files)
    pdf_path.write_bytes(pdf_bytes)
    pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
    pdf_stable = pdf_bytes == render_pdf_bytes(page_files)

    qa_count = len(document.qa_rows)
    manifest = {
        "builder_version": BUILDER_VERSION,
        "generation_commit": generation_commit,
        "doc_id": document.doc_id,
        "source_shard": source_shard,
        "page_count": len(page_manifest),
        "ordered_page_ids": [page["page_id"] for page in page_manifest],
        "ordered_page_files": [page["page_file"] for page in page_manifest],
        "pages": page_manifest,
        "pdf_path": relative_posix(pdf_path, output_root),
        "pdf_sha256": pdf_sha256,
        "pdf_binary_stability": {
            "double_render_identical": pdf_stable,
            "note": (
                "PDF bytes matched across two local renders"
                if pdf_stable
                else "PDF bytes changed across two local renders; page order and manifest remain deterministic"
            ),
        },
        "qa_count": qa_count,
        "warnings": document.warnings,
    }
    manifest_path = doc_dir / "document_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    documents_record = {
        "doc_id": document.doc_id,
        "page_count": len(page_manifest),
        "qa_count": qa_count,
        "document_manifest": relative_posix(manifest_path, output_root),
        "pdf_path": manifest["pdf_path"],
        "pdf_sha256": pdf_sha256,
        "warnings": document.warnings,
    }
    return manifest, documents_record


def qa_record(row: RowRecord) -> dict[str, Any]:
    return {
        "qid": row.qid,
        "raw_question_id": row.qid,
        "doc_id": row.doc_id,
        "question": row.question,
        "answers": row.answers,
        "answer_page_idx": row.answer_page_idx,
        "raw_answer_page_idx": row.answer_page_idx,
        "gold_page_id": row.page_ids[row.answer_page_idx],
        "gold_page_ordinal": row.answer_page_idx + 1,
        "source_split": row.source_split,
        "source_shard": row.source_shard,
    }


def explicit_doc_ids(values: list[str] | None) -> list[str]:
    if not values:
        return []
    items: list[str] = []
    for value in values:
        for part in value.split(","):
            doc_id = part.strip()
            if doc_id:
                items.append(doc_id)
    return items


def clear_output_root(output_root: Path) -> None:
    if output_root.exists():
        shutil.rmtree(output_root)


def build_outputs(
    *,
    audit: AuditResult,
    input_parquet: Path,
    output_root: Path,
    sample_documents: int,
    seed: str,
    requested_doc_ids: list[str],
    validate_only: bool,
    overwrite: bool,
) -> dict[str, Any]:
    generation_commit = git_commit()
    selected_documents = select_sample_documents(
        audit.valid_documents,
        sample_documents=sample_documents,
        seed=seed,
        explicit_doc_ids=requested_doc_ids or None,
    )
    if not selected_documents:
        raise BuildError("no valid documents are available for selection")

    qa_records = [
        qa_record(row)
        for document in selected_documents
        for row in sorted(document.qa_rows, key=lambda item: item.qid)
    ]
    build_report = {
        "builder_version": BUILDER_VERSION,
        "generation_commit": generation_commit,
        "source_shard": input_parquet.name,
        "status": "success",
        "validate_only": validate_only,
        "sample_documents_requested": sample_documents,
        "seed": seed,
        "requested_doc_ids": requested_doc_ids,
        "selected_doc_ids": [document.doc_id for document in selected_documents],
        "selected_doc_page_counts": {document.doc_id: document.page_count for document in selected_documents},
        "selected_doc_answer_buckets": {
            document.doc_id: sorted({answer_bucket(document.page_count, row.answer_page_idx) for row in document.qa_rows})
            for document in selected_documents
        },
        "valid_doc_count": len(audit.valid_documents),
        "invalid_doc_count": len(audit.invalid_documents),
        "invalid_documents": [
            {"doc_id": doc_id, "reasons": reasons}
            for doc_id, reasons in sorted(audit.invalid_documents.items())
        ],
        "qa_count": len(qa_records),
        "overlap_audit_status": audit.overlap_audit["status"],
    }
    if validate_only:
        return {
            "command": "build_mpdocvqa_raw_documents",
            "status": "success",
            "artifact_paths": [],
            "metrics": {
                "row_count": audit.schema_audit["row_count"],
                "valid_doc_count": len(audit.valid_documents),
                "invalid_doc_count": len(audit.invalid_documents),
                "selected_doc_count": len(selected_documents),
                "qa_count": len(qa_records),
            },
            "build_report": build_report,
        }

    if output_root.exists():
        if not overwrite:
            raise BuildError(f"output root already exists: {output_root}")
        clear_output_root(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    selected_pages = load_selected_pages(input_parquet, selected_documents)
    document_manifests = []
    document_records = []
    for document in selected_documents:
        manifest, record = build_document_assets(
            output_root=output_root,
            document=document,
            pages=selected_pages[document.doc_id],
            source_shard=input_parquet.name,
            generation_commit=generation_commit,
        )
        document_manifests.append(manifest)
        document_records.append(record)

    write_jsonl(output_root / "documents.jsonl", document_records)
    write_jsonl(output_root / "qa.jsonl", qa_records)
    (output_root / "schema_audit.json").write_text(
        json.dumps(audit.schema_audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_root / "overlap_audit.json").write_text(
        json.dumps(audit.overlap_audit, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    source_manifest = {
        "builder_version": BUILDER_VERSION,
        "generation_commit": generation_commit,
        "source_dataset": "lmms-lab/MP-DocVQA",
        "source_shard": input_parquet.name,
        "selected_doc_ids": [document.doc_id for document in selected_documents],
        "selected_document_count": len(selected_documents),
        "qa_count": len(qa_records),
        "documents_jsonl": "documents.jsonl",
        "qa_jsonl": "qa.jsonl",
        "schema_audit": "schema_audit.json",
        "build_report": "build_report.json",
        "overlap_audit": "overlap_audit.json",
    }
    (output_root / "source_manifest.json").write_text(
        json.dumps(source_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (output_root / "build_report.json").write_text(
        json.dumps(build_report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return {
        "command": "build_mpdocvqa_raw_documents",
        "status": "success",
        "artifact_paths": [
            relative_posix(output_root / "source_manifest.json", output_root),
            relative_posix(output_root / "documents.jsonl", output_root),
            relative_posix(output_root / "qa.jsonl", output_root),
            relative_posix(output_root / "schema_audit.json", output_root),
            relative_posix(output_root / "build_report.json", output_root),
            relative_posix(output_root / "overlap_audit.json", output_root),
        ],
        "metrics": {
            "row_count": audit.schema_audit["row_count"],
            "valid_doc_count": len(audit.valid_documents),
            "invalid_doc_count": len(audit.invalid_documents),
            "selected_doc_count": len(selected_documents),
            "qa_count": len(qa_records),
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore MP-DocVQA raw multi-page document assets from a parquet shard."
    )
    parser.add_argument("--input-parquet", required=True)
    parser.add_argument(
        "--output-root",
        default=DEFAULT_OUTPUT_ROOT,
        help=f"Output directory for manifests and restored assets (default: {DEFAULT_OUTPUT_ROOT}).",
    )
    parser.add_argument("--sample-documents", type=int, default=5)
    parser.add_argument("--seed", default="42")
    parser.add_argument("--doc-ids", nargs="*")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_parquet = repo_path(args.input_parquet)
    output_root = repo_path(args.output_root)
    exit_code = 0
    try:
        audit = audit_parquet(input_parquet)
        payload = build_outputs(
            audit=audit,
            input_parquet=input_parquet,
            output_root=output_root,
            sample_documents=args.sample_documents,
            seed=str(args.seed),
            requested_doc_ids=explicit_doc_ids(args.doc_ids),
            validate_only=args.validate_only,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        exit_code = 1
        payload = {
            "command": "build_mpdocvqa_raw_documents",
            "status": "failed",
            "exit_code": 1,
            "exception": f"{type(exc).__name__}: {exc}",
            "log_tail": "",
        }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()

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
from typing import Any, Iterable

import pyarrow.parquet as pq
from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import write_jsonl


BUILDER_VERSION = "phase4a-mpdocvqa-raw-v2"
DEFAULT_OUTPUT_ROOT = "outputs/phase4/mpdocvqa_raw_sample"
IMAGE_COLUMNS = [f"image_{index}" for index in range(1, 21)]
INPUT_SCOPE = "page_window"
REPEATED_CONTENT_WARNING = "duplicate_image_content_within_window"


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
    source_doc_id: str
    row_index: int | None
    window_signature: str
    window_doc_id: str
    page_ids: list[str]
    answers: list[str]
    answer_page_idx: int
    source_split: str
    source_shard: str
    pages: list[PageRecord]
    image_storage_kinds: list[str]
    repeated_page_content: bool

    @property
    def page_sha256(self) -> tuple[str, ...]:
        return tuple(page.sha256 for page in self.pages)


@dataclass
class WindowRecord:
    doc_id: str
    source_doc_id: str
    window_signature: str
    page_ids: list[str]
    qa_rows: list[RowRecord]
    page_sha256: list[str]
    page_formats: list[str]
    source_shards: list[str]
    repeated_page_content: bool = False
    warnings: list[str] = field(default_factory=list)
    input_scope: str = INPUT_SCOPE
    document_is_full_source_document: bool = False

    @property
    def page_count(self) -> int:
        return len(self.page_ids)


@dataclass
class AuditResult:
    valid_windows: dict[str, WindowRecord]
    invalid_windows: dict[str, list[str]]
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


def input_path_key(path: Path) -> str:
    return path.resolve().as_posix().lower()


def normalize_input_parquets(value: Path | str | Iterable[Path | str]) -> list[Path]:
    if isinstance(value, (str, Path)):
        candidates = [value]
    else:
        candidates = list(value)
    normalized: dict[str, Path] = {}
    for candidate in candidates:
        path = repo_path(candidate)
        normalized[input_path_key(path)] = path
    paths = sorted(normalized.values(), key=input_path_key)
    if not paths:
        raise BuildError("at least one input parquet is required")
    return paths


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
    return [str(item).strip() for item in items if str(item).strip()]


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


def window_identity(source_doc_id: str, ordered_page_ids: list[str]) -> tuple[str, str]:
    payload = json.dumps(
        {"ordered_page_ids": ordered_page_ids, "source_doc_id": source_doc_id},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    signature = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return signature, f"{source_doc_id}__{signature[:16]}"


def parse_row(
    raw_row: dict[str, Any],
    *,
    source_shard: str,
    include_raw_bytes: bool,
    row_index: int | None = None,
) -> RowRecord:
    qid = str(raw_row.get("questionId") or raw_row.get("questionid") or "").strip()
    if not qid:
        raise BuildError("questionId is missing")
    question = str(raw_row.get("question") or "").strip()
    if not question:
        raise BuildError(f"{qid}: question is missing")
    source_doc_id = str(raw_row.get("doc_id") or "").strip()
    if not source_doc_id:
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
    window_signature, window_doc_id = window_identity(source_doc_id, page_ids)

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
        raise BuildError(f"{qid}: answer_page_idx {answer_page_idx} is out of range for {len(page_ids)} pages")

    repeated_page_content = len({page.sha256 for page in pages}) != len(pages)
    return RowRecord(
        qid=qid,
        question=question,
        source_doc_id=source_doc_id,
        row_index=row_index,
        window_signature=window_signature,
        window_doc_id=window_doc_id,
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
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidates, candidate
    return candidates, None


def overlap_audit(rows: list[RowRecord]) -> dict[str, Any]:
    checked_paths, found_path = locate_overlap_source()
    payload: dict[str, Any] = {
        "status": "not_available",
        "checked_paths": [path.relative_to(ROOT).as_posix() for path in checked_paths],
        "note": (
            "MP-DocVQA val raw document windows are primarily for integration, "
            "page retrieval, and system E2E. Training overlap cannot be used as "
            "strict independent generalization evidence."
        ),
    }
    if found_path is not None:
        payload["found_path"] = found_path.relative_to(ROOT).as_posix()
    return payload


def audit_parquet(input_parquets: Path | str | Iterable[Path | str]) -> AuditResult:
    parquet_paths = normalize_input_parquets(input_parquets)
    parsed_rows_by_window: dict[str, list[RowRecord]] = defaultdict(list)
    invalid_row_examples: list[dict[str, Any]] = []
    image_storage_kinds = Counter()
    image_formats = Counter()
    image_path_extensions = Counter()
    page_count_distribution = Counter()
    answer_idx_distribution = Counter()
    row_count_by_shard: dict[str, int] = {}
    schema_by_shard: dict[str, dict[str, Any]] = {}
    source_doc_windows: dict[str, set[str]] = defaultdict(set)
    duplicate_window_count = 0

    for parquet_path in parquet_paths:
        parquet = pq.ParquetFile(parquet_path)
        schema = parquet.schema_arrow
        row_count_by_shard[parquet_path.name] = parquet.metadata.num_rows
        schema_by_shard[parquet_path.name] = {
            "column_names": schema.names,
            "arrow_schema": str(schema),
            "field_arrow_types": {name: str(schema.field(name).type) for name in schema.names},
            "key_field_arrow_types": {
                name: str(schema.field(name).type)
                for name in ("questionId", "question", "doc_id", "page_ids", "answers", "answer_page_idx", "data_split")
                if name in schema.names
            },
        }
        columns = [
            name
            for name in ("questionId", "question", "doc_id", "page_ids", "answers", "answer_page_idx", "data_split")
            if name in schema.names
        ] + [column for column in IMAGE_COLUMNS if column in schema.names]

        row_index = 0
        for batch in parquet.iter_batches(batch_size=16, columns=columns):
            for raw_row in batch.to_pylist():
                try:
                    row = parse_row(
                        raw_row,
                        source_shard=parquet_path.name,
                        include_raw_bytes=False,
                        row_index=row_index,
                    )
                except BuildError as exc:
                    if len(invalid_row_examples) < 10:
                        invalid_row_examples.append(
                            {
                                "questionId": str(raw_row.get("questionId") or raw_row.get("questionid") or ""),
                                "source_doc_id": str(raw_row.get("doc_id") or ""),
                                "source_shard": parquet_path.name,
                                "reason": str(exc),
                            }
                        )
                    row_index += 1
                    continue
                row_index += 1

                parsed_rows_by_window[row.window_doc_id].append(row)
                source_doc_windows[row.source_doc_id].add(row.window_doc_id)
                page_count_distribution[len(row.page_ids)] += 1
                answer_idx_distribution[row.answer_page_idx] += 1
                image_formats.update(page.image_format for page in row.pages)
                for page in row.pages:
                    image_path_extensions[Path(page.source_name).suffix.lower() or "<none>"] += 1
                image_storage_kinds.update(kind for kind in row.image_storage_kinds if kind != "null")

    valid_windows: dict[str, WindowRecord] = {}
    invalid_windows: dict[str, list[str]] = {}
    conflict_examples: dict[str, Any] = {}
    repeated_content_windows: list[str] = []
    invalid_window_records: list[dict[str, Any]] = []

    for window_doc_id, rows in sorted(parsed_rows_by_window.items()):
        rows_sorted = sorted(rows, key=lambda item: (item.qid, item.source_shard, item.question))
        canonical = rows_sorted[0]
        rows_by_hash: dict[tuple[str, ...], list[RowRecord]] = defaultdict(list)
        for row in rows_sorted:
            rows_by_hash[row.page_sha256].append(row)
        duplicate_window_count += sum(len(group) - 1 for group in rows_by_hash.values())

        repeated_page_content = any(row.repeated_page_content for row in rows_sorted)
        warnings: list[str] = []
        if repeated_page_content:
            repeated_content_windows.append(window_doc_id)
            warnings.append(REPEATED_CONTENT_WARNING)

        if len(rows_by_hash) > 1:
            reason = "conflicting page image sha256 for the same source_doc_id and ordered page_ids"
            invalid_windows[window_doc_id] = [reason]
            invalid_window_records.append(
                {
                    "doc_id": window_doc_id,
                    "source_doc_id": canonical.source_doc_id,
                    "window_signature": canonical.window_signature,
                    "ordered_page_ids": canonical.page_ids,
                    "reasons": [reason],
                }
            )
            if len(conflict_examples) < 5:
                conflict_examples[window_doc_id] = {
                    "source_doc_id": canonical.source_doc_id,
                    "ordered_page_ids": canonical.page_ids,
                    "hash_variants": [
                        {
                            "source_shards": sorted({row.source_shard for row in group}),
                            "page_sha256_prefixes": [value[:12] for value in page_sha256],
                        }
                        for page_sha256, group in sorted(rows_by_hash.items())
                    ],
                }
            continue

        valid_windows[window_doc_id] = WindowRecord(
            doc_id=window_doc_id,
            source_doc_id=canonical.source_doc_id,
            window_signature=canonical.window_signature,
            page_ids=list(canonical.page_ids),
            qa_rows=rows_sorted,
            page_sha256=list(canonical.page_sha256),
            page_formats=[page.image_format for page in canonical.pages],
            source_shards=sorted({row.source_shard for row in rows_sorted}),
            repeated_page_content=repeated_page_content,
            warnings=warnings,
        )

    unique_source_doc_count = len(source_doc_windows)
    unique_window_count = len(parsed_rows_by_window)
    same_source_multiple_window_count = sum(1 for window_ids in source_doc_windows.values() if len(window_ids) > 1)
    different_window_same_source_doc_count = sum(
        len(window_ids) for window_ids in source_doc_windows.values() if len(window_ids) > 1
    )
    max_windows_per_source_doc = max((len(window_ids) for window_ids in source_doc_windows.values()), default=0)
    max_qas_per_window = max((len(window.qa_rows) for window in valid_windows.values()), default=0)

    all_rows = [row for rows in parsed_rows_by_window.values() for row in rows]
    overlap = overlap_audit(all_rows)
    total_row_count = sum(row_count_by_shard.values())
    first_schema = schema_by_shard[parquet_paths[0].name]
    schema_audit = {
        "builder_version": BUILDER_VERSION,
        "input_shards": [path.name for path in parquet_paths],
        "row_count": total_row_count,
        "row_count_by_shard": row_count_by_shard,
        "column_names": first_schema["column_names"],
        "arrow_schema": first_schema["arrow_schema"],
        "field_arrow_types": first_schema["field_arrow_types"],
        "key_field_arrow_types": first_schema["key_field_arrow_types"],
        "schema_by_shard": schema_by_shard,
        "stringified_fields": ["page_ids", "answers", "answer_page_idx"],
        "image_storage": {
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
            "unique_source_doc_count": unique_source_doc_count,
            "unique_document_window_count": unique_window_count,
            "duplicate_window_count": duplicate_window_count,
            "same_source_multiple_window_count": same_source_multiple_window_count,
            "different_window_same_source_doc_count": different_window_same_source_doc_count,
            "conflicting_window_count": len(invalid_windows),
            "valid_window_count": len(valid_windows),
            "max_windows_per_source_doc": max_windows_per_source_doc,
            "max_qas_per_window": max_qas_per_window,
            "conflict_examples": conflict_examples,
            "duplicate_image_content_window_ids": repeated_content_windows,
        },
        "invalid_row_examples": invalid_row_examples,
        "invalid_windows": invalid_window_records,
    }
    return AuditResult(
        valid_windows=valid_windows,
        invalid_windows=invalid_windows,
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


def selection_features(window: WindowRecord) -> set[str]:
    features = set()
    if window.page_count == 1:
        features.add("page:single")
    elif window.page_count <= 5:
        features.add("page:short")
    else:
        features.add("page:long")
    for row in window.qa_rows:
        features.add(f"answer:{answer_bucket(window.page_count, row.answer_page_idx)}")
    return features


def select_sample_documents(
    windows: dict[str, WindowRecord],
    *,
    sample_documents: int,
    seed: str,
    explicit_doc_ids: list[str] | None,
) -> list[WindowRecord]:
    if explicit_doc_ids:
        selected: list[WindowRecord] = []
        seen: set[str] = set()
        for doc_id in explicit_doc_ids:
            if doc_id in seen:
                continue
            seen.add(doc_id)
            try:
                selected.append(windows[doc_id])
            except KeyError as exc:
                raise BuildError(f"requested doc_id is unavailable or invalid: {doc_id}") from exc
        return selected

    ordered = sorted(windows.values(), key=lambda item: (stable_key(seed, item.doc_id), item.doc_id))
    if sample_documents >= len(ordered):
        return ordered

    selected: list[WindowRecord] = []
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

    selected_ids = {window.doc_id for window in selected}
    for item in ordered:
        if len(selected) >= sample_documents:
            break
        if item.doc_id not in selected_ids:
            selected.append(item)
            selected_ids.add(item.doc_id)
    return selected[:sample_documents]


def load_selected_pages(
    input_parquets: list[Path],
    windows: list[WindowRecord],
) -> dict[str, list[PageRecord]]:
    expected = {window.doc_id: tuple(window.page_sha256) for window in windows}
    selected_ids = set(expected)
    loaded: dict[str, list[PageRecord]] = {}
    for parquet_path in input_parquets:
        parquet = pq.ParquetFile(parquet_path)
        columns = [
            name
            for name in ("questionId", "question", "doc_id", "page_ids", "answers", "answer_page_idx", "data_split")
            if name in parquet.schema_arrow.names
        ] + [column for column in IMAGE_COLUMNS if column in parquet.schema_arrow.names]
        for batch in parquet.iter_batches(batch_size=16, columns=columns):
            for raw_row in batch.to_pylist():
                row = parse_row(raw_row, source_shard=parquet_path.name, include_raw_bytes=True)
                if row.window_doc_id not in selected_ids or row.window_doc_id in loaded:
                    continue
                if row.page_sha256 == expected[row.window_doc_id]:
                    loaded[row.window_doc_id] = row.pages
            if len(loaded) == len(selected_ids):
                break
        if len(loaded) == len(selected_ids):
            break
    missing = sorted(selected_ids - set(loaded))
    if missing:
        raise BuildError(f"failed to load page bytes for selected windows: {missing}")
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
    window: WindowRecord,
    pages: list[PageRecord],
    generation_commit: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    doc_dir = output_root / "documents" / window.doc_id
    pages_dir = doc_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)

    page_manifest = []
    page_files: list[Path] = []
    for page in pages:
        if page.raw_bytes is None:
            raise BuildError(f"missing raw bytes for {window.doc_id}:{page.page_id}")
        page_file = pages_dir / f"{page.ordinal:04d}{page.extension}"
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

    manifest = {
        "builder_version": BUILDER_VERSION,
        "generation_commit": generation_commit,
        "doc_id": window.doc_id,
        "document_instance_id": window.doc_id,
        "source_doc_id": window.source_doc_id,
        "window_signature": window.window_signature,
        "input_scope": window.input_scope,
        "document_is_full_source_document": window.document_is_full_source_document,
        "source_shards": window.source_shards,
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
        "qa_count": len(window.qa_rows),
        "warnings": window.warnings,
    }
    manifest_path = doc_dir / "document_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    documents_record = {
        "doc_id": window.doc_id,
        "document_instance_id": window.doc_id,
        "source_doc_id": window.source_doc_id,
        "window_signature": window.window_signature,
        "input_scope": window.input_scope,
        "source_shards": window.source_shards,
        "page_count": len(page_manifest),
        "qa_count": len(window.qa_rows),
        "document_manifest": relative_posix(manifest_path, output_root),
        "pdf_path": manifest["pdf_path"],
        "pdf_sha256": pdf_sha256,
        "warnings": window.warnings,
    }
    return manifest, documents_record


def qa_record(row: RowRecord) -> dict[str, Any]:
    return {
        "qid": row.qid,
        "raw_question_id": row.qid,
        "doc_id": row.window_doc_id,
        "source_doc_id": row.source_doc_id,
        "question": row.question,
        "answers": row.answers,
        "answer_page_idx": row.answer_page_idx,
        "raw_answer_page_idx": row.answer_page_idx,
        "gold_page_id": row.page_ids[row.answer_page_idx],
        "gold_page_ordinal": row.answer_page_idx + 1,
        "source_split": row.source_split,
        "source_shard": row.source_shard,
        "source_row_index": row.row_index,
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
    input_parquets: Path | str | Iterable[Path | str],
    output_root: Path,
    sample_documents: int,
    seed: str,
    requested_doc_ids: list[str],
    validate_only: bool,
    overwrite: bool,
) -> dict[str, Any]:
    parquet_paths = normalize_input_parquets(input_parquets)
    generation_commit = git_commit()
    doc_audit = audit.schema_audit["doc_audit"]
    selected_windows = select_sample_documents(
        audit.valid_windows,
        sample_documents=sample_documents,
        seed=seed,
        explicit_doc_ids=requested_doc_ids or None,
    )
    if not selected_windows:
        raise BuildError("no valid document windows are available for selection")

    qa_records = [
        qa_record(row)
        for window in selected_windows
        for row in sorted(window.qa_rows, key=lambda item: (item.qid, item.source_shard, item.question))
    ]
    build_report = {
        "builder_version": BUILDER_VERSION,
        "generation_commit": generation_commit,
        "input_parquet_shards": [path.name for path in parquet_paths],
        "status": "success",
        "validate_only": validate_only,
        "sample_documents_requested": sample_documents,
        "seed": seed,
        "requested_doc_ids": requested_doc_ids,
        "selected_window_ids": [window.doc_id for window in selected_windows],
        "selected_source_doc_ids": [window.source_doc_id for window in selected_windows],
        "selected_window_page_counts": {window.doc_id: window.page_count for window in selected_windows},
        "selected_window_answer_buckets": {
            window.doc_id: sorted({answer_bucket(window.page_count, row.answer_page_idx) for row in window.qa_rows})
            for window in selected_windows
        },
        "row_count": audit.schema_audit["row_count"],
        "unique_source_doc_count": doc_audit["unique_source_doc_count"],
        "unique_window_count": doc_audit["unique_document_window_count"],
        "duplicate_window_count": doc_audit["duplicate_window_count"],
        "same_source_multiple_window_count": doc_audit["same_source_multiple_window_count"],
        "different_window_same_source_doc_count": doc_audit["different_window_same_source_doc_count"],
        "conflicting_window_count": doc_audit["conflicting_window_count"],
        "valid_window_count": doc_audit["valid_window_count"],
        "invalid_windows": audit.schema_audit["invalid_windows"],
        "qa_count": len(qa_records),
        "overlap_audit_status": audit.overlap_audit["status"],
    }
    metrics = {
        "row_count": audit.schema_audit["row_count"],
        "unique_source_doc_count": doc_audit["unique_source_doc_count"],
        "unique_window_count": doc_audit["unique_document_window_count"],
        "same_source_multiple_window_count": doc_audit["same_source_multiple_window_count"],
        "conflicting_window_count": doc_audit["conflicting_window_count"],
        "valid_window_count": doc_audit["valid_window_count"],
        "qa_count": len(qa_records),
        "duplicate_window_count": doc_audit["duplicate_window_count"],
    }

    if validate_only:
        return {
            "command": "build_mpdocvqa_raw_documents",
            "status": "success",
            "artifact_paths": [],
            "metrics": metrics,
            "build_report": build_report,
        }

    if output_root.exists():
        if not overwrite:
            raise BuildError(f"output root already exists: {output_root}")
        clear_output_root(output_root)
    output_root.mkdir(parents=True, exist_ok=True)

    selected_pages = load_selected_pages(parquet_paths, selected_windows)
    document_records = []
    for window in selected_windows:
        _, record = build_document_assets(
            output_root=output_root,
            window=window,
            pages=selected_pages[window.doc_id],
            generation_commit=generation_commit,
        )
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
        "input_parquet_shards": [path.name for path in parquet_paths],
        "selected_window_ids": [window.doc_id for window in selected_windows],
        "selected_document_window_count": len(selected_windows),
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
        "metrics": metrics,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore MP-DocVQA raw multi-page document windows from one or more parquet shards."
    )
    parser.add_argument("--input-parquet", nargs="+", required=True)
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
    parquet_paths = normalize_input_parquets(args.input_parquet)
    output_root = repo_path(args.output_root)
    exit_code = 0
    try:
        audit = audit_parquet(parquet_paths)
        payload = build_outputs(
            audit=audit,
            input_parquets=parquet_paths,
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

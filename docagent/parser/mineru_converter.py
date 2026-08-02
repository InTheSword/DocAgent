from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from docagent.schemas import Chunk, EvidenceLocation


TEXT_TYPES = {"text", "title", "heading", "paragraph", "list", "list_item", "caption"}
TABLE_TYPES = {"table"}
IMAGE_TYPES = {"image", "figure", "chart"}
BOILERPLATE_TYPES = {"header", "footer", "page_header", "page_footer", "page_number"}
KNOWN_RAW_TYPES = (
    TEXT_TYPES
    | TABLE_TYPES
    | IMAGE_TYPES
    | BOILERPLATE_TYPES
    | {"aside_text", "code", "equation", "index", "page_footnote", "ref_text"}
)
TEXTISH_KEYS = (
    "text",
    "content",
    "value",
    "table_text",
    "table_caption",
    "table_footnote",
    "caption",
    "image_caption",
    "chart_caption",
    "chart_footnote",
    "nearby_text",
)
VISUAL_SUMMARY_KEYS = (
    "visual_summary",
    "image_summary",
    "figure_summary",
    "chart_summary",
    "alt_text",
    "content",
)
NESTED_TEXT_KEYS = ("spans", "lines", "children", "blocks", "items", "cells", "rows")
RESOURCE_PATH_KEYS = (
    "image_path",
    "img_path",
    "image_url",
    "img_url",
    "table_image_path",
    "table_img_path",
    "table_image_url",
    "table_img_url",
)
URL_RE = re.compile(r"^https?://", re.IGNORECASE)
CHUNK_CONTRACT_VERSION = "docagent_chunk_v3"
SPLITTABLE_CONTENT_TYPES = {"body", "list_item", "reference"}
TABLE_SPLIT_MAX_CHARS = 1800
TABLE_SPLIT_MAX_ROWS = 12
TABLE_CAPTION_MARKER_RE = re.compile(r"(?i)(?<!\w)(?:table|tab\.)\s*\d+[a-z]?\s*[.:：]?|表\s*\d+\s*[.:：、]?")


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[list[tuple[str, int, int, bool]]] = []
        self._row: list[tuple[str, int, int, bool]] | None = None
        self._cell_parts: list[str] | None = None
        self._cell_is_header = False
        self._cell_rowspan = 1
        self._cell_colspan = 1

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() == "tr":
            self._row = []
        elif tag.lower() in {"td", "th"} and self._row is not None:
            attributes = {str(key).casefold(): value for key, value in attrs}
            self._cell_parts = []
            self._cell_is_header = tag.lower() == "th"
            self._cell_rowspan = _positive_span(attributes.get("rowspan"))
            self._cell_colspan = _positive_span(attributes.get("colspan"))

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            self._row.append(
                (
                    _clean_text(" ".join(self._cell_parts)),
                    self._cell_rowspan,
                    self._cell_colspan,
                    self._cell_is_header,
                )
            )
            self._cell_parts = None
        elif normalized == "tr" and self._row is not None:
            if any(cell[0] for cell in self._row):
                self._rows.append(self._row)
            self._row = None

    @property
    def rows(self) -> list[list[str]]:
        return _expand_table_cells(self._rows)

    @property
    def header_row_count(self) -> int:
        explicit = 0
        for row in self._rows:
            if row and all(cell[3] for cell in row):
                explicit += 1
            else:
                break
        if explicit:
            return explicit
        if not self._rows:
            return 0
        first_row = self._rows[0]
        return min(
            2 if any(rowspan > 1 or colspan > 1 for _text, rowspan, colspan, _header in first_row) else 1,
            len(self._rows),
        )


def _positive_span(value: object) -> int:
    try:
        return max(1, int(str(value or "1")))
    except ValueError:
        return 1


def _expand_table_cells(rows: list[list[tuple[str, int, int, bool]]]) -> list[list[str]]:
    grid: dict[tuple[int, int], str] = {}
    width = 0
    for row_index, row in enumerate(rows):
        column = 0
        for text, rowspan, colspan, _is_header in row:
            while (row_index, column) in grid:
                column += 1
            for row_offset in range(rowspan):
                for column_offset in range(colspan):
                    grid[(row_index + row_offset, column + column_offset)] = text
            column += colspan
        width = max(width, column, *(index + 1 for (index_row, index) in grid if index_row == row_index))
    return [
        [grid.get((row_index, column), "") for column in range(width)]
        for row_index in range(len(rows))
    ]


def _clean_text(value: object) -> str:
    if isinstance(value, list):
        parts = [_clean_text(item) for item in value]
        return " ".join(part for part in parts if part).strip()
    if isinstance(value, dict):
        parts = [_clean_text(value[key]) for key in TEXTISH_KEYS if key in value]
        if not any(parts):
            parts = [_clean_text(value[key]) for key in NESTED_TEXT_KEYS if key in value]
        if not any(parts):
            parts = [_clean_text(item) for item in value.values()]
        return " ".join(part for part in parts if part).strip()
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _is_page_number_like(text: str) -> bool:
    normalized = _clean_text(text).casefold()
    normalized = normalized.strip(" -–—|·•")
    if not normalized:
        return True
    return bool(
        re.fullmatch(
            r"(page\s*)?\d{1,4}(\s*(of|/)\s*\d{1,4})?",
            normalized,
        )
        or re.fullmatch(r"[ivxlcdm]{1,8}", normalized)
    )


def _has_substantive_signal(text: str) -> bool:
    normalized = _clean_text(text)
    if not normalized:
        return False
    if re.search(r"[$€£¥%]|\d[\d,]*(?:\.\d+)?", normalized):
        return True
    tokens = re.findall(r"[A-Za-z0-9]+", normalized)
    return len(tokens) >= 6


def _is_boilerplate(raw_type: str, text: str) -> bool:
    if raw_type not in BOILERPLATE_TYPES:
        return False
    if _is_page_number_like(text):
        return True
    return not _has_substantive_signal(text)


def _strip_html(value: str | None) -> str:
    if not value:
        return ""
    return _clean_text(re.sub(r"<[^>]+>", " ", value))


def _page_idx(item: dict[str, Any]) -> int | None:
    value = item.get("page_idx")
    if value is None:
        value = item.get("page")
    if value is None:
        value = item.get("page_id")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _docagent_page(item: dict[str, Any]) -> int | None:
    page_idx = _page_idx(item)
    return page_idx + 1 if page_idx is not None else None


def _bbox(item: dict[str, Any]) -> list[float] | None:
    value = item.get("bbox")
    if not isinstance(value, list) or not value:
        return None
    result: list[float] = []
    for item_value in value[:4]:
        try:
            result.append(float(item_value))
        except (TypeError, ValueError):
            return None
    return result if len(result) == 4 else None


def _raw_type(item: dict[str, Any]) -> str:
    return str(item.get("type", item.get("block_type", "text"))).lower()


def _block_type(raw_type: str) -> str:
    if raw_type in TABLE_TYPES:
        return "table"
    if raw_type in IMAGE_TYPES:
        return "image"
    return "text"


def _content_type(item: dict[str, Any], raw_type: str, block_type: str) -> str:
    if raw_type in {"title", "heading"} or item.get("text_level") is not None:
        return "heading"
    return {
        "text": "body",
        "paragraph": "body",
        "list": "list_item",
        "list_item": "list_item",
        "caption": "caption",
        "table": "table",
        "image": "image",
        "figure": "figure",
        "chart": "chart",
        "header": "page_header",
        "page_header": "page_header",
        "footer": "page_footer",
        "page_footer": "page_footer",
        "page_number": "page_number",
        "page_footnote": "footnote",
        "ref_text": "reference",
        "equation": "equation",
        "code": "code",
        "aside_text": "aside",
        "index": "index",
    }.get(raw_type, block_type if block_type in {"table", "image"} else "unknown")


def _heading_level(item: dict[str, Any], content_type: str) -> int | None:
    if content_type != "heading":
        return None
    value = item.get("text_level", item.get("level", 1))
    try:
        level = int(value)
    except (TypeError, ValueError):
        return 1
    return max(level, 1)


def _stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _printed_page_numbers(data: list[Any]) -> dict[int, str]:
    result: dict[int, str] = {}
    for item in data:
        if not isinstance(item, dict) or _raw_type(item) != "page_number":
            continue
        page_idx = _page_idx(item)
        label = _clean_text(item.get("text") or item.get("content"))
        if page_idx is not None and label:
            result.setdefault(page_idx, label)
    return result


def _summary_text(item: dict[str, Any], *, block_type: str, content_type: str) -> str | None:
    explicit = _unique_text_parts(
        _clean_text(item.get("summary")),
        _clean_text(item.get("abstract")),
        _clean_text(item.get("description")),
    )
    if explicit:
        return explicit
    if block_type == "image":
        return _visual_summary(item) or _caption_text(item, "caption", "image_caption", "chart_caption") or None
    if content_type == "table":
        return _caption_text(item, "table_caption") or None
    return None


def _keywords(item: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for key in ("keywords", "tags", "keyphrases"):
        for value in _as_list(item.get(key)):
            cleaned = _clean_text(value)
            if cleaned:
                values.append(cleaned)
    return list(dict.fromkeys(values))


def _as_list(value: object) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _table_html(item: dict[str, Any]) -> str | None:
    value = item.get("table_html") or item.get("table_body")
    return str(value) if value else None


def _table_structure(item: dict[str, Any], table_html: str | None) -> dict[str, Any]:
    headers = [_clean_text(value) for value in _as_list(item.get("headers")) if _clean_text(value)]
    raw_rows = item.get("rows")
    rows: list[list[str]] = []
    if isinstance(raw_rows, list):
        for row in raw_rows:
            if isinstance(row, list):
                cleaned = [_clean_text(cell) for cell in row]
                if any(cleaned):
                    rows.append(cleaned)
    if table_html and not rows:
        parser = _TableParser()
        try:
            parser.feed(table_html)
        except Exception:
            parser = _TableParser()
        rows = parser.rows
        if not headers and parser.header_row_count:
            headers = _combine_table_headers(rows[: parser.header_row_count])
            rows = rows[parser.header_row_count :]
    if not headers and not rows:
        return {}
    width = max([len(headers), *(len(row) for row in rows)], default=0)
    result = {
        "table_headers": headers,
        "table_rows": rows,
        "row_count": len(rows),
        "column_count": width,
    }
    result["table_markdown"] = _table_markdown(headers, rows)
    return result


def _combine_table_headers(rows: list[list[str]]) -> list[str]:
    width = max((len(row) for row in rows), default=0)
    headers: list[str] = []
    for column in range(width):
        parts: list[str] = []
        for row in rows:
            value = row[column] if column < len(row) else ""
            if value and (not parts or value.casefold() != parts[-1].casefold()):
                parts.append(value)
        headers.append(" ".join(parts).strip() or f"column_{column + 1}")
    return headers


def _table_markdown(headers: list[str], rows: list[list[str]]) -> str:
    width = max([len(headers), *(len(row) for row in rows)], default=0)
    if width == 0:
        return ""
    normalized_headers = [*(headers or [f"column_{index + 1}" for index in range(width)])]
    normalized_headers.extend([""] * (width - len(normalized_headers)))

    def render(row: list[str]) -> str:
        cells = [*row, *([""] * (width - len(row)))]
        return "| " + " | ".join(cell.replace("|", "\\|") for cell in cells[:width]) + " |"

    lines = [render(normalized_headers[:width]), "| " + " | ".join("---" for _ in range(width)) + " |"]
    lines.extend(render(row) for row in rows)
    return "\n".join(lines)


def _table_text(
    *,
    caption: str = "",
    context: str = "",
    markdown: str = "",
    unit: str = "",
    footnote: str = "",
) -> str:
    return _unique_text_parts(caption, unit, context, markdown, footnote)


def _table_caption_segments(value: str) -> list[str]:
    matches = list(TABLE_CAPTION_MARKER_RE.finditer(value))
    if len(matches) < 2:
        return [value.strip()] if value.strip() else []
    prefix = value[: matches[0].start()].strip()
    segments = [
        value[match.start() : matches[index + 1].start()].strip()
        if index + 1 < len(matches)
        else value[match.start() :].strip()
        for index, match in enumerate(matches)
    ]
    if prefix:
        segments[0] = f"{prefix} {segments[0]}".strip()
    return [segment for segment in segments if segment]


def _set_table_caption(block: Chunk, caption: str) -> None:
    metadata = block.metadata
    previous_caption = str(metadata.get("table_caption") or "")
    context = str(metadata.get("table_context") or "")
    if previous_caption and previous_caption in context:
        context = context.replace(previous_caption, "", 1).strip()
    metadata["table_caption"] = caption
    metadata["summary"] = caption
    if context:
        metadata["table_context"] = context
    else:
        metadata.pop("table_context", None)
    block.text = _table_text(
        caption=caption,
        context=context,
        markdown=str(metadata.get("table_markdown") or ""),
        unit=str(metadata.get("table_unit") or ""),
        footnote=str(metadata.get("table_footnote") or ""),
    )


def _repair_table_caption_associations(blocks: list[Chunk]) -> None:
    for index, caption_block in enumerate(blocks):
        if caption_block.metadata.get("content_type") != "caption":
            continue
        caption = caption_block.text.strip()
        if not TABLE_CAPTION_MARKER_RE.search(caption):
            continue
        for candidate_index in (index + 1, index - 1):
            if not 0 <= candidate_index < len(blocks):
                continue
            table = blocks[candidate_index]
            if (
                table.page_id == caption_block.page_id
                and table.block_type == "table"
                and not table.metadata.get("table_caption")
            ):
                _set_table_caption(table, caption)
                table.metadata["table_caption_source_block_id"] = caption_block.block_id
                caption_block.metadata["related_block_id"] = table.block_id
                break

    for index, block in enumerate(blocks):
        if block.block_type != "table":
            continue
        caption = str(block.metadata.get("table_caption") or "").strip()
        segments = _table_caption_segments(caption)
        if len(segments) < 2:
            continue
        previous_tables: list[Chunk] = []
        cursor = index - 1
        while cursor >= 0:
            previous = blocks[cursor]
            if previous.page_id != block.page_id or previous.block_type != "table":
                break
            if previous.metadata.get("table_caption"):
                break
            previous_tables.append(previous)
            cursor -= 1
        assign_count = min(len(previous_tables), len(segments) - 1)
        if assign_count == 0:
            continue
        targets = list(reversed(previous_tables[:assign_count]))
        for target, target_caption in zip(targets, segments[:assign_count]):
            _set_table_caption(target, target_caption)
            target.metadata["table_caption_source_block_id"] = block.block_id
        _set_table_caption(block, " ".join(segments[assign_count:]))
        block.metadata["table_caption_split"] = True


def _caption_text(item: dict[str, Any], *keys: str) -> str:
    parts: list[str] = []
    for key in keys:
        parts.extend(_clean_text(value) for value in _as_list(item.get(key)))
    return _unique_text_parts(*parts)


def _unique_text_parts(*parts: str) -> str:
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        cleaned = _clean_text(part)
        if not cleaned:
            continue
        key = cleaned.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return "\n".join(result).strip()


def _item_text(item: dict[str, Any], raw_type: str, block_type: str) -> str:
    if block_type == "table":
        caption = _caption_text(item, "table_caption")
        footnote = _caption_text(item, "table_footnote")
        body_text = _unique_text_parts(
            _clean_text(item.get("table_text")),
            _clean_text(item.get("text")),
            _clean_text(item.get("content")),
            _strip_html(_table_html(item)),
        )
        return _unique_text_parts(caption, body_text, footnote)
    if raw_type == "chart":
        caption = _caption_text(item, "chart_caption")
        footnote = _caption_text(item, "chart_footnote")
        content = _unique_text_parts(
            _visual_summary(item),
            _clean_text(item.get("nearby_text")),
            _clean_text(item.get("text")),
            _clean_text(item.get("content")),
        )
        return _unique_text_parts(caption, content, footnote)
    if block_type == "image":
        return _unique_text_parts(
            _visual_summary(item),
            _caption_text(item, "caption", "image_caption"),
            _clean_text(item.get("nearby_text")),
            _clean_text(item.get("text")),
            _clean_text(item.get("content")),
        )
    return _unique_text_parts(_clean_text(item.get("text")), _clean_text(item.get("content")))


def _visual_summary(item: dict[str, Any]) -> str:
    return _caption_text(item, *VISUAL_SUMMARY_KEYS)


def _visual_content_metadata(
    item: dict[str, Any],
    *,
    block_type: str,
    image_path: str | None,
    visual_summary: str,
) -> dict[str, Any]:
    if block_type != "image":
        return {}
    sources: list[str] = []
    if visual_summary:
        sources.append("visual_summary")
    if _caption_text(item, "caption", "image_caption", "chart_caption"):
        sources.append("caption")
    if _clean_text(item.get("nearby_text")):
        sources.append("nearby_text")
    if _clean_text(item.get("text")):
        sources.append("ocr_text")

    if visual_summary:
        status = "vlm_summarized"
    elif any(source in {"nearby_text", "ocr_text"} for source in sources):
        status = "ocr_or_nearby_text"
    elif "caption" in sources:
        status = "caption_only"
    elif image_path:
        status = "resource_only"
    else:
        status = "empty"
    return {
        "visual_content_status": status,
        "visual_text_sources": sources,
        "requires_visual_understanding": bool(image_path) and status in {"resource_only", "caption_only"},
    }


def _resource_path(item: dict[str, Any]) -> tuple[str | None, str | None]:
    for key in RESOURCE_PATH_KEYS:
        value = item.get(key)
        if value:
            return str(value), key
    return None, None


def _default_document_dir(content_list_path: Path) -> Path:
    return content_list_path.parent.parent if content_list_path.parent.name == "mineru" else content_list_path.parent


def _relative_posix(path: Path, document_dir: Path) -> str:
    try:
        return path.resolve().relative_to(document_dir.resolve()).as_posix()
    except ValueError:
        return path.name if path.is_absolute() else path.as_posix()


def _is_url(value: str) -> bool:
    return bool(URL_RE.match(value.strip()))


def _resolve_resource_path(raw_path: str | None, root: Path, document_dir: Path) -> tuple[str | None, bool | None, bool]:
    if not raw_path:
        return None, None, False
    if _is_url(raw_path):
        return raw_path.strip(), None, True
    path = Path(raw_path)
    if not path.is_absolute():
        path = root / path
    return _relative_posix(path, document_dir), path.is_file(), False


def _layout_metadata(content_list_path: Path, document_dir: Path) -> dict[str, Any]:
    layout_path = content_list_path.parent / "layout.json"
    if not layout_path.exists():
        return {}
    try:
        data = json.loads(layout_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {"layout_path": _relative_posix(layout_path, document_dir), "layout_readable": False}
    return {
        "layout_path": _relative_posix(layout_path, document_dir),
        "layout_readable": True,
        "mineru_backend": data.get("_backend"),
        "mineru_version": data.get("_version_name"),
        "mineru_ocr_enable": data.get("_ocr_enable"),
        "mineru_vlm_ocr_enable": data.get("_vlm_ocr_enable"),
        "layout_page_count": len(data.get("pdf_info") or []),
    }


def _layout_page_dimensions(content_list_path: Path) -> dict[int, tuple[float, float]]:
    layout_path = content_list_path.parent / "layout.json"
    try:
        data = json.loads(layout_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    result: dict[int, tuple[float, float]] = {}
    for page in data.get("pdf_info") or []:
        if not isinstance(page, dict):
            continue
        page_idx = _page_idx(page)
        size = page.get("page_size")
        if page_idx is None or not isinstance(size, list) or len(size) < 2:
            continue
        try:
            result[page_idx] = (float(size[0]), float(size[1]))
        except (TypeError, ValueError):
            continue
    return result


def _make_block(
    *,
    doc_id: str,
    item: dict[str, Any],
    index: int,
    content_list_path: Path,
    resource_root: Path,
    document_dir: Path,
    provenance: dict[str, Any],
    printed_page_numbers: dict[int, str],
    page_dimensions: dict[int, tuple[float, float]],
) -> Chunk | None:
    raw_type = _raw_type(item)
    block_type = _block_type(raw_type)
    content_type = _content_type(item, raw_type, block_type)
    page = _docagent_page(item)
    mineru_page_idx = _page_idx(item)
    visual_summary = _visual_summary(item) if block_type == "image" else ""
    table_html = _table_html(item) if block_type == "table" else None
    table_structure = _table_structure(item, table_html) if block_type == "table" else {}
    text = _item_text(item, raw_type, block_type)
    table_context = text if block_type == "table" else ""
    if block_type == "table" and table_structure.get("table_markdown"):
        text = _table_text(
            caption=_caption_text(item, "table_caption"),
            context=table_context,
            markdown=str(table_structure["table_markdown"]),
            unit=_caption_text(item, "table_unit", "unit"),
            footnote=_caption_text(item, "table_footnote"),
        )
    boilerplate = _is_boilerplate(raw_type, text)
    raw_image_path, raw_resource_key = _resource_path(item)
    resource_path, resource_exists, resource_is_remote = _resolve_resource_path(raw_image_path, resource_root, document_dir)
    image_path = resource_path if block_type == "image" else None
    if block_type == "table" and raw_image_path:
        image_path = resource_path
    if not text and not table_html and not image_path and not boilerplate:
        return None

    safe_page = page if page is not None else 0
    block_id = f"{doc_id}_p{safe_page:03d}_b{index:04d}"
    metadata: dict[str, Any] = {
        "parser": "mineru",
        "chunk_strategy": "mineru_block_identity",
        "chunk_contract_version": CHUNK_CONTRACT_VERSION,
        "source_block_ids": [block_id],
        "source_item_id": _source_item_id(item),
        "source_item_ids": [value for value in [_source_item_id(item)] if value],
        "source_item_hash": _stable_hash(item),
        "source_item_hashes": [_stable_hash(item)],
        "source_page_numbers": [page] if page is not None else [],
        "document_page_number_start": page,
        "document_page_number_end": page,
        "global_chunk_id": block_id,
        "reading_order": index,
        "raw_item_index": index,
        "raw_mineru_type": raw_type,
        "content_type": content_type,
        "document_page_index": mineru_page_idx,
        "document_page_number": page,
        "printed_page_number": printed_page_numbers.get(mineru_page_idx) if mineru_page_idx is not None else None,
        "section_id": None,
        "section_path": [],
        "heading_level": _heading_level(item, content_type),
        "heading_role": None,
        "parent_heading_id": None,
        "previous_block_id": None,
        "next_block_id": None,
        "previous_document_block_id": None,
        "next_document_block_id": None,
        "continuation_of": None,
        "continued_by": None,
        "cross_page_group_id": None,
        "container_id": block_id if block_type in {"table", "image"} else None,
        "container_type": content_type,
        "summary": _summary_text(item, block_type=block_type, content_type=content_type),
        "keywords": _keywords(item),
        "feature_tags": [],
        "raw_boilerplate_type": raw_type in BOILERPLATE_TYPES,
        "is_boilerplate": boilerplate,
        "is_page_header": content_type == "page_header",
        "is_page_footer": content_type == "page_footer",
        "exclude_from_retrieval": boilerplate,
        "mineru_provenance": provenance,
    }
    if mineru_page_idx in page_dimensions:
        metadata["page_width"], metadata["page_height"] = page_dimensions[mineru_page_idx]
    if raw_type not in KNOWN_RAW_TYPES:
        metadata["unknown_raw_type"] = True
    if mineru_page_idx is not None:
        metadata["mineru_page_idx"] = mineru_page_idx
    if "text_level" in item:
        metadata["text_level"] = item["text_level"]
    if block_type == "table":
        metadata.update(table_structure)
        metadata["table_role"] = "identity"
        metadata["include_in_structured_table_index"] = True
        if table_context:
            metadata["table_context"] = table_context
        table_caption = _caption_text(item, "table_caption")
        table_footnote = _caption_text(item, "table_footnote")
        table_unit = _caption_text(item, "table_unit", "unit")
        if table_caption:
            metadata["table_caption"] = table_caption
        if table_footnote:
            metadata["table_footnote"] = table_footnote
        if table_unit:
            metadata["table_unit"] = table_unit
    elif block_type == "image":
        image_caption = _caption_text(item, "caption", "image_caption", "chart_caption")
        image_footnote = _caption_text(item, "chart_footnote")
        if image_caption:
            metadata["image_caption"] = image_caption
        if image_footnote:
            metadata["image_footnote"] = image_footnote
    nearby_text = _clean_text(item.get("nearby_text"))
    if nearby_text:
        metadata["nearby_text"] = nearby_text
    if item.get("sub_type") is not None:
        metadata["visual_subtype"] = _clean_text(item.get("sub_type"))
    if raw_image_path is not None:
        metadata["source_resource_path"] = raw_image_path
        if raw_resource_key is not None:
            metadata["resource_key"] = raw_resource_key
        metadata["resource_exists"] = resource_exists
        metadata["resource_is_remote"] = resource_is_remote
    if visual_summary:
        metadata["visual_summary"] = visual_summary
    metadata.update(
        _visual_content_metadata(
            item,
            block_type=block_type,
            image_path=image_path,
            visual_summary=visual_summary,
        )
    )

    return Chunk(
        doc_id=doc_id,
        page_id=page,
        block_id=block_id,
        block_type=block_type,
        text=text,
        table_html=table_html,
        image_path=image_path,
        visual_summary=visual_summary or None,
        location=EvidenceLocation(page=page, block_id=block_id, bbox=_bbox(item)),
        metadata=metadata,
    )


def _source_item_id(item: dict[str, Any]) -> str | None:
    for key in ("id", "block_id", "uuid", "content_id"):
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return None


def _assign_page_reading_order(blocks: list[Chunk]) -> None:
    reading_orders = [block.metadata.get("reading_order") for block in blocks]
    if (
        any(not isinstance(value, int) for value in reading_orders)
        or len(reading_orders) != len(set(reading_orders))
    ):
        for reading_order, block in enumerate(blocks, start=1):
            block.metadata["reading_order"] = reading_order
    counters: dict[int | None, int] = {}
    for block in blocks:
        counters[block.page_id] = counters.get(block.page_id, 0) + 1
        block.metadata["page_reading_order"] = counters[block.page_id]


def _link_neighbors(blocks: list[Chunk]) -> None:
    for index, block in enumerate(blocks):
        block.metadata["previous_block_id"] = None
        block.metadata["next_block_id"] = None
        block.metadata["previous_document_block_id"] = blocks[index - 1].block_id if index > 0 else None
        block.metadata["next_document_block_id"] = blocks[index + 1].block_id if index + 1 < len(blocks) else None
        if index > 0:
            previous = blocks[index - 1]
            if previous.page_id == block.page_id:
                block.metadata["previous_block_id"] = previous.block_id
        if index + 1 < len(blocks) and blocks[index + 1].page_id == block.page_id:
            block.metadata["next_block_id"] = blocks[index + 1].block_id


def _link_related_blocks(blocks: list[Chunk]) -> None:
    by_page: dict[int | None, list[Chunk]] = {}
    for block in blocks:
        by_page.setdefault(block.page_id, []).append(block)
    for page_blocks in by_page.values():
        targets = [
            block
            for block in page_blocks
            if block.block_type in {"table", "image"}
            and block.metadata.get("table_role") != "retrieval_child"
        ]
        text_context = [
            block
            for block in page_blocks
            if block.metadata.get("content_type") in {"body", "heading", "list_item"}
            and not block.metadata.get("is_boilerplate")
        ]
        for target in targets:
            target_order = int(target.metadata.get("page_reading_order") or 0)
            nearby = sorted(
                text_context,
                key=lambda block: (
                    abs(int(block.metadata.get("page_reading_order") or 0) - target_order),
                    int(block.metadata.get("page_reading_order") or 0),
                ),
            )[:2]
            target.metadata["nearby_block_ids"] = [block.block_id for block in nearby]
            target.metadata.setdefault("caption_block_ids", [])
        for caption in [block for block in page_blocks if block.metadata.get("content_type") == "caption"]:
            if not targets:
                continue
            caption_order = int(caption.metadata.get("page_reading_order") or 0)
            target = min(
                targets,
                key=lambda block: (
                    abs(int(block.metadata.get("page_reading_order") or 0) - caption_order),
                    int(block.metadata.get("page_reading_order") or 0),
                ),
            )
            target.metadata.setdefault("caption_block_ids", []).append(caption.block_id)
            caption.metadata["related_block_id"] = target.block_id


def _apply_heading_hierarchy(blocks: list[Chunk]) -> None:
    stack: list[tuple[int, str, str]] = []
    seen_heading = False
    for block in blocks:
        content_type = str(block.metadata.get("content_type") or "")
        if content_type == "heading":
            level = int(block.metadata.get("heading_level") or 1)
            while stack and stack[-1][0] >= level:
                stack.pop()
            block.metadata["parent_heading_id"] = stack[-1][2] if stack else None
            block.metadata["section_path"] = [item[1] for item in stack] + [block.text]
            block.metadata["section_id"] = block.block_id
            block.metadata["heading_role"] = "document_title" if not seen_heading else "section_heading"
            seen_heading = True
            stack.append((level, block.text, block.block_id))
            continue
        block.metadata["section_path"] = [item[1] for item in stack]
        block.metadata["section_id"] = stack[-1][2] if stack else None
        block.metadata["parent_heading_id"] = stack[-1][2] if stack else None


def _merge_cross_page_text(blocks: list[Chunk]) -> list[Chunk]:
    by_page: dict[int, list[Chunk]] = {}
    for block in blocks:
        if block.page_id is not None and not block.metadata.get("is_boilerplate"):
            by_page.setdefault(block.page_id, []).append(block)

    links: dict[str, Chunk] = {}
    for page in sorted(by_page):
        next_page = page + 1
        if next_page not in by_page:
            continue
        left = by_page[page][-1]
        right = by_page[next_page][0]
        if _is_cross_page_continuation(left, right):
            links[left.block_id] = right

    if not links:
        return blocks
    linked_targets = {block.block_id for block in links.values()}
    consumed: set[str] = set()
    result: list[Chunk] = []
    for block in blocks:
        if block.block_id in consumed or block.block_id in linked_targets:
            continue
        group = [block]
        while group[-1].block_id in links:
            following = links[group[-1].block_id]
            group.append(following)
            consumed.add(following.block_id)
        result.append(_merge_cross_page_group(group) if len(group) > 1 else block)
    return result


def _is_cross_page_continuation(left: Chunk, right: Chunk) -> bool:
    if left.block_type != "text" or right.block_type != "text":
        return False
    if left.metadata.get("content_type") not in SPLITTABLE_CONTENT_TYPES:
        return False
    if right.metadata.get("content_type") != left.metadata.get("content_type"):
        return False
    if list(left.metadata.get("section_path") or []) != list(right.metadata.get("section_path") or []):
        return False
    if not left.text.strip() or not right.text.strip():
        return False
    if re.search(r'[。！？.!?]["”’\']?\s*$', left.text):
        return False
    boundary_signal = _has_page_boundary_signal(left, right)
    continuation_signal = (
        left.text.rstrip().endswith(("-", "‐", "‑"))
        or _starts_with_lowercase_letter(right.text)
    )
    left_length = len(left.text.strip())
    return (
        (left_length >= 20 and boundary_signal)
        or (left_length >= 40 and continuation_signal)
    )


def _has_page_boundary_signal(left: Chunk, right: Chunk) -> bool:
    left_bbox = left.location.bbox
    right_bbox = right.location.bbox
    left_height = left.metadata.get("page_height")
    right_height = right.metadata.get("page_height")
    if not left_bbox or not right_bbox or not left_height or not right_height:
        return False
    return (
        float(left_bbox[3]) >= 0.78 * float(left_height)
        and float(right_bbox[1]) <= 0.22 * float(right_height)
    )


def _starts_with_lowercase_letter(text: str) -> bool:
    first_letter = next((character for character in text.lstrip() if character.isalpha()), "")
    return bool(first_letter and first_letter.islower())


def _merge_cross_page_group(group: list[Chunk]) -> Chunk:
    first, last = group[0], group[-1]
    block_id = f"{first.block_id}_xp{int(last.page_id or first.page_id or 0):03d}"
    source_block_ids = [
        source_id
        for block in group
        for source_id in block.metadata.get("source_block_ids") or [block.block_id]
    ]
    source_item_ids = [
        source_id
        for block in group
        for source_id in block.metadata.get("source_item_ids") or []
    ]
    source_item_hashes = [
        source_hash
        for block in group
        for source_hash in block.metadata.get("source_item_hashes")
        or [block.metadata.get("source_item_hash")]
        if source_hash
    ]
    source_pages = list(
        dict.fromkeys(
            page
            for block in group
            for page in block.metadata.get("source_page_numbers") or [block.page_id]
            if page is not None
        )
    )
    metadata = {
        **first.metadata,
        "chunk_strategy": "cross_page_merge",
        "source_block_ids": source_block_ids,
        "source_item_id": source_item_ids[0] if source_item_ids else None,
        "source_item_ids": source_item_ids,
        "source_item_hash": _stable_hash(source_item_hashes),
        "source_item_hashes": source_item_hashes,
        "source_page_numbers": source_pages,
        "document_page_number_start": first.page_id,
        "document_page_number_end": last.page_id,
        "printed_page_number_end": last.metadata.get("printed_page_number"),
        "cross_page_group_id": block_id,
        "continuation_of": None,
        "continued_by": None,
        "end_bbox": last.location.bbox,
    }
    return Chunk(
        doc_id=first.doc_id,
        page_id=first.page_id,
        block_id=block_id,
        block_type=first.block_type,
        text="\n".join(block.text.strip() for block in group if block.text.strip()),
        location=EvidenceLocation(page=first.page_id, block_id=block_id, bbox=first.location.bbox),
        metadata=metadata,
    )


def _finalize_chunk_metadata(blocks: list[Chunk]) -> None:
    for block in blocks:
        content_type = str(block.metadata.get("content_type") or block.block_type)
        tags = [f"content_type:{content_type}", f"modality:{block.block_type}"]
        if block.metadata.get("is_boilerplate"):
            tags.append("boilerplate")
        if block.metadata.get("summary"):
            tags.append("has_summary")
        if block.metadata.get("table_headers") or block.metadata.get("table_rows"):
            tags.append("has_table_structure")
        block.metadata["global_chunk_id"] = block.block_id
        block.metadata["feature_tags"] = tags
        block.metadata["content_hash"] = _stable_hash(
            {
                "block_type": block.block_type,
                "content_type": content_type,
                "text": block.text,
                "table_html": block.table_html,
                "visual_summary": block.visual_summary,
            }
        )


def validate_mineru_chunk_contract(blocks: list[Chunk]) -> dict[str, list[str]]:
    """Return contract violations keyed by block_id without mutating chunks."""

    required = (
        "chunk_contract_version",
        "source_block_ids",
        "source_item_hash",
        "source_item_hashes",
        "source_page_numbers",
        "global_chunk_id",
        "reading_order",
        "page_reading_order",
        "content_type",
        "document_page_index",
        "document_page_number",
        "document_page_number_start",
        "document_page_number_end",
        "section_path",
        "feature_tags",
        "content_hash",
        "is_boilerplate",
        "exclude_from_retrieval",
    )
    errors: dict[str, list[str]] = {}
    seen: set[str] = set()
    for block in blocks:
        block_errors: list[str] = []
        if block.block_id in seen:
            block_errors.append("duplicate_block_id")
        seen.add(block.block_id)
        missing = [key for key in required if key not in block.metadata]
        block_errors.extend(f"missing:{key}" for key in missing)
        if block.metadata.get("chunk_contract_version") != CHUNK_CONTRACT_VERSION:
            block_errors.append("invalid:chunk_contract_version")
        if block.metadata.get("global_chunk_id") != block.block_id:
            block_errors.append("invalid:global_chunk_id")
        if block.location.block_id != block.block_id or block.location.page != block.page_id:
            block_errors.append("invalid:location")
        if block.metadata.get("document_page_number") != block.page_id:
            block_errors.append("invalid:document_page_number")
        if not isinstance(block.metadata.get("section_path"), list):
            block_errors.append("invalid:section_path")
        if not isinstance(block.metadata.get("source_block_ids"), list):
            block_errors.append("invalid:source_block_ids")
        if not re.fullmatch(r"[0-9a-f]{64}", str(block.metadata.get("source_item_hash") or "")):
            block_errors.append("invalid:source_item_hash")
        if not re.fullmatch(r"[0-9a-f]{64}", str(block.metadata.get("content_hash") or "")):
            block_errors.append("invalid:content_hash")
        if block.block_type == "table":
            table_role = block.metadata.get("table_role")
            if table_role not in {"identity", "structured_parent", "retrieval_child"}:
                block_errors.append("invalid:table_role")
            elif table_role == "structured_parent":
                if not block.metadata.get("child_block_ids"):
                    block_errors.append("invalid:child_block_ids")
                if block.metadata.get("exclude_from_retrieval") is not True:
                    block_errors.append("invalid:structured_parent_retrieval")
                if block.metadata.get("include_in_structured_table_index") is not True:
                    block_errors.append("invalid:structured_parent_index")
            elif table_role == "retrieval_child":
                if not block.metadata.get("table_parent_id"):
                    block_errors.append("invalid:table_parent_id")
                if not isinstance(block.metadata.get("row_start"), int) or not isinstance(
                    block.metadata.get("row_end"), int
                ):
                    block_errors.append("invalid:table_row_range")
                if block.metadata.get("include_in_structured_table_index") is not False:
                    block_errors.append("invalid:retrieval_child_index")
        if block_errors:
            errors[block.block_id] = block_errors
    return errors


def _split_large_block(block: Chunk, max_chars: int) -> list[Chunk]:
    if (
        len(block.text) <= max_chars
        or block.block_type != "text"
        or block.metadata.get("content_type") not in SPLITTABLE_CONTENT_TYPES
        or block.metadata.get("is_boilerplate")
    ):
        return [block]
    parts = _sentence_units(block.text, max_chars)
    chunks: list[str] = []
    current = ""
    for part in parts:
        if current and len(current) + 1 + len(part) > max_chars:
            chunks.append(current)
            current = part
        else:
            current = f"{current} {part}".strip()
    if current:
        chunks.append(current)
    if len(chunks) <= 1:
        return [block]
    result: list[Chunk] = []
    source_block_ids = list(block.metadata.get("source_block_ids") or [block.block_id])
    for idx, text in enumerate(chunks, start=1):
        child_id = f"{block.block_id}_s{idx:03d}"
        result.append(
            Chunk(
                doc_id=block.doc_id,
                page_id=block.page_id,
                block_id=child_id,
                block_type=block.block_type,
                text=text,
                location=EvidenceLocation(page=block.page_id, block_id=child_id, bbox=block.location.bbox),
                metadata={
                    **block.metadata,
                    "chunk_strategy": (
                        "cross_page_sentence_split"
                        if block.metadata.get("cross_page_group_id")
                        else "sentence_window_split"
                    ),
                    "source_block_ids": source_block_ids,
                    "parent_block_id": block.block_id,
                    "segment_index": idx,
                    "segment_count": len(chunks),
                },
            )
        )
    return result


def _split_large_table(
    block: Chunk,
    *,
    max_chars: int,
    max_rows: int,
) -> list[Chunk]:
    headers = [str(value) for value in block.metadata.get("table_headers") or []]
    rows = [
        [str(value) for value in row]
        for row in block.metadata.get("table_rows") or []
        if isinstance(row, list)
    ]
    markdown = str(block.metadata.get("table_markdown") or "")
    if (
        block.block_type != "table"
        or not headers
        or not rows
        or (len(rows) <= max_rows and len(markdown) <= max_chars)
    ):
        block.metadata.setdefault("table_role", "identity")
        block.metadata.setdefault("include_in_structured_table_index", True)
        return [block]

    groups: list[list[list[str]]] = []
    current: list[list[str]] = []
    for row in rows:
        proposed = [*current, row]
        if current and (
            len(proposed) > max_rows
            or len(_table_markdown(headers, proposed)) > max_chars
        ):
            groups.append(current)
            current = [row]
        else:
            current = proposed
    if current:
        groups.append(current)
    if len(groups) <= 1:
        return [block]

    child_ids: list[str] = []
    children: list[Chunk] = []
    row_start = 1
    for group in groups:
        row_end = row_start + len(group) - 1
        child_id = f"{block.block_id}_r{row_start:03d}_{row_end:03d}"
        child_ids.append(child_id)
        child_markdown = _table_markdown(headers, group)
        child_metadata = {
            **block.metadata,
            "chunk_strategy": "table_row_group_split",
            "parent_block_id": block.block_id,
            "container_id": block.block_id,
            "table_parent_id": block.block_id,
            "table_role": "retrieval_child",
            "include_in_structured_table_index": False,
            "exclude_from_retrieval": False,
            "table_rows": group,
            "table_markdown": child_markdown,
            "row_count": len(group),
            "table_total_row_count": len(rows),
            "row_start": row_start,
            "row_end": row_end,
        }
        child_metadata.pop("table_context", None)
        child_metadata.pop("child_block_ids", None)
        children.append(
            Chunk(
                doc_id=block.doc_id,
                page_id=block.page_id,
                block_id=child_id,
                block_type="table",
                text=_table_text(
                    caption=str(child_metadata.get("table_caption") or ""),
                    markdown=child_markdown,
                    unit=str(child_metadata.get("table_unit") or ""),
                    footnote=str(child_metadata.get("table_footnote") or ""),
                ),
                location=EvidenceLocation(
                    page=block.page_id,
                    block_id=child_id,
                    table_id=block.block_id,
                    bbox=block.location.bbox,
                ),
                metadata=child_metadata,
            )
        )
        row_start = row_end + 1

    block.metadata.update(
        {
            "table_role": "structured_parent",
            "include_in_structured_table_index": True,
            "exclude_from_retrieval": True,
            "child_block_ids": child_ids,
            "table_total_row_count": len(rows),
        }
    )
    return [block, *children]


def _sentence_units(text: str, max_chars: int) -> list[str]:
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[。！？!?])(?:\s+|(?=[^\s]))|(?<=[.;])\s+|\n+", text)
        if part.strip()
    ]
    result: list[str] = []
    for sentence in sentences or [text.strip()]:
        if len(sentence) <= max_chars:
            result.append(sentence)
            continue
        clauses = [
            part.strip()
            for part in re.split(r"(?<=[,，;；:：])\s*|\s+", sentence)
            if part.strip()
        ]
        current = ""
        for clause in clauses or [sentence]:
            if len(clause) > max_chars:
                if current:
                    result.append(current)
                    current = ""
                result.extend(clause[index : index + max_chars] for index in range(0, len(clause), max_chars))
            elif current and len(current) + 1 + len(clause) > max_chars:
                result.append(current)
                current = clause
            else:
                current = f"{current} {clause}".strip()
        if current:
            result.append(current)
    return result


def normalize_blocks(
    blocks: list[Chunk],
    *,
    merge_small_chars: int = 0,
    merge_max_chars: int = 1000,
    split_max_chars: int = 1200,
    table_split_max_chars: int = TABLE_SPLIT_MAX_CHARS,
    table_split_max_rows: int = TABLE_SPLIT_MAX_ROWS,
) -> list[Chunk]:
    merged: list[Chunk] = []
    pending: Chunk | None = None

    def flush_pending() -> None:
        nonlocal pending
        if pending is not None:
            merged.append(pending)
            pending = None

    for block in blocks:
        can_merge = (
            merge_small_chars > 0
            and block.block_type == "text"
            and block.metadata.get("content_type") == "body"
            and not block.metadata.get("is_boilerplate")
            and len(block.text) < merge_small_chars
            and pending is not None
            and pending.block_type == "text"
            and pending.metadata.get("content_type") == "body"
            and not pending.metadata.get("is_boilerplate")
            and pending.page_id == block.page_id
            and len(pending.text) + 1 + len(block.text) <= merge_max_chars
        )
        if can_merge:
            pending.text = f"{pending.text}\n{block.text}".strip()
            pending.metadata.setdefault("merged_block_ids", [pending.block_id])
            pending.metadata["merged_block_ids"].append(block.block_id)
            pending.metadata["chunk_strategy"] = "adjacent_text_merge"
            pending.metadata["source_block_ids"] = list(
                dict.fromkeys(
                    [
                        *list(pending.metadata.get("source_block_ids") or [pending.block_id]),
                        *list(block.metadata.get("source_block_ids") or [block.block_id]),
                    ]
                )
            )
            continue
        flush_pending()
        pending = block
    flush_pending()

    normalized: list[Chunk] = []
    for block in merged:
        if block.block_type == "table":
            normalized.extend(
                _split_large_table(
                    block,
                    max_chars=table_split_max_chars,
                    max_rows=table_split_max_rows,
                )
            )
        else:
            normalized.extend(_split_large_block(block, split_max_chars))
    _link_neighbors(normalized)
    return normalized


def build_page_blocks(doc_id: str, blocks: list[Chunk]) -> list[Chunk]:
    by_page: dict[int, list[Chunk]] = {}
    for block in blocks:
        if block.block_type == "page":
            continue
        source_pages = block.metadata.get("source_page_numbers") or [block.page_id]
        for page in source_pages:
            if page is not None:
                by_page.setdefault(int(page), []).append(block)
    pages: list[Chunk] = []
    for page, page_blocks in sorted(by_page.items()):
        page_blocks.sort(key=lambda item: int(item.metadata.get("reading_order", 0)))
        block_id = f"{doc_id}_p{page:03d}_page"
        text = "\n".join(block.retrieval_text for block in page_blocks if block.retrieval_text)
        page_block = Chunk(
            doc_id=doc_id,
            page_id=page,
            block_id=block_id,
            block_type="page",
            text=text,
            location=EvidenceLocation(page=page, block_id=block_id),
            metadata={
                "parser": "mineru",
                "chunk_contract_version": CHUNK_CONTRACT_VERSION,
                "content_type": "page_aggregate",
                "document_page_index": page - 1,
                "document_page_number": page,
                "printed_page_number": next(
                    (
                        block.metadata.get("printed_page_number")
                        for block in page_blocks
                        if block.metadata.get("printed_page_number")
                    ),
                    None,
                ),
                "section_path": [],
                "summary": None,
                "keywords": [],
                "feature_tags": [],
                "exclude_from_retrieval": True,
                "child_block_ids": [block.block_id for block in page_blocks],
                "excluded_child_block_ids": [
                    block.block_id for block in page_blocks if block.metadata.get("exclude_from_retrieval")
                ],
            },
        )
        _finalize_chunk_metadata([page_block])
        pages.append(page_block)
    return pages


def raw_content_list_stats(content_list_path: str | Path) -> dict[str, Any]:
    path = Path(content_list_path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("content_list") or data.get("blocks") or []
    if not isinstance(data, list):
        raise ValueError("MinerU content list must be a list or a dict with content_list/blocks")
    pages = {_page_idx(item) for item in data if isinstance(item, dict) and _page_idx(item) is not None}
    types = Counter(_raw_type(item) for item in data if isinstance(item, dict))
    return {
        "root_type": "list",
        "raw_block_count": len(data),
        "content_list_pages": len(pages),
        "raw_type_distribution": dict(sorted(types.items())),
        "missing_page_count": sum(1 for item in data if not isinstance(item, dict) or _page_idx(item) is None),
        "missing_or_invalid_bbox_count": sum(1 for item in data if not isinstance(item, dict) or _bbox(item) is None),
    }


def content_list_to_chunks(
    *,
    doc_id: str,
    content_list_path: str | Path,
    merge_cross_page: bool = True,
    merge_small_chars: int = 0,
    split_max_chars: int = 1200,
    table_split_max_chars: int = TABLE_SPLIT_MAX_CHARS,
    table_split_max_rows: int = TABLE_SPLIT_MAX_ROWS,
    resource_root: str | Path | None = None,
    document_dir: str | Path | None = None,
) -> list[Chunk]:
    """Convert MinerU JSON into canonical retrieval Chunks.

    Raw MinerU items are normalized first, then cross-page continuations are
    merged, and only afterwards are long textual units sentence-split.
    """

    path = Path(content_list_path)
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("content_list") or data.get("blocks") or []
    if not isinstance(data, list):
        raise ValueError("MinerU content list must be a list or a dict with content_list/blocks")
    resource_base = Path(resource_root) if resource_root is not None else path.parent
    document_base = Path(document_dir) if document_dir is not None else _default_document_dir(path)
    provenance = _layout_metadata(path, document_base)
    provenance["content_list_file"] = _relative_posix(path, document_base)
    printed_page_numbers = _printed_page_numbers(data)
    page_dimensions = _layout_page_dimensions(path)
    blocks = [
        _make_block(
            doc_id=doc_id,
            item=item,
            index=index,
            content_list_path=path,
            resource_root=resource_base,
            document_dir=document_base,
            provenance=provenance,
            printed_page_numbers=printed_page_numbers,
            page_dimensions=page_dimensions,
        )
        for index, item in enumerate(data, start=1)
        if isinstance(item, dict)
    ]
    result = [block for block in blocks if block is not None]
    _apply_heading_hierarchy(result)
    _repair_table_caption_associations(result)
    if merge_cross_page:
        result = _merge_cross_page_text(result)
    result = normalize_blocks(
        result,
        merge_small_chars=merge_small_chars,
        split_max_chars=split_max_chars,
        table_split_max_chars=table_split_max_chars,
        table_split_max_rows=table_split_max_rows,
    )
    _assign_page_reading_order(result)
    _link_neighbors(result)
    _link_related_blocks(result)
    _finalize_chunk_metadata(result)
    return result


def content_list_to_blocks(
    *,
    doc_id: str,
    content_list_path: str | Path,
    normalize: bool = False,
    resource_root: str | Path | None = None,
    document_dir: str | Path | None = None,
) -> list[Chunk]:
    """Compatibility wrapper; new code should use content_list_to_chunks."""

    return content_list_to_chunks(
        doc_id=doc_id,
        content_list_path=content_list_path,
        merge_small_chars=100 if normalize else 0,
        resource_root=resource_root,
        document_dir=document_dir,
    )


def find_content_list(output_dir: str | Path) -> Path:
    root = Path(output_dir)
    ordinary_candidates = [
        path
        for path in sorted(root.rglob("*content_list.json"))
        if not path.name.endswith("_content_list_v2.json") and path.name != "content_list_v2.json"
    ]
    if len(ordinary_candidates) > 1:
        names = ", ".join(str(path) for path in ordinary_candidates)
        raise ValueError(f"multiple ordinary MinerU content-list files found under {root}: {names}")

    if ordinary_candidates:
        return ordinary_candidates[0]

    v2_candidates = [
        path
        for path in sorted(root.rglob("*content_list_v2.json"))
        if path.name.endswith("_content_list_v2.json") or path.name == "content_list_v2.json"
    ]
    if not v2_candidates:
        raise FileNotFoundError(f"no MinerU content-list file found under {root}")
    if len(v2_candidates) > 1:
        names = ", ".join(str(path) for path in v2_candidates)
        raise ValueError(f"multiple MinerU content-list v2 files found under {root}: {names}")
    return v2_candidates[0]

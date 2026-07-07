from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docagent.integrations.vlm_api import OpenAICompatibleVLMClient, load_vlm_config
from docagent.schemas import EvidenceBlock


VISUAL_SUMMARY_PROMPT_VERSION = "visual-summary-v1"
CAPTION_RE = re.compile(r"^\s*(fig(?:ure)?\.?|table|chart|图|表)\s*[\w\d一二三四五六七八九十\-\.]*\s*[:：.\-]?", re.IGNORECASE)
VISUAL_QUESTION_RE = re.compile(
    r"\b(figure|fig\.?|image|picture|photo|chart|diagram|plot|visual|screenshot|axis|legend|颜色|图片|图像|图表|图|照片|示意图|截图)\b",
    re.IGNORECASE,
)


@dataclass
class VisualEnhancementResult:
    status: str
    mode: str
    block_count: int = 0
    candidate_image_count: int = 0
    native_caption_attached_count: int = 0
    vlm_summary_count: int = 0
    cache_hit_count: int = 0
    skipped_count: int = 0
    error_count: int = 0
    warnings: list[str] | None = None
    used_vlm: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "mode": self.mode,
            "block_count": self.block_count,
            "candidate_image_count": self.candidate_image_count,
            "native_caption_attached_count": self.native_caption_attached_count,
            "vlm_summary_count": self.vlm_summary_count,
            "cache_hit_count": self.cache_hit_count,
            "skipped_count": self.skipped_count,
            "error_count": self.error_count,
            "warnings": list(dict.fromkeys(self.warnings or [])),
            "used_vlm": self.used_vlm,
        }


def is_visual_question(question: str) -> bool:
    return VISUAL_QUESTION_RE.search(str(question or "")) is not None


def enhance_visual_blocks(
    blocks: list[EvidenceBlock],
    *,
    document_dir: str | Path,
    mode: str = "caption",
    env_file: Path | None = None,
    max_images: int = 8,
    client: Any | None = None,
) -> VisualEnhancementResult:
    normalized_mode = mode if mode in {"off", "caption", "auto", "vlm"} else "caption"
    result = VisualEnhancementResult(status="success", mode=normalized_mode, block_count=len(blocks), warnings=[])
    if normalized_mode == "off":
        return result
    result.native_caption_attached_count = attach_native_captions(blocks)
    images = [block for block in blocks if block.block_type in {"image", "figure"} and block.image_path]
    result.candidate_image_count = len(images)
    if normalized_mode == "caption":
        return result
    selected = [block for block in images if _should_vlm_summarize(block, mode=normalized_mode)]
    if max_images >= 0:
        selected = selected[:max_images]
    if not selected:
        return result
    visual_client = client
    config_warnings: list[str] = []
    if visual_client is None:
        config, config_warnings = load_vlm_config(env_file=env_file)
        result.warnings.extend(config_warnings)
        if config is None:
            result.skipped_count += len(selected)
            return result
        visual_client = OpenAICompatibleVLMClient(config)
    cache_path = Path(document_dir) / "visual_summaries.jsonl"
    cache = _load_cache(cache_path)
    changed_cache = False
    for block in selected:
        image_path = _resolve_image_path(block, document_dir=Path(document_dir))
        if image_path is None:
            result.skipped_count += 1
            continue
        try:
            cache_key = _cache_key(image_path, model=_client_model(visual_client))
        except OSError:
            result.skipped_count += 1
            continue
        cached = cache.get(cache_key)
        if cached:
            result.cache_hit_count += 1
            _apply_visual_summary(block, cached, source="vlm_api_cache", cache_key=cache_key, model=_client_model(visual_client))
            continue
        try:
            response = visual_client.summarize_image(
                image_path=image_path,
                context=_visual_context(block),
            )
        except Exception as exc:
            result.error_count += 1
            result.warnings.append(f"vlm_summary_failed:{type(exc).__name__}")
            continue
        cache[cache_key] = response
        changed_cache = True
        result.vlm_summary_count += 1
        result.used_vlm = True
        _apply_visual_summary(block, response, source="vlm_api", cache_key=cache_key, model=_client_model(visual_client))
    if changed_cache:
        _write_cache(cache_path, cache)
    return result


def visual_observation_for_block(
    block: EvidenceBlock,
    question: str,
    *,
    mode: str = "off",
    document_dir: str | Path | None = None,
    env_file: Path | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    normalized_mode = mode if mode in {"off", "auto", "force"} else "off"
    citation = _citation(block)
    if normalized_mode == "off":
        return _skipped_visual_result(block, question, "visual_review_disabled")
    if block.visual_summary and normalized_mode == "auto" and not block.metadata.get("requires_visual_understanding"):
        return {
            "status": "success",
            "tool": "visual_review",
            "answer": block.visual_summary,
            "reasoning_summary": "Existing visual summary was used as image evidence.",
            "citations": [citation],
            "evidence_used": [citation],
            "structured_result": {
                "source": "existing_visual_summary",
                "visual_summary": block.visual_summary,
                "used_vlm": False,
            },
        }
    if normalized_mode == "auto" and not is_visual_question(question) and not block.metadata.get("requires_visual_understanding"):
        return _skipped_visual_result(block, question, "visual_question_not_detected")
    image_path = _resolve_image_path(block, document_dir=Path(document_dir) if document_dir else None)
    if image_path is None:
        return _skipped_visual_result(block, question, "image_resource_unavailable")
    visual_client = client
    warnings: list[str] = []
    if visual_client is None:
        config, warnings = load_vlm_config(env_file=env_file)
        if config is None:
            return _skipped_visual_result(block, question, "vlm_not_configured", warnings=warnings)
        visual_client = OpenAICompatibleVLMClient(config)
    try:
        response = visual_client.answer_image_question(
            image_path=image_path,
            question=question,
            context=_visual_context(block),
        )
    except Exception as exc:
        return _skipped_visual_result(block, question, f"vlm_failed:{type(exc).__name__}")
    answer = _first_text(response, "answer", "visual_summary", "caption")
    summary = _first_text(response, "reasoning_summary", "visual_summary")
    if not answer:
        return _skipped_visual_result(block, question, "vlm_empty_answer")
    return {
        "status": "success",
        "tool": "visual_review",
        "answer": answer,
        "reasoning_summary": summary or "The visual evidence was inspected for the question.",
        "citations": [citation],
        "evidence_used": [citation],
        "structured_result": {
            "source": "vlm_api",
            "used_vlm": True,
            "visual_response": _compact_visual_response(response),
            "warnings": warnings,
        },
    }


def attach_native_captions(blocks: list[EvidenceBlock]) -> int:
    by_id = {block.block_id: block for block in blocks}
    changed = 0
    for block in blocks:
        if block.block_type not in {"image", "figure", "table"}:
            continue
        if _existing_caption(block):
            continue
        candidates = []
        for neighbor_id in (block.metadata.get("previous_block_id"), block.metadata.get("next_block_id")):
            neighbor = by_id.get(str(neighbor_id or ""))
            if neighbor is None or neighbor.page_id != block.page_id or neighbor.block_type != "text":
                continue
            text = neighbor.text.strip()
            if text and CAPTION_RE.search(text):
                candidates.append((neighbor, text))
        if not candidates:
            continue
        neighbor, caption = candidates[0]
        key = "table_caption" if block.block_type == "table" else "caption"
        block.metadata[key] = caption
        block.metadata["caption_source"] = "adjacent_text"
        block.metadata["caption_block_id"] = neighbor.block_id
        if block.block_type in {"image", "figure"}:
            _refresh_visual_status(block)
        changed += 1
    return changed


def _should_vlm_summarize(block: EvidenceBlock, *, mode: str) -> bool:
    if block.visual_summary:
        return False
    if mode == "vlm":
        return True
    return bool(block.metadata.get("requires_visual_understanding")) or str(block.metadata.get("visual_content_status") or "") in {
        "resource_only",
        "caption_only",
    }


def _apply_visual_summary(
    block: EvidenceBlock,
    response: dict[str, Any],
    *,
    source: str,
    cache_key: str,
    model: str,
) -> None:
    summary = _first_text(response, "visual_summary", "caption", "answer")
    if not summary:
        return
    block.visual_summary = summary
    block.metadata["visual_summary"] = summary
    block.metadata["visual_summary_source"] = source
    block.metadata["visual_summary_model"] = model
    block.metadata["visual_summary_prompt_version"] = VISUAL_SUMMARY_PROMPT_VERSION
    block.metadata["visual_cache_key"] = cache_key
    if response.get("image_kind"):
        block.metadata["image_kind"] = response.get("image_kind")
    if response.get("caption") and not _existing_caption(block):
        block.metadata["caption"] = response.get("caption")
        block.metadata["caption_source"] = source
    if response.get("key_text"):
        block.metadata["visual_key_text"] = response.get("key_text")
    if response.get("data_points"):
        block.metadata["visual_data_points"] = response.get("data_points")
    block.metadata["visual_content_status"] = "vlm_summarized"
    block.metadata["requires_visual_understanding"] = False
    sources = list(block.metadata.get("visual_text_sources") or [])
    sources.append("visual_summary")
    block.metadata["visual_text_sources"] = list(dict.fromkeys(str(item) for item in sources if str(item or "").strip()))


def _refresh_visual_status(block: EvidenceBlock) -> None:
    if block.visual_summary:
        status = "vlm_summarized"
    elif block.metadata.get("nearby_text") or block.text:
        status = "ocr_or_nearby_text"
    elif _existing_caption(block):
        status = "caption_only"
    elif block.image_path:
        status = "resource_only"
    else:
        status = "empty"
    block.metadata["visual_content_status"] = status
    block.metadata["requires_visual_understanding"] = bool(block.image_path) and status in {"resource_only", "caption_only"}
    sources = []
    if block.visual_summary:
        sources.append("visual_summary")
    if _existing_caption(block):
        sources.append("caption")
    if block.metadata.get("nearby_text"):
        sources.append("nearby_text")
    if block.text:
        sources.append("ocr_text")
    block.metadata["visual_text_sources"] = sources


def _existing_caption(block: EvidenceBlock) -> str:
    for key in ("caption", "image_caption", "chart_caption", "table_caption"):
        value = block.metadata.get(key)
        if isinstance(value, list):
            text = " ".join(str(item).strip() for item in value if str(item or "").strip()).strip()
        else:
            text = str(value or "").strip()
        if text:
            return text
    return ""


def _resolve_image_path(block: EvidenceBlock, *, document_dir: Path | None) -> Path | str | None:
    if not block.image_path:
        return None
    text = str(block.image_path).strip()
    if re.match(r"^https?://", text, flags=re.IGNORECASE):
        return text
    path = Path(text)
    if path.is_absolute():
        return path if path.is_file() else None
    if document_dir is None:
        return None
    resolved = document_dir / path
    return resolved if resolved.is_file() else None


def _visual_context(block: EvidenceBlock) -> str:
    parts = [
        _existing_caption(block),
        str(block.metadata.get("nearby_text") or ""),
        block.text or "",
        block.visual_summary or "",
    ]
    return "\n".join(part for part in parts if str(part or "").strip())[:1200]


def _citation(block: EvidenceBlock) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "doc_id": block.doc_id,
            "page": block.location.page if block.location.page is not None else block.page_id,
            "block_id": block.block_id,
            "block_type": block.block_type,
            "text_preview": block.visual_summary or block.text or _existing_caption(block),
            "image_caption": _existing_caption(block),
            "visual_summary": block.visual_summary,
            "visual_content_status": block.metadata.get("visual_content_status"),
            "requires_visual_understanding": block.metadata.get("requires_visual_understanding"),
        }.items()
        if value not in {None, ""}
    }


def _skipped_visual_result(
    block: EvidenceBlock,
    question: str,
    reason: str,
    *,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "status": "skipped",
        "tool": "visual_review",
        "block_id": block.block_id,
        "question": question,
        "answer": "",
        "reasoning_summary": "",
        "structured_result": {"skip_reason": reason, "used_vlm": False, "warnings": warnings or []},
    }


def _first_text(data: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            text = " ".join(str(item).strip() for item in value if str(item or "").strip()).strip()
        else:
            text = str(value or "").strip()
        if text:
            return text
    return ""


def _compact_visual_response(response: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in {
            "answer": response.get("answer"),
            "visual_summary": response.get("visual_summary"),
            "caption": response.get("caption"),
            "key_text": response.get("key_text"),
            "data_points": response.get("data_points"),
            "confidence": response.get("confidence"),
            "support_status": response.get("support_status"),
        }.items()
        if value not in {None, ""}
    }


def _cache_key(image_path: Path | str, *, model: str) -> str:
    if isinstance(image_path, str):
        identity = image_path
    else:
        identity = hashlib.sha256(image_path.read_bytes()).hexdigest()
    return hashlib.sha256(f"{VISUAL_SUMMARY_PROMPT_VERSION}|{model}|{identity}".encode("utf-8")).hexdigest()


def _client_model(client: Any) -> str:
    config = getattr(client, "config", None)
    return str(getattr(config, "model", "") or "unknown")


def _load_cache(path: Path) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return cache
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        key = str(row.get("cache_key") or "")
        response = row.get("response")
        if key and isinstance(response, dict):
            cache[key] = response
    return cache


def _write_cache(path: Path, cache: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        json.dumps({"cache_key": key, "response": value}, ensure_ascii=False)
        for key, value in sorted(cache.items())
    ]
    path.write_text("\n".join(rows) + ("\n" if rows else ""), encoding="utf-8")

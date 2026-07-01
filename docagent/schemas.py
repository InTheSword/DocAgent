from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


VALID_ANSWER_TYPES = {
    "extractive",
    "numeric",
    "visual",
    "boolean",
    "choice",
    "refusal",
    "summary",
}

VALID_BLOCK_TYPES = {
    "text",
    "table",
    "image",
    "figure",
    "visual_summary",
    "page",
}

RETRIEVAL_METADATA_TEXT_KEYS = (
    "table_caption",
    "table_footnote",
    "caption",
    "image_caption",
    "chart_caption",
    "chart_footnote",
    "nearby_text",
)


def _clean_retrieval_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(part for item in value if (part := _clean_retrieval_value(item))).strip()
    if isinstance(value, dict):
        return " ".join(part for item in value.values() if (part := _clean_retrieval_value(item))).strip()
    return re.sub(r"\s+", " ", str(value)).strip()


def _unique_retrieval_parts(parts: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        text = _clean_retrieval_value(part)
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
    return result


@dataclass
class EvidenceLocation:
    page: int | None = None
    block_id: str | None = None
    table_id: str | None = None
    image_id: str | None = None
    bbox: list[float] | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "EvidenceLocation":
        if not data:
            return cls()
        return cls(
            page=data.get("page"),
            block_id=data.get("block_id"),
            table_id=data.get("table_id"),
            image_id=data.get("image_id"),
            bbox=data.get("bbox"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "page": self.page,
                "block_id": self.block_id,
                "table_id": self.table_id,
                "image_id": self.image_id,
                "bbox": self.bbox,
            }.items()
            if value is not None
        }


@dataclass
class EvidenceBlock:
    doc_id: str
    block_id: str
    block_type: str
    text: str = ""
    page_id: int | None = None
    table_html: str | None = None
    image_path: str | None = None
    visual_summary: str | None = None
    location: EvidenceLocation = field(default_factory=EvidenceLocation)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.block_type not in VALID_BLOCK_TYPES:
            raise ValueError(f"invalid block_type: {self.block_type}")
        if not self.block_id:
            raise ValueError("block_id is required")
        if not self.doc_id:
            raise ValueError("doc_id is required")

    @property
    def retrieval_text(self) -> str:
        if self.metadata.get("exclude_from_retrieval"):
            return ""
        parts: list[Any] = []
        section = self.metadata.get("section_title")
        if section:
            parts.append(section)
        parts.extend(self.metadata.get(key) for key in RETRIEVAL_METADATA_TEXT_KEYS)
        parts.extend([self.text or "", self.table_html or "", self.visual_summary or ""])
        return "\n".join(_unique_retrieval_parts(parts)).strip()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceBlock":
        return cls(
            doc_id=data["doc_id"],
            block_id=data["block_id"],
            block_type=data["block_type"],
            text=data.get("text") or "",
            page_id=data.get("page_id"),
            table_html=data.get("table_html"),
            image_path=data.get("image_path"),
            visual_summary=data.get("visual_summary"),
            location=EvidenceLocation.from_dict(data.get("location")),
            metadata=data.get("metadata") or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "page_id": self.page_id,
            "block_id": self.block_id,
            "block_type": self.block_type,
            "text": self.text,
            "table_html": self.table_html,
            "image_path": self.image_path,
            "visual_summary": self.visual_summary,
            "location": self.location.to_dict(),
            "metadata": self.metadata,
        }


@dataclass
class DocAgentSample:
    qid: str
    source: str
    doc_id: str
    question: str
    answer: str | list[str]
    answer_type: str
    evidence: list[EvidenceBlock]
    verifiable: bool = True
    split: str = "train"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.answer_type not in VALID_ANSWER_TYPES:
            raise ValueError(f"invalid answer_type: {self.answer_type}")
        if not self.qid:
            raise ValueError("qid is required")
        if not self.question:
            raise ValueError("question is required")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocAgentSample":
        evidence = [EvidenceBlock.from_dict(item) for item in data.get("evidence", [])]
        return cls(
            qid=data["qid"],
            source=data["source"],
            doc_id=data["doc_id"],
            question=data["question"],
            answer=data["answer"],
            answer_type=data["answer_type"],
            evidence=evidence,
            verifiable=bool(data.get("verifiable", True)),
            split=data.get("split", "train"),
            metadata=data.get("metadata") or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "qid": self.qid,
            "source": self.source,
            "doc_id": self.doc_id,
            "question": self.question,
            "answer": self.answer,
            "answer_type": self.answer_type,
            "evidence": [block.to_dict() for block in self.evidence],
            "verifiable": self.verifiable,
            "split": self.split,
            "metadata": self.metadata,
        }


@dataclass
class QAResult:
    answer: str
    evidence_location: EvidenceLocation
    evidence: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "evidence_location": self.evidence_location.to_dict(),
            "evidence": self.evidence,
            "reason": self.reason,
        }


@dataclass
class QAState:
    qid: str
    question: str
    doc_id: str | None = None
    answer_type: str | None = None
    run_id: str | None = None
    rewritten_query: str = ""
    retrieved_blocks: list[EvidenceBlock] = field(default_factory=list)
    table_results: list[dict[str, Any]] = field(default_factory=list)
    visual_results: list[dict[str, Any]] = field(default_factory=list)
    draft_answer: dict[str, Any] = field(default_factory=dict)
    generation_metadata: dict[str, Any] = field(default_factory=dict)
    parse_result: dict[str, Any] = field(default_factory=dict)
    format_check: dict[str, Any] = field(default_factory=dict)
    location_check: dict[str, Any] = field(default_factory=dict)
    repair_attempted: bool = False
    repair_result: dict[str, Any] | None = None
    final_answer: dict[str, Any] = field(default_factory=dict)
    status: str = "initialized"
    error: str | None = None
    trace: list[dict[str, Any]] = field(default_factory=list)

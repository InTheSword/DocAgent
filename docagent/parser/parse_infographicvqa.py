from __future__ import annotations

from typing import Any

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("answer") or ""))
            else:
                parts.append(str(item))
        return " ".join(part for part in parts if part.strip())
    if isinstance(value, dict):
        return str(value.get("text") or value.get("answer") or "")
    return str(value)


def convert_infographic_record(record: dict[str, Any], split: str = "train") -> DocAgentSample:
    qid = str(record.get("questionId") or record.get("qid") or record.get("id"))
    doc_id = str(record.get("image") or record.get("image_id") or record.get("doc_id") or qid)
    ocr_text = _text(record.get("ocr_text") or record.get("ocr") or record.get("context") or record.get("text"))
    image_path = record.get("image_path") or record.get("image")
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id=f"{doc_id}_image",
        block_type="image",
        text=ocr_text,
        image_path=image_path,
        location=EvidenceLocation(page=1, image_id=f"{doc_id}_image"),
        metadata={"source_record": "infographicvqa"},
    )
    return DocAgentSample(
        qid=qid,
        source="infographicvqa",
        doc_id=doc_id,
        question=str(record["question"]),
        answer=_text(record.get("answer") or record.get("answers")),
        answer_type="visual",
        evidence=[block],
        verifiable=bool(_text(record.get("answer") or record.get("answers"))),
        split=split,
    )

from __future__ import annotations

from typing import Any

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation


def _first_text(value: Any) -> str:
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


def _first_page(value: Any) -> int | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def convert_mpdocvqa_record(record: dict[str, Any], split: str = "train") -> DocAgentSample:
    qid = str(record.get("qid") or record.get("questionId") or record.get("id"))
    doc_id = str(record.get("doc_id") or record.get("document_id") or record.get("docId") or record.get("image") or qid)
    question = str(record["question"])
    answer = _first_text(record.get("answer") or record.get("answers"))
    page = _first_page(record.get("page") or record.get("answer_page") or record.get("answerPage") or record.get("page_id"))
    text = _first_text(
        record.get("ocr_text")
        or record.get("ocr")
        or record.get("context")
        or record.get("text")
        or record.get("page_text")
    )
    block = EvidenceBlock(
        doc_id=doc_id,
        page_id=page,
        block_id=f"{doc_id}_p{page or 0}_gold",
        block_type="text",
        text=text,
        location=EvidenceLocation(page=page),
        metadata={"source_record": "mp_docvqa"},
    )
    return DocAgentSample(
        qid=qid,
        source="mp_docvqa",
        doc_id=doc_id,
        question=question,
        answer=answer,
        answer_type="extractive",
        evidence=[block],
        verifiable=bool(answer),
        split=split,
    )

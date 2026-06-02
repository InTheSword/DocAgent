from __future__ import annotations

from typing import Any

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation


def convert_infographic_record(record: dict[str, Any], split: str = "train") -> DocAgentSample:
    qid = str(record.get("questionId") or record.get("qid") or record.get("id"))
    doc_id = str(record.get("image") or record.get("image_id") or record.get("doc_id") or qid)
    ocr_text = record.get("ocr_text") or record.get("text") or ""
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
        answer=record.get("answer") or record.get("answers") or "",
        answer_type="visual",
        evidence=[block],
        verifiable=bool(record.get("answer") or record.get("answers")),
        split=split,
    )


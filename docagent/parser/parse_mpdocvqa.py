from __future__ import annotations

from typing import Any

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation


def convert_mpdocvqa_record(record: dict[str, Any], split: str = "train") -> DocAgentSample:
    qid = str(record.get("qid") or record.get("questionId") or record.get("id"))
    doc_id = str(record.get("doc_id") or record.get("document_id") or record.get("image") or qid)
    question = str(record["question"])
    answer = record.get("answer") or record.get("answers") or ""
    page = record.get("page") or record.get("answer_page") or record.get("page_id")
    text = record.get("ocr_text") or record.get("text") or ""
    block = EvidenceBlock(
        doc_id=doc_id,
        page_id=int(page) if page is not None else None,
        block_id=f"{doc_id}_p{page or 0}_gold",
        block_type="text",
        text=text,
        location=EvidenceLocation(page=int(page) if page is not None else None),
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


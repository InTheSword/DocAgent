from __future__ import annotations

from typing import Any

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation


def table_to_markdown(table: list[list[Any]]) -> str:
    if not table:
        return ""
    rows = [["" if cell is None else str(cell) for cell in row] for row in table]
    header = rows[0]
    body = rows[1:]
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join(["---"] * len(header)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def convert_tatqa_question(
    context_record: dict[str, Any],
    question_record: dict[str, Any],
    split: str = "train",
) -> DocAgentSample:
    table_obj = context_record.get("table", {})
    table_uid = table_obj.get("uid") if isinstance(table_obj, dict) else None
    doc_id = str(context_record.get("uid") or context_record.get("doc_id") or table_uid or "tatqa_doc")
    qid = str(question_record.get("uid") or question_record.get("qid") or question_record.get("question"))
    table = table_obj.get("table") if isinstance(table_obj, dict) else context_record.get("table")
    table = table or []
    paragraphs = context_record.get("paragraphs") or []
    paragraph_text = "\n".join(
        str(item.get("text") if isinstance(item, dict) else item) for item in paragraphs
    )
    table_text = table_to_markdown(table) if isinstance(table, list) else str(table)
    answer = question_record.get("answer") or question_record.get("answer_from") or ""
    answer_type = "numeric" if question_record.get("derivation") else "extractive"
    table_block = EvidenceBlock(
        doc_id=doc_id,
        block_id=f"{doc_id}_table",
        block_type="table",
        text=table_text,
        table_html=None,
        location=EvidenceLocation(table_id=f"{doc_id}_table"),
        metadata={"source_record": "tatqa"},
    )
    text_block = EvidenceBlock(
        doc_id=doc_id,
        block_id=f"{doc_id}_paragraphs",
        block_type="text",
        text=paragraph_text,
        location=EvidenceLocation(block_id=f"{doc_id}_paragraphs"),
        metadata={"source_record": "tatqa"},
    )
    return DocAgentSample(
        qid=qid,
        source="tatqa",
        doc_id=doc_id,
        question=str(question_record["question"]),
        answer=answer,
        answer_type=answer_type,
        evidence=[table_block, text_block],
        verifiable=bool(answer),
        split=split,
        metadata={
            "derivation": question_record.get("derivation"),
            "scale": question_record.get("scale"),
            "answer_from": question_record.get("answer_from"),
            "gold_block_ids": _gold_block_ids(doc_id, question_record.get("answer_from")),
        },
    )


def _gold_block_ids(doc_id: str, answer_from: str | None) -> list[str]:
    if answer_from == "table":
        return [f"{doc_id}_table"]
    if answer_from == "text":
        return [f"{doc_id}_paragraphs"]
    return [f"{doc_id}_table", f"{doc_id}_paragraphs"]

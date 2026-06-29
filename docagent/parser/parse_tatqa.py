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


def table_to_html(table: list[list[Any]]) -> str:
    rows = [["" if cell is None else str(cell) for cell in row] for row in table]
    if not rows:
        return ""
    html_rows = []
    for row_index, row in enumerate(rows):
        tag = "th" if row_index == 0 else "td"
        cells = "".join(f"<{tag}>{_escape_html(cell)}</{tag}>" for cell in row)
        html_rows.append(f"<tr>{cells}</tr>")
    return "<table>" + "".join(html_rows) + "</table>"


def _escape_html(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


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
    table_text = table_to_markdown(table) if isinstance(table, list) else str(table)
    answer = question_record.get("answer") or question_record.get("answer_from") or ""
    raw_answer_type = str(question_record.get("answer_type") or "")
    answer_type = "numeric" if question_record.get("derivation") or raw_answer_type in {"arithmetic", "count"} else "extractive"
    table_block = EvidenceBlock(
        doc_id=doc_id,
        block_id=f"{doc_id}_table",
        block_type="table",
        text=table_text,
        table_html=table_to_html(table) if isinstance(table, list) else None,
        page_id=1,
        location=EvidenceLocation(page=1, block_id=f"{doc_id}_table", table_id=f"{doc_id}_table"),
        metadata={"source_record": "tatqa", "table_uid": table_uid},
    )
    paragraph_blocks = _paragraph_blocks(doc_id, paragraphs)
    return DocAgentSample(
        qid=qid,
        source="tatqa",
        doc_id=doc_id,
        question=str(question_record["question"]),
        answer=answer,
        answer_type=answer_type,
        evidence=[table_block, *paragraph_blocks],
        verifiable=bool(answer),
        split=split,
        metadata={
            "derivation": question_record.get("derivation"),
            "scale": question_record.get("scale"),
            "raw_answer_type": raw_answer_type,
            "answer_from": question_record.get("answer_from"),
            "gold_block_ids": _gold_block_ids(
                doc_id,
                question_record.get("answer_from"),
                question_record.get("rel_paragraphs"),
                paragraph_blocks,
            ),
        },
    )


def _paragraph_blocks(doc_id: str, paragraphs: list[Any]) -> list[EvidenceBlock]:
    blocks: list[EvidenceBlock] = []
    for index, item in enumerate(paragraphs, start=1):
        if isinstance(item, dict):
            order = item.get("order") or index
            text = str(item.get("text") or "")
            paragraph_uid = item.get("uid")
        else:
            order = index
            text = str(item)
            paragraph_uid = None
        block_id = f"{doc_id}_paragraph_{order}"
        blocks.append(
            EvidenceBlock(
                doc_id=doc_id,
                block_id=block_id,
                block_type="text",
                text=text,
                page_id=1,
                location=EvidenceLocation(page=1, block_id=block_id),
                metadata={
                    "source_record": "tatqa",
                    "paragraph_uid": paragraph_uid,
                    "paragraph_order": order,
                },
            )
        )
    return blocks


def _gold_block_ids(
    doc_id: str,
    answer_from: str | None,
    rel_paragraphs: list[Any] | None,
    paragraph_blocks: list[EvidenceBlock],
) -> list[str]:
    paragraph_ids = [block.block_id for block in paragraph_blocks]
    rel_ids = []
    for value in rel_paragraphs or []:
        rel_ids.append(f"{doc_id}_paragraph_{value}")
    text_ids = rel_ids or paragraph_ids
    if answer_from == "table":
        return [f"{doc_id}_table"]
    if answer_from == "text":
        return text_ids
    return [f"{doc_id}_table", *text_ids]

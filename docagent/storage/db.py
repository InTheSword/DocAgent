from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from docagent.schemas import EvidenceBlock, QAState


SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def save_evidence_blocks(conn: sqlite3.Connection, blocks: list[EvidenceBlock]) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO evidence_blocks(block_id, doc_id, page_id, block_type, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (block.block_id, block.doc_id, block.page_id, block.block_type, json.dumps(block.to_dict(), ensure_ascii=False))
            for block in blocks
        ],
    )
    conn.commit()


def save_qa_state(conn: sqlite3.Connection, state: QAState) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO qa_logs(qid, question, answer_json) VALUES (?, ?, ?)",
        (state.qid, state.question, json.dumps(state.final_answer, ensure_ascii=False)),
    )
    conn.executemany(
        "INSERT INTO tool_traces(qid, step, payload_json) VALUES (?, ?, ?)",
        [(state.qid, item.get("step", "unknown"), json.dumps(item, ensure_ascii=False)) for item in state.trace],
    )
    conn.commit()


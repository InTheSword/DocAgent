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
    _migrate_schema(conn)
    return conn


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    if column not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _migrate_schema(conn: sqlite3.Connection) -> None:
    for column, definition in {
        "sha256": "TEXT",
        "original_name": "TEXT",
        "mime_type": "TEXT",
        "file_size": "INTEGER",
        "page_count": "INTEGER",
        "parser_backend": "TEXT",
        "parse_status": "TEXT DEFAULT 'registered'",
        "index_status": "TEXT DEFAULT 'not_started'",
        "updated_at": "TEXT",
    }.items():
        _add_column(conn, "documents", column, definition)
    for column, definition in {
        "text": "TEXT",
        "table_html": "TEXT",
        "image_path": "TEXT",
        "bbox_json": "TEXT",
        "metadata_json": "TEXT",
    }.items():
        _add_column(conn, "evidence_blocks", column, definition)
    conn.commit()


def save_evidence_blocks(conn: sqlite3.Connection, blocks: list[EvidenceBlock]) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO evidence_blocks(
          block_id, doc_id, page_id, block_type, text, table_html, image_path,
          bbox_json, metadata_json, payload_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                block.block_id,
                block.doc_id,
                block.page_id,
                block.block_type,
                block.text,
                block.table_html,
                block.image_path,
                json.dumps(block.location.bbox, ensure_ascii=False) if block.location.bbox else None,
                json.dumps(block.metadata, ensure_ascii=False),
                json.dumps(block.to_dict(), ensure_ascii=False),
            )
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

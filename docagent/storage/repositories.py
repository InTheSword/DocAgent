from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any

from docagent.ingestion.document_registry import DocumentRecord
from docagent.schemas import EvidenceBlock


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DocumentRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def upsert_document(self, record: DocumentRecord) -> None:
        now = utc_now_iso()
        self.conn.execute(
            """
            INSERT INTO documents(
              doc_id, source, file_path, sha256, original_name, mime_type, file_size,
              page_count, parser_backend, parse_status, index_status, updated_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(doc_id) DO UPDATE SET
              source = excluded.source,
              file_path = excluded.file_path,
              sha256 = excluded.sha256,
              original_name = excluded.original_name,
              mime_type = excluded.mime_type,
              file_size = excluded.file_size,
              page_count = excluded.page_count,
              parser_backend = excluded.parser_backend,
              parse_status = excluded.parse_status,
              index_status = excluded.index_status,
              updated_at = excluded.updated_at
            """,
            (
                record.doc_id,
                record.original_name,
                record.file_path,
                record.sha256,
                record.original_name,
                record.mime_type,
                record.file_size,
                record.page_count,
                record.parser_backend,
                record.parse_status,
                record.index_status,
                now,
                now,
            ),
        )
        self.conn.commit()

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT doc_id, sha256, original_name, mime_type, file_size, file_path,
                   page_count, parser_backend, parse_status, index_status, created_at, updated_at
            FROM documents
            WHERE doc_id = ?
            """,
            (doc_id,),
        ).fetchone()
        if row is None:
            return None
        keys = [
            "doc_id",
            "sha256",
            "original_name",
            "mime_type",
            "file_size",
            "file_path",
            "page_count",
            "parser_backend",
            "parse_status",
            "index_status",
            "created_at",
            "updated_at",
        ]
        return dict(zip(keys, row))

    def list_documents(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT doc_id, original_name, file_path, parse_status, index_status, created_at, updated_at
            FROM documents
            ORDER BY created_at DESC
            """
        ).fetchall()
        keys = ["doc_id", "original_name", "file_path", "parse_status", "index_status", "created_at", "updated_at"]
        return [dict(zip(keys, row)) for row in rows]

    def save_evidence_blocks(self, blocks: list[EvidenceBlock]) -> None:
        self.conn.executemany(
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
        self.conn.commit()

    def load_evidence_blocks(self, doc_id: str, *, include_page_blocks: bool = False) -> list[EvidenceBlock]:
        rows = self.conn.execute(
            """
            SELECT payload_json
            FROM evidence_blocks
            WHERE doc_id = ?
            ORDER BY page_id ASC, block_id ASC
            """,
            (doc_id,),
        ).fetchall()
        blocks = [EvidenceBlock.from_dict(json.loads(row[0])) for row in rows]
        if not include_page_blocks:
            blocks = [block for block in blocks if block.block_type != "page"]
        return blocks

    def save_index_metadata(
        self,
        *,
        doc_id: str,
        index_type: str,
        model_id: str | None,
        artifact_path: str,
        metadata: dict[str, Any],
    ) -> None:
        self.conn.execute(
            """
            INSERT OR REPLACE INTO document_indexes(doc_id, index_type, model_id, artifact_path, metadata_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (doc_id, index_type, model_id or "", artifact_path, json.dumps(metadata, ensure_ascii=False), utc_now_iso()),
        )
        self.conn.commit()

    def list_indexes(self, doc_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT doc_id, index_type, model_id, artifact_path, metadata_json, created_at
            FROM document_indexes
            WHERE doc_id = ?
            ORDER BY index_type, model_id
            """,
            (doc_id,),
        ).fetchall()
        result = []
        for row in rows:
            result.append(
                {
                    "doc_id": row[0],
                    "index_type": row[1],
                    "model_id": row[2],
                    "artifact_path": row[3],
                    "metadata": json.loads(row[4] or "{}"),
                    "created_at": row[5],
                }
            )
        return result


class TraceRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create_run(
        self,
        *,
        run_id: str | None = None,
        qid: str | None,
        doc_id: str | None,
        question: str,
        policy_mode: str,
        status: str = "running",
    ) -> str:
        run_id = run_id or str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO qa_runs(run_id, qid, doc_id, question, policy_mode, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, qid, doc_id, question, policy_mode, status, utc_now_iso()),
        )
        self.conn.commit()
        return run_id

    def append_trace(
        self,
        *,
        run_id: str,
        step_index: int,
        node_name: str,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        success: bool = True,
        latency_ms: float | None = None,
        error: str | None = None,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO tool_traces(
              run_id, step_index, node_name, input_summary_json, output_summary_json,
              success, latency_ms, error, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                step_index,
                node_name,
                json.dumps(input_summary or {}, ensure_ascii=False),
                json.dumps(output_summary or {}, ensure_ascii=False),
                1 if success else 0,
                latency_ms,
                error,
                utc_now_iso(),
            ),
        )
        self.conn.commit()

    def complete_run(self, *, run_id: str, final_answer: dict[str, Any], status: str = "completed") -> None:
        self.conn.execute(
            """
            UPDATE qa_runs
            SET status = ?, final_answer_json = ?, completed_at = ?
            WHERE run_id = ?
            """,
            (status, json.dumps(final_answer, ensure_ascii=False), utc_now_iso(), run_id),
        )
        self.conn.commit()

    def fail_run(self, *, run_id: str, error: str) -> None:
        self.conn.execute(
            """
            UPDATE qa_runs
            SET status = 'failed', error = ?, completed_at = ?
            WHERE run_id = ?
            """,
            (error, utc_now_iso(), run_id),
        )
        self.conn.commit()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            """
            SELECT run_id, qid, doc_id, question, policy_mode, status, final_answer_json, error, created_at, completed_at
            FROM qa_runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        keys = [
            "run_id",
            "qid",
            "doc_id",
            "question",
            "policy_mode",
            "status",
            "final_answer_json",
            "error",
            "created_at",
            "completed_at",
        ]
        result = dict(zip(keys, row))
        if result.get("final_answer_json"):
            result["final_answer"] = json.loads(result["final_answer_json"])
        return result

    def list_traces(self, run_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT step_index, node_name, input_summary_json, output_summary_json, success, latency_ms, error, created_at
            FROM tool_traces
            WHERE run_id = ?
            ORDER BY step_index ASC, id ASC
            """,
            (run_id,),
        ).fetchall()
        traces = []
        for row in rows:
            traces.append(
                {
                    "step_index": row[0],
                    "node_name": row[1],
                    "input_summary": json.loads(row[2] or "{}"),
                    "output_summary": json.loads(row[3] or "{}"),
                    "success": bool(row[4]),
                    "latency_ms": row[5],
                    "error": row[6],
                    "created_at": row[7],
                }
            )
        return traces

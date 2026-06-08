from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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

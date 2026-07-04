from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.build_phase5i_clean_answer_quality_cases import build_clean_answer_quality_cases


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")


def _case(case_id: str, *, answer_keywords: list[str], evidence_keywords: list[str], page: int = 1) -> dict:
    return {
        "case_id": case_id,
        "user_request": "Which financial year is mentioned?",
        "request_form": "interrogative",
        "expected_task_type": "local_fact_qa",
        "expected_answer_type": "extractive",
        "answerable": True,
        "unsupported_ok": False,
        "expected_page": page,
        "expected_evidence_keywords": evidence_keywords,
        "expected_answer_keywords": answer_keywords,
        "forbidden_answer_keywords": [],
    }


def _db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            """
            create table evidence_blocks (
              block_id text,
              doc_id text,
              page_id integer,
              block_type text,
              text text,
              table_html text,
              image_path text,
              bbox_json text,
              metadata_json text,
              payload_json text,
              created_at text
            )
            """
        )
        conn.execute(
            """
            insert into evidence_blocks
            (block_id, doc_id, page_id, block_type, text, table_html, payload_json)
            values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc1_p001_b0001",
                "doc1",
                1,
                "text",
                "unclaimed dividend for financial year 2000-01 transferred to iepf",
                None,
                None,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_build_clean_answer_quality_cases_accepts_supported_case(tmp_path: Path) -> None:
    db_path = tmp_path / "docagent.db"
    _db(db_path)
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(cases_path, [_case("supported", answer_keywords=["2000-01"], evidence_keywords=["unclaimed dividend"])])

    summary = build_clean_answer_quality_cases(
        candidate_cases_path=cases_path,
        db_path=db_path,
        doc_id="doc1",
        output_dir=tmp_path / "out",
        run_id="clean_cases",
    )
    accepted = json.loads((tmp_path / "out" / "accepted_answer_quality_cases.jsonl").read_text(encoding="utf-8").strip())

    assert summary["status"] == "success"
    assert summary["accepted_case_count"] == 1
    assert summary["rejected_case_count"] == 0
    assert accepted["case_id"] == "supported"


def test_build_clean_answer_quality_cases_rejects_weak_or_missing_gold(tmp_path: Path) -> None:
    db_path = tmp_path / "docagent.db"
    _db(db_path)
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            _case("weak_keyword", answer_keywords=["date"], evidence_keywords=["unclaimed dividend"]),
            _case("missing_answer", answer_keywords=["1993-94"], evidence_keywords=["unclaimed dividend"]),
        ],
    )

    summary = build_clean_answer_quality_cases(
        candidate_cases_path=cases_path,
        db_path=db_path,
        doc_id="doc1",
        output_dir=tmp_path / "out",
        run_id="clean_cases",
    )
    rejected = [
        json.loads(line)
        for line in (tmp_path / "out" / "rejected_cases.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    assert summary["accepted_case_count"] == 0
    assert summary["rejection_reason_counts"]["answer_keywords_are_type_markers_not_answer_values"] == 1
    assert summary["rejection_reason_counts"]["expected_page_missing_answer_keywords"] >= 1
    assert {row["case_id"] for row in rejected} == {"weak_keyword", "missing_answer"}


def test_build_clean_answer_quality_cases_blocks_missing_db(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(cases_path, [_case("supported", answer_keywords=["2000-01"], evidence_keywords=["unclaimed dividend"])])

    summary = build_clean_answer_quality_cases(
        candidate_cases_path=cases_path,
        db_path=tmp_path / "missing.db",
        doc_id="doc1",
        output_dir=tmp_path / "out",
        run_id="clean_cases",
    )

    assert summary["status"] == "blocked"
    assert summary["blocker"]["type"] == "db_path_not_found"
    assert summary["accepted_case_count"] == 0

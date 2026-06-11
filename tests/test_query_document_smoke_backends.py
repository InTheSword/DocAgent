from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_query_document_hash_dense_keyword_reranker(tmp_path: Path) -> None:
    db_path = tmp_path / "docagent.db"
    document_root = tmp_path / "documents"
    fixture = tmp_path / "fixture"
    input_jsonl = tmp_path / "input.jsonl"
    record = {
        "qid": "q1",
        "source": "mock",
        "doc_id": "doc1",
        "question": "What is the invoice date?",
        "answer": "March 12, 2020",
        "answer_type": "extractive",
        "evidence": [
            {
                "doc_id": "doc1",
                "page_id": 1,
                "block_id": "doc1_p1_ocr",
                "block_type": "text",
                "text": "Invoice Date: March 12, 2020",
                "location": {"page": 1, "block_id": "doc1_p1_ocr"},
                "metadata": {},
            }
        ],
        "metadata": {"gold_block_ids": ["doc1_p1_ocr"]},
    }
    input_jsonl.write_text(json.dumps(record) + "\n", encoding="utf-8")

    fixture_result = subprocess.run(
        [
            sys.executable,
            "scripts/build_phase2_parse_existing_fixture.py",
            "--input",
            str(input_jsonl),
            "--output-dir",
            str(fixture),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    fixture_payload = json.loads(fixture_result.stdout)
    ingest_result = subprocess.run(
        [
            sys.executable,
            "scripts/ingest_document.py",
            "--file",
            fixture_payload["source_file"],
            "--parser-mode",
            "parse_existing",
            "--mineru-output-dir",
            fixture_payload["mineru_output_dir"],
            "--document-root",
            str(document_root),
            "--sqlite-path",
            str(db_path),
            "--force-parse",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    doc_id = json.loads(ingest_result.stdout)["doc_id"]
    query_result = subprocess.run(
        [
            sys.executable,
            "scripts/query_document.py",
            "--doc-id",
            doc_id,
            "--question",
            "What is the invoice date?",
            "--retriever",
            "hybrid_rerank",
            "--policy-mode",
            "heuristic",
            "--dense-backend",
            "hash",
            "--build-index-if-missing",
            "--reranker-backend",
            "keyword",
            "--document-root",
            str(document_root),
            "--sqlite-path",
            str(db_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(query_result.stdout)

    assert payload["dense_backend"] == "hash"
    assert payload["reranker_backend"] == "keyword"
    assert payload["final_answer"]["answer"] == "March 12, 2020"
    assert payload["trace"][0]["retriever_mode"] == "hybrid_rerank"

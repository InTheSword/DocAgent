from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _write_eval_jsonl(path: Path) -> None:
    record = {
        "qid": "q1",
        "source": "mock",
        "doc_id": "doc1",
        "question": "What is the full form of BSE?",
        "answer": "Bombay Stock Exchange",
        "answer_type": "extractive",
        "evidence": [
            {
                "doc_id": "doc1",
                "page_id": 1,
                "block_id": "wrong",
                "block_type": "text",
                "text": "the business is in a full state of readiness",
                "location": {"page": 1, "block_id": "wrong"},
                "metadata": {},
            },
            {
                "doc_id": "doc1",
                "page_id": 24,
                "block_id": "right",
                "block_type": "text",
                "text": "bombay stock exchange (bse)",
                "location": {"page": 24, "block_id": "right"},
                "metadata": {},
            },
        ],
        "metadata": {"gold_block_ids": ["right"]},
    }
    path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")


def test_eval_retrieval_phase2_hash_keyword(tmp_path: Path) -> None:
    input_path = tmp_path / "eval.jsonl"
    output_path = tmp_path / "retrieval.json"
    _write_eval_jsonl(input_path)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/eval_retrieval_phase2.py",
            "--input",
            str(input_path),
            "--modes",
            "bm25,hybrid_rerank",
            "--dense-backend",
            "hash",
            "--reranker-backend",
            "keyword",
            "--output",
            str(output_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(completed.stdout)

    assert summary["dense_backend"] == "hash"
    assert summary["reranker_backend"] == "keyword"
    assert summary["modes"]["hybrid_rerank"]["recall_at_1"] == 1.0


def test_eval_workflow_phase2_hash_keyword(tmp_path: Path) -> None:
    input_path = tmp_path / "eval.jsonl"
    output_path = tmp_path / "workflow.jsonl"
    summary_path = tmp_path / "workflow_summary.json"
    db_path = tmp_path / "workflow.sqlite"
    _write_eval_jsonl(input_path)

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/eval_workflow_phase2.py",
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--summary-output",
            str(summary_path),
            "--retriever",
            "hybrid_rerank",
            "--policy-mode",
            "heuristic",
            "--dense-backend",
            "hash",
            "--reranker-backend",
            "keyword",
            "--sqlite-path",
            str(db_path),
            "--limit",
            "1",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(completed.stdout)

    assert summary["dense_backend"] == "hash"
    assert summary["reranker_backend"] == "keyword"
    assert summary["workflow_success_rate"] == 1.0
    assert summary["location_accuracy"] == 1.0

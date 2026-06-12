from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _model_dir(path: Path) -> None:
    path.mkdir(parents=True)
    (path / "config.json").write_text("{}", encoding="utf-8")
    (path / "tokenizer_config.json").write_text("{}", encoding="utf-8")


def _benchmark(path: Path) -> None:
    record = {
        "qid": "q1",
        "source": "unit",
        "doc_id": "doc1",
        "question": "What is shown?",
        "answer": "Revenue",
        "answer_type": "extractive",
        "evidence": [
            {
                "doc_id": "doc1",
                "block_id": "b1",
                "block_type": "text",
                "text": "Revenue",
                "location": {"page": 1, "block_id": "b1"},
                "metadata": {},
            }
        ],
    }
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")


def test_preflight_writes_json_when_resources_are_missing(tmp_path: Path) -> None:
    output = tmp_path / "phase2.json"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/preflight_phase2.py",
            "--qwen-model-path",
            str(tmp_path / "missing-qwen"),
            "--bge-model-path",
            str(tmp_path / "missing-bge"),
            "--reranker-model-path",
            str(tmp_path / "missing-reranker"),
            "--benchmark-artifact",
            str(tmp_path / "missing.jsonl"),
            "--dense-index-root",
            str(tmp_path / "missing-documents"),
            "--mineru-output-root",
            str(tmp_path / "missing-documents"),
            "--sqlite-path",
            str(tmp_path / "missing.sqlite"),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    stdout_payload = json.loads(completed.stdout)
    assert payload["status"] == "success"
    assert stdout_payload["command"] == "phase2_preflight"
    assert payload["models"]["bge_m3"]["status"] == "missing"
    assert "model:bge_m3" in payload["summary"]["missing_required"]
    assert payload["artifacts"]["dense_index"]["status"] == "optional_missing"


def test_preflight_detects_lightweight_files_and_artifacts(tmp_path: Path) -> None:
    qwen = tmp_path / "models" / "Qwen3-1.7B"
    bge = tmp_path / "models" / "bge-m3"
    reranker = tmp_path / "models" / "bge-reranker-v2-m3"
    for model_path in (qwen, bge, reranker):
        _model_dir(model_path)

    benchmark = tmp_path / "data" / "benchmark" / "eval.jsonl"
    _benchmark(benchmark)

    document_root = tmp_path / "data" / "documents"
    index_dir = document_root / "doc1"
    index_dir.mkdir(parents=True)
    embeddings = index_dir / "dense_embeddings.npy"
    embeddings.write_bytes(b"placeholder")
    (index_dir / "index_metadata.json").write_text(
        json.dumps(
            {
                "model_id": str(bge),
                "backend": "faiss",
                "embeddings_path": str(embeddings),
                "faiss_path": None,
            }
        ),
        encoding="utf-8",
    )
    mineru_dir = document_root / "doc1" / "mineru"
    mineru_dir.mkdir()
    (mineru_dir / "sample_content_list.json").write_text("[]", encoding="utf-8")

    output = tmp_path / "phase2.json"
    subprocess.run(
        [
            sys.executable,
            "scripts/preflight_phase2.py",
            "--qwen-model-path",
            str(qwen),
            "--bge-model-path",
            str(bge),
            "--reranker-model-path",
            str(reranker),
            "--benchmark-artifact",
            str(benchmark),
            "--dense-index-root",
            str(document_root),
            "--mineru-output-root",
            str(document_root),
            "--sqlite-path",
            str(tmp_path / "missing.sqlite"),
            "--output",
            str(output),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["models"]["qwen3"]["status"] == "ready"
    assert payload["models"]["bge_m3"]["status"] == "ready"
    assert payload["models"]["bge_reranker_v2_m3"]["status"] == "ready"
    assert payload["artifacts"]["benchmark_evidence"]["status"] == "ready"
    assert payload["artifacts"]["dense_index"]["status"] == "ready"
    assert payload["artifacts"]["real_mineru_output"]["status"] == "ready"

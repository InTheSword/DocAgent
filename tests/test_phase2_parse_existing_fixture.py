from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_build_phase2_parse_existing_fixture_from_docagent_jsonl(tmp_path: Path) -> None:
    input_path = tmp_path / "sample.jsonl"
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
                "metadata": {"source": "test"},
            }
        ],
        "split": "dev",
        "metadata": {"gold_block_ids": ["doc1_p1_ocr"]},
    }
    input_path.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    output_dir = tmp_path / "fixture"

    completed = subprocess.run(
        [
            sys.executable,
            "scripts/build_phase2_parse_existing_fixture.py",
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    summary = json.loads(completed.stdout)
    content = json.loads((output_dir / "mineru" / "sample_content_list.json").read_text(encoding="utf-8"))

    assert summary["qid"] == "q1"
    assert Path(summary["source_file"]).is_file()
    assert content[0]["type"] == "text"
    assert content[0]["text"] == "Invoice Date: March 12, 2020"

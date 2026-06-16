from __future__ import annotations

from argparse import Namespace
import subprocess
import sys
from pathlib import Path

import pytest

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import write_jsonl
from scripts.run_phase3_server_acceptance import AcceptanceRunner


def _block(block_id: str) -> dict:
    return EvidenceBlock(
        doc_id="doc1",
        page_id=1,
        block_id=block_id,
        block_type="text",
        text="Invoice Date March 12 2020",
        location=EvidenceLocation(page=1, block_id=block_id),
    ).to_dict()


def _server_contract_fixture(tmp_path: Path) -> tuple[Path, Path]:
    document_dir = tmp_path / "documents" / "doc1"
    document_dir.mkdir(parents=True)
    write_jsonl(document_dir / "evidence_blocks.jsonl", [_block("b1")])
    (document_dir / "ingestion_report.json").write_text("{}", encoding="utf-8")
    (document_dir / "structure_quality.json").write_text("{}", encoding="utf-8")
    qa_path = tmp_path / "scenario_qa.jsonl"
    write_jsonl(
        qa_path,
        [
            {
                "qid": f"q{index}",
                "doc_id": "doc1",
                "question": "What is the invoice date?",
                "answers": ["March 12 2020"],
                "answer_type": "text",
                "source_qa_role": "globocan_scenario_acceptance",
                "gold_pages": [1],
                "gold_block_ids": ["b1"],
                "verified": True,
            }
            for index in range(8)
        ],
    )
    return document_dir, qa_path


@pytest.mark.parametrize(
    ("script", "expected_flag"),
    [
        ("scripts/run_phase3_focused_eval.py", "--retrieval-only"),
        ("scripts/build_sft_dataset.py", "--preserve-evidence-order"),
        ("scripts/build_grpo_dataset.py", "--preserve-evidence-order"),
    ],
)
def test_modified_phase3_cli_help_starts(script: str, expected_flag: str) -> None:
    result = subprocess.run(
        [sys.executable, script, "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert expected_flag in result.stdout


def test_phase3_server_acceptance_cli_help_starts() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_phase3_server_acceptance.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--stage" in result.stdout
    assert "real-document-regression" in result.stdout


def test_real_document_builder_cli_help_starts() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/build_real_document_benchmark.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--document-dir" in result.stdout
    assert "--qa-path" in result.stdout


def test_server_globocan_contract_summary_accepts_scenario_regression(tmp_path: Path) -> None:
    document_dir, qa_path = _server_contract_fixture(tmp_path)
    args = Namespace(
        output_root=str(tmp_path / "outputs"),
        log_dir=str(tmp_path / "logs"),
        globocan_document_dir=str(document_dir),
        globocan_qa_path=str(qa_path),
    )

    result = AcceptanceRunner(args).build_globocan_contract()

    assert result["status"] == "ready"
    assert result["evaluation_scope"] == "scenario_regression"
    assert result["formal_benchmark"] is False
    assert result["primary_benchmark"] is False
    assert result["source_qa_role"] == "globocan_scenario_acceptance"
    assert result["verified_qa_count"] == 8
    assert result["corpus_is_query_independent"] is True
    assert result["gold_block_coverage"]["coverage_rate"] == 1.0

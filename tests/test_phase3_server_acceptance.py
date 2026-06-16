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


def test_server_real_document_regression_passes_manifest_and_runs_full_chain(tmp_path: Path) -> None:
    args = Namespace(
        output_root=str(tmp_path / "outputs"),
        log_dir=str(tmp_path / "logs"),
        top_k=5,
        bge_model_path="/models/bge",
        reranker_model_path="/models/reranker",
        base_model_path="/models/qwen",
        sft_adapter_path="outputs/checkpoints/sft",
        grpo_adapter_path="outputs/checkpoints/grpo",
        retrieval_device="cuda:1",
        qwen_device="cuda:0",
    )
    runner = AcceptanceRunner(args)
    commands: dict[str, list[str]] = {}

    def fake_contract() -> dict:
        return {
            "status": "ready",
            "qa": "outputs/contracts/globocan/qa.jsonl",
            "corpus": "outputs/contracts/globocan/corpus.jsonl",
            "manifest": "outputs/contracts/globocan/manifest.json",
        }

    def fake_run_command(name: str, command: list[str], *, allow_failure: bool = False) -> dict:
        commands[name] = command
        if name == "globocan_real_document_retrieval":
            summary_path = runner.output_root / "focused_eval" / "globocan-real-document-retrieval" / "summary.json"
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            summary_path.write_text(
                '{"evaluation_scope":"scenario_regression","formal_benchmark":false,'
                '"retrieval":{"comparison":{}},"answer_policy":{"comparison":{}}}',
                encoding="utf-8",
            )
        return {"status": "success", "exit_code": 0, "log": "log.txt"}

    runner.build_globocan_contract = fake_contract  # type: ignore[method-assign]
    runner.run_command = fake_run_command  # type: ignore[method-assign]

    result = runner.real_document_regression()

    command = commands["globocan_real_document_retrieval"]
    assert "--benchmark-manifest" in command
    assert "outputs/contracts/globocan/manifest.json" in command
    assert "--retrieval-only" not in command
    assert result["evaluation_scope"] == "scenario_regression"
    assert result["formal_benchmark"] is False

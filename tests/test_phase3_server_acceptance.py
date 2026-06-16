from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


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

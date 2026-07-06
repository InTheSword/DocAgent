from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_cli(*args: str) -> dict:
    cli_args = list(args)
    if "--execution-profile" not in cli_args:
        cli_args = ["--execution-profile", "self_test", *cli_args]
    completed = subprocess.run(
        [sys.executable, "scripts/docagent_cli.py", *cli_args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    output = completed.stdout.strip()
    assert output.startswith("{")
    assert output.endswith("}")
    return json.loads(output)


def test_cli_document_summary_dispatch_writes_artifacts(tmp_path: Path) -> None:
    source = tmp_path / "summary_source.txt"
    source.write_text(
        "DocAgent is a complex document question answering MVP.\n"
        "It converts parsed document content into EvidenceBlock records.\n"
        "The system supports routing, deterministic tools, citations, JSON artifacts, and traces.\n"
        "The current milestone implements a document summary tool based on textual evidence blocks.\n",
        encoding="utf-8",
    )

    payload = _run_cli(
        "--db-path",
        str(tmp_path / "docagent.db"),
        "--document-root",
        str(tmp_path / "documents"),
        "--file",
        str(source),
        "--question",
        "总结这份文档",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "document_summary"
    assert payload["router_plan"]["task_type"] == "document_summary"
    assert payload["router_plan"]["selected_tools"] == ["document_summary"]
    assert payload["tools_used"] == ["document_summary"]
    assert payload["structured_result"]["status"] == "completed"
    assert payload["summary"]["key_points"]
    assert payload["summary"]["page_summaries"]
    assert payload["citations"]
    for name in ("result.json", "summary.json", "router_plan.json", "trace.json"):
        assert Path(payload["artifact_dir"], name).is_file()

    summary_artifact = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary_artifact["summary"]["key_points"]
    assert summary_artifact["trace"]["used_llm"] is False
    assert summary_artifact["used_external_api"] is False
    assert summary_artifact["used_vlm"] is False
    assert summary_artifact["used_training"] is False


def test_cli_summary_no_longer_returns_unsupported(tmp_path: Path) -> None:
    source = tmp_path / "summary_source.txt"
    source.write_text(
        "Project memo\n"
        "DocAgent now has a deterministic document summary path with citations.\n",
        encoding="utf-8",
    )

    payload = _run_cli(
        "--db-path",
        str(tmp_path / "docagent.db"),
        "--document-root",
        str(tmp_path / "documents"),
        "--file",
        str(source),
        "--question",
        "Summarize this document.",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["task_type"] == "document_summary"
    assert payload["status"] == "success"
    assert payload["error"] == {}
    assert "document_summary_not_implemented" not in payload["warnings"]
    assert payload["structured_result"]["error"] == {}


def test_cli_dry_run_keeps_existing_semantics(tmp_path: Path) -> None:
    source = tmp_path / "summary_source.txt"
    source.write_text(
        "DocAgent summary dry-run source text with enough content for a normal summary.",
        encoding="utf-8",
    )

    payload = _run_cli(
        "--db-path",
        str(tmp_path / "docagent.db"),
        "--document-root",
        str(tmp_path / "documents"),
        "--file",
        str(source),
        "--question",
        "Summarize this document.",
        "--dry-run",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "document_summary"
    assert payload["router_plan"]["selected_tools"] == ["document_summary"]
    assert payload["tools_used"] == ["document_summary"]
    assert payload["answer"] == ""
    assert "summary" not in payload
    assert "dry_run_no_answer_generated" in payload["warnings"]

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MINERU_FIXTURE = ROOT / "tests" / "fixtures" / "mineru_real_schema"


def _run_cli(*args: str) -> tuple[dict, str]:
    completed = subprocess.run(
        [sys.executable, "scripts/docagent_cli.py", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    output = completed.stdout.strip()
    assert output.startswith("{")
    assert output.endswith("}")
    return json.loads(output), output


def _paths(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\n% phase5f3 parser-backed smoke fixture\n")
    return source, tmp_path / "docagent.db", tmp_path / "documents", tmp_path / "cli"


def _mineru_args(source: Path, db_path: Path, document_root: Path, output_dir: Path, question: str) -> list[str]:
    return [
        "--db-path",
        str(db_path),
        "--document-root",
        str(document_root),
        "--file",
        str(source),
        "--parser",
        "mineru_existing",
        "--mineru-output-dir",
        str(MINERU_FIXTURE),
        "--question",
        question,
        "--output-dir",
        str(output_dir),
    ]


def test_mineru_backend_unavailable_without_existing_output_is_structured(tmp_path: Path) -> None:
    source, db_path, document_root, output_dir = _paths(tmp_path)

    payload, raw = _run_cli(
        "--db-path",
        str(db_path),
        "--document-root",
        str(document_root),
        "--file",
        str(source),
        "--question",
        "How many pages are in this document?",
        "--output-dir",
        str(output_dir),
    )

    assert raw.startswith("{") and raw.endswith("}")
    assert payload["status"] == "error"
    assert payload["error"]["type"] == "parser_backend_unavailable"
    assert payload["source"]["type"] == "file"
    assert payload["source"]["was_ingested"] is False
    assert payload["source"]["reused_existing"] is False
    assert Path(payload["artifact_dir"], "result.json").is_file()


def test_mineru_existing_file_ingestion_routes_to_document_statistics(tmp_path: Path) -> None:
    source, db_path, document_root, output_dir = _paths(tmp_path)

    payload, raw = _run_cli(*_mineru_args(source, db_path, document_root, output_dir, "How many pages are in this document?"))

    assert raw.startswith("{") and raw.endswith("}")
    assert payload["status"] == "success"
    assert payload["doc_id"]
    assert payload["source"]["was_ingested"] is True
    assert payload["source"]["reused_existing"] is False
    assert payload["source"]["ingestion_status"] == "parsed"
    assert payload["source"]["parser"] == "mineru_existing"
    assert payload["task_type"] == "document_statistics"
    assert payload["tools_used"] == ["count_pages"]
    assert "2 pages" in payload["answer"]
    assert payload["metadata_consistency"]["documents_page_count"] == 2
    assert payload["metadata_consistency"]["page_documents_count"] == 2
    for name in ("result.json", "summary.json", "router_plan.json", "trace.json"):
        assert Path(payload["artifact_dir"], name).is_file()
    summary = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["used_external_api"] is False
    assert summary["used_vlm"] is False
    assert summary["used_training"] is False
    assert summary["used_full_e2e"] is False


def test_mineru_existing_file_ingestion_routes_to_page_lookup(tmp_path: Path) -> None:
    source, db_path, document_root, output_dir = _paths(tmp_path)

    payload, _raw = _run_cli(*_mineru_args(source, db_path, document_root, output_dir, "Show the text from page 1."))

    assert payload["status"] == "success"
    assert payload["task_type"] == "page_lookup"
    assert payload["tools_used"] == ["get_page_text"]
    assert "AFRICA" in payload["answer"]
    assert payload["citations"][0]["page"] == 1
    assert payload["metadata_consistency"]["status"] == "ok"


def test_mineru_existing_file_ingestion_supports_local_fact_qa_dry_run_fallback(tmp_path: Path) -> None:
    source, db_path, document_root, output_dir = _paths(tmp_path)

    payload, _raw = _run_cli(
        *_mineru_args(source, db_path, document_root, output_dir, "What is this document about?"),
        "--dry-run",
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "local_fact_qa"
    assert payload["router_plan"]["task_type"] == "document_summary"
    assert payload["router_plan"]["selected_tools"] == ["local_fact_qa"]
    assert payload["tools_used"] == ["local_fact_qa"]
    assert payload["answer"] == ""
    assert payload["supporting_evidence_ids"]
    assert "fallback_to_local_fact_qa" in payload["warnings"]
    assert "dry_run_no_answer_generated" in payload["warnings"]

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from scripts import docagent_cli


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


def test_mineru_api_requires_live_api_before_ingestion(tmp_path: Path) -> None:
    source, db_path, document_root, output_dir = _paths(tmp_path)

    payload, raw = _run_cli(
        "--db-path",
        str(db_path),
        "--document-root",
        str(document_root),
        "--file",
        str(source),
        "--parser",
        "mineru_api",
        "--question",
        "How many pages are in this document?",
        "--output-dir",
        str(output_dir),
    )

    assert raw.startswith("{") and raw.endswith("}")
    assert payload["status"] == "error"
    assert payload["error"]["type"] == "mineru_api_requires_live_api"
    assert payload["source"]["was_ingested"] is False
    assert payload["source"]["ingestion_error"]["type"] == "mineru_api_requires_live_api"


def test_mineru_api_file_ingestion_routes_to_document_statistics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source, db_path, document_root, output_dir = _paths(tmp_path)
    env_file = tmp_path / "mineru.env"
    env_file.write_text("MINERU_TOKEN=fake-token\n", encoding="utf-8")
    created_clients = []

    class FakeMinerUApiClient:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.calls = []
            created_clients.append(self)

        def run(self, **kwargs):
            self.calls.append(kwargs)
            shutil.copytree(MINERU_FIXTURE, kwargs["output_dir"])
            return {
                "status": "success",
                "batch_id": "batch-1",
                "source_sha256": "sha",
                "result_zip_sha256": "zip-sha",
            }

    monkeypatch.setattr(docagent_cli, "MinerUApiClient", FakeMinerUApiClient)
    args = docagent_cli.build_parser().parse_args(
        [
            "--db-path",
            str(db_path),
            "--document-root",
            str(document_root),
            "--file",
            str(source),
            "--parser",
            "mineru_api",
            "--live-api",
            "--mineru-env-file",
            str(env_file),
            "--question",
            "How many pages are in this document?",
            "--output-dir",
            str(output_dir),
        ]
    )

    payload = docagent_cli.run_cli(args)

    assert payload["status"] == "success"
    assert payload["task_type"] == "document_statistics"
    assert payload["source"]["parser"] == "mineru_api"
    assert payload["source"]["parser_mode"] == "parse_existing"
    assert payload["source"]["used_mineru_api"] is True
    assert payload["source"]["mineru_api"]["api_status"] == "submitted"
    assert created_clients[0].kwargs["env_file"] == env_file
    assert created_clients[0].calls[0]["file_path"] == source
    summary = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["used_mineru_api"] is True
    assert summary["used_external_api"] is True


def test_mineru_api_file_ingestion_replaces_incomplete_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source, db_path, document_root, output_dir = _paths(tmp_path)
    preview_record = docagent_cli.DocumentRegistry(document_root).register(source)
    stale_mineru_dir = Path(preview_record.document_dir) / "mineru"
    stale_mineru_dir.mkdir(parents=True)
    (stale_mineru_dir / "mineru_result.zip").write_bytes(b"partial")
    created_clients = []

    class FakeMinerUApiClient:
        def __init__(self, **kwargs):
            self.calls = []
            created_clients.append(self)

        def run(self, **kwargs):
            self.calls.append(kwargs)
            assert not (stale_mineru_dir / "mineru_result.zip").exists()
            shutil.copytree(MINERU_FIXTURE, kwargs["output_dir"])
            return {
                "status": "success",
                "batch_id": "batch-1",
                "source_sha256": "sha",
                "result_zip_sha256": "zip-sha",
                "api_attempt_count": 1,
                "retry_errors": [],
            }

    monkeypatch.setattr(docagent_cli, "MinerUApiClient", FakeMinerUApiClient)
    args = docagent_cli.build_parser().parse_args(
        [
            "--db-path",
            str(db_path),
            "--document-root",
            str(document_root),
            "--file",
            str(source),
            "--parser",
            "mineru_api",
            "--live-api",
            "--question",
            "How many pages are in this document?",
            "--output-dir",
            str(output_dir),
            "--mineru-api-max-attempts",
            "5",
            "--mineru-api-retry-delay-seconds",
            "0",
        ]
    )

    payload = docagent_cli.run_cli(args)

    assert payload["status"] == "success"
    assert len(created_clients) == 1
    assert created_clients[0].calls[0]["api_max_attempts"] == 5
    assert payload["source"]["mineru_api"]["manifest"]["api_attempt_count"] == 1


def test_mineru_api_file_ingestion_replaces_cache_when_parse_options_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source, db_path, document_root, output_dir = _paths(tmp_path)
    preview_record = docagent_cli.DocumentRegistry(document_root).register(source)
    stale_mineru_dir = Path(preview_record.document_dir) / "mineru"
    shutil.copytree(MINERU_FIXTURE, stale_mineru_dir)
    (stale_mineru_dir / "mineru_api_manifest.json").write_text(
        json.dumps(
            {
                "status": "success",
                "parse_options": {
                    "model_version": "vlm",
                    "is_ocr": False,
                    "enable_table": True,
                    "enable_formula": True,
                    "language": "en",
                },
            }
        ),
        encoding="utf-8",
    )
    created_clients = []

    class FakeMinerUApiClient:
        def __init__(self, **kwargs):
            self.calls = []
            created_clients.append(self)

        def run(self, **kwargs):
            self.calls.append(kwargs)
            assert not stale_mineru_dir.exists()
            shutil.copytree(MINERU_FIXTURE, kwargs["output_dir"])
            return {
                "status": "success",
                "batch_id": "batch-1",
                "source_sha256": "sha",
                "result_zip_sha256": "zip-sha",
                "api_attempt_count": 1,
                "retry_errors": [],
            }

    monkeypatch.setattr(docagent_cli, "MinerUApiClient", FakeMinerUApiClient)
    args = docagent_cli.build_parser().parse_args(
        [
            "--db-path",
            str(db_path),
            "--document-root",
            str(document_root),
            "--file",
            str(source),
            "--parser",
            "mineru_api",
            "--live-api",
            "--question",
            "How many pages are in this document?",
            "--output-dir",
            str(output_dir),
            "--mineru-ocr",
        ]
    )

    payload = docagent_cli.run_cli(args)

    assert payload["status"] == "success"
    assert len(created_clients) == 1
    assert created_clients[0].calls[0]["is_ocr"] is True


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


def test_mineru_existing_file_ingestion_supports_document_summary_dry_run(tmp_path: Path) -> None:
    source, db_path, document_root, output_dir = _paths(tmp_path)

    payload, _raw = _run_cli(
        *_mineru_args(source, db_path, document_root, output_dir, "What is this document about?"),
        "--dry-run",
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "document_summary"
    assert payload["router_plan"]["task_type"] == "document_summary"
    assert payload["router_plan"]["selected_tools"] == ["document_summary"]
    assert payload["tools_used"] == ["document_summary"]
    assert payload["answer"] == ""
    assert payload["supporting_evidence_ids"] == []
    assert "fallback_to_local_fact_qa" not in payload["warnings"]
    assert "dry_run_no_answer_generated" in payload["warnings"]

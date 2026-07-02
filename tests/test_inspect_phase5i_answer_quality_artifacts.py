from __future__ import annotations

import json
from pathlib import Path

from docagent.ingestion.document_registry import DocumentRecord
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from scripts.inspect_phase5i_answer_quality_artifacts import inspect_phase5i_answer_quality_run, main
from scripts.run_phase5i_answer_quality_benchmark import CommandResult, run_phase5i_benchmark


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _payload(output_dir: Path) -> str:
    artifact_dir = output_dir / "case"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "result.json").write_text("{}", encoding="utf-8")
    payload = {
        "status": "success",
        "task_type": "local_fact_qa",
        "router_plan": {"task_type": "local_fact_qa", "router_source": "rule", "warnings": []},
        "answer": "The financial year is 2019.",
        "citations": [{"page": 24, "block_id": "b1", "text_preview": "financial year 2019"}],
        "query_planner": {"enabled": True, "mode": "hybrid", "final_queries": ["financial year"]},
        "artifact_dir": str(artifact_dir),
        "artifact_paths": [str(artifact_dir / "result.json")],
        "used_llm_query_rewriter": True,
        "used_qwen_answer_policy": True,
    }
    return json.dumps(payload)


def _write_minimal_document_context(tmp_path: Path, *, doc_id: str = "doc1") -> Path:
    db_path = tmp_path / "docagent.db"
    source = tmp_path / "source.txt"
    source.write_text("financial year 2019", encoding="utf-8")
    conn = connect(db_path)
    try:
        repository = DocumentRepository(conn)
        repository.upsert_document(
            DocumentRecord(
                doc_id=doc_id,
                sha256="1" * 64,
                original_name="source.txt",
                mime_type="text/plain",
                file_size=source.stat().st_size,
                file_path=str(source),
                document_dir=str(tmp_path / doc_id),
                page_count=1,
                parser_backend="text",
                parse_status="success",
                index_status="not_started",
            )
        )
        repository.save_evidence_blocks(
            [
                EvidenceBlock(
                    doc_id=doc_id,
                    block_id=f"{doc_id}_p001_b0001",
                    block_type="text",
                    text="financial year 2019",
                    page_id=1,
                    location=EvidenceLocation(page=1, block_id=f"{doc_id}_p001_b0001"),
                )
            ]
        )
    finally:
        conn.close()
    return db_path


def _make_phase5ib_run(tmp_path: Path) -> Path:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "fact",
                "user_request": "What financial year is mentioned?",
                "request_form": "interrogative",
                "expected_task_type": "local_fact_qa",
                "expected_answer_type": "extractive",
                "answerable": True,
                "unsupported_ok": False,
                "expected_page": 24,
                "expected_evidence_keywords": ["financial year"],
                "expected_answer_keywords": ["2019"],
                "forbidden_answer_keywords": [],
            }
        ],
    )

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        output_dir = Path(command[command.index("--output-dir") + 1])
        return CommandResult(0, _payload(output_dir), "")

    db_path = _write_minimal_document_context(tmp_path, doc_id="doc1")
    summary = run_phase5i_benchmark(
        db_path=db_path,
        doc_id="doc1",
        router_llm_env_file=tmp_path / "router.env",
        output_root=tmp_path / "benchmark",
        cases_jsonl=cases_path,
        command_runner=fake_runner,
        run_id="phase5ib_artifact_review",
        evaluate_final_answer=True,
    )
    return Path(summary["artifact_dir"])


def test_inspect_phase5i_answer_quality_artifacts_accepts_valid_manifest(tmp_path: Path) -> None:
    run_dir = _make_phase5ib_run(tmp_path)

    result = inspect_phase5i_answer_quality_run(run_dir)

    assert result["status"] == "success"
    assert result["final_answer_quality_evaluated"] is True
    assert result["formal_benchmark_acceptance"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["used_training"] is False
    assert result["manifest_review"]["status"] == "success"
    assert result["artifact_counts"]["training_candidate_raw_count"] == 0
    assert result["next_action"] == "review_answer_quality_metrics_before_formal_benchmark_or_training"


def test_inspect_phase5i_answer_quality_artifacts_rejects_stale_hash(tmp_path: Path) -> None:
    run_dir = _make_phase5ib_run(tmp_path)
    metrics_path = run_dir / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["answer_correct_rate"] = 0.0
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")

    result = inspect_phase5i_answer_quality_run(run_dir)

    assert result["status"] == "failed"
    assert "manifest_failed" in result["failures"]
    assert any(failure["type"] == "sha256_mismatch" for failure in result["manifest_review"]["failures"])
    assert result["next_action"] == "fix_phase5i_answer_quality_artifact_contract"


def test_inspect_phase5i_answer_quality_artifacts_cli_writes_review_files(tmp_path: Path, capsys) -> None:
    run_dir = _make_phase5ib_run(tmp_path)
    output_dir = tmp_path / "review"

    main(["--run-dir", str(run_dir), "--run-id", "phase5ib_review", "--output-dir", str(output_dir)])

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    review_dir = output_dir / "phase5ib_review"
    assert payload["status"] == "success"
    assert (review_dir / "result.json").is_file()
    assert (review_dir / "summary.json").is_file()
    assert (review_dir / "summary.md").is_file()
    assert (review_dir / "manifest.json").is_file()

from __future__ import annotations

import json
from pathlib import Path

from scripts.run_phase5i_answer_quality_benchmark import CommandResult, run_phase5i_benchmark


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _payload(
    *,
    output_dir: Path,
    case_name: str,
    status: str,
    task_type: str,
    answer: str = "",
    citations: list[dict] | None = None,
    warnings: list[str] | None = None,
    error: dict | None = None,
    query_planner: dict | None = None,
) -> str:
    artifact_dir = output_dir / case_name
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "result.json").write_text("{}", encoding="utf-8")
    return json.dumps(
        {
            "status": status,
            "task_type": task_type,
            "router_plan": {"task_type": task_type, "router_source": "rule", "warnings": warnings or []},
            "answer": answer,
            "citations": citations or [],
            "supporting_evidence_ids": ["ev1"] if citations else [],
            "tools_used": ["local_fact_qa"] if task_type == "local_fact_qa" else [],
            "warnings": warnings or [],
            "error": error or {},
            "query_planner": query_planner or {},
            "artifact_dir": str(artifact_dir),
        },
        ensure_ascii=False,
    )


def test_phase5i_runner_scores_fake_cli_outputs_and_writes_artifacts(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "fact_ok",
                "user_request": "What financial year is mentioned?",
                "request_form": "interrogative",
                "expected_task_type": "local_fact_qa",
                "expected_answer_type": "extractive",
                "answerable": True,
                "unsupported_ok": False,
                "expected_page": 24,
                "expected_evidence_keywords": ["unclaimed", "dividend"],
                "expected_answer_keywords": ["financial year"],
                "forbidden_answer_keywords": [],
            },
            {
                "case_id": "summary_boundary",
                "user_request": "Summarize this document.",
                "request_form": "summary",
                "expected_task_type": "document_summary",
                "expected_answer_type": "unsupported",
                "answerable": False,
                "unsupported_ok": True,
                "expected_page": None,
                "expected_evidence_keywords": [],
                "expected_answer_keywords": [],
                "forbidden_answer_keywords": [],
            },
            {
                "case_id": "abstain_ok",
                "user_request": "What is the CEO's favorite color?",
                "request_form": "interrogative",
                "expected_task_type": "local_fact_qa",
                "expected_answer_type": "abstain",
                "answerable": False,
                "unsupported_ok": False,
                "expected_page": None,
                "expected_evidence_keywords": [],
                "expected_answer_keywords": [],
                "forbidden_answer_keywords": ["blue"],
            },
        ],
    )

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        output_dir = Path(command[command.index("--output-dir") + 1])
        question = command[command.index("--question") + 1]
        if question == "What financial year is mentioned?":
            return CommandResult(
                0,
                _payload(
                    output_dir=output_dir,
                    case_name="fact_ok",
                    status="success",
                    task_type="local_fact_qa",
                    answer="The financial year is 2013-14.",
                    citations=[{"page": 24, "block_id": "b1", "text_preview": "unclaimed dividend notice"}],
                    query_planner={
                        "enabled": True,
                        "mode": "hybrid",
                        "final_queries": ["financial year unclaimed dividend"],
                        "llm_status": "used",
                    },
                ),
            )
        if question == "Summarize this document.":
            return CommandResult(
                0,
                _payload(
                    output_dir=output_dir,
                    case_name="summary_boundary",
                    status="error",
                    task_type="document_summary",
                    warnings=["document_summary_not_implemented"],
                    error={"type": "document_summary_not_implemented", "message": "not implemented"},
                ),
            )
        return CommandResult(
            0,
            _payload(
                output_dir=output_dir,
                case_name="abstain_ok",
                status="success",
                task_type="local_fact_qa",
                answer="Insufficient evidence in the document to answer.",
            ),
        )

    summary = run_phase5i_benchmark(
        db_path=tmp_path / "docagent.db",
        doc_id="doc1",
        router_llm_env_file=tmp_path / "router.env",
        output_root=tmp_path / "benchmark",
        cases_jsonl=cases_path,
        command_runner=fake_runner,
        run_id="phase5i_test",
    )

    assert summary["status"] == "success"
    assert summary["quality_status"] == "passed"
    assert summary["case_count"] == 3
    assert summary["passed_count"] == 3
    assert summary["failed_count"] == 0
    assert summary["task_type_accuracy"] == 1.0
    assert summary["evidence_keyword_hit_count"] == 1
    assert summary["answer_keyword_hit_count"] == 1
    assert summary["citation_page_hit_count"] == 1
    assert summary["unsupported_boundary_pass_count"] == 1
    assert summary["abstention_pass_count"] == 1
    assert summary["used_external_api"] is True

    run_dir = Path(summary["artifact_dir"])
    assert (run_dir / "phase5i_cases.jsonl").is_file()
    assert (run_dir / "phase5i_results.jsonl").is_file()
    assert (run_dir / "phase5i_summary.json").is_file()
    assert (run_dir / "preview.json").is_file()
    assert (run_dir / "manual_review.md").is_file()

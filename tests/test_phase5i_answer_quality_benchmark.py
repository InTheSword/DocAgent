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


def test_answer_keyword_missing_does_not_fail_evidence_readiness_by_default(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "fact_evidence_ready_answer_not_evaluated",
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
            }
        ],
    )

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        output_dir = Path(command[command.index("--output-dir") + 1])
        return CommandResult(
            0,
            _payload(
                output_dir=output_dir,
                case_name="fact",
                status="success",
                task_type="local_fact_qa",
                answer="Relevant evidence was retrieved.",
                citations=[{"page": 24, "block_id": "b1", "text_preview": "unclaimed dividend notice"}],
                query_planner={"enabled": True, "mode": "hybrid", "final_queries": ["unclaimed dividend"]},
            ),
        )

    summary = run_phase5i_benchmark(
        db_path=tmp_path / "docagent.db",
        doc_id="doc1",
        router_llm_env_file=tmp_path / "router.env",
        output_root=tmp_path / "benchmark",
        cases_jsonl=cases_path,
        command_runner=fake_runner,
        run_id="phase5i_answer_keyword_default",
    )

    assert summary["evaluation_scope"] == "pre_llm_evidence_readiness"
    assert summary["final_answer_generation_enabled"] is False
    assert summary["final_answer_quality_evaluated"] is False
    assert summary["evidence_readiness_status"] == "passed"
    assert summary["passed_count"] == 1
    assert summary["failed_count"] == 0
    assert summary["downstream_answer_required_count"] == 1
    assert summary["evidence_ready_count"] == 1
    assert summary["evidence_readiness_pass_count"] == 1

    run_dir = Path(summary["artifact_dir"])
    result = json.loads((run_dir / "phase5i_results.jsonl").read_text(encoding="utf-8").strip())
    assert result["answer_keyword_hit"] is False
    assert result["answer_keyword_evaluated"] is False
    assert result["downstream_answer_required"] is True
    assert result["final_answer_quality_evaluated"] is False
    assert result["evidence_ready"] is True
    assert result["evidence_readiness_pass"] is True
    assert result["pass_fail"] == "passed"
    assert "answer_keyword_missing" not in result["failure_reasons"]

    manual_review = (run_dir / "manual_review.md").read_text(encoding="utf-8")
    assert "Evidence found; final answer generation not evaluated in Phase 5I-A." in manual_review


def test_evaluate_final_answer_flag_makes_answer_keyword_missing_hard_fail(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "fact_final_answer_eval",
                "user_request": "What financial year is mentioned?",
                "request_form": "interrogative",
                "expected_task_type": "local_fact_qa",
                "expected_answer_type": "extractive",
                "answerable": True,
                "unsupported_ok": False,
                "expected_page": 24,
                "expected_evidence_keywords": ["unclaimed"],
                "expected_answer_keywords": ["financial year"],
                "forbidden_answer_keywords": [],
            }
        ],
    )

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        output_dir = Path(command[command.index("--output-dir") + 1])
        return CommandResult(
            0,
            _payload(
                output_dir=output_dir,
                case_name="fact",
                status="success",
                task_type="local_fact_qa",
                answer="Relevant evidence was retrieved.",
                citations=[{"page": 24, "block_id": "b1", "text_preview": "unclaimed dividend notice"}],
                query_planner={"enabled": True, "mode": "hybrid", "final_queries": ["unclaimed dividend"]},
            ),
        )

    summary = run_phase5i_benchmark(
        db_path=tmp_path / "docagent.db",
        doc_id="doc1",
        router_llm_env_file=tmp_path / "router.env",
        output_root=tmp_path / "benchmark",
        cases_jsonl=cases_path,
        command_runner=fake_runner,
        run_id="phase5i_final_answer_eval",
        evaluate_final_answer=True,
    )

    result = json.loads((Path(summary["artifact_dir"]) / "phase5i_results.jsonl").read_text(encoding="utf-8").strip())
    assert summary["final_answer_generation_enabled"] is True
    assert summary["final_answer_quality_evaluated"] is True
    assert summary["evidence_readiness_status"] == "baseline_has_failures"
    assert result["answer_keyword_evaluated"] is True
    assert result["answer_keyword_hit"] is False
    assert result["pass_fail"] == "failed"
    assert "answer_keyword_missing" in result["failure_reasons"]
    assert result["failure_stage"] == "downstream_answer_not_evaluated"


def test_downstream_flags_for_calculation_summary_and_table_cases(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "calc_case",
                "user_request": "Calculate the difference between two amounts.",
                "request_form": "calculation",
                "expected_task_type": "table_lookup_or_calculation",
                "expected_answer_type": "unsupported",
                "answerable": False,
                "unsupported_ok": True,
                "expected_page": None,
                "expected_evidence_keywords": [],
                "expected_answer_keywords": [],
                "forbidden_answer_keywords": [],
            },
            {
                "case_id": "summary_case",
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
                "case_id": "table_case",
                "user_request": "Which table contains the financial information?",
                "request_form": "extraction",
                "expected_task_type": "table_lookup_or_calculation",
                "expected_answer_type": "unsupported",
                "answerable": False,
                "unsupported_ok": True,
                "expected_page": None,
                "expected_evidence_keywords": [],
                "expected_answer_keywords": [],
                "forbidden_answer_keywords": [],
            },
        ],
    )

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        output_dir = Path(command[command.index("--output-dir") + 1])
        question = command[command.index("--question") + 1]
        if question.startswith("Summarize"):
            return CommandResult(
                0,
                _payload(
                    output_dir=output_dir,
                    case_name="summary",
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
                case_name=question.split()[0].lower(),
                status="error",
                task_type="table_lookup_or_calculation",
                warnings=["table_lookup_not_implemented"],
                error={"type": "table_lookup_not_implemented", "message": "not implemented"},
            ),
        )

    summary = run_phase5i_benchmark(
        db_path=tmp_path / "docagent.db",
        doc_id="doc1",
        router_llm_env_file=tmp_path / "router.env",
        output_root=tmp_path / "benchmark",
        cases_jsonl=cases_path,
        command_runner=fake_runner,
        run_id="phase5i_downstream_flags",
    )

    rows = [
        json.loads(line)
        for line in (Path(summary["artifact_dir"]) / "phase5i_results.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    by_id = {row["case_id"]: row for row in rows}
    assert by_id["calc_case"]["downstream_calculation_required"] is True
    assert by_id["calc_case"]["downstream_task_type"] == "simple_calculation"
    assert by_id["summary_case"]["downstream_summary_required"] is True
    assert by_id["summary_case"]["downstream_task_type"] == "document_summary"
    assert by_id["table_case"]["downstream_table_required"] is True
    assert by_id["table_case"]["downstream_task_type"] == "table_lookup"
    assert summary["downstream_calculation_required_count"] == 1
    assert summary["downstream_summary_required_count"] == 1
    assert summary["downstream_table_required_count"] == 1
    assert summary["unsupported_boundary_pass_count"] == 3


def test_unsupported_boundary_missing_remains_evidence_readiness_failure(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "summary_boundary_missing",
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
            }
        ],
    )

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        output_dir = Path(command[command.index("--output-dir") + 1])
        return CommandResult(
            0,
            _payload(
                output_dir=output_dir,
                case_name="bad_summary",
                status="success",
                task_type="document_summary",
                answer="A summary-like answer without a boundary signal.",
            ),
        )

    summary = run_phase5i_benchmark(
        db_path=tmp_path / "docagent.db",
        doc_id="doc1",
        router_llm_env_file=tmp_path / "router.env",
        output_root=tmp_path / "benchmark",
        cases_jsonl=cases_path,
        command_runner=fake_runner,
        run_id="phase5i_boundary_missing",
    )

    result = json.loads((Path(summary["artifact_dir"]) / "phase5i_results.jsonl").read_text(encoding="utf-8").strip())
    assert summary["failed_count"] == 1
    assert result["pass_fail"] == "failed"
    assert result["evidence_readiness_pass"] is False
    assert result["unsupported_boundary_pass"] is False
    assert "unsupported_boundary_missing" in result["failure_reasons"]
    assert result["failure_stage"] == "unsupported_boundary"

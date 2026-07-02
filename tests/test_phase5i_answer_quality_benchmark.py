from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.run_phase5i_answer_quality_benchmark import CommandResult, build_parser, run_phase5i_benchmark


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
    extra: dict | None = None,
) -> str:
    artifact_dir = output_dir / case_name
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "result.json").write_text("{}", encoding="utf-8")
    payload = {
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
    }
    payload.update(extra or {})
    return json.dumps(
        payload,
        ensure_ascii=False,
    )


def test_phase5i_parser_exposes_run_id_for_documented_cli() -> None:
    args = build_parser().parse_args(["--run-id", "phase5ib_probe", "--no-full-model-path"])

    assert args.run_id == "phase5ib_probe"


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
    assert (run_dir / "metrics.json").is_file()
    assert (run_dir / "predictions.jsonl").is_file()
    assert (run_dir / "case_reports.jsonl").is_file()
    assert (run_dir / "failure_analysis.md").is_file()
    assert (run_dir / "acceptance_report.json").is_file()
    assert (run_dir / "training_candidates_raw.jsonl").is_file()
    assert (run_dir / "manifest.json").is_file()
    acceptance = json.loads((run_dir / "acceptance_report.json").read_text(encoding="utf-8"))
    assert acceptance["formal_benchmark_acceptance"] is False
    assert acceptance["validation_subset_used_for_training"] is False
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == "phase5i_test"
    assert manifest["formal_benchmark_acceptance"] is False
    assert manifest["validation_subset_used_for_training"] is False
    manifest_files = {Path(item["path"]).name: item for item in manifest["files"]}
    assert "manifest.json" not in manifest_files
    for name in ("phase5i_summary.json", "metrics.json", "acceptance_report.json", "training_candidates_raw.jsonl"):
        artifact = run_dir / name
        assert name in manifest_files
        assert manifest_files[name]["sha256"] == hashlib.sha256(artifact.read_bytes()).hexdigest()


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
    assert summary["evaluation_scope"] == "final_answer_quality_small_scenario"
    assert summary["final_answer_generation_enabled"] is True
    assert summary["final_answer_quality_evaluated"] is True
    assert summary["answer_quality_evaluation_scope"] == "final_answer_quality_small_scenario"
    assert summary["formal_benchmark_acceptance"] is False
    assert summary["validation_subset_used_for_training"] is False
    assert summary["evidence_readiness_status"] == "baseline_has_failures"
    assert result["answer_keyword_evaluated"] is True
    assert result["evaluation_scope"] == "final_answer_quality_small_scenario"
    assert result["answer_keyword_hit"] is False
    assert result["pass_fail"] == "failed"
    assert "answer_keyword_missing" in result["failure_reasons"]
    assert result["failure_stage"] == "downstream_answer_not_evaluated"
    run_dir = Path(summary["artifact_dir"])
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    predictions = [
        json.loads(line)
        for line in (run_dir / "predictions.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    case_reports = [
        json.loads(line)
        for line in (run_dir / "case_reports.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert metrics["final_answer_quality_evaluated"] is True
    assert metrics["answer_correct_count"] == 0
    assert predictions[0]["answer_correct"] is False
    assert isinstance(predictions[0]["format_valid"], bool)
    assert "citation_valid" in predictions[0]
    assert "location_valid" in predictions[0]
    assert case_reports[0]["failure_stage"] == "downstream_answer_not_evaluated"
    assert (run_dir / "training_candidates_raw.jsonl").read_text(encoding="utf-8") == ""


def test_full_model_path_passes_cli_flags_and_records_model_path_fields(tmp_path: Path) -> None:
    cases_path = tmp_path / "cases.jsonl"
    router_env = tmp_path / "router.env"
    router_env.write_text(
        "\n".join(
            [
                "DOCAGENT_ROUTER_LLM_API_KEY=fake-secret-key",
                "DOCAGENT_ROUTER_LLM_BASE_URL=https://example.test/compatible-mode/v1",
                "DOCAGENT_ROUTER_LLM_MODEL=fake-router-model",
            ]
        ),
        encoding="utf-8",
    )
    _write_jsonl(
        cases_path,
        [
            {
                "case_id": "fact_full_path",
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
    captured_commands: list[list[str]] = []

    def fake_runner(command: list[str], _cwd: Path, _timeout_seconds: int) -> CommandResult:
        captured_commands.append(command)
        output_dir = Path(command[command.index("--output-dir") + 1])
        return CommandResult(
            0,
            _payload(
                output_dir=output_dir,
                case_name="fact_full_path",
                status="success",
                task_type="local_fact_qa",
                answer="The financial year is 2013-14.",
                citations=[{"page": 24, "block_id": "b1", "text_preview": "unclaimed dividend notice"}],
                query_planner={
                    "enabled": True,
                    "mode": "hybrid",
                    "llm_status": "used",
                    "final_queries": ["financial year unclaimed dividend", "shareholder dividend year"],
                    "query_sources": {
                        "rule": ["financial year unclaimed dividend"],
                        "llm": ["shareholder dividend year"],
                    },
                },
                extra={
                    "full_model_path": True,
                    "router_execution": {
                        "router_source": "rule",
                        "llm_router_status": "skipped",
                        "llm_router_skip_reason": "high_confidence_or_rule_sufficient",
                        "rule_confidence": 0.86,
                        "final_task_type": "local_fact_qa",
                    },
                    "query_planner_execution": {
                        "query_planner_mode": "hybrid",
                        "llm_query_rewriter_status": "used",
                        "used_llm_query_rewriter": True,
                    },
                    "used_llm_router": False,
                    "llm_router_status": "skipped",
                    "used_llm_query_rewriter": True,
                    "llm_query_rewriter_status": "used",
                    "answer_policy_mode": "base",
                    "used_qwen_answer_policy": True,
                    "used_external_answer_api": False,
                    "retrieval_candidate_count": 1,
                    "citation_count": 1,
                    "trace_run_id": "qa-run-1",
                    "tool_run_id": "qa-run-1",
                },
            ),
        )

    summary = run_phase5i_benchmark(
        db_path=tmp_path / "docagent.db",
        doc_id="doc1",
        router_llm_env_file=router_env,
        output_root=tmp_path / "benchmark",
        cases_jsonl=cases_path,
        command_runner=fake_runner,
        run_id="phase5i_full_model_path",
        full_model_path=True,
        require_llm_planning_config=True,
        answer_policy="base",
        base_model_path="/models/qwen",
    )

    assert captured_commands
    command = captured_commands[0]
    assert "--full-model-path" in command
    assert command[command.index("--answer-policy") + 1] == "base"
    assert command[command.index("--base-model-path") + 1] == "/models/qwen"
    assert summary["full_model_path"] is True
    assert summary["passed_count"] == 1
    assert summary["used_llm_query_rewriter_count"] == 1
    assert summary["used_qwen_answer_policy_count"] == 1
    assert summary["trace_run_id_count"] == 1
    assert summary["used_external_answer_api"] is False

    result = json.loads((Path(summary["artifact_dir"]) / "phase5i_results.jsonl").read_text(encoding="utf-8").strip())
    assert result["full_model_path"] is True
    assert result["used_llm_query_rewriter"] is True
    assert result["answer_policy_mode"] == "base"
    assert result["used_qwen_answer_policy"] is True
    assert result["trace_run_id"] == "qa-run-1"


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

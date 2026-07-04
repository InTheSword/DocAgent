from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.inspect_final_delivery_benchmark_gate import inspect_gate, main, verify_manifest
from scripts.run_final_delivery_benchmark_gate import CommandResult, build_parser, run_final_delivery_benchmark_gate, sha256_file


def _touch_inputs(tmp_path: Path) -> dict[str, Path]:
    paths = {
        "tatqa_samples": tmp_path / "tatqa" / "samples.jsonl",
        "tatqa_manifest": tmp_path / "tatqa" / "sample_manifest.jsonl",
        "mpdocvqa_manifest": tmp_path / "mp" / "sample_manifest.jsonl",
        "mpdocvqa_evidence_manifest": tmp_path / "mp_evidence" / "sample_evidence_manifest.jsonl",
        "mpdocvqa_db": tmp_path / "mp_evidence" / "docagent.db",
        "router_env": tmp_path / "secrets" / "router_llm.env",
    }
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    return paths


def _args(tmp_path: Path, paths: dict[str, Path]):
    return build_parser().parse_args(
        [
            "--run-id",
            "gate_test",
            "--output-dir",
            str(tmp_path / "gate"),
            "--sync-output-dir",
            str(tmp_path / "sync"),
            "--python-executable",
            sys.executable,
            "--answer-policy",
            "heuristic",
            "--dense-backend",
            "hash",
            "--reranker-backend",
            "keyword",
            "--tatqa-samples",
            str(paths["tatqa_samples"]),
            "--tatqa-manifest",
            str(paths["tatqa_manifest"]),
            "--mpdocvqa-manifest",
            str(paths["mpdocvqa_manifest"]),
            "--mpdocvqa-evidence-manifest",
            str(paths["mpdocvqa_evidence_manifest"]),
            "--mpdocvqa-db-path",
            str(paths["mpdocvqa_db"]),
            "--mpdocvqa-workflow-evidence-manifest",
            str(paths["mpdocvqa_evidence_manifest"]),
            "--mpdocvqa-workflow-db-path",
            str(paths["mpdocvqa_db"]),
            "--router-llm-env-file",
            str(paths["router_env"]),
            "--answer-policy-max-samples",
            "3",
            "--mpdocvqa-workflow-limit",
            "2",
        ]
    )


def _fake_runner(command: list[str], _cwd: Path, _timeout: int) -> CommandResult:
    script = Path(command[1]).name
    if script == "check_final_delivery_readiness.py":
        payload = {
            "command": "check_final_delivery_readiness",
            "status": "success",
            "check_count": 5,
            "passed_check_count": 5,
            "used_qwen": False,
        }
    elif script == "run_final_answer_policy_baseline.py":
        payload = {
            "command": "run_final_answer_policy_baseline",
            "status": "success",
            "answer_output_contract": "candidate_citations",
            "evaluated_count": 3,
            "answer_hit_rate": 0.67,
            "citation_block_hit_rate": 1.0,
            "format_valid_rate": 1.0,
            "formal_benchmark_acceptance": False,
        }
    else:
        payload = {
            "command": "run_mpdocvqa_full_workflow_diagnostic",
            "status": "success",
            "answer_output_contract": "candidate_citations",
            "evaluated_count": 2,
            "local_fact_qa_count": 2,
            "used_qwen_answer_policy_count": 2,
            "used_dense_retrieval_count": 2,
            "used_reranker_count": 2,
            "used_llm_query_rewriter_count": 2,
            "cli_success_rate": 1.0,
            "retrieved_gold_page_hit_rate": 1.0,
            "citation_page_hit_rate": 1.0,
            "answer_hit_rate": 0.5,
            "bucket_counts": {"passed": 1, "answer_generation_or_metric_miss": 1},
            "formal_benchmark_acceptance": False,
        }
    return CommandResult(0, json.dumps(payload), "")


def _make_gate_run(tmp_path: Path) -> tuple[Path, Path]:
    paths = _touch_inputs(tmp_path)
    args = _args(tmp_path, paths)
    result = run_final_delivery_benchmark_gate(args=args, command_runner=_fake_runner)
    assert result["status"] == "success"
    return tmp_path / "gate" / "gate_test", tmp_path / "sync" / "gate_test"


def _refresh_local_manifest_hash(run_dir: Path, artifact_path: Path) -> None:
    manifest_path = run_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for item in manifest["files"]:
        if item["path"].endswith(artifact_path.name):
            item["byte_size"] = artifact_path.stat().st_size
            item["sha256"] = sha256_file(artifact_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def test_inspect_final_delivery_benchmark_gate_accepts_valid_artifacts(tmp_path: Path) -> None:
    run_dir, sync_dir = _make_gate_run(tmp_path)

    result = inspect_gate(run_dir, sync_bundle_dir=sync_dir)

    assert result["status"] == "success"
    assert result["gate_status"] == "success"
    assert result["step_statuses"] == {
        "readiness": "success",
        "answer_policy_baseline": "success",
        "mpdocvqa_full_workflow": "success",
    }
    assert result["formal_benchmark_acceptance_reviewed"] is True
    assert result["validation_subset_used_for_training_reviewed"] is True
    assert result["used_training_reviewed"] is True
    assert result["local_manifest"]["status"] == "success"
    assert result["sync_manifest"]["status"] == "success"
    assert result["step_metrics"]["answer_policy_baseline"]["answer_hit_rate"] == 0.67
    assert result["metric_review"]["answer_policy"]["citation_block_hit_rate"] == 1.0
    assert result["metric_review"]["contract_review"]["failure_count"] == 0
    assert result["metric_review"]["contract_review"]["steps"]["answer_policy_baseline"]["answer_output_contract_match"] is True
    assert result["metric_review"]["contract_review"]["steps"]["mpdocvqa_full_workflow"]["answer_output_contract_match"] is True
    assert result["metric_review"]["mpdocvqa_full_workflow"]["component_usage"]["incomplete_components"] == []
    assert result["next_action"] == "review_answer_quality_metrics_before_formal_benchmark_or_training"


def test_inspect_final_delivery_benchmark_gate_flags_incomplete_component_use(tmp_path: Path) -> None:
    run_dir, sync_dir = _make_gate_run(tmp_path)
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for step in summary["steps"]:
        if step["name"] == "mpdocvqa_full_workflow":
            step["metrics"]["used_reranker_count"] = 1
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _refresh_local_manifest_hash(run_dir, summary_path)

    result = inspect_gate(run_dir, sync_bundle_dir=sync_dir)

    assert result["status"] == "success"
    assert result["metric_review"]["mpdocvqa_full_workflow"]["component_usage"]["incomplete_components"] == ["reranker"]
    assert result["next_action"] == "inspect_full_workflow_component_usage_before_benchmark"


def test_inspect_final_delivery_benchmark_gate_uses_non_local_fact_bucket_for_component_expected_count(tmp_path: Path) -> None:
    run_dir, sync_dir = _make_gate_run(tmp_path)
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for step in summary["steps"]:
        if step["name"] == "mpdocvqa_full_workflow":
            step["metrics"].pop("local_fact_qa_count")
            step["metrics"].update(
                {
                    "evaluated_count": 24,
                    "used_qwen_answer_policy_count": 23,
                    "used_dense_retrieval_count": 23,
                    "used_reranker_count": 23,
                    "used_llm_query_rewriter_count": 23,
                    "bucket_counts": {
                        "passed": 9,
                        "answer_generation_or_metric_miss": 5,
                        "retrieval_gold_page_miss": 9,
                        "task_type_not_local_fact_qa": 1,
                    },
                }
            )
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _refresh_local_manifest_hash(run_dir, summary_path)

    result = inspect_gate(run_dir, sync_bundle_dir=sync_dir)

    component_usage = result["metric_review"]["mpdocvqa_full_workflow"]["component_usage"]
    assert result["status"] == "success"
    assert component_usage["expected_component_count"] == 23
    assert component_usage["expected_component_count_source"] == "evaluated_count_minus_task_type_not_local_fact_qa"
    assert component_usage["incomplete_components"] == []
    assert result["next_action"] == "review_answer_quality_metrics_before_formal_benchmark_or_training"


def test_inspect_final_delivery_benchmark_gate_flags_missing_component_metrics(tmp_path: Path) -> None:
    run_dir, sync_dir = _make_gate_run(tmp_path)
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    component_keys = {
        "used_qwen_answer_policy_count",
        "used_dense_retrieval_count",
        "used_reranker_count",
        "used_llm_query_rewriter_count",
    }
    for step in summary["steps"]:
        if step["name"] == "mpdocvqa_full_workflow":
            for key in component_keys:
                step["metrics"].pop(key)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _refresh_local_manifest_hash(run_dir, summary_path)

    result = inspect_gate(run_dir, sync_bundle_dir=sync_dir)

    component_usage = result["metric_review"]["mpdocvqa_full_workflow"]["component_usage"]
    assert result["status"] == "success"
    assert component_usage["full_component_metrics_present"] is False
    assert component_usage["missing_component_metrics"] == [
        "qwen_answer_policy",
        "dense_retrieval",
        "reranker",
        "llm_query_rewriter",
    ]
    assert result["metric_review"]["metric_gaps"] == ["mpdocvqa_full_workflow_component_usage"]
    assert result["next_action"] == "rerun_gate_with_component_metric_contract_before_benchmark"


def test_inspect_final_delivery_benchmark_gate_flags_child_output_contract_mismatch(tmp_path: Path) -> None:
    run_dir, sync_dir = _make_gate_run(tmp_path)
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    for step in summary["steps"]:
        if step["name"] == "mpdocvqa_full_workflow":
            step["metrics"]["answer_output_contract"] = "v3_refs"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _refresh_local_manifest_hash(run_dir, summary_path)

    result = inspect_gate(run_dir, sync_bundle_dir=sync_dir)

    assert result["status"] == "failed"
    assert "child_step_output_contract_failed" in result["failures"]
    contract_failures = result["metric_review"]["contract_review"]["failures"]
    assert contract_failures == [
        {
            "step": "mpdocvqa_full_workflow",
            "type": "answer_output_contract_mismatch",
            "expected": "candidate_citations",
            "observed": "v3_refs",
        }
    ]


def test_inspect_final_delivery_benchmark_gate_rejects_stale_hash(tmp_path: Path) -> None:
    run_dir, sync_dir = _make_gate_run(tmp_path)
    summary_path = run_dir / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["status"] = "tampered"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    result = inspect_gate(run_dir, sync_bundle_dir=sync_dir)

    assert result["status"] == "failed"
    assert "summary_result_status_mismatch" in result["failures"]
    assert "local_manifest_failed" in result["failures"]
    assert any(failure["type"] == "sha256_mismatch" for failure in result["local_manifest"]["failures"])


def test_inspect_final_delivery_benchmark_gate_cli_writes_review_artifacts(tmp_path: Path, capsys) -> None:
    run_dir, sync_dir = _make_gate_run(tmp_path)
    output_dir = tmp_path / "review"

    main(
        [
            "--run-dir",
            str(run_dir),
            "--sync-bundle-dir",
            str(sync_dir),
            "--run-id",
            "review_test",
            "--output-dir",
            str(output_dir),
        ]
    )

    captured = json.loads(capsys.readouterr().out)
    review_dir = output_dir / "review_test"
    assert captured["status"] == "success"
    assert (review_dir / "result.json").is_file()
    assert (review_dir / "summary.json").is_file()
    assert (review_dir / "summary.md").is_file()
    assert (review_dir / "manifest.json").is_file()
    assert "Final Delivery Benchmark Gate Review" in (review_dir / "summary.md").read_text(encoding="utf-8")
    assert verify_manifest(review_dir / "manifest.json")["status"] == "success"

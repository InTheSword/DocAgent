from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.inspect_final_delivery_benchmark_gate import inspect_gate, main, verify_manifest
from scripts.run_final_delivery_benchmark_gate import CommandResult, build_parser, run_final_delivery_benchmark_gate


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
        payload = {"command": "check_final_delivery_readiness", "status": "success", "used_qwen": False}
    elif script == "run_final_answer_policy_baseline.py":
        payload = {
            "command": "run_final_answer_policy_baseline",
            "status": "success",
            "evaluated_count": 3,
            "formal_benchmark_acceptance": False,
        }
    else:
        payload = {
            "command": "run_mpdocvqa_full_workflow_diagnostic",
            "status": "success",
            "evaluated_count": 2,
            "formal_benchmark_acceptance": False,
        }
    return CommandResult(0, json.dumps(payload), "")


def _make_gate_run(tmp_path: Path) -> tuple[Path, Path]:
    paths = _touch_inputs(tmp_path)
    args = _args(tmp_path, paths)
    result = run_final_delivery_benchmark_gate(args=args, command_runner=_fake_runner)
    assert result["status"] == "success"
    return tmp_path / "gate" / "gate_test", tmp_path / "sync" / "gate_test"


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

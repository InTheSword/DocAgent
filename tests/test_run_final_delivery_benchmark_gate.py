from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.run_final_delivery_benchmark_gate import CommandResult, ROOT, build_parser, run_final_delivery_benchmark_gate, sha256_file


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


def _args(tmp_path: Path, paths: dict[str, Path], *extra: str):
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
            *extra,
        ]
    )


def _resolve_artifact_path(path_text: str) -> Path:
    path = Path(path_text)
    return path if path.is_absolute() else ROOT / path


def _assert_manifest_hashes(manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    file_names = {Path(file["path"]).name for file in manifest["files"]}
    assert "manifest.json" not in file_names
    assert {"result.json", "summary.json", "summary.md", "steps.jsonl", "preview.json"} <= file_names
    for file in manifest["files"]:
        artifact_path = _resolve_artifact_path(file["path"])
        assert artifact_path.is_file()
        assert file["byte_size"] == artifact_path.stat().st_size
        assert file["sha256"] == sha256_file(artifact_path)


def test_final_delivery_benchmark_gate_orchestrates_safe_steps(tmp_path: Path) -> None:
    paths = _touch_inputs(tmp_path)
    qwen_path = tmp_path / "models" / "qwen"
    qwen_path.mkdir(parents=True)
    (qwen_path / "config.json").write_text("{}", encoding="utf-8")
    adapter_path = tmp_path / "adapters" / "promptfix"
    adapter_path.mkdir(parents=True)
    args = _args(
        tmp_path,
        paths,
        "--answer-policy",
        "sft",
        "--base-model-path",
        str(qwen_path),
        "--adapter-path",
        str(adapter_path),
        "--answer-output-contract",
        "v3_refs",
    )
    commands: list[list[str]] = []

    def fake_runner(command: list[str], _cwd: Path, _timeout: int) -> CommandResult:
        commands.append(command)
        script = Path(command[1]).name
        if script == "check_final_delivery_readiness.py":
            payload = {"command": "check_final_delivery_readiness", "status": "success", "used_qwen": False}
        elif script == "run_final_answer_policy_baseline.py":
            payload = {
                "command": "run_final_answer_policy_baseline",
                "status": "success",
                "evaluated_count": 3,
                "answer_hit_rate": 0.67,
                "formal_benchmark_acceptance": False,
            }
        else:
            payload = {
                "command": "run_mpdocvqa_full_workflow_diagnostic",
                "status": "success",
                "evaluated_count": 2,
                "retrieved_gold_page_hit_rate": 1.0,
                "formal_benchmark_acceptance": False,
            }
        return CommandResult(0, json.dumps(payload), "")

    result = run_final_delivery_benchmark_gate(args=args, command_runner=fake_runner)

    assert result["status"] == "success"
    assert result["formal_benchmark_acceptance"] is False
    assert result["validation_subset_used_for_training"] is False
    assert result["step_statuses"] == {
        "readiness": "success",
        "answer_policy_baseline": "success",
        "mpdocvqa_full_workflow": "success",
    }
    assert len(commands) == 3
    answer_policy_command = commands[1]
    assert "--max-samples" in answer_policy_command
    assert answer_policy_command[answer_policy_command.index("--max-samples") + 1] == "3"
    assert answer_policy_command[answer_policy_command.index("--answer-output-contract") + 1] == "v3_refs"
    assert answer_policy_command[answer_policy_command.index("--adapter-path") + 1] == str(adapter_path)
    workflow_command = commands[2]
    assert workflow_command[workflow_command.index("--dense-backend") + 1] == "hash"
    assert workflow_command[workflow_command.index("--reranker-backend") + 1] == "keyword"
    assert workflow_command[workflow_command.index("--answer-policy") + 1] == "sft"
    assert workflow_command[workflow_command.index("--answer-output-contract") + 1] == "v3_refs"
    assert workflow_command[workflow_command.index("--adapter-path") + 1] == str(adapter_path)
    run_dir = tmp_path / "gate" / "gate_test"
    assert (run_dir / "result.json").is_file()
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "steps.jsonl").is_file()
    _assert_manifest_hashes(run_dir / "manifest.json")
    sync_dir = tmp_path / "sync" / "gate_test"
    sync_summary = json.loads((sync_dir / "summary.json").read_text(encoding="utf-8"))
    assert any(path.endswith("manifest.json") for path in sync_summary["sync_artifact_paths"])
    _assert_manifest_hashes(sync_dir / "manifest.json")


def test_final_delivery_benchmark_gate_blocks_missing_qwen_model_before_steps(tmp_path: Path) -> None:
    paths = _touch_inputs(tmp_path)
    args = _args(tmp_path, paths, "--answer-policy", "base", "--base-model-path", str(tmp_path / "missing_qwen"))
    called = False

    def fake_runner(_command: list[str], _cwd: Path, _timeout: int) -> CommandResult:
        nonlocal called
        called = True
        return CommandResult(0, "{}", "")

    result = run_final_delivery_benchmark_gate(args=args, command_runner=fake_runner)

    assert called is False
    assert result["status"] == "failed"
    summary = json.loads((tmp_path / "gate" / "gate_test" / "summary.json").read_text(encoding="utf-8"))
    assert summary["preflight"]["status"] == "failed"
    assert "qwen_base_model" in summary["preflight"]["missing"]
    assert summary["steps"] == []

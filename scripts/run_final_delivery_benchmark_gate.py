from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "final_delivery_benchmark_gate"
DEFAULT_SYNC_ROOT = ROOT / "outputs" / "sync"
DEFAULT_QWEN_BASE_MODEL_PATH = "/root/autodl-tmp/models/Qwen3-1.7B"
DEFAULT_BGE_MODEL_PATH = "/root/autodl-tmp/models/bge-m3"
DEFAULT_RERANKER_MODEL_PATH = "/root/autodl-tmp/models/bge-reranker-v2-m3"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


CommandRunner = Callable[[list[str], Path, int], CommandResult]


def _now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"final_delivery_benchmark_gate_{stamp}_{uuid.uuid4().hex[:8]}"


def repo_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def safe_relpath(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.resolve().as_posix()


def _json_default(value: Any) -> str:
    return str(value)


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, default=_json_default) for row in rows) + "\n", encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        completed = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False)
        return completed.stdout.strip() if completed.returncode == 0 else ""
    except Exception:
        return ""


def _default_command_runner(command: list[str], cwd: Path, timeout_seconds: int) -> CommandResult:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout_seconds, check=False)
    return CommandResult(returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)


def _extract_json(text: str) -> tuple[dict[str, Any] | None, str]:
    stripped = (text or "").strip()
    if not stripped:
        return None, "stdout_empty"
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start, end = stripped.find("{"), stripped.rfind("}")
        if start < 0 or end <= start:
            return None, "stdout_not_json"
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError:
            return None, "stdout_not_json"
    return (payload, "") if isinstance(payload, dict) else (None, "stdout_json_not_object")


def _tail(text: str, limit: int = 2000) -> str:
    compact = text or ""
    return compact[-limit:]


def _path_exists(path: Path, *, require_config: bool = False) -> bool:
    if require_config:
        return (path / "config.json").is_file()
    return path.exists()


def preflight(args: argparse.Namespace) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    required: dict[str, tuple[Path, bool]] = {
        "readiness_script": (ROOT / "scripts" / "check_final_delivery_readiness.py", False),
    }
    if not args.skip_answer_policy:
        required.update(
            {
                "answer_policy_baseline_script": (ROOT / "scripts" / "run_final_answer_policy_baseline.py", False),
                "tatqa_samples": (repo_path(args.tatqa_samples) or Path(args.tatqa_samples), False),
                "tatqa_manifest": (repo_path(args.tatqa_manifest) or Path(args.tatqa_manifest), False),
                "mpdocvqa_manifest": (repo_path(args.mpdocvqa_manifest) or Path(args.mpdocvqa_manifest), False),
                "mpdocvqa_evidence_manifest": (repo_path(args.mpdocvqa_evidence_manifest) or Path(args.mpdocvqa_evidence_manifest), False),
                "mpdocvqa_db_path": (repo_path(args.mpdocvqa_db_path) or Path(args.mpdocvqa_db_path), False),
            }
        )
    if not args.skip_mpdocvqa_workflow:
        required.update(
            {
                "mpdocvqa_workflow_script": (ROOT / "scripts" / "run_mpdocvqa_full_workflow_diagnostic.py", False),
                "mpdocvqa_workflow_evidence_manifest": (repo_path(args.mpdocvqa_workflow_evidence_manifest) or Path(args.mpdocvqa_workflow_evidence_manifest), False),
                "mpdocvqa_workflow_db_path": (repo_path(args.mpdocvqa_workflow_db_path) or Path(args.mpdocvqa_workflow_db_path), False),
                "router_llm_env_file": (repo_path(args.router_llm_env_file) or Path(args.router_llm_env_file), False),
            }
        )
        if args.dense_backend == "bge":
            required["bge_model"] = (Path(args.dense_model_path), True)
        if args.reranker_backend == "cross_encoder":
            required["reranker_model"] = (Path(args.reranker_model_path), True)
    if args.answer_policy != "heuristic" and (not args.skip_answer_policy or not args.skip_mpdocvqa_workflow):
        required["qwen_base_model"] = (Path(args.base_model_path), True)
    if args.answer_policy in {"sft", "grpo"}:
        if not args.adapter_path:
            checks["adapter_path"] = {"path": "", "exists": False, "required": True}
        else:
            required["adapter_path"] = (Path(args.adapter_path), False)

    missing: list[str] = []
    for name, (path, require_config) in required.items():
        exists = _path_exists(path, require_config=require_config)
        checks[name] = {"path": str(path), "exists": exists, "required": True, "requires_config_json": require_config}
        if not exists:
            missing.append(name)
    if checks.get("adapter_path", {}).get("exists") is False:
        missing.append("adapter_path")
    return {"status": "success" if not missing else "failed", "missing": missing, "checks": checks}


def _readiness_command(args: argparse.Namespace, run_id: str) -> list[str]:
    return [
        args.python_executable,
        "scripts/check_final_delivery_readiness.py",
        "--run-id",
        f"{run_id}_readiness",
        "--output-dir",
        "outputs/final_delivery_readiness",
    ]


def _answer_policy_command(args: argparse.Namespace, run_id: str) -> list[str]:
    command = [
        args.python_executable,
        "scripts/run_final_answer_policy_baseline.py",
        "--run-id",
        f"{run_id}_answer_policy",
        "--output-dir",
        str(repo_path(args.answer_policy_output_dir) or Path(args.answer_policy_output_dir)),
        "--tatqa-samples",
        str(repo_path(args.tatqa_samples) or Path(args.tatqa_samples)),
        "--tatqa-manifest",
        str(repo_path(args.tatqa_manifest) or Path(args.tatqa_manifest)),
        "--mpdocvqa-manifest",
        str(repo_path(args.mpdocvqa_manifest) or Path(args.mpdocvqa_manifest)),
        "--mpdocvqa-evidence-manifest",
        str(repo_path(args.mpdocvqa_evidence_manifest) or Path(args.mpdocvqa_evidence_manifest)),
        "--mpdocvqa-db-path",
        str(repo_path(args.mpdocvqa_db_path) or Path(args.mpdocvqa_db_path)),
        "--answer-policy",
        args.answer_policy,
        "--base-model-path",
        args.base_model_path,
        "--device",
        args.device,
        "--torch-dtype",
        args.torch_dtype,
        "--max-prompt-tokens",
        str(args.max_prompt_tokens),
        "--max-new-tokens",
        str(args.answer_policy_max_new_tokens),
        "--top-k",
        str(args.top_k),
        "--sync-output-dir",
        str(repo_path(args.sync_output_dir) or Path(args.sync_output_dir)),
        "--preserve-input-order",
    ]
    if args.answer_policy_max_samples is not None:
        command.extend(["--max-samples", str(args.answer_policy_max_samples)])
    if args.adapter_path:
        command.extend(["--adapter-path", args.adapter_path])
    return command


def _mpdocvqa_workflow_command(args: argparse.Namespace, run_id: str) -> list[str]:
    command = [
        args.python_executable,
        "scripts/run_mpdocvqa_full_workflow_diagnostic.py",
        "--run-id",
        f"{run_id}_mpdocvqa_workflow",
        "--evidence-manifest",
        str(repo_path(args.mpdocvqa_workflow_evidence_manifest) or Path(args.mpdocvqa_workflow_evidence_manifest)),
        "--db-path",
        str(repo_path(args.mpdocvqa_workflow_db_path) or Path(args.mpdocvqa_workflow_db_path)),
        "--output-dir",
        str(repo_path(args.mpdocvqa_workflow_output_dir) or Path(args.mpdocvqa_workflow_output_dir)),
        "--limit",
        str(args.mpdocvqa_workflow_limit),
        "--offset",
        str(args.mpdocvqa_workflow_offset),
        "--sync-output-dir",
        str(repo_path(args.sync_output_dir) or Path(args.sync_output_dir)),
        "--router-llm-env-file",
        args.router_llm_env_file,
        "--retriever-mode",
        args.retriever_mode,
        "--dense-backend",
        args.dense_backend,
        "--dense-model-path",
        args.dense_model_path,
        "--dense-device",
        args.dense_device,
        "--reranker-backend",
        args.reranker_backend,
        "--reranker-model-path",
        args.reranker_model_path,
        "--reranker-device",
        args.reranker_device,
        "--answer-policy",
        args.answer_policy,
        "--base-model-path",
        args.base_model_path,
        "--device",
        args.device,
        "--torch-dtype",
        args.torch_dtype,
        "--max-prompt-tokens",
        str(args.max_prompt_tokens),
        "--max-new-tokens",
        str(args.mpdocvqa_max_new_tokens),
    ]
    if args.dense_fp16:
        command.append("--dense-fp16")
    if args.reranker_fp16:
        command.append("--reranker-fp16")
    if args.sample_ids:
        command.extend(["--sample-ids", args.sample_ids])
    return command


def _run_step(
    *,
    name: str,
    command: list[str],
    command_runner: CommandRunner,
    timeout_seconds: int,
) -> dict[str, Any]:
    result = command_runner(command, ROOT, timeout_seconds)
    parsed, parse_error = _extract_json(result.stdout)
    return {
        "name": name,
        "status": "success" if result.returncode == 0 and (parsed or {}).get("status") == "success" else "failed",
        "returncode": result.returncode,
        "command": command,
        "parsed_status": (parsed or {}).get("status"),
        "parsed_command": (parsed or {}).get("command"),
        "metrics": _compact_metrics(parsed or {}),
        "artifact_paths": (parsed or {}).get("artifact_paths") or [],
        "sync_bundle_path": (parsed or {}).get("sync_bundle_path"),
        "parse_error": parse_error,
        "stdout_tail": _tail(result.stdout),
        "stderr_tail": _tail(result.stderr),
    }


def _compact_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    scalar_keys = (
        "case_count",
        "evaluated_count",
        "passed_count",
        "failed_count",
        "skipped_count",
        "document_count",
        "document_passed_count",
        "document_failed_count",
        "sample_count",
        "sample_evidence_ready_count",
        "check_count",
        "passed_check_count",
        "failed_check_count",
        "pass_rate",
        "answer_hit_rate",
        "citation_block_hit_rate",
        "citation_page_hit_rate",
        "retrieved_gold_page_hit_rate",
        "selected_gold_page_hit_rate",
        "cli_success_rate",
        "format_valid_rate",
        "location_valid_rate",
        "tool_success_rate",
        "sample_evidence_ready_rate",
        "answer_text_gold_page_hit_rate",
        "used_qwen_answer_policy_count",
        "used_dense_retrieval_count",
        "used_reranker_count",
        "used_llm_query_rewriter_count",
        "local_fact_qa_count",
    )
    structured_keys = ("bucket_counts", "failure_reason_distribution", "step_statuses")
    metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else payload
    compact = {key: metrics.get(key) for key in scalar_keys if metrics.get(key) is not None}
    for key in structured_keys:
        value = metrics.get(key)
        if isinstance(value, dict):
            compact[key] = value
    return compact


def _summary_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Final Delivery Benchmark Gate",
        "",
        f"- status: `{summary['status']}`",
        f"- quality_status: `{summary['quality_status']}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
        f"- validation_subset_used_for_training: `{str(summary['validation_subset_used_for_training']).lower()}`",
        f"- used_qwen: `{str(summary['used_qwen']).lower()}`",
        f"- used_training: `{str(summary['used_training']).lower()}`",
        "",
        "## Steps",
        "",
    ]
    for step in summary["steps"]:
        lines.append(f"- {step['name']}: `{step['status']}`")
    lines.extend(["", "## Next Action", "", str(summary.get("next_action") or "")])
    return "\n".join(lines) + "\n"


def _manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files = []
    for artifact in artifact_paths:
        if artifact.is_file():
            files.append({"path": safe_relpath(artifact), "byte_size": artifact.stat().st_size, "sha256": sha256_file(artifact)})
    write_json(path, {"run_id": run_id, "script_version": "final-delivery-benchmark-gate-v1", "git_commit": git_commit(), "files": files})


def _sync_bundle(sync_root: Path, run_id: str, artifact_paths: list[Path]) -> tuple[str, list[str]]:
    sync_dir = sync_root / run_id
    sync_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for source in artifact_paths:
        if source.is_file() and source.name in {"result.json", "summary.json", "summary.md", "preview.json", "steps.jsonl"}:
            target = sync_dir / source.name
            shutil.copy2(source, target)
            copied.append(target)
    manifest_path = sync_dir / "manifest.json"
    _manifest(manifest_path, run_id=run_id, artifact_paths=copied)
    copied.append(manifest_path)
    return safe_relpath(sync_dir), [safe_relpath(path) for path in copied]


def run_final_delivery_benchmark_gate(
    *,
    args: argparse.Namespace,
    command_runner: CommandRunner = _default_command_runner,
) -> dict[str, Any]:
    run_id = args.run_id or _now_run_id()
    artifact_dir = (repo_path(args.output_dir) or Path(args.output_dir)) / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)
    preflight_result = preflight(args)
    steps: list[dict[str, Any]] = []

    if preflight_result["status"] == "success":
        steps.append(
            _run_step(
                name="readiness",
                command=_readiness_command(args, run_id),
                command_runner=command_runner,
                timeout_seconds=args.timeout_seconds,
            )
        )
        if not args.skip_answer_policy:
            steps.append(
                _run_step(
                    name="answer_policy_baseline",
                    command=_answer_policy_command(args, run_id),
                    command_runner=command_runner,
                    timeout_seconds=args.timeout_seconds,
                )
            )
        if not args.skip_mpdocvqa_workflow:
            steps.append(
                _run_step(
                    name="mpdocvqa_full_workflow",
                    command=_mpdocvqa_workflow_command(args, run_id),
                    command_runner=command_runner,
                    timeout_seconds=args.timeout_seconds,
                )
            )

    status = "success" if preflight_result["status"] == "success" and steps and all(step["status"] == "success" for step in steps) else "failed"
    used_qwen = args.answer_policy != "heuristic" and any(step["name"] != "readiness" and step["status"] == "success" for step in steps)
    summary = {
        "command": "run_final_delivery_benchmark_gate",
        "status": status,
        "script_version": "final-delivery-benchmark-gate-v1",
        "quality_status": "diagnostic_gate_only",
        "resource_boundary": "server_required",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "preflight": preflight_result,
        "steps": steps,
        "step_count": len(steps),
        "successful_step_count": sum(1 for step in steps if step["status"] == "success"),
        "used_qwen": used_qwen,
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "next_action": "review_gate_artifacts_before_training_or_benchmark_acceptance" if status == "success" else "fix_preflight_or_failed_gate_step",
    }
    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "steps": artifact_dir / "steps.jsonl",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }
    artifact_paths = [safe_relpath(path) for path in paths.values()]
    summary["artifact_paths"] = artifact_paths
    result = {
        "command": summary["command"],
        "status": summary["status"],
        "run_id": run_id,
        "quality_status": summary["quality_status"],
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "used_qwen": used_qwen,
        "used_training": False,
        "preflight_status": preflight_result["status"],
        "step_statuses": {step["name"]: step["status"] for step in steps},
        "next_action": summary["next_action"],
        "artifact_paths": artifact_paths,
    }
    if args.sync_output_dir:
        sync_root = repo_path(args.sync_output_dir) or Path(args.sync_output_dir)
        sync_dir = sync_root / run_id
        sync_artifact_paths = [
            safe_relpath(sync_dir / path.name)
            for path in paths.values()
            if path.name in {"result.json", "summary.json", "summary.md", "preview.json", "steps.jsonl", "manifest.json"}
        ]
        summary["sync_bundle_path"] = safe_relpath(sync_dir)
        result["sync_bundle_path"] = safe_relpath(sync_dir)
        summary["sync_artifact_paths"] = sync_artifact_paths
        result["sync_artifact_paths"] = sync_artifact_paths
    write_json(paths["summary"], summary)
    write_json(paths["result"], result)
    paths["summary_md"].write_text(_summary_markdown(summary), encoding="utf-8")
    write_jsonl(paths["steps"], steps)
    write_json(paths["preview"], {"run_id": run_id, "preflight": preflight_result, "steps": [{k: v for k, v in step.items() if k not in {"stdout_tail", "stderr_tail", "command"}} for step in steps]})
    _manifest(paths["manifest"], run_id=run_id, artifact_paths=[path for key, path in paths.items() if key != "manifest"])
    if args.sync_output_dir:
        _sync_bundle(sync_root, run_id, list(paths.values()))
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Safely orchestrate final-delivery benchmark diagnostics without claiming benchmark acceptance.")
    parser.add_argument("--run-id")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--sync-output-dir", default=str(DEFAULT_SYNC_ROOT))
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--skip-answer-policy", action="store_true")
    parser.add_argument("--skip-mpdocvqa-workflow", action="store_true")
    parser.add_argument("--answer-policy-output-dir", default=str(ROOT / "outputs" / "final_eval" / "answer_policy_baseline"))
    parser.add_argument("--tatqa-samples", default=str(ROOT / "outputs" / "final_eval" / "tatqa_dev_subset" / "samples.jsonl"))
    parser.add_argument("--tatqa-manifest", default=str(ROOT / "outputs" / "final_eval" / "tatqa_dev_subset" / "sample_manifest.jsonl"))
    parser.add_argument("--mpdocvqa-manifest", default=str(ROOT / "outputs" / "final_eval" / "mpdocvqa_val_subset" / "sample_manifest.jsonl"))
    parser.add_argument("--mpdocvqa-evidence-manifest", default=str(ROOT / "outputs" / "final_eval" / "mpdocvqa_val_evidence" / "mpdocvqa_evidence_api_retry_failed_hardened_20260630" / "sample_evidence_manifest.jsonl"))
    parser.add_argument("--mpdocvqa-db-path", default=str(ROOT / "outputs" / "final_eval" / "mpdocvqa_val_evidence" / "mpdocvqa_evidence_api_full_subset_20260630" / "docagent.db"))
    parser.add_argument("--answer-policy-max-samples", type=int)
    parser.add_argument("--mpdocvqa-workflow-output-dir", default=str(ROOT / "outputs" / "final_eval" / "mpdocvqa_full_workflow_diagnostic"))
    parser.add_argument("--mpdocvqa-workflow-evidence-manifest", default=str(ROOT / "outputs" / "final_eval" / "mpdocvqa_val_evidence" / "mpdocvqa_evidence_api_retry_failed_hardened_20260630" / "sample_evidence_manifest.jsonl"))
    parser.add_argument("--mpdocvqa-workflow-db-path", default=str(ROOT / "outputs" / "final_eval" / "mpdocvqa_val_evidence" / "mpdocvqa_evidence_api_full_subset_20260630" / "docagent.db"))
    parser.add_argument("--mpdocvqa-workflow-limit", type=int, default=24)
    parser.add_argument("--mpdocvqa-workflow-offset", type=int, default=0)
    parser.add_argument("--sample-ids")
    parser.add_argument("--router-llm-env-file", default=".secrets/router_llm.env")
    parser.add_argument("--retriever-mode", choices=["bm25", "dense", "hybrid", "hybrid_rerank"], default="hybrid_rerank")
    parser.add_argument("--dense-backend", choices=["bge", "hash"], default="bge")
    parser.add_argument("--dense-model-path", default=DEFAULT_BGE_MODEL_PATH)
    parser.add_argument("--dense-device", default="cuda:0")
    parser.add_argument("--dense-fp16", action="store_true")
    parser.add_argument("--reranker-backend", choices=["cross_encoder", "keyword"], default="cross_encoder")
    parser.add_argument("--reranker-model-path", default=DEFAULT_RERANKER_MODEL_PATH)
    parser.add_argument("--reranker-device", default="cpu")
    parser.add_argument("--reranker-fp16", action="store_true")
    parser.add_argument("--answer-policy", choices=["heuristic", "base", "sft", "grpo"], default="base")
    parser.add_argument("--base-model-path", default=DEFAULT_QWEN_BASE_MODEL_PATH)
    parser.add_argument("--adapter-path")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--answer-policy-max-new-tokens", type=int, default=1024)
    parser.add_argument("--mpdocvqa-max-new-tokens", type=int, default=512)
    parser.add_argument("--top-k", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    result = run_final_delivery_benchmark_gate(args=args)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default))


if __name__ == "__main__":
    main()

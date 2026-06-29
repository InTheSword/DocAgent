from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.models.base import AnswerPolicy, HeuristicAnswerPolicy
from docagent.schemas import DocAgentSample
from docagent.utils.jsonl import read_jsonl, write_jsonl
from docagent.workflow.answer_contract import candidate_citation_ids, primary_location_from_output
from docagent.workflow.graph import run_qa_workflow
from scripts.run_final_eval_subset import answer_metrics, as_list, gold_block_ids, load_manifest, safe_relpath, write_json


SCRIPT_VERSION = "final-answer-policy-baseline-v1"
EVALUATION_SCOPE = "final_subset_answer_policy_baseline_not_formal_benchmark"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "answer_policy_baseline"
DEFAULT_TATQA_SAMPLES = ROOT / "outputs" / "final_eval" / "tatqa_dev_subset" / "samples.jsonl"
DEFAULT_TATQA_MANIFEST = ROOT / "outputs" / "final_eval" / "tatqa_dev_subset" / "sample_manifest.jsonl"
DEFAULT_MPDOCVQA_MANIFEST = ROOT / "outputs" / "final_eval" / "mpdocvqa_val_subset" / "sample_manifest.jsonl"
DEFAULT_QWEN_BASE_MODEL_PATH = "/root/autodl-tmp/models/Qwen3-1.7B"


def repo_path(path: str | Path | None) -> Path | None:
    if path is None:
        return None
    value = Path(path)
    return value if value.is_absolute() else ROOT / value


def now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"final_answer_policy_{stamp}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit() -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            check=True,
            text=True,
            capture_output=True,
        )
        return completed.stdout.strip()
    except Exception:
        return ""


def load_samples(path: Path | None) -> list[DocAgentSample]:
    if path is None or not path.is_file():
        return []
    return [DocAgentSample.from_dict(row) for row in read_jsonl(path)]


def build_answer_policy(
    *,
    answer_policy: str,
    base_model_path: str,
    adapter_path: str | None,
    device: str,
    torch_dtype: str,
    max_prompt_tokens: int | None,
    max_new_tokens: int,
) -> AnswerPolicy:
    if answer_policy == "heuristic":
        return HeuristicAnswerPolicy()
    from docagent.models.qwen_answer_policy import QwenAnswerPolicy, QwenAnswerPolicyConfig

    return QwenAnswerPolicy(
        QwenAnswerPolicyConfig(
            mode=answer_policy,
            base_model_path=base_model_path,
            adapter_path=adapter_path,
            device=device,
            torch_dtype=torch_dtype,
            max_prompt_tokens=max_prompt_tokens,
            max_new_tokens=max_new_tokens,
        )
    )


def preflight_model(answer_policy: str, base_model_path: str, adapter_path: str | None) -> dict[str, Any]:
    if answer_policy == "heuristic":
        return {"status": "success", "requires_qwen": False}
    model_path = Path(base_model_path)
    if not (model_path / "config.json").is_file():
        return {
            "status": "blocked",
            "type": "missing_base_model_config",
            "message": f"base model is missing config.json: {model_path}",
            "base_model_path": str(model_path),
        }
    if answer_policy in {"sft", "grpo"}:
        if not adapter_path:
            return {"status": "blocked", "type": "missing_adapter_path", "message": f"adapter_path is required for {answer_policy}"}
        adapter = Path(adapter_path)
        if not (adapter / "adapter_config.json").is_file():
            return {
                "status": "blocked",
                "type": "missing_adapter_config",
                "message": f"adapter is missing adapter_config.json: {adapter}",
                "adapter_path": str(adapter),
            }
        if not any((adapter / name).is_file() for name in ("adapter_model.safetensors", "adapter_model.bin")):
            return {
                "status": "blocked",
                "type": "missing_adapter_weights",
                "message": f"adapter is missing adapter weights: {adapter}",
                "adapter_path": str(adapter),
            }
    return {"status": "success", "requires_qwen": True, "base_model_path": str(model_path)}


def row_from_skipped_mpdocvqa(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "sample_id": str(manifest.get("sample_id") or ""),
        "dataset": "mp_docvqa",
        "doc_id": str(manifest.get("doc_id") or ""),
        "question": str(manifest.get("question") or ""),
        "evaluation_mode": "skipped_requires_raw_pdf_mineru_retrieval",
        "skip_reason": "mpdocvqa_page_manifest_has_no_evidence_blocks_for_direct_answer_policy",
        "pass_fail": "skipped",
        "requires_mineru_or_retrieval": True,
        "requires_model_answer": True,
        "answer_evaluated": False,
        "citation_evaluated": False,
        "format_valid": False,
        "used_qwen": False,
    }


def should_run_answer_policy(manifest: dict[str, Any]) -> bool:
    tools = {str(item) for item in manifest.get("expected_tools") or []}
    return "local_fact_qa" in tools


def evaluate_tatqa_sample(
    *,
    sample: DocAgentSample,
    manifest: dict[str, Any],
    answer_policy: AnswerPolicy,
    top_k: int,
    preserve_input_order: bool,
) -> dict[str, Any]:
    expected_tools = [str(item) for item in manifest.get("expected_tools") or []]
    answers = as_list(manifest.get("answers") if "answers" in manifest else sample.answer)
    expected_answer_type = str(manifest.get("expected_answer_type") or sample.answer_type)
    gold_ids = gold_block_ids(manifest, sample)
    base = {
        "sample_id": sample.qid,
        "dataset": "tatqa",
        "doc_id": sample.doc_id,
        "question": sample.question,
        "answers": answers,
        "expected_tools": expected_tools,
        "expected_answer_type": expected_answer_type,
        "gold_block_ids": sorted(gold_ids),
        "requires_model_answer": True,
        "requires_mineru_or_retrieval": False,
        "answer_policy_mode": str(getattr(answer_policy, "mode", "unknown")),
        "used_qwen": str(getattr(answer_policy, "mode", "")) in {"base", "sft", "grpo"},
    }
    if not should_run_answer_policy(manifest):
        return {
            **base,
            "evaluation_mode": "skipped_deterministic_tool_case",
            "skip_reason": "expected_tools_do_not_include_local_fact_qa",
            "pass_fail": "skipped",
            "answer_evaluated": False,
            "citation_evaluated": False,
            "format_valid": False,
        }

    try:
        state = run_qa_workflow(
            qid=sample.qid,
            question=sample.question,
            blocks=sample.evidence,
            answer_policy=answer_policy,
            top_k=top_k,
            answer_type_hint=sample.answer_type,
            doc_id=sample.doc_id,
            preserve_input_order=preserve_input_order,
        )
    except Exception as exc:
        return {
            **base,
            "evaluation_mode": "answer_policy_generation",
            "pass_fail": "failed",
            "failure_stage": "answer_policy",
            "failure_reasons": [type(exc).__name__],
            "error": {"type": type(exc).__name__, "message": str(exc)},
            "answer_evaluated": False,
            "citation_evaluated": False,
            "format_valid": False,
        }

    final_answer = state.final_answer if isinstance(state.final_answer, dict) else {}
    prediction = str(final_answer.get("answer") or "")
    metrics = answer_metrics(prediction, answers, expected_answer_type)
    citation_ids = set(candidate_citation_ids(final_answer))
    location = primary_location_from_output(final_answer)
    if location.get("block_id"):
        citation_ids.add(str(location["block_id"]))
    citation_block_hit = bool(gold_ids and citation_ids and gold_ids.intersection(citation_ids))
    citation_evaluated = bool(gold_ids)
    format_valid = bool((state.format_check or {}).get("success"))
    location_valid = bool((state.location_check or {}).get("success"))
    pass_fail = "passed" if format_valid and location_valid and metrics.get("answer_hit") and (not citation_evaluated or citation_block_hit) else "failed"
    failure_reasons = failure_reasons_for_row(
        format_valid=format_valid,
        location_valid=location_valid,
        answer_hit=bool(metrics.get("answer_hit")),
        citation_evaluated=citation_evaluated,
        citation_block_hit=citation_block_hit,
    )
    return {
        **base,
        "evaluation_mode": "answer_policy_generation",
        "pass_fail": pass_fail,
        "failure_reasons": failure_reasons,
        "failure_stage": failure_stage(failure_reasons),
        "format_valid": format_valid,
        "location_valid": location_valid,
        "answer_evaluated": True,
        "prediction_answer": prediction,
        "reasoning_summary": str(final_answer.get("reasoning_summary") or final_answer.get("reason") or ""),
        "citation_evaluated": citation_evaluated,
        "citation_block_hit": citation_block_hit,
        "citation_block_ids": sorted(citation_ids),
        "final_answer_keys": sorted(final_answer),
        "prompt_version": state.generation_metadata.get("prompt_version"),
        "parse_result": state.parse_result,
        "retrieved_block_ids": [block.block_id for block in state.retrieved_blocks],
        "trace_step_count": len(state.trace),
        **metrics,
    }


def failure_reasons_for_row(
    *,
    format_valid: bool,
    location_valid: bool,
    answer_hit: bool,
    citation_evaluated: bool,
    citation_block_hit: bool,
) -> list[str]:
    reasons: list[str] = []
    if not format_valid:
        reasons.append("format_invalid")
    if not location_valid:
        reasons.append("location_invalid")
    if citation_evaluated and not citation_block_hit:
        reasons.append("citation_block_miss")
    if not answer_hit:
        reasons.append("answer_miss")
    return reasons


def failure_stage(reasons: list[str]) -> str:
    if not reasons:
        return ""
    order = [
        ("format", {"format_invalid"}),
        ("location", {"location_invalid"}),
        ("attribution", {"citation_block_miss"}),
        ("answer_quality", {"answer_miss"}),
    ]
    reason_set = set(reasons)
    for stage, markers in order:
        if reason_set.intersection(markers):
            return stage
    return "other"


def summarize(rows: list[dict[str, Any]], *, run_id: str, artifact_dir: Path, answer_policy: str) -> dict[str, Any]:
    status_counts = Counter(str(row.get("pass_fail") or "") for row in rows)
    evaluated = [row for row in rows if row.get("evaluation_mode") == "answer_policy_generation"]
    evaluated_count = len(evaluated)
    failure_reasons = Counter(reason for row in rows for reason in row.get("failure_reasons") or [])
    failure_stages = Counter(str(row.get("failure_stage") or "") for row in rows if row.get("failure_stage"))
    used_qwen = any(bool(row.get("used_qwen")) for row in rows) or answer_policy in {"base", "sft", "grpo"}
    summary = {
        "command": "run_final_answer_policy_baseline",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "quality_status_semantics": "answer policy baseline over prepared subset evidence; not formal MP-DocVQA/TAT-QA benchmark acceptance",
        "resource_boundary": "server_required" if used_qwen else "local_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "answer_policy_mode": answer_policy,
        "case_count": len(rows),
        "evaluated_count": evaluated_count,
        "passed_count": status_counts.get("passed", 0),
        "failed_count": status_counts.get("failed", 0),
        "skipped_count": status_counts.get("skipped", 0),
        "pass_rate": round(status_counts.get("passed", 0) / evaluated_count, 4) if evaluated_count else 0.0,
        "format_valid_count": sum(1 for row in evaluated if row.get("format_valid")),
        "format_valid_rate": rate(sum(1 for row in evaluated if row.get("format_valid")), evaluated_count),
        "location_valid_count": sum(1 for row in evaluated if row.get("location_valid")),
        "location_valid_rate": rate(sum(1 for row in evaluated if row.get("location_valid")), evaluated_count),
        "answer_hit_count": sum(1 for row in evaluated if row.get("answer_hit")),
        "answer_hit_rate": rate(sum(1 for row in evaluated if row.get("answer_hit")), evaluated_count),
        "citation_block_hit_count": sum(1 for row in evaluated if row.get("citation_block_hit")),
        "citation_block_hit_rate": rate(sum(1 for row in evaluated if row.get("citation_block_hit")), sum(1 for row in evaluated if row.get("citation_evaluated"))),
        "json_valid_count": sum(1 for row in evaluated if (row.get("parse_result") or {}).get("raw_json_ok")),
        "schema_valid_count": sum(1 for row in evaluated if (row.get("parse_result") or {}).get("schema_ok")),
        "used_qwen": used_qwen,
        "used_vlm": False,
        "used_training": False,
        "used_online_mineru_ocr": False,
        "used_external_api": False,
        "formal_benchmark_acceptance": False,
        "failure_reason_distribution": dict(sorted(failure_reasons.items())),
        "failure_stage_distribution": dict(sorted(failure_stages.items())),
        "results_path": safe_relpath(artifact_dir / "results.jsonl"),
        "summary_path": safe_relpath(artifact_dir / "summary.json"),
        "summary_markdown_path": safe_relpath(artifact_dir / "summary.md"),
        "preview_path": safe_relpath(artifact_dir / "preview.json"),
        "failures_sample_path": safe_relpath(artifact_dir / "failures_sample.jsonl"),
        "manifest_path": safe_relpath(artifact_dir / "manifest.json"),
    }
    return summary


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Final AnswerPolicy Baseline",
        "",
        f"- evaluation_scope: `{summary['evaluation_scope']}`",
        f"- quality_status: `{summary['quality_status']}`",
        f"- resource_boundary: `{summary['resource_boundary']}`",
        f"- answer_policy_mode: `{summary['answer_policy_mode']}`",
        f"- used_qwen: `{str(summary['used_qwen']).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary['formal_benchmark_acceptance']).lower()}`",
        "",
        "## Counts",
        "",
        f"- case_count: {summary['case_count']}",
        f"- evaluated_count: {summary['evaluated_count']}",
        f"- passed_count: {summary['passed_count']}",
        f"- failed_count: {summary['failed_count']}",
        f"- skipped_count: {summary['skipped_count']}",
        f"- pass_rate: {summary['pass_rate']}",
        "",
        "## Metrics",
        "",
        f"- format_valid_rate: {summary['format_valid_rate']}",
        f"- location_valid_rate: {summary['location_valid_rate']}",
        f"- answer_hit_rate: {summary['answer_hit_rate']}",
        f"- citation_block_hit_rate: {summary['citation_block_hit_rate']}",
        f"- json_valid_count: {summary['json_valid_count']}",
        f"- schema_valid_count: {summary['schema_valid_count']}",
        "",
        "## Failure Taxonomy",
        "",
        *markdown_distribution(summary.get("failure_stage_distribution") or {}),
        "",
        "This runner is a baseline diagnostic. Promotion beyond `implemented` requires a real Qwen server run and review of these artifacts.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def markdown_distribution(distribution: dict[str, Any]) -> list[str]:
    if not distribution:
        return ["- none"]
    return [f"- {key}: {value}" for key, value in sorted(distribution.items())]


def write_manifest(path: Path, *, run_id: str, artifact_dir: Path, summary: dict[str, Any], artifact_paths: list[Path]) -> None:
    payload = {
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "git_commit": git_commit(),
        "artifact_dir": safe_relpath(artifact_dir),
        "summary": {
            "status": summary.get("status"),
            "answer_policy_mode": summary.get("answer_policy_mode"),
            "used_qwen": summary.get("used_qwen"),
            "evaluated_count": summary.get("evaluated_count"),
        },
        "files": [
            {
                "path": safe_relpath(path),
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in artifact_paths
            if path.is_file()
        ],
    }
    write_json(path, payload)


def result_payload(summary: dict[str, Any], artifact_paths: list[Path]) -> dict[str, Any]:
    return {
        "command": summary.get("command", "run_final_answer_policy_baseline"),
        "status": summary.get("status"),
        "run_id": summary.get("run_id"),
        "artifact_dir": summary.get("artifact_dir"),
        "quality_status": summary.get("quality_status"),
        "resource_boundary": summary.get("resource_boundary"),
        "answer_policy_mode": summary.get("answer_policy_mode"),
        "used_qwen": bool(summary.get("used_qwen", False)),
        "used_vlm": bool(summary.get("used_vlm", False)),
        "used_training": bool(summary.get("used_training", False)),
        "formal_benchmark_acceptance": bool(summary.get("formal_benchmark_acceptance", False)),
        "metrics": {
            "case_count": summary.get("case_count", 0),
            "evaluated_count": summary.get("evaluated_count", 0),
            "passed_count": summary.get("passed_count", 0),
            "failed_count": summary.get("failed_count", 0),
            "skipped_count": summary.get("skipped_count", 0),
            "pass_rate": summary.get("pass_rate", 0.0),
            "format_valid_rate": summary.get("format_valid_rate", 0.0),
            "location_valid_rate": summary.get("location_valid_rate", 0.0),
            "answer_hit_rate": summary.get("answer_hit_rate", 0.0),
            "citation_block_hit_rate": summary.get("citation_block_hit_rate", 0.0),
        },
        "artifact_paths": [safe_relpath(path) for path in artifact_paths if path.is_file() or path.name == "result.json"],
    }


def write_text_tail(source: Path | None, target: Path, *, max_lines: int = 120) -> None:
    if source is None or not source.is_file():
        target.write_text("No log file was provided to this runner.\n", encoding="utf-8")
        return
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    target.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")


def create_sync_bundle(
    *,
    sync_root: Path,
    run_id: str,
    artifact_dir: Path,
    summary: dict[str, Any],
    artifact_paths: list[Path],
    log_file: Path | None = None,
    stderr_file: Path | None = None,
) -> tuple[Path, list[Path]]:
    sync_dir = sync_root / run_id
    sync_dir.mkdir(parents=True, exist_ok=True)
    copy_names = {
        "result.json",
        "summary.json",
        "summary.md",
        "preview.json",
        "failures_sample.jsonl",
    }
    copied: list[Path] = []
    for source in artifact_paths:
        if source.name not in copy_names or not source.is_file():
            continue
        target = sync_dir / source.name
        target.write_bytes(source.read_bytes())
        copied.append(target)
    log_tail = sync_dir / "log_tail.txt"
    stderr_tail = sync_dir / "stderr_tail.txt"
    write_text_tail(log_file, log_tail)
    write_text_tail(stderr_file, stderr_tail)
    copied.extend([log_tail, stderr_tail])
    write_manifest(sync_dir / "manifest.json", run_id=run_id, artifact_dir=artifact_dir, summary=summary, artifact_paths=copied)
    copied.append(sync_dir / "manifest.json")
    return sync_dir, copied


def blocked_result(*, run_id: str, artifact_dir: Path, preflight: dict[str, Any], answer_policy: str) -> dict[str, Any]:
    artifact_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "command": "run_final_answer_policy_baseline",
        "status": "blocked",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "blocked",
        "resource_boundary": "server_required",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "answer_policy_mode": answer_policy,
        "blocker": preflight,
        "used_qwen": False,
        "used_vlm": False,
        "used_training": False,
        "formal_benchmark_acceptance": False,
    }
    artifact_paths = [
        artifact_dir / "result.json",
        artifact_dir / "results.jsonl",
        artifact_dir / "summary.json",
        artifact_dir / "summary.md",
        artifact_dir / "preview.json",
        artifact_dir / "failures_sample.jsonl",
    ]
    summary["result_path"] = safe_relpath(artifact_paths[0])
    write_jsonl(artifact_paths[1], [])
    write_json(artifact_paths[2], summary)
    write_summary_markdown(artifact_paths[3], {**summary, **default_count_summary()})
    write_json(artifact_paths[4], {"summary": summary, "results": []})
    write_jsonl(artifact_paths[5], [])
    write_json(artifact_paths[0], result_payload({**summary, **default_count_summary()}, artifact_paths))
    write_manifest(artifact_dir / "manifest.json", run_id=run_id, artifact_dir=artifact_dir, summary=summary, artifact_paths=artifact_paths)
    return {
        **summary,
        "artifact_paths": [safe_relpath(path) for path in [*artifact_paths, artifact_dir / "manifest.json"]],
    }


def default_count_summary() -> dict[str, Any]:
    return {
        "case_count": 0,
        "evaluated_count": 0,
        "passed_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "pass_rate": 0.0,
        "format_valid_rate": 0.0,
        "location_valid_rate": 0.0,
        "answer_hit_rate": 0.0,
        "citation_block_hit_rate": 0.0,
        "json_valid_count": 0,
        "schema_valid_count": 0,
        "failure_stage_distribution": {},
    }


def run_final_answer_policy_baseline(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    tatqa_samples: Path | None = DEFAULT_TATQA_SAMPLES,
    tatqa_manifest: Path | None = DEFAULT_TATQA_MANIFEST,
    mpdocvqa_manifest: Path | None = DEFAULT_MPDOCVQA_MANIFEST,
    max_samples: int | None = None,
    answer_policy_mode: str = "base",
    base_model_path: str = DEFAULT_QWEN_BASE_MODEL_PATH,
    adapter_path: str | None = None,
    device: str = "cuda",
    torch_dtype: str = "bfloat16",
    max_prompt_tokens: int | None = 4096,
    max_new_tokens: int = 1024,
    top_k: int = 5,
    preserve_input_order: bool = False,
    answer_policy: AnswerPolicy | None = None,
    sync_output_root: Path | None = None,
    log_file: Path | None = None,
    stderr_file: Path | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    if answer_policy is None:
        preflight = preflight_model(answer_policy_mode, base_model_path, adapter_path)
        if preflight["status"] != "success":
            result = blocked_result(run_id=run_id, artifact_dir=artifact_dir, preflight=preflight, answer_policy=answer_policy_mode)
            if sync_output_root is not None:
                sync_dir, sync_paths = create_sync_bundle(
                    sync_root=sync_output_root,
                    run_id=run_id,
                    artifact_dir=artifact_dir,
                    summary=result,
                    artifact_paths=[artifact_dir / Path(path).name for path in result["artifact_paths"]],
                    log_file=log_file,
                    stderr_file=stderr_file,
                )
                result["sync_bundle_path"] = safe_relpath(sync_dir)
                result["sync_artifact_paths"] = [safe_relpath(path) for path in sync_paths]
            return result
        answer_policy = build_answer_policy(
            answer_policy=answer_policy_mode,
            base_model_path=base_model_path,
            adapter_path=adapter_path,
            device=device,
            torch_dtype=torch_dtype,
            max_prompt_tokens=max_prompt_tokens,
            max_new_tokens=max_new_tokens,
        )

    manifest_by_id = load_manifest(tatqa_manifest)
    samples = load_samples(tatqa_samples)
    if max_samples is not None:
        samples = samples[: max(0, int(max_samples))]

    rows = [
        evaluate_tatqa_sample(
            sample=sample,
            manifest=manifest_by_id.get(sample.qid, {}),
            answer_policy=answer_policy,
            top_k=top_k,
            preserve_input_order=preserve_input_order,
        )
        for sample in samples
    ]
    mp_rows = list(load_manifest(mpdocvqa_manifest).values())
    if max_samples is not None:
        mp_rows = mp_rows[: max(0, int(max_samples))]
    rows.extend(row_from_skipped_mpdocvqa(row) for row in mp_rows)

    summary = summarize(rows, run_id=run_id, artifact_dir=artifact_dir, answer_policy=str(getattr(answer_policy, "mode", answer_policy_mode)))
    failures = [row for row in rows if row.get("pass_fail") == "failed"][:50]
    artifact_paths = [
        artifact_dir / "result.json",
        artifact_dir / "results.jsonl",
        artifact_dir / "summary.json",
        artifact_dir / "summary.md",
        artifact_dir / "preview.json",
        artifact_dir / "failures_sample.jsonl",
    ]
    summary["result_path"] = safe_relpath(artifact_paths[0])
    write_jsonl(artifact_paths[1], rows)
    write_json(artifact_paths[2], summary)
    write_summary_markdown(artifact_paths[3], summary)
    write_json(artifact_paths[4], {"summary": summary, "results": rows[:5]})
    write_jsonl(artifact_paths[5], failures)
    write_json(artifact_paths[0], result_payload(summary, artifact_paths))
    write_manifest(artifact_dir / "manifest.json", run_id=run_id, artifact_dir=artifact_dir, summary=summary, artifact_paths=artifact_paths)
    result = {
        **summary,
        "artifact_paths": [safe_relpath(path) for path in [*artifact_paths, artifact_dir / "manifest.json"]],
    }
    if sync_output_root is not None:
        sync_dir, sync_paths = create_sync_bundle(
            sync_root=sync_output_root,
            run_id=run_id,
            artifact_dir=artifact_dir,
            summary=summary,
            artifact_paths=[*artifact_paths, artifact_dir / "manifest.json"],
            log_file=log_file,
            stderr_file=stderr_file,
        )
        result["sync_bundle_path"] = safe_relpath(sync_dir)
        result["sync_artifact_paths"] = [safe_relpath(path) for path in sync_paths]
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run AnswerPolicy/Qwen baseline over prepared final-evaluation subset evidence.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--tatqa-samples", default=str(DEFAULT_TATQA_SAMPLES))
    parser.add_argument("--tatqa-manifest", default=str(DEFAULT_TATQA_MANIFEST))
    parser.add_argument("--mpdocvqa-manifest", default=str(DEFAULT_MPDOCVQA_MANIFEST))
    parser.add_argument("--max-samples", type=int)
    parser.add_argument("--answer-policy", choices=["heuristic", "base", "sft", "grpo"], default="base")
    parser.add_argument("--base-model-path", default=DEFAULT_QWEN_BASE_MODEL_PATH)
    parser.add_argument("--adapter-path")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--preserve-input-order", action="store_true")
    parser.add_argument("--sync-output-dir")
    parser.add_argument("--log-file")
    parser.add_argument("--stderr-file")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_final_answer_policy_baseline(
        output_root=repo_path(args.output_dir) or DEFAULT_OUTPUT_ROOT,
        run_id=args.run_id,
        tatqa_samples=repo_path(args.tatqa_samples),
        tatqa_manifest=repo_path(args.tatqa_manifest),
        mpdocvqa_manifest=repo_path(args.mpdocvqa_manifest),
        max_samples=args.max_samples,
        answer_policy_mode=str(args.answer_policy),
        base_model_path=str(args.base_model_path),
        adapter_path=str(args.adapter_path) if args.adapter_path else None,
        device=str(args.device),
        torch_dtype=str(args.torch_dtype),
        max_prompt_tokens=args.max_prompt_tokens,
        max_new_tokens=int(args.max_new_tokens),
        top_k=int(args.top_k),
        preserve_input_order=bool(args.preserve_input_order),
        sync_output_root=repo_path(args.sync_output_dir),
        log_file=repo_path(args.log_file),
        stderr_file=repo_path(args.stderr_file),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

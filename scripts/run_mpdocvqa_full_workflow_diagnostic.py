from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_final_eval_subset import answer_metrics, as_list, citation_pages


SCRIPT_VERSION = "mpdocvqa-full-workflow-diagnostic-v1"
EVALUATION_SCOPE = "mpdocvqa_cli_full_workflow_diagnostic_not_formal_benchmark"
DEFAULT_EVIDENCE_MANIFEST = (
    ROOT
    / "outputs"
    / "final_eval"
    / "mpdocvqa_val_evidence"
    / "mpdocvqa_evidence_api_retry_failed_hardened_20260630"
    / "sample_evidence_manifest.jsonl"
)
DEFAULT_DB_PATH = (
    ROOT
    / "outputs"
    / "final_eval"
    / "mpdocvqa_val_evidence"
    / "mpdocvqa_evidence_api_full_subset_20260630"
    / "docagent.db"
)
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "mpdocvqa_full_workflow_diagnostic"
DEFAULT_CLI_PATH = ROOT / "scripts" / "docagent_cli.py"
DEFAULT_QWEN_BASE_MODEL_PATH = "/root/autodl-tmp/models/Qwen3-1.7B"
DEFAULT_BGE_MODEL_PATH = "/root/autodl-tmp/models/bge-m3"
DEFAULT_RERANKER_MODEL_PATH = "/root/autodl-tmp/models/bge-reranker-v2-m3"


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str = ""


CommandRunner = Callable[[list[str], Path, int], CommandResult]


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


def now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"mpdocvqa_full_workflow_{stamp}"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _default_command_runner(command: list[str], cwd: Path, timeout_seconds: int) -> CommandResult:
    completed = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=timeout_seconds, check=False)
    return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def parse_stdout(stdout: str) -> tuple[dict[str, Any] | None, str]:
    text = (stdout or "").strip()
    if not text:
        return None, "stdout_empty"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                return None, "stdout_not_json"
        else:
            return None, "stdout_not_json"
    return (payload, "") if isinstance(payload, dict) else (None, "stdout_json_not_object")


def load_rows(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    return [row for row in read_jsonl(path) if isinstance(row, dict)]


def selected_samples(rows: list[dict[str, Any]], *, limit: int, offset: int, sample_ids: set[str] | None = None) -> list[dict[str, Any]]:
    filtered = [
        row
        for row in rows
        if str(row.get("dataset") or "") in {"mp_docvqa", "mpdocvqa"}
        and row.get("evidence_ready") is True
        and str(row.get("ingested_doc_id") or "")
    ]
    if sample_ids:
        filtered = [row for row in filtered if str(row.get("sample_id") or "") in sample_ids]
    if offset:
        filtered = filtered[offset:]
    return filtered[:limit] if limit > 0 else filtered


def gold_pages(row: dict[str, Any]) -> set[int]:
    pages: set[int] = set()
    for value in row.get("gold_pages") or []:
        try:
            pages.add(int(value))
        except (TypeError, ValueError):
            continue
    return pages


def page_set(values: Any) -> set[int]:
    if not isinstance(values, list):
        values = [values] if values not in (None, "") else []
    pages: set[int] = set()
    for value in values:
        try:
            pages.add(int(value))
        except (TypeError, ValueError):
            continue
    return pages


def workflow_trace(result: dict[str, Any]) -> list[dict[str, Any]]:
    trace = result.get("workflow_trace")
    if isinstance(trace, list):
        return [item for item in trace if isinstance(item, dict)]
    trace_path = Path(str(result.get("trace_path") or ""))
    if trace_path.is_file():
        try:
            payload = json.loads(trace_path.read_text(encoding="utf-8"))
            trace = payload.get("workflow_trace") if isinstance(payload, dict) else []
            return [item for item in trace if isinstance(item, dict)]
        except Exception:
            return []
    return []


def trace_steps(trace: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("step") or item.get("node") or item.get("name") or "") for item in trace]


def retrieve_candidates(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for item in trace:
        if str(item.get("step") or item.get("node") or "") == "retrieve_evidence":
            candidates = item.get("candidates")
            return [candidate for candidate in candidates if isinstance(candidate, dict)] if isinstance(candidates, list) else []
    return []


def selected_block_ids(trace: list[dict[str, Any]]) -> list[str]:
    for item in trace:
        if str(item.get("step") or item.get("node") or "") == "build_evidence_context":
            return [str(block_id) for block_id in item.get("selected_block_ids") or [] if str(block_id or "").strip()]
    return []


def candidate_pages(candidates: list[dict[str, Any]]) -> set[int]:
    return page_set([candidate.get("page") for candidate in candidates])


def page_by_block(candidates: list[dict[str, Any]]) -> dict[str, int]:
    pages: dict[str, int] = {}
    for candidate in candidates:
        block_id = str(candidate.get("block_id") or "")
        if not block_id:
            continue
        try:
            pages[block_id] = int(candidate.get("page"))
        except (TypeError, ValueError):
            continue
    return pages


def pages_for_block_ids(block_ids: list[str], pages: dict[str, int]) -> set[int]:
    return {pages[block_id] for block_id in block_ids if block_id in pages}


def first_gold_rank(candidates: list[dict[str, Any]], pages: set[int]) -> int | None:
    if not pages:
        return None
    for index, candidate in enumerate(candidates, start=1):
        try:
            page = int(candidate.get("page"))
        except (TypeError, ValueError):
            continue
        if page in pages:
            return int(candidate.get("final_rank") or index)
    return None


def citation_block_ids(citations: list[dict[str, Any]]) -> list[str]:
    return [str(item.get("block_id")) for item in citations if isinstance(item, dict) and str(item.get("block_id") or "")]


def row_bucket(
    *,
    cli_success: bool,
    task_type: str,
    retrieved_hit: bool,
    selected_hit: bool,
    selected_pages: set[int],
    citation_hit: bool,
    answer_hit: bool,
) -> str:
    if not cli_success:
        return "cli_execution_failed"
    if task_type != "local_fact_qa":
        return "task_type_not_local_fact_qa"
    if not retrieved_hit:
        return "retrieval_gold_page_miss"
    if selected_pages and not selected_hit:
        return "selected_context_gold_page_miss"
    if not citation_hit:
        return "citation_selection_page_miss"
    if not answer_hit:
        return "answer_generation_or_metric_miss"
    return "passed"


def build_cli_command(
    *,
    python_executable: str,
    cli_path: Path,
    db_path: Path,
    output_dir: Path,
    sample: dict[str, Any],
    args: argparse.Namespace,
) -> list[str]:
    command = [
        python_executable,
        str(cli_path),
        "--db-path",
        str(db_path),
        "--output-dir",
        str(output_dir),
        "--doc-id",
        str(sample.get("ingested_doc_id") or ""),
        "--question",
        str(sample.get("question") or ""),
        "--full-model-path",
        "--router-llm-env-file",
        str(args.router_llm_env_file),
        "--router-llm-threshold",
        str(args.router_llm_threshold),
        "--retriever-mode",
        str(args.retriever_mode),
        "--dense-backend",
        str(args.dense_backend),
        "--dense-model-path",
        str(args.dense_model_path),
        "--dense-device",
        str(args.dense_device),
        "--build-dense-index-if-missing",
        "--reranker-backend",
        str(args.reranker_backend),
        "--reranker-model-path",
        str(args.reranker_model_path),
        "--reranker-device",
        str(args.reranker_device),
        "--answer-policy",
        str(args.answer_policy),
        "--base-model-path",
        str(args.base_model_path),
        "--device",
        str(args.device),
        "--torch-dtype",
        str(args.torch_dtype),
        "--max-prompt-tokens",
        str(args.max_prompt_tokens),
        "--max-new-tokens",
        str(args.max_new_tokens),
    ]
    if args.dense_fp16:
        command.append("--dense-fp16")
    if args.reranker_fp16:
        command.append("--reranker-fp16")
    return command


def evaluate_result(sample: dict[str, Any], result: dict[str, Any] | None, completed: CommandResult, parse_error: str) -> dict[str, Any]:
    result = result or {}
    trace = workflow_trace(result)
    candidates = retrieve_candidates(trace)
    block_pages = page_by_block(candidates)
    selected_ids = selected_block_ids(trace)
    selected_pages = pages_for_block_ids(selected_ids, block_pages)
    retrieved_pages = candidate_pages(candidates)
    citations = [item for item in result.get("citations") or [] if isinstance(item, dict)]
    cited_pages = citation_pages(citations)
    gold = gold_pages(sample)
    metrics = answer_metrics(
        str(result.get("answer") or ""),
        as_list(sample.get("answers")),
        str(sample.get("expected_answer_type") or "extractive"),
    )
    cli_success = completed.returncode == 0 and not parse_error and result.get("status") == "success"
    retrieved_hit = bool(gold and retrieved_pages and gold.intersection(retrieved_pages))
    selected_hit = bool(gold and selected_pages and gold.intersection(selected_pages))
    citation_hit = bool(gold and cited_pages and gold.intersection(cited_pages))
    answer_hit = bool(metrics.get("answer_hit"))
    task_type = str(result.get("task_type") or "")
    bucket = row_bucket(
        cli_success=cli_success,
        task_type=task_type,
        retrieved_hit=retrieved_hit,
        selected_hit=selected_hit,
        selected_pages=selected_pages,
        citation_hit=citation_hit,
        answer_hit=answer_hit,
    )
    return {
        "sample_id": str(sample.get("sample_id") or ""),
        "dataset": "mp_docvqa",
        "doc_id": str(sample.get("doc_id") or ""),
        "ingested_doc_id": str(sample.get("ingested_doc_id") or ""),
        "source_document": str(sample.get("source_document") or ""),
        "question": str(sample.get("question") or ""),
        "answers": as_list(sample.get("answers")),
        "expected_answer_type": str(sample.get("expected_answer_type") or "extractive"),
        "gold_pages": sorted(gold),
        "pass_fail": "passed" if bucket == "passed" else "failed",
        "bucket": bucket,
        "returncode": completed.returncode,
        "stdout_parse_error": parse_error,
        "cli_status": result.get("status") or "",
        "task_type": task_type,
        "answer": str(result.get("answer") or ""),
        "reasoning_summary": str(result.get("reasoning_summary") or ""),
        "answer_hit": answer_hit,
        "citation_page_hit": citation_hit,
        "retrieved_gold_page_hit": retrieved_hit,
        "selected_gold_page_hit": selected_hit,
        "retrieved_gold_page_rank": first_gold_rank(candidates, gold),
        "retrieved_pages": sorted(retrieved_pages),
        "selected_pages": sorted(selected_pages),
        "citation_pages": sorted(cited_pages),
        "retrieved_block_ids": [str(candidate.get("block_id") or "") for candidate in candidates if candidate.get("block_id")],
        "selected_block_ids": selected_ids,
        "citation_block_ids": citation_block_ids(citations),
        "retrieval_candidate_count": int(result.get("retrieval_candidate_count") or len(candidates)),
        "citation_count": int(result.get("citation_count") or len(citations)),
        "full_model_path": bool(result.get("full_model_path")),
        "used_llm_router": bool(result.get("used_llm_router")),
        "used_llm_query_rewriter": bool(result.get("used_llm_query_rewriter")),
        "used_qwen_answer_policy": bool(result.get("used_qwen_answer_policy")),
        "retriever_mode": str(result.get("retriever_mode") or (result.get("retriever") or {}).get("mode") or ""),
        "used_dense_retrieval": bool((result.get("retriever") or {}).get("uses_dense")),
        "used_reranker": bool((result.get("retriever") or {}).get("uses_reranker")),
        "workflow_trace_steps": trace_steps(trace),
        "artifact_dir": str(result.get("artifact_dir") or ""),
        "trace_path": str(result.get("trace_path") or ""),
        "error": result.get("error") or {},
        "stderr_tail": completed.stderr[-1000:],
        **metrics,
    }


def run_mpdocvqa_full_workflow_diagnostic(
    *,
    evidence_manifest: Path,
    db_path: Path,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    limit: int = 10,
    offset: int = 0,
    sample_ids: set[str] | None = None,
    command_runner: CommandRunner = _default_command_runner,
    args: argparse.Namespace | None = None,
    sync_output_root: Path | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    cli_artifact_dir = artifact_dir / "cli_artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    cli_artifact_dir.mkdir(parents=True, exist_ok=True)
    if args is None:
        args = build_parser().parse_args([])

    missing = []
    if not evidence_manifest.is_file():
        missing.append(safe_relpath(evidence_manifest))
    if not db_path.is_file():
        missing.append(safe_relpath(db_path))
    cli_path = repo_path(args.cli_path) or Path(args.cli_path)
    if not cli_path.is_file():
        missing.append(safe_relpath(cli_path))
    if missing:
        summary = {
            "command": "run_mpdocvqa_full_workflow_diagnostic",
            "status": "failed",
            "quality_status": "blocked",
            "run_id": run_id,
            "artifact_dir": safe_relpath(artifact_dir),
            "missing": missing,
            "used_training": False,
            "formal_benchmark_acceptance": False,
        }
        return write_outputs(artifact_dir=artifact_dir, summary=summary, cases=[], rows=[], preview=[], sync_output_root=sync_output_root)

    rows = load_rows(evidence_manifest)
    cases = selected_samples(rows, limit=limit, offset=offset, sample_ids=sample_ids)
    results: list[dict[str, Any]] = []
    for index, sample in enumerate(cases, start=1):
        case_output_dir = cli_artifact_dir / f"{index:03d}_{sample.get('sample_id')}"
        command = build_cli_command(
            python_executable=str(args.python_executable),
            cli_path=cli_path,
            db_path=db_path,
            output_dir=case_output_dir,
            sample=sample,
            args=args,
        )
        completed = command_runner(command, ROOT, int(args.timeout_seconds))
        payload, parse_error = parse_stdout(completed.stdout)
        row = evaluate_result(sample, payload, completed, parse_error)
        row["command"] = command
        results.append(row)

    summary = summarize(
        run_id=run_id,
        artifact_dir=artifact_dir,
        evidence_manifest=evidence_manifest,
        db_path=db_path,
        source_sample_count=len(rows),
        cases=cases,
        rows=results,
        args=args,
    )
    preview = [row for row in results if row.get("bucket") != "passed"][:12]
    return write_outputs(artifact_dir=artifact_dir, summary=summary, cases=cases, rows=results, preview=preview, sync_output_root=sync_output_root)


def summarize(
    *,
    run_id: str,
    artifact_dir: Path,
    evidence_manifest: Path,
    db_path: Path,
    source_sample_count: int,
    cases: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    args: argparse.Namespace,
) -> dict[str, Any]:
    bucket_counts = Counter(str(row.get("bucket") or "") for row in rows)
    total = len(rows)
    cli_success = sum(1 for row in rows if row.get("cli_status") == "success" and not row.get("stdout_parse_error"))
    answer_hits = sum(1 for row in rows if row.get("answer_hit"))
    citation_hits = sum(1 for row in rows if row.get("citation_page_hit"))
    retrieval_hits = sum(1 for row in rows if row.get("retrieved_gold_page_hit"))
    selected_hits = sum(1 for row in rows if row.get("selected_gold_page_hit"))
    return {
        "command": "run_mpdocvqa_full_workflow_diagnostic",
        "status": "success" if total and cli_success == total else "failed",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "evidence_manifest_path": safe_relpath(evidence_manifest),
        "db_path": safe_relpath(db_path),
        "source_sample_count": source_sample_count,
        "selected_sample_count": len(cases),
        "evaluated_count": total,
        "cli_success_count": cli_success,
        "cli_success_rate": rate(cli_success, total),
        "pass_count": bucket_counts.get("passed", 0),
        "pass_rate": rate(bucket_counts.get("passed", 0), total),
        "answer_hit_count": answer_hits,
        "answer_hit_rate": rate(answer_hits, total),
        "citation_page_hit_count": citation_hits,
        "citation_page_hit_rate": rate(citation_hits, total),
        "retrieved_gold_page_hit_count": retrieval_hits,
        "retrieved_gold_page_hit_rate": rate(retrieval_hits, total),
        "selected_gold_page_hit_count": selected_hits,
        "selected_gold_page_hit_rate": rate(selected_hits, total),
        "retrieval_recall_at_1": rate(sum(1 for row in rows if _rank_at_most(row.get("retrieved_gold_page_rank"), 1)), total),
        "retrieval_recall_at_3": rate(sum(1 for row in rows if _rank_at_most(row.get("retrieved_gold_page_rank"), 3)), total),
        "retrieval_recall_at_5": rate(sum(1 for row in rows if _rank_at_most(row.get("retrieved_gold_page_rank"), 5)), total),
        "full_model_path_count": sum(1 for row in rows if row.get("full_model_path")),
        "used_llm_router_count": sum(1 for row in rows if row.get("used_llm_router")),
        "used_llm_query_rewriter_count": sum(1 for row in rows if row.get("used_llm_query_rewriter")),
        "used_qwen_answer_policy_count": sum(1 for row in rows if row.get("used_qwen_answer_policy")),
        "used_dense_retrieval_count": sum(1 for row in rows if row.get("used_dense_retrieval")),
        "used_reranker_count": sum(1 for row in rows if row.get("used_reranker")),
        "bucket_counts": dict(sorted(bucket_counts.items())),
        "retriever_mode": str(args.retriever_mode),
        "answer_policy": str(args.answer_policy),
        "used_training": False,
        "used_vlm": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "recommendation": recommendation(bucket_counts),
    }


def _rank_at_most(rank: Any, k: int) -> bool:
    return isinstance(rank, int) and rank <= k


def rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def recommendation(bucket_counts: Counter[str]) -> dict[str, Any]:
    if bucket_counts.get("retrieval_gold_page_miss", 0):
        next_action = "compare_cli_hybrid_retrieval_rows_before_training"
    elif bucket_counts.get("selected_context_gold_page_miss", 0):
        next_action = "inspect_context_selection_before_training"
    elif bucket_counts.get("citation_selection_page_miss", 0):
        next_action = "inspect_citation_selection_before_training"
    elif bucket_counts.get("answer_generation_or_metric_miss", 0):
        next_action = "review_mpdocvqa_answer_generation_or_metric_before_training"
    else:
        next_action = "continue_qwen_eval_before_training"
    return {
        "next_action": next_action,
        "do_not_train_yet": True,
        "reason": "This is a small MP-DocVQA full-workflow diagnostic over existing validation artifacts; it does not create training data or claim formal benchmark acceptance.",
    }


def write_outputs(
    *,
    artifact_dir: Path,
    summary: dict[str, Any],
    cases: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    preview: list[dict[str, Any]],
    sync_output_root: Path | None,
) -> dict[str, Any]:
    paths = {
        "result": artifact_dir / "result.json",
        "summary": artifact_dir / "summary.json",
        "summary_md": artifact_dir / "summary.md",
        "cases": artifact_dir / "cases.jsonl",
        "rows": artifact_dir / "results.jsonl",
        "preview": artifact_dir / "preview.json",
        "manifest": artifact_dir / "manifest.json",
    }
    summary.update(
        {
            "summary_path": safe_relpath(paths["summary"]),
            "summary_markdown_path": safe_relpath(paths["summary_md"]),
            "cases_path": safe_relpath(paths["cases"]),
            "results_path": safe_relpath(paths["rows"]),
            "preview_path": safe_relpath(paths["preview"]),
            "manifest_path": safe_relpath(paths["manifest"]),
        }
    )
    result = {
        "command": summary["command"],
        "status": summary["status"],
        "run_id": summary["run_id"],
        "artifact_dir": summary["artifact_dir"],
        "quality_status": summary["quality_status"],
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "evaluated_count": summary.get("evaluated_count", 0),
        "retrieved_gold_page_hit_rate": summary.get("retrieved_gold_page_hit_rate", 0.0),
        "citation_page_hit_rate": summary.get("citation_page_hit_rate", 0.0),
        "answer_hit_rate": summary.get("answer_hit_rate", 0.0),
        "bucket_counts": summary.get("bucket_counts", {}),
        "recommendation": summary.get("recommendation", {}),
        "artifact_paths": [safe_relpath(path) for path in paths.values()],
    }
    write_json(paths["summary"], summary)
    write_summary_markdown(paths["summary_md"], summary)
    write_jsonl(paths["cases"], cases)
    write_jsonl(paths["rows"], rows)
    write_json(paths["preview"], preview)
    write_json(paths["result"], result)
    write_manifest(paths["manifest"], run_id=str(summary["run_id"]), artifact_paths=list(paths.values()))
    if sync_output_root is not None:
        sync_bundle_path = safe_relpath(sync_output_root / str(summary["run_id"]))
        summary["sync_bundle_path"] = sync_bundle_path
        result["sync_bundle_path"] = sync_bundle_path
        write_json(paths["summary"], summary)
        write_json(paths["result"], result)
        sync_outputs(sync_output_root / str(summary["run_id"]), paths)
    return {**result, **summary, "artifact_paths": [safe_relpath(path) for path in paths.values()]}


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    recommendation_payload = summary.get("recommendation") or {}
    lines = [
        "# MP-DocVQA Full Workflow Diagnostic",
        "",
        f"- status: `{summary.get('status')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        f"- selected_sample_count: {summary.get('selected_sample_count', 0)}",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        f"- formal_benchmark_acceptance: `{str(summary.get('formal_benchmark_acceptance')).lower()}`",
        "",
        "## Metrics",
        "",
        f"- cli_success_rate: {summary.get('cli_success_rate', 0.0)}",
        f"- retrieved_gold_page_hit_rate: {summary.get('retrieved_gold_page_hit_rate', 0.0)}",
        f"- selected_gold_page_hit_rate: {summary.get('selected_gold_page_hit_rate', 0.0)}",
        f"- citation_page_hit_rate: {summary.get('citation_page_hit_rate', 0.0)}",
        f"- answer_hit_rate: {summary.get('answer_hit_rate', 0.0)}",
        f"- retrieval_recall_at_5: {summary.get('retrieval_recall_at_5', 0.0)}",
        "",
        "## Buckets",
        "",
        *[f"- {key}: {value}" for key, value in sorted((summary.get("bucket_counts") or {}).items())],
        "",
        "## Recommendation",
        "",
        f"- next_action: `{recommendation_payload.get('next_action')}`",
        f"- do_not_train_yet: `{str(recommendation_payload.get('do_not_train_yet')).lower()}`",
        f"- reason: {recommendation_payload.get('reason')}",
        "",
        "This diagnostic executes the CLI full-model path on existing MP-DocVQA evidence. It is not a formal benchmark.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_manifest(path: Path, *, run_id: str, artifact_paths: list[Path]) -> None:
    files: list[dict[str, Any]] = []
    for artifact in artifact_paths:
        if not artifact.is_file():
            continue
        files.append(
            {
                "path": safe_relpath(artifact),
                "size_bytes": artifact.stat().st_size,
                "sha256": sha256_file(artifact),
            }
        )
    write_json(path, {"run_id": run_id, "script_version": SCRIPT_VERSION, "files": files})


def sync_outputs(sync_dir: Path, paths: dict[str, Path]) -> None:
    sync_dir.mkdir(parents=True, exist_ok=True)
    for key in ("result", "summary", "summary_md", "preview", "manifest"):
        if paths[key].is_file():
            shutil.copy2(paths[key], sync_dir / paths[key].name)


def parse_sample_ids(value: str | None) -> set[str] | None:
    if not value:
        return None
    ids = {item.strip() for item in value.split(",") if item.strip()}
    return ids or None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run MP-DocVQA rows through the CLI full-model workflow diagnostic path.")
    parser.add_argument("--evidence-manifest", default=str(DEFAULT_EVIDENCE_MANIFEST))
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--sample-ids")
    parser.add_argument("--sync-output-dir")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--cli-path", default=str(DEFAULT_CLI_PATH))
    parser.add_argument("--router-llm-env-file", default=".secrets/router_llm.env")
    parser.add_argument("--router-llm-threshold", type=float, default=1.01)
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
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=512)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = run_mpdocvqa_full_workflow_diagnostic(
        evidence_manifest=repo_path(args.evidence_manifest) or Path(args.evidence_manifest),
        db_path=repo_path(args.db_path) or Path(args.db_path),
        output_root=repo_path(args.output_dir) or Path(args.output_dir),
        run_id=args.run_id,
        limit=int(args.limit),
        offset=int(args.offset),
        sample_ids=parse_sample_ids(args.sample_ids),
        args=args,
        sync_output_root=repo_path(args.sync_output_dir) if args.sync_output_dir else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

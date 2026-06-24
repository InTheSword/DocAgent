from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docagent.models.base import HeuristicAnswerPolicy
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository, TraceRepository
from docagent.tools.local_fact_qa import local_fact_qa


DEFAULT_OUTPUT_DIR = ROOT / "outputs" / "smoke" / "phase5d_local_fact_qa"


@dataclass(frozen=True)
class SmokeQuestion:
    question: str
    doc_id: str | None = None
    qid: str | None = None


def _now_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"phase5d_local_fact_qa_{stamp}_{uuid.uuid4().hex[:8]}"


def _json_default(value: Any) -> str:
    return str(value)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")


def load_questions(
    *,
    question: list[str] | None = None,
    questions_jsonl: str | Path | None = None,
    limit: int | None = None,
) -> list[SmokeQuestion]:
    items: list[SmokeQuestion] = []
    for value in question or []:
        text = value.strip()
        if text:
            items.append(SmokeQuestion(question=text))

    if questions_jsonl:
        path = Path(questions_jsonl)
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}: {exc}") from exc
                if not isinstance(payload, dict):
                    raise ValueError(f"invalid JSONL at {path}:{line_number}: expected object")
                item_question = str(payload.get("question") or "").strip()
                if not item_question:
                    raise ValueError(f"invalid JSONL at {path}:{line_number}: missing question")
                items.append(
                    SmokeQuestion(
                        question=item_question,
                        doc_id=str(payload["doc_id"]).strip() if payload.get("doc_id") else None,
                        qid=str(payload["qid"]).strip() if payload.get("qid") else None,
                    )
                )

    if limit is not None and limit >= 0:
        return items[:limit]
    return items


def build_answer_policy(
    *,
    answer_policy: str,
    base_model_path: str,
    adapter_path: str | None,
    device: str,
    torch_dtype: str,
    max_prompt_tokens: int | None,
    max_new_tokens: int,
    do_sample: bool,
    temperature: float,
    top_p: float,
    rank_aware_context: bool,
):
    if answer_policy == "heuristic":
        return HeuristicAnswerPolicy(rank_aware_context=rank_aware_context)

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
            do_sample=do_sample,
            temperature=temperature,
            top_p=top_p,
            rank_aware_context=rank_aware_context,
        )
    )


def _failure_row(
    *,
    run_id: str,
    doc_id: str | None,
    question: str,
    error_type: str,
    message: str,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "doc_id": doc_id or "",
        "question": question,
        "status": "error",
        "answer": "",
        "citations": [],
        "supporting_evidence_ids": [],
        "tools_used": ["local_fact_qa"],
        "trace_path": "",
        "warnings": warnings or [],
        "error": {"type": error_type, "message": message},
    }


def _result_row(*, run_id: str, doc_id: str, question: str, result: dict[str, Any]) -> dict[str, Any]:
    status = str(result.get("status") or "error")
    return {
        "run_id": run_id,
        "doc_id": doc_id,
        "question": question,
        "status": status,
        "answer": result.get("answer") or "",
        "citations": result.get("citations") or [],
        "supporting_evidence_ids": result.get("supporting_evidence_ids") or [],
        "tools_used": result.get("tools_used") or ["local_fact_qa"],
        "trace_path": result.get("trace_path") or "",
        "warnings": result.get("warnings") or [],
        "error": result.get("error") or {},
        "tool_run_id": result.get("run_id") or "",
        "workflow_status": result.get("workflow_status") or "",
        "query_used": result.get("query_used") or "",
    }


def _summary_status(completed_count: int, failed_count: int) -> str:
    if failed_count == 0:
        return "success"
    if completed_count == 0:
        return "failed"
    return "partial"


def _summary_markdown(summary: dict[str, Any]) -> str:
    failure_lines = []
    for failure in summary["failures"][:10]:
        error = failure.get("error") or {}
        failure_lines.append(f"- {failure.get('question', '')}: {error.get('type', 'unknown')} {error.get('message', '')}".rstrip())
    if not failure_lines:
        failure_lines.append("- none")

    warning_lines = [f"- {warning}" for warning in summary["warnings"]] or ["- none"]
    return "\n".join(
        [
            "# Phase 5D-S local_fact_qa smoke",
            "",
            f"- status: {summary['status']}",
            f"- run_id: {summary['run_id']}",
            f"- doc_id: {summary['doc_id']}",
            f"- question_count: {summary['question_count']}",
            f"- dry_run: {summary['used_dry_run']}",
            f"- real_workflow: {summary['used_real_workflow']}",
            f"- completed_count: {summary['completed_count']}",
            f"- failed_count: {summary['failed_count']}",
            f"- output_dir: {summary['output_dir']}",
            f"- results_path: {summary['results_path']}",
            f"- preview_path: {summary['preview_path']}",
            "",
            "## Warnings",
            *warning_lines,
            "",
            "## Failures",
            *failure_lines,
            "",
            "## Next step",
            "- Run the same command on the server with real SQLite evidence, retrieval artifacts, and Qwen AnswerPolicy when required.",
            "",
        ]
    )


def run_smoke(
    *,
    db_path: str | Path,
    doc_id: str | None,
    questions: list[SmokeQuestion],
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    dry_run: bool = False,
    answer_policy: str = "heuristic",
    retrieval_config: str | None = None,
    workflow_config: str | None = None,
    evidence_packing: str | None = None,
    top_k: int = 5,
    base_model_path: str = "/root/autodl-tmp/models/Qwen3-1.7B",
    adapter_path: str | None = None,
    device: str = "cuda",
    torch_dtype: str = "bfloat16",
    max_prompt_tokens: int | None = 4096,
    max_new_tokens: int = 1024,
    do_sample: bool = False,
    temperature: float = 0.0,
    top_p: float = 1.0,
    rank_aware_context: bool = False,
) -> dict[str, Any]:
    run_id = _now_run_id()
    output_root = Path(output_dir)
    run_dir = output_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results_path = run_dir / "results.jsonl"
    preview_path = run_dir / "preview.json"
    summary_path = run_dir / "summary.json"
    summary_md_path = run_dir / "summary.md"

    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    db_file = Path(db_path)

    if retrieval_config:
        warnings.append("retrieval_config_recorded_only")
    if workflow_config:
        warnings.append("workflow_config_recorded_only")
    if dry_run:
        warnings.append("dry_run_does_not_verify_answer_quality")

    if not questions:
        rows.append(
            _failure_row(
                run_id=run_id,
                doc_id=doc_id,
                question="",
                error_type="missing_questions",
                message="at least one --question or --questions-jsonl row is required",
            )
        )
    elif not doc_id and all(item.doc_id is None for item in questions):
        rows.append(
            _failure_row(
                run_id=run_id,
                doc_id=doc_id,
                question="",
                error_type="missing_doc_id",
                message="--doc-id is required unless every questions-jsonl row provides doc_id",
            )
        )
    elif not db_file.is_file():
        for item in questions:
            rows.append(
                _failure_row(
                    run_id=run_id,
                    doc_id=item.doc_id or doc_id,
                    question=item.question,
                    error_type="db_path_not_found",
                    message=f"SQLite database not found: {db_file}",
                )
            )
    else:
        conn = connect(db_file)
        try:
            document_repository = DocumentRepository(conn)
            trace_repository = None if dry_run else TraceRepository(conn)
            policy = None
            if not dry_run:
                policy = build_answer_policy(
                    answer_policy=answer_policy,
                    base_model_path=base_model_path,
                    adapter_path=adapter_path,
                    device=device,
                    torch_dtype=torch_dtype,
                    max_prompt_tokens=max_prompt_tokens,
                    max_new_tokens=max_new_tokens,
                    do_sample=do_sample,
                    temperature=temperature,
                    top_p=top_p,
                    rank_aware_context=rank_aware_context,
                )

            for index, item in enumerate(questions, start=1):
                active_doc_id = item.doc_id or doc_id or ""
                options: dict[str, Any] = {
                    "dry_run": dry_run,
                    "top_k": top_k,
                    "qid": item.qid or f"{run_id}_{index}",
                }
                if evidence_packing:
                    options["evidence_packing"] = evidence_packing
                if not dry_run:
                    options["trace_path"] = str(db_file)
                result = local_fact_qa(
                    {"doc_id": active_doc_id, "question": item.question, "options": options},
                    document_repository=document_repository,
                    trace_repository=trace_repository,
                    answer_policy=policy,
                )
                rows.append(_result_row(run_id=run_id, doc_id=active_doc_id, question=item.question, result=result))
        finally:
            conn.close()

    completed_count = sum(1 for row in rows if row["status"] == "success")
    failed_count = len(rows) - completed_count
    failures = [row for row in rows if row["status"] != "success"]
    used_real_workflow = any(
        row.get("workflow_status") not in {"", "not_started", "dry_run"}
        for row in rows
    )
    result_warnings = []
    for row in rows:
        result_warnings.extend(row.get("warnings") or [])

    summary = {
        "status": _summary_status(completed_count, failed_count),
        "run_id": run_id,
        "doc_id": doc_id or "",
        "question_count": len(questions),
        "completed_count": completed_count,
        "failed_count": failed_count,
        "output_dir": str(run_dir),
        "results_path": str(results_path),
        "preview_path": str(preview_path),
        "summary_path": str(summary_path),
        "summary_md_path": str(summary_md_path),
        "db_path": str(db_file),
        "answer_policy": answer_policy,
        "retrieval_config": retrieval_config or "",
        "workflow_config": workflow_config or "",
        "evidence_packing": evidence_packing or "",
        "used_dry_run": dry_run,
        "used_real_workflow": used_real_workflow,
        "used_external_api": False,
        "used_vlm": False,
        "used_training": False,
        "used_full_e2e": False,
        "warnings": sorted(set(warnings + result_warnings)),
        "failures": failures,
    }
    preview = {"run_id": run_id, "results": rows[: min(3, len(rows))]}

    _write_jsonl(results_path, rows)
    _write_json(preview_path, preview)
    _write_json(summary_path, summary)
    summary_md_path.write_text(_summary_markdown(summary), encoding="utf-8")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase 5D-S local_fact_qa smoke and write JSON artifacts.")
    parser.add_argument("--db-path", required=True)
    parser.add_argument("--doc-id")
    parser.add_argument("--question", action="append")
    parser.add_argument("--questions-jsonl")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--answer-policy", choices=["heuristic", "base", "sft", "grpo"], default="heuristic")
    parser.add_argument("--retrieval-config")
    parser.add_argument("--workflow-config")
    parser.add_argument("--evidence-packing")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--base-model-path", default="/root/autodl-tmp/models/Qwen3-1.7B")
    parser.add_argument("--adapter-path")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--torch-dtype", default="bfloat16")
    parser.add_argument("--max-prompt-tokens", type=int, default=4096)
    parser.add_argument("--max-new-tokens", type=int, default=1024)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--top-p", type=float, default=1.0)
    parser.add_argument("--do-sample", action="store_true")
    parser.add_argument("--rank-aware-context", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        questions = load_questions(question=args.question, questions_jsonl=args.questions_jsonl, limit=args.limit)
        summary = run_smoke(
            db_path=args.db_path,
            doc_id=args.doc_id,
            questions=questions,
            output_dir=args.output_dir,
            dry_run=args.dry_run,
            answer_policy=args.answer_policy,
            retrieval_config=args.retrieval_config,
            workflow_config=args.workflow_config,
            evidence_packing=args.evidence_packing,
            top_k=args.top_k,
            base_model_path=args.base_model_path,
            adapter_path=args.adapter_path,
            device=args.device,
            torch_dtype=args.torch_dtype,
            max_prompt_tokens=args.max_prompt_tokens,
            max_new_tokens=args.max_new_tokens,
            do_sample=args.do_sample,
            temperature=args.temperature,
            top_p=args.top_p,
            rank_aware_context=args.rank_aware_context,
        )
    except Exception as exc:
        payload = {"status": "failed", "error": {"type": type(exc).__name__, "message": str(exc)}}
        print(json.dumps(payload, ensure_ascii=False))
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

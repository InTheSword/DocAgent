from __future__ import annotations

import argparse
import json
import subprocess
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DOC_ID = "c1fc1c5e040ec894"
DEFAULT_OUTPUT_ROOT = Path("outputs/smoke/phase5c3_query_rewriter")


@dataclass(frozen=True)
class SmokeCase:
    case_id: str
    question: str
    category: str
    expect_semantic_expansion: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "category": self.category,
            "expect_semantic_expansion": self.expect_semantic_expansion,
        }


def default_cases() -> list[SmokeCase]:
    return [
        SmokeCase(
            "unclaimed_dividend_notice",
            "What date or financial year is mentioned in the shareholder notice about unclaimed dividend?",
            "unclaimed_dividend_shareholder_notice",
            True,
        ),
        SmokeCase("effective_date_notice", "What effective date is stated in the notice?", "date", True),
        SmokeCase("amount_or_percentage", "What amount or percentage is reported in the document?", "amount_number_percentage", True),
        SmokeCase("page_one_information", "What information appears on page 1?", "page_lookup", False),
        SmokeCase("document_page_count", "How many pages does this document have?", "document_statistics", False),
        SmokeCase("financial_table", "Which table contains the relevant financial information?", "table_related", False),
        SmokeCase("document_main_topic", "What is this document mainly about?", "summary_broad", True),
        SmokeCase("ambiguous_main_topic", "What is this document mainly about?", "ambiguous_summary", True),
        SmokeCase("chinese_summary", "请概括这份文件的主要内容", "chinese_or_mixed", True),
        SmokeCase("short_date_question", "What is the date?", "short_duplicate_prone", True),
    ]


def case_pass_reason(payload: dict[str, Any], case: SmokeCase) -> tuple[bool, str]:
    if payload.get("status") != "success":
        return False, f"cli_status_{payload.get('status') or 'unknown'}"
    query_planner = payload.get("query_planner") or {}
    if not query_planner:
        if case.expect_semantic_expansion:
            return False, "query_planner_missing_for_semantic_case"
        return True, "query_planner_not_invoked_for_deterministic_or_unsupported_task"
    if query_planner.get("mode") != "hybrid":
        return False, "query_planner_mode_not_hybrid"
    if not case.expect_semantic_expansion:
        return True, "query_planner_observed_but_unique_expansion_not_required"
    if query_planner.get("llm_status") != "used":
        return False, f"llm_status_{query_planner.get('llm_status') or 'unknown'}"
    if not query_planner.get("llm_queries"):
        return False, "llm_queries_empty"
    if not query_planner.get("llm_unique_queries"):
        return False, "llm_unique_queries_empty"
    if int(query_planner.get("llm_added_unique_query_count") or 0) <= 0:
        return False, "llm_added_unique_query_count_zero"
    if not (query_planner.get("query_sources") or {}).get("llm"):
        return False, "query_sources_llm_empty"
    return True, "llm_semantic_expansion_observed"


def result_record(payload: dict[str, Any], case: SmokeCase, passed: bool, reason: str) -> dict[str, Any]:
    query_planner = payload.get("query_planner") or {}
    router_plan = payload.get("router_plan") or {}
    return {
        **case.to_dict(),
        "passed": passed,
        "pass_fail_reason": reason,
        "status": payload.get("status"),
        "task_type": payload.get("task_type"),
        "router_task_type": router_plan.get("task_type"),
        "query_planner_enabled": bool(query_planner.get("enabled")),
        "query_planner_mode": query_planner.get("mode"),
        "rule_queries": query_planner.get("rule_queries") or [],
        "llm_queries": query_planner.get("llm_queries") or [],
        "llm_unique_queries": query_planner.get("llm_unique_queries") or [],
        "llm_duplicate_queries": query_planner.get("llm_duplicate_queries") or [],
        "llm_added_unique_query_count": query_planner.get("llm_added_unique_query_count") or 0,
        "llm_status": query_planner.get("llm_status") or "",
        "llm_retry_count": query_planner.get("llm_retry_count") or 0,
        "query_sources": query_planner.get("query_sources") or {},
        "final_queries": query_planner.get("final_queries") or [],
        "warnings": payload.get("warnings") or [],
        "artifact_dir": payload.get("artifact_dir"),
    }


def run_case(
    *,
    case: SmokeCase,
    db_path: Path,
    doc_id: str,
    router_llm_env_file: Path,
    cli_output_dir: Path,
) -> dict[str, Any]:
    command = [
        sys.executable,
        "scripts/docagent_cli.py",
        "--db-path",
        str(db_path),
        "--doc-id",
        doc_id,
        "--question",
        case.question,
        "--dry-run",
        "--router-llm-env-file",
        str(router_llm_env_file),
        "--enable-query-planning",
        "--query-planner-mode",
        "hybrid",
        "--output-dir",
        str(cli_output_dir),
    ]
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            **case.to_dict(),
            "passed": False,
            "pass_fail_reason": "stdout_not_json",
            "status": "error",
            "returncode": completed.returncode,
            "stdout_preview": completed.stdout[:1000],
            "stderr_preview": completed.stderr[:1000],
        }
    passed, reason = case_pass_reason(payload, case)
    record = result_record(payload, case, passed, reason)
    record["returncode"] = completed.returncode
    if completed.stderr.strip():
        record["stderr_preview"] = completed.stderr[:1000]
    return record


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_summary(run_id: str, artifact_dir: Path, results: list[dict[str, Any]]) -> dict[str, Any]:
    passed_count = sum(1 for item in results if item.get("passed") is True)
    semantic_cases = [item for item in results if item.get("expect_semantic_expansion")]
    semantic_passed = sum(1 for item in semantic_cases if item.get("passed") is True)
    return {
        "command": "phase5c3_query_rewriter_multi_smoke",
        "status": "success" if passed_count == len(results) else "failed",
        "run_id": run_id,
        "artifact_dir": str(artifact_dir),
        "case_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "semantic_case_count": len(semantic_cases),
        "semantic_passed_count": semantic_passed,
        "failure_reasons": _count_by(results, "pass_fail_reason", passed=False),
        "task_type_distribution": _count_by(results, "task_type"),
        "router_task_type_distribution": _count_by(results, "router_task_type"),
    }


def _count_by(rows: list[dict[str, Any]], key: str, passed: bool | None = None) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        if passed is not None and row.get("passed") is not passed:
            continue
        value = str(row.get(key) or "")
        counts[value] = counts.get(value, 0) + 1
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Phase 5C-3 multi-question query rewriter smoke.")
    parser.add_argument("--db-path", default="outputs/docagent.db")
    parser.add_argument("--doc-id", default=DEFAULT_DOC_ID)
    parser.add_argument("--router-llm-env-file", default=".secrets/router_llm.env")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT))
    args = parser.parse_args(argv)

    db_path = Path(args.db_path)
    env_file = Path(args.router_llm_env_file)
    run_id = f"phase5c3_query_rewriter_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    artifact_dir = Path(args.output_root) / run_id
    cli_output_dir = artifact_dir / "cli"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    cli_output_dir.mkdir(parents=True, exist_ok=True)

    cases = default_cases()
    results = [
        run_case(
            case=case,
            db_path=db_path,
            doc_id=str(args.doc_id),
            router_llm_env_file=env_file,
            cli_output_dir=cli_output_dir,
        )
        for case in cases
    ]
    summary = build_summary(run_id, artifact_dir, results)

    cases_path = artifact_dir / "query_rewriter_cases.jsonl"
    results_path = artifact_dir / "query_rewriter_results.jsonl"
    summary_path = artifact_dir / "query_rewriter_summary.json"
    preview_path = artifact_dir / "preview.json"
    write_jsonl(cases_path, [case.to_dict() for case in cases])
    write_jsonl(results_path, results)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    preview_path.write_text(json.dumps(results[:3], ensure_ascii=False, indent=2), encoding="utf-8")

    output = {
        **summary,
        "artifact_paths": [str(cases_path), str(results_path), str(summary_path), str(preview_path)],
    }
    print(json.dumps(output, ensure_ascii=False))
    return 0 if summary["status"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_phase5i_answer_quality_benchmark import GoldenCase, default_cases


DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "phase5i_case_quality_audit"
SCRIPT_VERSION = "phase5i-case-quality-audit-v1"

GENERIC_ANSWER_KEYWORDS = {
    "%",
    "amount",
    "date",
    "financial year",
    "number",
    "percentage",
    "value",
    "year",
}


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _load_cases(cases_path: Path | None) -> list[GoldenCase]:
    if cases_path is None:
        return default_cases()
    cases: list[GoldenCase] = []
    for row in _read_jsonl(cases_path):
        cases.append(GoldenCase.from_dict(row))
    return cases


def _case_key(row: dict[str, Any], index: int) -> str:
    return str(row.get("case_id") or row.get("id") or index)


def _load_run_rows(run_dirs: Iterable[Path]) -> dict[str, list[dict[str, Any]]]:
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for run_dir in run_dirs:
        run_dir = run_dir.resolve()
        rows = _read_jsonl(run_dir / "predictions.jsonl")
        if not rows:
            rows = _read_jsonl(run_dir / "phase5i_results.jsonl")
        for index, row in enumerate(rows):
            enriched = dict(row)
            enriched["_source_run_dir"] = str(run_dir)
            by_case[_case_key(row, index)].append(enriched)
    return dict(by_case)


def _lower_set(values: Iterable[str]) -> set[str]:
    return {str(value).strip().casefold() for value in values if str(value).strip()}


def _citation_pages(row: dict[str, Any]) -> list[int]:
    pages: list[int] = []
    raw_pages = row.get("citation_pages")
    if isinstance(raw_pages, list):
        for value in raw_pages:
            try:
                pages.append(int(value))
            except (TypeError, ValueError):
                continue
    if pages:
        return pages
    for citation in row.get("citations") or []:
        if isinstance(citation, dict):
            try:
                pages.append(int(citation.get("page")))
            except (TypeError, ValueError):
                continue
    return pages


def _audit_case(case: GoldenCase, run_rows: list[dict[str, Any]]) -> dict[str, Any]:
    flags: list[str] = []
    severity = "info"
    expected_answer_keywords = case.effective_optional_answer_keywords
    keyword_set = _lower_set(expected_answer_keywords)

    if case.answerable and case.expected_answer_type in {"extractive", "numeric"}:
        if not expected_answer_keywords:
            flags.append("answer_quality_not_auto_judgable_without_keywords")
            severity = "review"
        elif keyword_set and keyword_set <= GENERIC_ANSWER_KEYWORDS:
            flags.append("answer_keywords_are_type_markers_not_answer_values")
            severity = "review"
        elif keyword_set & GENERIC_ANSWER_KEYWORDS:
            flags.append("answer_keywords_include_generic_type_marker")
            severity = "review" if severity == "info" else severity

    if case.expected_answer_type == "numeric" and any(keyword.casefold() == "%" for keyword in expected_answer_keywords):
        flags.append("percentage_symbol_alone_is_weak_numeric_gold")
        severity = "review"

    if case.downstream_answer_required and case.expected_answer_type in {"extractive", "numeric"} and not case.expected_page:
        flags.append("downstream_answer_case_missing_expected_page")
        severity = "review"

    expected_page = case.expected_page
    observed_page_mismatches = 0
    observed_page_hits = 0
    observed_answer_misses = 0
    observed_passes = 0
    observed_rows = 0
    observed_non_expected_pages: Counter[int] = Counter()
    for row in run_rows:
        observed_rows += 1
        if row.get("pass_fail") == "passed":
            observed_passes += 1
        reasons = row.get("failure_reasons") or []
        if "answer_keyword_missing" in reasons:
            observed_answer_misses += 1
        pages = _citation_pages(row)
        if expected_page is not None and pages:
            if expected_page in pages:
                observed_page_hits += 1
            else:
                observed_page_mismatches += 1
                observed_non_expected_pages.update(pages)

    if observed_rows and observed_answer_misses == observed_rows and (
        "answer_keywords_are_type_markers_not_answer_values" in flags
        or "answer_keywords_include_generic_type_marker" in flags
        or "percentage_symbol_alone_is_weak_numeric_gold" in flags
    ):
        flags.append("all_observed_runs_fail_weak_answer_keyword_check")
        severity = "review"

    if observed_rows and expected_page is not None and observed_page_mismatches == observed_rows and observed_page_hits == 0:
        flags.append("all_observed_runs_cite_non_expected_page")
        severity = "review"

    if not flags:
        flags.append("case_quality_no_issue_detected")

    return {
        "case_id": case.case_id,
        "severity": severity,
        "flags": flags,
        "user_request": case.user_request,
        "expected_task_type": case.expected_task_type,
        "expected_answer_type": case.expected_answer_type,
        "expected_page": case.expected_page,
        "expected_answer_keywords": case.expected_answer_keywords,
        "optional_answer_keywords": case.effective_optional_answer_keywords,
        "expected_evidence_keywords": case.expected_evidence_keywords,
        "notes": case.notes,
        "observed_run_count": observed_rows,
        "observed_pass_count": observed_passes,
        "observed_answer_keyword_miss_count": observed_answer_misses,
        "observed_page_mismatch_count": observed_page_mismatches,
        "observed_page_hit_count": observed_page_hits,
        "observed_non_expected_page_counts": dict(observed_non_expected_pages),
    }


def audit_phase5i_case_quality(
    *,
    cases_path: Path | None,
    run_dirs: list[Path],
    output_dir: Path,
    run_id: str,
    sync_output_dir: Path | None = None,
) -> dict[str, Any]:
    cases = _load_cases(cases_path)
    run_rows = _load_run_rows(run_dirs)
    rows = [_audit_case(case, run_rows.get(case.case_id, [])) for case in cases]

    severity_counts = Counter(row["severity"] for row in rows)
    flag_counts = Counter(flag for row in rows for flag in row["flags"])
    review_rows = [row for row in rows if row["severity"] != "info"]

    output_dir.mkdir(parents=True, exist_ok=True)
    rows_path = output_dir / "rows.jsonl"
    rows_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    preview_path = output_dir / "preview.json"
    _write_json(preview_path, {"review_rows": review_rows[:20], "flag_counts": dict(flag_counts)})

    summary = {
        "command": "audit_phase5i_case_quality",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "evaluation_scope": "phase5i_case_quality_audit_not_training",
        "quality_status": "diagnostic_only",
        "case_count": len(rows),
        "review_case_count": len(review_rows),
        "severity_counts": dict(severity_counts),
        "flag_counts": dict(flag_counts),
        "cases_path": str(cases_path) if cases_path else "default_cases",
        "run_dirs": [str(path) for path in run_dirs],
        "used_qwen": False,
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "recommendation": {
            "next_action": "use_review_flags_to_curate_cleaner_phase5i_answer_quality_cases_before_more_training",
            "do_not_train_yet": True,
            "reason": (
                "This audit identifies weak case definitions and observed page/keyword "
                "mismatches without changing benchmark scoring, rerunning models, or "
                "creating training data."
            ),
        },
    }
    result_path = output_dir / "result.json"
    summary_path = output_dir / "summary.json"
    summary_md_path = output_dir / "summary.md"
    manifest_path = output_dir / "manifest.json"
    _write_json(result_path, summary)
    _write_json(summary_path, summary)
    summary_md_path.write_text(_summary_markdown(summary, review_rows), encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "artifact_paths": [str(path) for path in [result_path, summary_path, summary_md_path, rows_path, preview_path]],
        "used_qwen": False,
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    _write_json(manifest_path, manifest)
    summary["artifact_paths"] = [str(path) for path in [result_path, summary_path, summary_md_path, rows_path, preview_path, manifest_path]]

    if sync_output_dir is not None:
        sync_output_dir.mkdir(parents=True, exist_ok=True)
        for path in [result_path, summary_path, summary_md_path, rows_path, preview_path, manifest_path]:
            shutil.copy2(path, sync_output_dir / path.name)
        summary["sync_bundle_path"] = str(sync_output_dir)

    _write_json(result_path, summary)
    _write_json(summary_path, summary)
    return summary


def _summary_markdown(summary: dict[str, Any], review_rows: list[dict[str, Any]]) -> str:
    lines = [
        "# Phase 5I Case Quality Audit",
        "",
        f"- case_count: {summary['case_count']}",
        f"- review_case_count: {summary['review_case_count']}",
        f"- severity_counts: {json.dumps(summary['severity_counts'], ensure_ascii=False)}",
        f"- flag_counts: {json.dumps(summary['flag_counts'], ensure_ascii=False)}",
        "",
        "This audit is diagnostic-only. It does not rerun models, alter scoring, or create training data.",
        "",
    ]
    for row in review_rows[:20]:
        lines.extend(
            [
                f"## {row['case_id']}",
                f"- flags: {json.dumps(row['flags'], ensure_ascii=False)}",
                f"- expected_answer_keywords: {json.dumps(row['expected_answer_keywords'], ensure_ascii=False)}",
                f"- optional_answer_keywords: {json.dumps(row['optional_answer_keywords'], ensure_ascii=False)}",
                f"- expected_page: {row['expected_page']}",
                f"- observed_run_count: {row['observed_run_count']}",
                f"- observed_page_mismatch_count: {row['observed_page_mismatch_count']}",
                "",
            ]
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Phase 5I case definitions and observed answer-quality artifacts.")
    parser.add_argument("--cases-path", type=Path, default=None, help="Optional phase5i_cases.jsonl. Defaults to built-in cases.")
    parser.add_argument("--run-dir", type=Path, action="append", default=[], help="Existing Phase 5I run directory to inspect.")
    parser.add_argument("--run-id", default=f"phase5i_case_quality_audit_{_utc_stamp()}")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--sync-output-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / args.run_id)
    summary = audit_phase5i_case_quality(
        cases_path=args.cases_path,
        run_dirs=args.run_dir,
        output_dir=output_dir,
        run_id=args.run_id,
        sync_output_dir=args.sync_output_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

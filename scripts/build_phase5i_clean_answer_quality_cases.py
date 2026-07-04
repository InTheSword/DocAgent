from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.audit_phase5i_case_quality import GENERIC_ANSWER_KEYWORDS
from scripts.run_phase5i_answer_quality_benchmark import GoldenCase


DEFAULT_CANDIDATE_CASES = ROOT / "configs" / "phase5i_clean_answer_quality_candidates.jsonl"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "phase5i_clean_answer_quality_cases"
SCRIPT_VERSION = "phase5i-clean-answer-quality-case-builder-v1"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + ("\n" if rows else ""), encoding="utf-8")


def _contains_all(text: str, keywords: list[str]) -> bool:
    lowered = text.casefold()
    return all(str(keyword).strip().casefold() in lowered for keyword in keywords if str(keyword).strip())


def _load_cases(path: Path) -> list[GoldenCase]:
    return [GoldenCase.from_dict(row) for row in _read_jsonl(path)]


def _page_text(conn: sqlite3.Connection, *, doc_id: str, page_id: int) -> tuple[str, list[str]]:
    conn.row_factory = sqlite3.Row
    block_ids: list[str] = []
    chunks: list[str] = []
    for row in conn.execute(
        """
        select block_id, text, table_html, payload_json
        from evidence_blocks
        where doc_id = ? and page_id = ?
        order by block_id
        """,
        (doc_id, page_id),
    ):
        block_ids.append(str(row["block_id"]))
        for key in ("text", "table_html"):
            value = row[key]
            if value:
                chunks.append(str(value))
        payload = row["payload_json"]
        if payload:
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {}
            for key in ("text", "content", "markdown", "html", "table_body"):
                value = data.get(key)
                if value:
                    chunks.append(str(value))
    return " ".join(chunks), block_ids


def _validate_case(case: GoldenCase, *, page_text: str, block_ids: list[str]) -> list[str]:
    reasons: list[str] = []
    if case.expected_task_type != "local_fact_qa":
        reasons.append(f"expected_task_type_not_local_fact_qa:{case.expected_task_type}")
    if case.expected_answer_type not in {"extractive", "numeric"}:
        reasons.append(f"expected_answer_type_not_answer_quality:{case.expected_answer_type}")
    if not case.answerable:
        reasons.append("case_not_answerable")
    if case.expected_page is None:
        reasons.append("expected_page_missing")
    if not case.expected_answer_keywords:
        reasons.append("expected_answer_keywords_missing")
    keyword_set = {keyword.casefold() for keyword in case.effective_optional_answer_keywords}
    if keyword_set and keyword_set <= GENERIC_ANSWER_KEYWORDS:
        reasons.append("answer_keywords_are_type_markers_not_answer_values")
    if not case.expected_evidence_keywords:
        reasons.append("expected_evidence_keywords_missing")
    if not block_ids:
        reasons.append("expected_page_has_no_evidence_blocks")
    if case.expected_evidence_keywords and not _contains_all(page_text, case.expected_evidence_keywords):
        reasons.append("expected_page_missing_evidence_keywords")
    if case.effective_optional_answer_keywords and not _contains_all(page_text, case.effective_optional_answer_keywords):
        reasons.append("expected_page_missing_answer_keywords")
    return reasons


def build_clean_answer_quality_cases(
    *,
    candidate_cases_path: Path,
    db_path: Path,
    doc_id: str,
    output_dir: Path,
    run_id: str,
    sync_output_dir: Path | None = None,
) -> dict[str, Any]:
    cases = _load_cases(candidate_cases_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []

    status = "success"
    blocker: dict[str, Any] = {}
    if not db_path.exists():
        status = "blocked"
        blocker = {"type": "db_path_not_found", "message": f"SQLite database not found: {db_path}"}
    else:
        conn = sqlite3.connect(db_path)
        try:
            for case in cases:
                text = ""
                block_ids: list[str] = []
                if case.expected_page is not None:
                    text, block_ids = _page_text(conn, doc_id=doc_id, page_id=int(case.expected_page))
                reasons = _validate_case(case, page_text=text, block_ids=block_ids)
                row = {
                    "case_id": case.case_id,
                    "status": "accepted" if not reasons else "rejected",
                    "rejection_reasons": reasons,
                    "expected_page": case.expected_page,
                    "expected_answer_keywords": case.expected_answer_keywords,
                    "expected_evidence_keywords": case.expected_evidence_keywords,
                    "supporting_block_ids": block_ids,
                    "page_text_char_count": len(text),
                }
                rows.append(row)
                if reasons:
                    rejected.append({**case.to_dict(), "rejection_reasons": reasons, "supporting_block_ids": block_ids})
                else:
                    accepted.append(case.to_dict())
        finally:
            conn.close()

    accepted_cases_path = output_dir / "accepted_answer_quality_cases.jsonl"
    rejected_cases_path = output_dir / "rejected_cases.jsonl"
    rows_path = output_dir / "rows.jsonl"
    preview_path = output_dir / "preview.json"
    result_path = output_dir / "result.json"
    summary_path = output_dir / "summary.json"
    summary_md_path = output_dir / "summary.md"
    manifest_path = output_dir / "manifest.json"

    _write_jsonl(accepted_cases_path, accepted)
    _write_jsonl(rejected_cases_path, rejected)
    _write_jsonl(rows_path, rows)
    rejection_counts = Counter(reason for row in rows for reason in row["rejection_reasons"])
    summary = {
        "command": "build_phase5i_clean_answer_quality_cases",
        "status": status,
        "script_version": SCRIPT_VERSION,
        "run_id": run_id,
        "evaluation_scope": "phase5i_clean_answer_quality_case_pack_not_training",
        "quality_status": "diagnostic_only",
        "candidate_case_count": len(cases),
        "accepted_case_count": len(accepted),
        "rejected_case_count": len(rejected),
        "rejection_reason_counts": dict(rejection_counts),
        "candidate_cases_path": str(candidate_cases_path),
        "db_path": str(db_path),
        "doc_id": doc_id,
        "accepted_cases_path": str(accepted_cases_path),
        "rejected_cases_path": str(rejected_cases_path),
        "used_qwen": False,
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
        "blocker": blocker,
        "recommendation": {
            "next_action": "run_phase5i_answer_quality_with_clean_cases_when_gpu_available"
            if accepted
            else "curate_more_specific_answer_quality_cases",
            "do_not_train_yet": True,
            "reason": (
                "This case pack validates exact answer-quality cases against persisted EvidenceBlocks. "
                "It does not call models, change scoring, or create training data."
            ),
        },
    }
    _write_json(result_path, summary)
    _write_json(summary_path, summary)
    _write_json(preview_path, {"accepted_cases": accepted[:20], "rejected_cases": rejected[:20], "rows": rows[:20]})
    summary_md_path.write_text(_summary_markdown(summary), encoding="utf-8")
    manifest = {
        "run_id": run_id,
        "script_version": SCRIPT_VERSION,
        "artifact_paths": [
            str(path)
            for path in [result_path, summary_path, summary_md_path, rows_path, accepted_cases_path, rejected_cases_path, preview_path]
        ],
        "used_qwen": False,
        "used_training": False,
        "formal_benchmark_acceptance": False,
        "validation_subset_used_for_training": False,
    }
    _write_json(manifest_path, manifest)
    summary["artifact_paths"] = [
        str(path)
        for path in [result_path, summary_path, summary_md_path, rows_path, accepted_cases_path, rejected_cases_path, preview_path, manifest_path]
    ]
    if sync_output_dir is not None:
        sync_output_dir.mkdir(parents=True, exist_ok=True)
        for path in [result_path, summary_path, summary_md_path, rows_path, accepted_cases_path, rejected_cases_path, preview_path, manifest_path]:
            shutil.copy2(path, sync_output_dir / path.name)
        summary["sync_bundle_path"] = str(sync_output_dir)
    _write_json(result_path, summary)
    _write_json(summary_path, summary)
    return summary


def _summary_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Phase 5I Clean Answer-Quality Case Pack",
            "",
            f"- status: {summary['status']}",
            f"- candidate_case_count: {summary['candidate_case_count']}",
            f"- accepted_case_count: {summary['accepted_case_count']}",
            f"- rejected_case_count: {summary['rejected_case_count']}",
            f"- rejection_reason_counts: {json.dumps(summary['rejection_reason_counts'], ensure_ascii=False)}",
            "",
            "This artifact is diagnostic-only and does not call models or create training data.",
            "",
        ]
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a clean Phase 5I AnswerPolicy answer-quality case pack.")
    parser.add_argument("--candidate-cases", type=Path, default=DEFAULT_CANDIDATE_CASES)
    parser.add_argument("--db-path", type=Path, required=True)
    parser.add_argument("--doc-id", required=True)
    parser.add_argument("--run-id", default=f"phase5i_clean_answer_quality_cases_{_utc_stamp()}")
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument("--sync-output-dir", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output_dir = args.output_dir or (DEFAULT_OUTPUT_ROOT / args.run_id)
    summary = build_clean_answer_quality_cases(
        candidate_cases_path=args.candidate_cases,
        db_path=args.db_path,
        doc_id=args.doc_id,
        output_dir=output_dir,
        run_id=args.run_id,
        sync_output_dir=args.sync_output_dir,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

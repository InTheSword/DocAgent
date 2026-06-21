from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from docagent.retrieval.candidate_answer_extraction import (
    bucket_candidate_answer_failures,
    candidate_answer_artifact_has_gold_leakage,
    candidate_span_contains_answer,
    compute_candidate_answer_coverage,
    extract_candidate_answers,
    summarize_candidate_answer_coverage,
)
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.analyze_phase4d_candidate_answer_coverage import run_phase4d_candidate_answer_coverage


def _span(
    candidate_id: str,
    text: str,
    *,
    page: int = 1,
    score: float = 0.5,
    bbox: list[float] | None = None,
) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "doc_id": "doc",
        "page": page,
        "page_aggregate_id": f"p{page}",
        "retrieval_page_rank": page,
        "block_ids": [f"{candidate_id}_b"],
        "primary_block_id": f"{candidate_id}_b",
        "block_types": ["text"],
        "text": text,
        "bbox": bbox or [0, 200, 100, 220],
        "score": score,
        "score_breakdown": {},
        "matched_terms": [],
        "detected_values": [],
    }


def _hints(answer_type: str = "unknown", *fields: str) -> dict[str, object]:
    return {
        "answer_type_hint": answer_type,
        "keywords": ["share", "segment"],
        "numeric_tokens": [],
        "date_tokens": [],
        "field_hints": list(fields),
    }


def test_typed_extraction_rules_no_gold_and_index_priority() -> None:
    index_board = extract_candidate_answers(
        "What index share is shown for the 21-25 segment?",
        _hints("numeric", "index", "share"),
        [_span("c0001", "Share of the 21-25 Segment: 2.5% (31)\nTotal amount: $1,234")],
    )
    candidates = index_board["candidate_answers"]
    types = {candidate["answer_type"] for candidate in candidates}

    assert candidates[0]["answer_type"] == "index"
    assert candidates[0]["normalized_answer"] == "31"
    assert {"index", "percentage", "numeric"}.issubset(types)
    assert index_board["answer_board_stats"]["same_type_distractor_count"] >= 0
    assert index_board["answer_board_stats"]["numeric_distractor_count"] >= 2
    assert candidate_answer_artifact_has_gold_leakage(index_board) is False
    assert candidate_answer_artifact_has_gold_leakage({"gold_answers": ["31"]}) is True

    date_board = extract_candidate_answers(
        "When is the signature date?",
        _hints("date", "date"),
        [_span("c0002", "Signature date: June 14, 1974")],
    )
    source_board = extract_candidate_answers(
        "What source is cited at the bottom?",
        _hints("source", "source"),
        [_span("c0003", "Source: company filings\nUSMM 2019-001\nhttps://example.com/report")],
    )
    heading_board = extract_candidate_answers(
        "What is the heading title?",
        _hints("heading", "heading"),
        [_span("c0004", "Risk Factors\nThe body starts here.", bbox=[0, 30, 100, 60])],
    )
    text_board = extract_candidate_answers(
        "What is the customer name?",
        _hints("text"),
        [_span("c0005", "Customer: Acme Corporation\nOther long paragraph follows.")],
    )

    assert any(candidate["answer_type"] == "date" and "1974" in candidate["normalized_answer"] for candidate in date_board["candidate_answers"])
    assert any(candidate["answer_type"] == "source" and "source" in candidate["normalized_answer"] for candidate in source_board["candidate_answers"])
    assert any(candidate["answer_type"] == "heading" and candidate["answer_text"] == "Risk Factors" for candidate in heading_board["candidate_answers"])
    assert any(candidate["answer_type"] == "text" and "acme corporation" in candidate["normalized_answer"] for candidate in text_board["candidate_answers"])


def test_coverage_rank_distribution_and_distractor_metrics() -> None:
    q1_candidates = [
        {"normalized_answer": "2.5%", "answer_text": "2.5%", "answer_type": "percentage"},
        {"normalized_answer": "31", "answer_text": "31", "answer_type": "index"},
    ]
    coverage = compute_candidate_answer_coverage(q1_candidates, ["31"])

    assert candidate_span_contains_answer([_span("c1", "Share of segment is 2.5% (31)")], ["31"]) is True
    assert candidate_span_contains_answer([_span("c2", "No matching value")], ["31"]) is False
    assert coverage["covered"] is True
    assert coverage["first_rank"] == 2
    assert coverage["rank_bucket"] == "rank_2"

    candidate_records = [
        {"qid": "q1", "candidate_spans": [_span("c1", "Share of segment is 2.5% (31)")]},
        {"qid": "q2", "candidate_spans": [_span("c2", "No matching value")]},
    ]
    answer_boards = [
        {
            "qid": "q1",
            "question_hints": {"answer_type_hint": "numeric"},
            "candidate_answers": q1_candidates,
            "answer_board_stats": {
                "candidate_answer_count": 2,
                "unique_normalized_answer_count": 2,
                "same_type_distractor_count": 1,
                "numeric_distractor_count": 1,
            },
        },
        {
            "qid": "q2",
            "question_hints": {"answer_type_hint": "text"},
            "candidate_answers": [],
            "answer_board_stats": {
                "candidate_answer_count": 0,
                "unique_normalized_answer_count": 0,
                "same_type_distractor_count": 0,
                "numeric_distractor_count": 0,
            },
        },
    ]
    qa_records = [
        {"qid": "q1", "answers": ["31"], "answer_type": "extractive"},
        {"qid": "q2", "answers": ["Acme"], "answer_type": "extractive"},
    ]
    metrics = summarize_candidate_answer_coverage(
        candidate_records=candidate_records,
        answer_boards=answer_boards,
        qa_records=qa_records,
    )

    assert metrics["candidate_span_answer_coverage"] == 0.5
    assert metrics["candidate_answer_coverage"] == 0.5
    assert metrics["gold_answer_rank_distribution"]["rank_2"] == 1
    assert metrics["gold_answer_rank_distribution"]["missing"] == 1
    assert metrics["mean_candidate_answer_count"] == 1.0
    assert metrics["mean_unique_candidate_answer_count"] == 1.0
    assert metrics["mean_same_type_distractor_count"] == 0.5
    assert metrics["mean_numeric_distractor_count"] == 0.5
    assert metrics["no_candidate_answer_count"] == 1
    assert metrics["candidate_answer_no_gold_leakage"] is True


def test_error_buckets_cover_a_to_f() -> None:
    qa_records = [
        {"qid": "qa", "doc_id": "doc", "question": "A?", "answers": ["A"], "gold_page_ordinal": 1},
        {"qid": "qb", "doc_id": "doc", "question": "B?", "answers": ["B"], "gold_page_ordinal": 2},
        {"qid": "qc", "doc_id": "doc", "question": "C?", "answers": ["C"], "gold_page_ordinal": 1},
        {"qid": "qd", "doc_id": "doc", "question": "D?", "answers": ["D"], "gold_page_ordinal": 1},
        {"qid": "qe", "doc_id": "doc", "question": "E?", "answers": ["E"], "gold_page_ordinal": 1},
        {"qid": "qf", "doc_id": "doc", "question": "F?", "answers": ["F"], "gold_page_ordinal": 1},
    ]
    candidate_records = [
        {"qid": "qa", "top_pages": [{"page": 1}], "candidate_spans": [_span("ca", "A", page=1)]},
        {"qid": "qb", "top_pages": [{"page": 2}], "candidate_spans": [_span("cb", "B", page=1)]},
        {"qid": "qc", "top_pages": [{"page": 1}], "candidate_spans": [_span("cc", "wrong", page=1)]},
        {"qid": "qd", "top_pages": [{"page": 1}], "candidate_spans": [_span("cd", "D", page=1)]},
        {"qid": "qe", "top_pages": [{"page": 1}], "candidate_spans": [_span("ce", "E", page=1)]},
        {"qid": "qf", "top_pages": [{"page": 1}], "candidate_spans": [_span("cf", "F", page=1)]},
    ]
    answer_boards = [
        {"qid": "qa", "candidate_answers": [{"normalized_answer": "a"}]},
        {"qid": "qb", "candidate_answers": [{"normalized_answer": "b"}]},
        {"qid": "qc", "candidate_answers": [{"normalized_answer": "wrong"}]},
        {"qid": "qd", "candidate_answers": []},
        {"qid": "qe", "candidate_answers": [{"normalized_answer": "e"}]},
        {"qid": "qf", "candidate_answers": [{"normalized_answer": "f"}]},
    ]
    retrieval_rows = [
        {"qid": "qa", "mode": "hybrid", "gold_page_rank": 6, "failure_taxonomy": ["retrieval_gold_miss_top5"]},
        {"qid": "qb", "mode": "hybrid", "gold_page_rank": 1},
        {"qid": "qc", "mode": "hybrid", "gold_page_rank": 1},
        {"qid": "qd", "mode": "hybrid", "gold_page_rank": 1},
        {"qid": "qe", "mode": "hybrid", "gold_page_rank": 1},
        {"qid": "qf", "mode": "hybrid", "gold_page_rank": 1},
    ]
    answer_results = [
        {"qid": "qe", "answer_metrics": {"answer_hit": False, "normalized_exact_match": False}},
        {"qid": "qf", "answer_metrics": {"answer_hit": True, "normalized_exact_match": True}},
    ]
    buckets = bucket_candidate_answer_failures(
        candidate_records=candidate_records,
        answer_boards=answer_boards,
        qa_records=qa_records,
        page_retrieval_rows=retrieval_rows,
        answer_results=answer_results,
    )

    assert buckets["answer_results_status"] == "available"
    assert buckets["bucket_counts"] == {"A": 1, "B": 1, "C": 1, "D": 1, "E": 1, "F": 1, "G": 0}


def test_runner_outputs_artifacts_without_answer_results(tmp_path: Path) -> None:
    candidate_evidence = tmp_path / "candidate_evidence.jsonl"
    qa_jsonl = tmp_path / "qa.jsonl"
    candidate_packing_metrics = tmp_path / "candidate_packing_metrics.json"
    phase4c_summary = tmp_path / "summary.json"
    output_root = tmp_path / "out"
    write_jsonl(
        candidate_evidence,
        [
            {
                "qid": "q1",
                "doc_id": "doc",
                "question": "What index share is shown?",
                "question_hints": _hints("numeric", "index", "share"),
                "top_pages": [{"page": 1}],
                "candidate_spans": [_span("c1", "Share of segment: 2.5% (31)", page=1)],
            }
        ],
    )
    write_jsonl(qa_jsonl, [{"qid": "q1", "doc_id": "doc", "question": "What index share is shown?", "answers": ["31"], "gold_page_ordinal": 1}])
    candidate_packing_metrics.write_text(json.dumps({"sample_count": 1}), encoding="utf-8")
    phase4c_summary.write_text(
        json.dumps({"evidence_packing_mode": "candidate_spans", "fixed_evidence_hash": "abc123"}),
        encoding="utf-8",
    )

    summary = run_phase4d_candidate_answer_coverage(
        Namespace(
            candidate_evidence=candidate_evidence,
            qa_jsonl=qa_jsonl,
            answer_results=tmp_path / "missing_answer_results.jsonl",
            page_retrieval_results=None,
            candidate_packing_metrics=candidate_packing_metrics,
            phase4c_summary=phase4c_summary,
            output_root=output_root,
            run_id="fixture",
            force=True,
        )
    )
    run_dir = output_root / "fixture"
    boards = read_jsonl(run_dir / "candidate_answers.jsonl")
    preview = json.loads((run_dir / "candidate_answers_preview.json").read_text(encoding="utf-8"))
    metrics = json.loads((run_dir / "candidate_answer_coverage_metrics.json").read_text(encoding="utf-8"))

    assert summary["status"] == "success"
    assert summary["error_buckets"]["answer_results_status"] == "unavailable"
    assert summary["no_gold_leakage_in_candidate_answers"] is True
    assert summary["phase4c_context"]["candidate_packing_metrics_status"] == "available"
    assert summary["phase4c_context"]["phase4c_evidence_packing_mode"] == "candidate_spans"
    assert summary["artifact_paths"]["candidate_answers"] == "candidate_answers.jsonl"
    assert "\\" not in json.dumps(summary["artifact_paths"])
    assert boards[0]["candidate_answers"][0]["answer_type"] == "index"
    assert candidate_answer_artifact_has_gold_leakage(boards) is False
    assert "gold_page" not in json.dumps(boards, ensure_ascii=False)
    assert "gold_page" not in json.dumps(preview, ensure_ascii=False)
    assert metrics["candidate_answer_coverage"] == 1.0
    assert (run_dir / "summary.md").is_file()


def test_cli_help() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/analyze_phase4d_candidate_answer_coverage.py", "--help"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--candidate-evidence" in result.stdout
    assert "--qa-jsonl" in result.stdout
    assert "--candidate-packing-metrics" in result.stdout
    assert "--phase4c-summary" in result.stdout

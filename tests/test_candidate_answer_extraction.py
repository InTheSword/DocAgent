from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from docagent.retrieval.candidate_answer_extraction import (
    build_topk_candidate_answer_boards,
    bucket_candidate_answer_failures,
    candidate_answer_artifact_has_gold_leakage,
    candidate_span_contains_answer,
    compute_candidate_answer_coverage,
    extract_candidate_answers,
    summarize_candidate_answer_coverage,
)
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.analyze_phase4d_candidate_answer_coverage import run_phase4d_candidate_answer_coverage
from scripts.export_phase4d_failure_inspection import run_phase4d_candidate_span_gap_review, run_phase4d_failure_inspection


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


def test_phase4d_a1_extraction_rules_for_headings_locations_quarters_and_entities() -> None:
    heading_board = extract_candidate_answers(
        "What is the heading of this page?",
        _hints("heading", "heading"),
        [_span("h1", "Consolidated Statements of Operations\n2024\nOther values", bbox=[0, 20, 100, 40])],
    )
    city_board = extract_candidate_answers(
        "In which city is the board?",
        _hints("text", "city", "board", "located"),
        [_span("l1", "The board is located at 100 Main Street, Springfield, IL 62701.")],
    )
    state_board = extract_candidate_answers(
        "In which state is the board located?",
        _hints("text", "state", "board", "located"),
        [_span("l2", "Board located: 100 Main Street, Springfield, Illinois 62701.")],
    )
    quarter_board = extract_candidate_answers(
        "What is the short form used for 3rd quarter of 2002?",
        _hints("text", "quarter"),
        [_span("q1", "Results for the third quarter are labeled 3Q02 and Q3FY02 in this table.")],
    )
    key_value_board = extract_candidate_answers(
        "What is the contract number?",
        {"answer_type_hint": "text", "keywords": ["contract", "number"], "numeric_tokens": [], "date_tokens": [], "field_hints": ["number"]},
        [_span("kv1", "Contract Number - AB-12345\nAmount: $8,000")],
    )
    organization_board = extract_candidate_answers(
        "What is the name of the board mentioned in the logo?",
        _hints("text", "name", "board", "logo"),
        [_span("o1", "STATE WATER RESOURCES CONTROL BOARD\nCalifornia Environmental Protection Agency")],
    )
    source_board = extract_candidate_answers(
        "What source is cited in the footer?",
        _hints("source", "source"),
        [_span("s1", "Source: Annual Report of the Board, Appendix A, page 42, accessed March 2024.")],
    )

    assert heading_board["candidate_answers"][0]["answer_text"] == "Consolidated Statements of Operations"
    assert heading_board["candidate_answers"][0]["answer_type"] == "heading"
    assert any(candidate["answer_type"] == "city" and "springfield" in candidate["normalized_answer"] for candidate in city_board["candidate_answers"])
    assert any(candidate["answer_type"] == "state" and "illinois" in candidate["normalized_answer"] for candidate in state_board["candidate_answers"])
    assert any(candidate["answer_type"] == "quarter" and candidate["normalized_answer"] in {"3q02", "q3fy02"} for candidate in quarter_board["candidate_answers"])
    assert any(candidate["answer_text"] == "AB-12345" for candidate in key_value_board["candidate_answers"])
    assert any(candidate["answer_type"] == "organization" and "board" in candidate["normalized_answer"] for candidate in organization_board["candidate_answers"])
    assert source_board["candidate_answers"][0]["answer_text"].startswith("Source: Annual Report of the Board")
    assert "page 42" in source_board["candidate_answers"][0]["answer_text"]


def test_ranking_duplicate_and_generic_numeric_penalties() -> None:
    board = extract_candidate_answers(
        "What is the company name?",
        _hints("text", "company", "name"),
        [
            _span("c1", "Company: Acme Corporation\nReference number: 12345", score=0.9),
            _span("c2", "Company: Acme Corporation", page=2, score=0.1),
        ],
    )
    candidates = board["candidate_answers"]
    acme = [candidate for candidate in candidates if candidate["normalized_answer"] == "acme corporation"]
    generic_number = next(candidate for candidate in candidates if candidate["normalized_answer"] == "12345")

    assert [candidate["rank"] for candidate in candidates] == list(range(1, len(candidates) + 1))
    assert candidates[0]["normalized_answer"] == "acme corporation"
    assert acme[0]["score_breakdown"]["duplicate_penalty"] == 0.0
    assert acme[1]["score_breakdown"]["duplicate_penalty"] < 0.0
    assert generic_number["score_breakdown"]["generic_numeric_penalty"] < 0.0
    assert generic_number["rank"] > candidates[0]["rank"]
    assert candidates[0]["is_top_k"] is True


def test_phase4d_a2_type_mismatch_index_and_percentage_ranking() -> None:
    heading_board = extract_candidate_answers(
        "What is the heading of this page?",
        _hints("heading", "heading"),
        [_span("h1", "Annual Governance Report\nPage 12\nTable 3\n2024", score=0.8, bbox=[0, 20, 100, 40])],
    )
    numeric_candidates = [candidate for candidate in heading_board["candidate_answers"] if candidate["answer_type"] in {"numeric", "date"}]

    assert heading_board["candidate_answers"][0]["normalized_answer"] == "annual governance report"
    assert all(candidate["score_breakdown"]["type_mismatch_penalty"] < 0.0 for candidate in numeric_candidates)

    index_board = extract_candidate_answers(
        "What index share is shown?",
        _hints("numeric", "index", "share"),
        [_span("i1", "Segment share was 2.5% (31) and page 12.")],
    )
    percentage_board = extract_candidate_answers(
        "What percentage is shown?",
        _hints("numeric", "percentage", "percent"),
        [_span("p1", "The value is 2.5% and the table number is 31.")],
    )

    assert index_board["candidate_answers"][0]["answer_type"] == "index"
    assert index_board["candidate_answers"][0]["normalized_answer"] == "31"
    assert percentage_board["candidate_answers"][0]["answer_type"] == "percentage"
    assert percentage_board["candidate_answers"][0]["normalized_answer"] == "2.5%"


def test_phase4d_a2_type_aware_topk_deduplicates_and_limits_numeric_noise() -> None:
    numeric_candidates = [
        {
            "candidate_answer_id": f"a{i:04d}",
            "answer_text": str(i),
            "normalized_answer": str(i),
            "answer_type": "numeric",
            "score": 1.0 - i * 0.001,
            "rank": i,
            "eligible_for_topk": True,
        }
        for i in range(1, 31)
    ]
    board = {
        "qid": "q_heading",
        "doc_id": "doc",
        "question": "What is the heading?",
        "question_hints": _hints("heading", "heading"),
        "candidate_answers": [
            *numeric_candidates,
            {
                "candidate_answer_id": "a1000",
                "answer_text": "Annual Governance Report",
                "normalized_answer": "annual governance report",
                "answer_type": "heading",
                "score": 0.9,
                "rank": 31,
                "eligible_for_topk": True,
            },
            {
                "candidate_answer_id": "a1001",
                "answer_text": "Annual  Governance Report.",
                "normalized_answer": "annual governance report",
                "answer_type": "heading",
                "score": 0.89,
                "rank": 32,
                "eligible_for_topk": True,
            },
        ],
        "answer_board_stats": {"candidate_answer_count": 32, "unique_normalized_answer_count": 31},
    }

    topk_board = build_topk_candidate_answer_boards([board], top_k=20)[0]
    topk_candidates = topk_board["candidate_answers"]
    numeric_count = sum(1 for candidate in topk_candidates if candidate["answer_type"] in {"numeric", "percentage", "index"})

    assert len(topk_candidates) <= 20
    assert numeric_count <= 3
    assert len({candidate["normalized_answer"] for candidate in topk_candidates}) == len(topk_candidates)
    assert [candidate["topk_rank"] for candidate in topk_candidates] == list(range(1, len(topk_candidates) + 1))
    assert any(candidate["normalized_answer"] == "annual governance report" for candidate in topk_candidates)
    assert topk_board["answer_board_stats"]["topk_numeric_candidate_count"] == numeric_count
    assert topk_board["answer_board_stats"]["topk_unique_candidate_answer_count"] == len(topk_candidates)


def test_coverage_rank_distribution_and_distractor_metrics() -> None:
    q1_candidates = [
        {"normalized_answer": "2.5%", "answer_text": "2.5%", "answer_type": "percentage", "rank": 1},
        {"normalized_answer": "31", "answer_text": "31", "answer_type": "index", "rank": 2},
    ]
    coverage = compute_candidate_answer_coverage(q1_candidates, ["31"])

    assert candidate_span_contains_answer([_span("c1", "Share of segment is 2.5% (31)")], ["31"]) is True
    assert candidate_span_contains_answer([_span("c2", "No matching value")], ["31"]) is False
    assert coverage["covered"] is True
    assert coverage["first_rank"] == 2
    assert coverage["rank_bucket"] == "rank_2"
    assert compute_candidate_answer_coverage(q1_candidates, ["31"], top_k=1)["covered"] is False
    assert compute_candidate_answer_coverage(q1_candidates, ["31"], top_k=3)["covered"] is True

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
    topk_boards = build_topk_candidate_answer_boards(answer_boards, top_k=20)
    metrics = summarize_candidate_answer_coverage(
        candidate_records=candidate_records,
        answer_boards=answer_boards,
        topk_answer_boards=topk_boards,
        qa_records=qa_records,
    )

    assert metrics["candidate_span_answer_coverage"] == 0.5
    assert metrics["candidate_answer_coverage"] == 0.5
    assert metrics["candidate_answer_coverage_all"] == 0.5
    assert metrics["candidate_answer_coverage_top1"] == 0.0
    assert metrics["candidate_answer_coverage_top3"] == 0.5
    assert metrics["candidate_answer_coverage_top5"] == 0.5
    assert metrics["candidate_answer_coverage_top10"] == 0.5
    assert metrics["candidate_answer_coverage_top20"] == 0.5
    assert metrics["gold_answer_rank_distribution"]["rank_2"] == 1
    assert metrics["gold_answer_rank_distribution"]["missing"] == 1
    assert metrics["mean_candidate_answer_count"] == 1.0
    assert metrics["mean_unique_candidate_answer_count"] == 1.0
    assert metrics["mean_top20_candidate_answer_count"] == 1.0
    assert metrics["mean_same_type_distractor_count"] == 0.5
    assert metrics["mean_numeric_distractor_count"] == 0.5
    assert metrics["topk_retention_ratio"] == 1.0
    assert metrics["topk_numeric_ratio"] == 1.0
    assert metrics["no_candidate_answer_count"] == 1
    assert metrics["candidate_answer_no_gold_leakage"] is True

    assert len(topk_boards[0]["candidate_answers"]) == 2
    assert len(answer_boards[0]["candidate_answers"]) == 2


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
            top_k=1,
            force=True,
        )
    )
    run_dir = output_root / "fixture"
    boards = read_jsonl(run_dir / "candidate_answers.jsonl")
    topk_boards = read_jsonl(run_dir / "candidate_answers_topk.jsonl")
    preview = json.loads((run_dir / "candidate_answers_preview.json").read_text(encoding="utf-8"))
    topk_preview = json.loads((run_dir / "candidate_answers_topk_preview.json").read_text(encoding="utf-8"))
    metrics = json.loads((run_dir / "candidate_answer_coverage_metrics.json").read_text(encoding="utf-8"))
    transition = json.loads((run_dir / "bucket_transition_estimate.json").read_text(encoding="utf-8"))
    comparison = json.loads((run_dir / "refinement_comparison.json").read_text(encoding="utf-8"))

    assert summary["status"] == "success"
    assert summary["error_buckets"]["answer_results_status"] == "unavailable"
    assert summary["no_gold_leakage_in_candidate_answers"] is True
    assert summary["phase4c_context"]["candidate_packing_metrics_status"] == "available"
    assert summary["phase4c_context"]["phase4c_evidence_packing_mode"] == "candidate_spans"
    assert summary["artifact_paths"]["candidate_answers"] == "candidate_answers.jsonl"
    assert summary["artifact_paths"]["candidate_answers_topk"] == "candidate_answers_topk.jsonl"
    assert summary["top_k"] == 1
    assert "\\" not in json.dumps(summary["artifact_paths"])
    assert boards[0]["candidate_answers"][0]["answer_type"] == "index"
    assert len(topk_boards[0]["candidate_answers"]) == 1
    assert len(boards[0]["candidate_answers"]) > len(topk_boards[0]["candidate_answers"])
    assert candidate_answer_artifact_has_gold_leakage(boards) is False
    assert candidate_answer_artifact_has_gold_leakage(topk_boards) is False
    assert "gold_page" not in json.dumps(boards, ensure_ascii=False)
    assert "gold_page" not in json.dumps(preview, ensure_ascii=False)
    assert "gold_page" not in json.dumps(topk_preview, ensure_ascii=False)
    assert metrics["candidate_answer_coverage"] == 1.0
    assert "candidate_answer_coverage_top1" in metrics
    assert "mean_ranked_candidate_answer_count" in metrics
    assert metrics["mean_topk_unique_candidate_answer_count"] == 1.0
    assert 0.0 <= metrics["topk_numeric_ratio"] <= 1.0
    assert transition["d_samples_potentially_fixed_by_extraction_improvement"] == 0
    assert comparison["baseline"]["candidate_answer_coverage_all"] == 0.5222
    assert "delta_vs_baseline" in comparison
    assert (run_dir / "summary.md").is_file()


def test_failure_inspection_exports_c_d_e_cases(tmp_path: Path) -> None:
    run_dir = tmp_path / "a2_run"
    run_dir.mkdir()
    candidate_evidence = tmp_path / "candidate_evidence.jsonl"
    qa_jsonl = tmp_path / "qa.jsonl"
    answer_results = tmp_path / "answer_results.jsonl"
    output_root = tmp_path / "inspection"
    write_jsonl(
        candidate_evidence,
        [
            {
                "qid": "qc",
                "doc_id": "doc",
                "question": "What title is shown?",
                "question_hints": _hints("heading", "title"),
                "top_pages": [{"page": 1}],
                "candidate_spans": [_span("c_c", "Wrong heading", page=1)],
            },
            {
                "qid": "qd",
                "doc_id": "doc",
                "question": "In which city is the board located?",
                "question_hints": _hints("text", "city", "located"),
                "top_pages": [{"page": 1}],
                "candidate_spans": [_span("c_d", "The board is located in Springfield city", page=1)],
            },
            {
                "qid": "qe",
                "doc_id": "doc",
                "question": "What index is listed?",
                "question_hints": _hints("numeric", "index"),
                "top_pages": [{"page": 1}],
                "candidate_spans": [_span("c_e", "The table shows index (31).", page=1)],
            },
        ],
    )
    write_jsonl(
        qa_jsonl,
        [
            {"qid": "qc", "doc_id": "doc", "question": "What title is shown?", "answers": ["Annual Report"], "gold_page_ordinal": 1},
            {"qid": "qd", "doc_id": "doc", "question": "In which city is the board located?", "answers": ["Springfield"], "gold_page_ordinal": 1},
            {"qid": "qe", "doc_id": "doc", "question": "What index is listed?", "answers": ["31"], "gold_page_ordinal": 1},
        ],
    )
    answer_boards = [
        {
            "qid": "qc",
            "doc_id": "doc",
            "question": "What title is shown?",
            "question_hints": _hints("heading", "title"),
            "candidate_answers": [{"candidate_answer_id": "a0001", "rank": 1, "answer_text": "Wrong heading", "normalized_answer": "wrong heading", "answer_type": "heading", "score": 0.8, "source_candidate_id": "c_c", "extraction_rule": "heading"}],
        },
        {
            "qid": "qd",
            "doc_id": "doc",
            "question": "In which city is the board located?",
            "question_hints": _hints("text", "city", "located"),
            "candidate_answers": [{"candidate_answer_id": "a0001", "rank": 1, "answer_text": "board", "normalized_answer": "board", "answer_type": "text", "score": 0.5, "source_candidate_id": "c_d", "extraction_rule": "generic"}],
        },
        {
            "qid": "qe",
            "doc_id": "doc",
            "question": "What index is listed?",
            "question_hints": _hints("numeric", "index"),
            "candidate_answers": [
                {"candidate_answer_id": "a0001", "rank": 1, "answer_text": "table", "normalized_answer": "table", "answer_type": "text", "score": 0.7, "source_candidate_id": "c_e", "extraction_rule": "generic"},
                {"candidate_answer_id": "a0002", "rank": 2, "answer_text": "31", "normalized_answer": "31", "answer_type": "index", "score": 0.6, "source_candidate_id": "c_e", "extraction_rule": "parenthesized_index"},
            ],
        },
    ]
    topk_boards = [
        {**board, "candidate_answers": [dict(answer, topk_rank=index + 1) for index, answer in enumerate(board["candidate_answers"])]}
        for board in answer_boards
    ]
    write_jsonl(run_dir / "candidate_answers.jsonl", answer_boards)
    write_jsonl(run_dir / "candidate_answers_topk.jsonl", topk_boards)
    (run_dir / "candidate_answer_error_buckets.json").write_text(
        json.dumps(
            {
                "records": [
                    {"qid": "qc", "doc_id": "doc", "bucket": "C", "reason": "gold_answer_not_in_candidate_spans"},
                    {"qid": "qd", "doc_id": "doc", "bucket": "D", "reason": "gold_answer_in_candidate_spans_but_not_extracted"},
                    {"qid": "qe", "doc_id": "doc", "bucket": "E", "reason": "gold_answer_in_candidate_answers_but_model_answer_wrong"},
                ]
            }
        ),
        encoding="utf-8",
    )
    write_jsonl(answer_results, [{"qid": "qe", "answer": "wrong", "answer_metrics": {"answer_hit": False}}])

    summary = run_phase4d_failure_inspection(
        Namespace(
            run_dir=run_dir,
            candidate_evidence=candidate_evidence,
            qa_jsonl=qa_jsonl,
            answer_results=answer_results,
            output_root=output_root,
            run_id="fixture",
            buckets="C,D,E",
            max_cases_per_bucket=999,
            top_spans=2,
            top_candidates=2,
            force=True,
        )
    )
    out_dir = output_root / "fixture"
    cases = read_jsonl(out_dir / "failure_inspection_cases.jsonl")
    cases_by_bucket = {case["bucket"]: case for case in cases}
    preview = json.loads((out_dir / "failure_inspection_preview.json").read_text(encoding="utf-8"))

    assert summary["phase"] == "Phase 4D-A.3.1"
    assert summary["bucket_counts"] == {"C": 1, "D": 1, "E": 1}
    assert summary["bucket_answer_hit_breakdown"]["E"]["final_answer_hit_false"] == 1
    assert summary["bucket_candidate_coverage_breakdown"]["E"]["top5_covered_true"] == 1
    assert summary["diagnosis_counts"] == {"candidate_span_gap": 1, "extraction_rule_gap": 1, "reader_or_candidate_selection_gap": 1}
    assert summary["recommended_next_action_counts"] == {
        "candidate_id_reader_or_reranking": 1,
        "improve_candidate_answer_extraction": 1,
        "improve_candidate_spans": 1,
    }
    assert summary["refined_failure_source_counts"] == {
        "candidate_span_or_normalization_gap": 1,
        "extraction_rule_gap": 1,
        "reader_selection_gap": 1,
    }
    assert summary["true_failure_action_counts"]["candidate_id_reader_or_reranking"] == 1
    assert summary["inspection_contains_gold_for_debug_only"] is True
    assert summary["candidate_answers_remain_gold_free"] is True
    assert summary["candidate_answers_topk_remain_gold_free"] is True
    assert cases_by_bucket["C"]["coverage_flags"]["candidate_span_answer_covered"] is False
    assert cases_by_bucket["D"]["diagnosis_hints"]["subtype"] == "city_state_location"
    assert cases_by_bucket["E"]["coverage_flags"]["top5_covered"] is True
    assert cases_by_bucket["E"]["diagnosis_hints"]["subtype"] == "reader_selection_issue"
    assert cases_by_bucket["E"]["top_candidate_answers"][1]["matches_gold"] is True
    assert cases_by_bucket["D"]["top_candidate_spans"][0]["contains_gold_answer"] is True
    assert "normalized_gold_answers" in cases_by_bucket["D"]["gold_answer_debug"]
    assert "gold" not in json.dumps(read_jsonl(run_dir / "candidate_answers.jsonl"), ensure_ascii=False).lower()
    assert len(read_jsonl(out_dir / "bucket_C_cases.jsonl")) == 1
    assert len(read_jsonl(out_dir / "bucket_D_cases.jsonl")) == 1
    assert len(read_jsonl(out_dir / "bucket_E_cases.jsonl")) == 1
    assert preview["records"]
    assert (out_dir / "failure_inspection_summary.md").is_file()
    assert (out_dir / "failure_inspection_refined_summary.json").is_file()
    assert (out_dir / "failure_inspection_refined_summary.md").is_file()
    assert read_jsonl(out_dir / "failure_inspection_refined_cases.jsonl")[2]["refined_failure_source"] == "reader_selection_gap"


def test_failure_inspection_refined_action_attribution_matrix(tmp_path: Path) -> None:
    run_dir = tmp_path / "a2_run"
    run_dir.mkdir()
    candidate_evidence = tmp_path / "candidate_evidence.jsonl"
    qa_jsonl = tmp_path / "qa.jsonl"
    answer_results = tmp_path / "answer_results.jsonl"
    output_root = tmp_path / "inspection"

    records = [
        ("q_ok", "C", "wrong span", [{"answer_text": "wrong", "normalized_answer": "wrong", "rank": 1}], [{"answer_text": "wrong", "normalized_answer": "wrong", "rank": 1, "topk_rank": 1}], "Gold", True),
        ("q_span", "C", "wrong span", [{"answer_text": "wrong", "normalized_answer": "wrong", "rank": 1}], [{"answer_text": "wrong", "normalized_answer": "wrong", "rank": 1, "topk_rank": 1}], "wrong", False),
        ("q_extract", "D", "gold value", [{"answer_text": "wrong", "normalized_answer": "wrong", "rank": 1}], [{"answer_text": "wrong", "normalized_answer": "wrong", "rank": 1, "topk_rank": 1}], "wrong", False),
        ("q_reader", "E", "gold value", [{"answer_text": "gold", "normalized_answer": "gold", "rank": 1}], [{"answer_text": "gold", "normalized_answer": "gold", "rank": 1, "topk_rank": 1}], "wrong", False),
        (
            "q_rank",
            "E",
            "gold value",
            [{"answer_text": f"wrong {i}", "normalized_answer": f"wrong {i}", "rank": i} for i in range(1, 6)] + [{"answer_text": "gold", "normalized_answer": "gold", "rank": 6}],
            [{"answer_text": f"wrong {i}", "normalized_answer": f"wrong {i}", "rank": i, "topk_rank": i} for i in range(1, 6)] + [{"answer_text": "gold", "normalized_answer": "gold", "rank": 6, "topk_rank": 6}],
            "wrong",
            False,
        ),
        ("q_topk", "E", "gold value", [{"answer_text": "gold", "normalized_answer": "gold", "rank": 21}], [{"answer_text": "wrong", "normalized_answer": "wrong", "rank": 1, "topk_rank": 1}], "wrong", False),
        ("q_norm", "C", "wrong span", [{"answer_text": "wrong", "normalized_answer": "wrong", "rank": 1}], [{"answer_text": "wrong", "normalized_answer": "wrong", "rank": 1, "topk_rank": 1}], "Gold Extra", False),
    ]
    write_jsonl(
        candidate_evidence,
        [
            {
                "qid": qid,
                "doc_id": "doc",
                "question": f"Question {qid}?",
                "top_pages": [{"page": 1}],
                "candidate_spans": [_span(f"c_{qid}", span_text, page=1)],
            }
            for qid, _, span_text, _, _, _, _ in records
        ],
    )
    write_jsonl(
        qa_jsonl,
        [
            {"qid": qid, "doc_id": "doc", "question": f"Question {qid}?", "answers": ["gold"], "gold_page_ordinal": 1}
            for qid, *_ in records
        ],
    )
    write_jsonl(
        run_dir / "candidate_answers.jsonl",
        [
            {"qid": qid, "doc_id": "doc", "question": f"Question {qid}?", "candidate_answers": candidates}
            for qid, _, _, candidates, _, _, _ in records
        ],
    )
    write_jsonl(
        run_dir / "candidate_answers_topk.jsonl",
        [
            {"qid": qid, "doc_id": "doc", "question": f"Question {qid}?", "candidate_answers": topk_candidates}
            for qid, _, _, _, topk_candidates, _, _ in records
        ],
    )
    (run_dir / "candidate_answer_error_buckets.json").write_text(
        json.dumps({"records": [{"qid": qid, "doc_id": "doc", "bucket": bucket, "reason": "fixture"} for qid, bucket, *_ in records]}),
        encoding="utf-8",
    )
    write_jsonl(
        answer_results,
        [{"qid": qid, "answer": answer, "answer_metrics": {"answer_hit": answer_hit}} for qid, _, _, _, _, answer, answer_hit in records],
    )

    summary = run_phase4d_failure_inspection(
        Namespace(
            run_dir=run_dir,
            candidate_evidence=candidate_evidence,
            qa_jsonl=qa_jsonl,
            answer_results=answer_results,
            output_root=output_root,
            run_id="fixture",
            buckets="C,D,E",
            max_cases_per_bucket=999,
            top_spans=1,
            top_candidates=20,
            force=True,
        )
    )
    refined_cases = {case["qid"]: case for case in read_jsonl(output_root / "fixture" / "failure_inspection_refined_cases.jsonl")}
    refined_summary = json.loads((output_root / "fixture" / "failure_inspection_refined_summary.json").read_text(encoding="utf-8"))

    assert refined_cases["q_ok"]["refined_recommended_action"] == "no_action_final_answer_already_correct"
    assert refined_cases["q_span"]["refined_failure_source"] == "candidate_span_or_normalization_gap"
    assert refined_cases["q_extract"]["refined_failure_source"] == "extraction_rule_gap"
    assert refined_cases["q_reader"]["refined_failure_source"] == "reader_selection_gap"
    assert refined_cases["q_rank"]["refined_failure_source"] == "candidate_ranking_gap"
    assert refined_cases["q_topk"]["refined_failure_source"] == "topk_filtering_gap"
    assert refined_cases["q_norm"]["refined_failure_source"] == "normalization_or_metric_gap"
    assert summary["bucket_answer_hit_breakdown"]["C"] == {"total": 3, "final_answer_hit_true": 1, "final_answer_hit_false": 2}
    assert summary["true_failure_action_counts"] == {
        "candidate_id_reader_or_reranking": 3,
        "improve_candidate_answer_extraction": 1,
        "improve_candidate_spans": 1,
        "no_action_final_answer_already_correct": 1,
        "normalization_or_metric_fix": 1,
    }
    assert refined_summary["true_failure_action_counts"] == summary["true_failure_action_counts"]


def test_failure_inspection_exports_c_d_without_answer_results(tmp_path: Path) -> None:
    run_dir = tmp_path / "a2_run"
    run_dir.mkdir()
    candidate_evidence = tmp_path / "candidate_evidence.jsonl"
    qa_jsonl = tmp_path / "qa.jsonl"
    output_root = tmp_path / "inspection"
    write_jsonl(
        candidate_evidence,
        [
            {"qid": "qc", "doc_id": "doc", "question": "What title?", "top_pages": [{"page": 1}], "candidate_spans": [_span("c_c", "Wrong", page=1)]},
            {"qid": "qd", "doc_id": "doc", "question": "What title?", "top_pages": [{"page": 1}], "candidate_spans": [_span("c_d", "Annual Report", page=1)]},
        ],
    )
    write_jsonl(
        qa_jsonl,
        [
            {"qid": "qc", "doc_id": "doc", "question": "What title?", "answers": ["Annual Report"], "gold_page_ordinal": 1},
            {"qid": "qd", "doc_id": "doc", "question": "What title?", "answers": ["Annual Report"], "gold_page_ordinal": 1},
        ],
    )
    write_jsonl(
        run_dir / "candidate_answers.jsonl",
        [
            {"qid": "qc", "candidate_answers": [{"rank": 1, "answer_text": "Wrong", "normalized_answer": "wrong"}]},
            {"qid": "qd", "candidate_answers": [{"rank": 1, "answer_text": "Wrong", "normalized_answer": "wrong"}]},
        ],
    )

    summary = run_phase4d_failure_inspection(
        Namespace(
            run_dir=run_dir,
            candidate_evidence=candidate_evidence,
            qa_jsonl=qa_jsonl,
            answer_results=tmp_path / "missing_answer_results.jsonl",
            output_root=output_root,
            run_id="fixture",
            buckets="C,D,E",
            max_cases_per_bucket=999,
            top_spans=1,
            top_candidates=1,
            force=True,
        )
    )

    assert summary["bucket_counts"] == {"C": 1, "D": 1, "E": 0}
    assert summary["diagnosis_counts"] == {"candidate_span_gap": 1, "extraction_rule_gap": 1}
    assert len(read_jsonl(output_root / "fixture" / "bucket_E_cases.jsonl")) == 0


def test_candidate_span_gap_review_exports_subtypes_and_summary(tmp_path: Path) -> None:
    source_dir = tmp_path / "gate4_failure_inspection_a2_refined"
    output_root = tmp_path / "inspection"
    source_dir.mkdir()
    refined_rows = [
        {"qid": "q_norm", "bucket": "C", "question": "In which city is the board?", "phase4c_normalized_answer": "nashville tennessee", "refined_failure_source": "candidate_span_or_normalization_gap"},
        {"qid": "q_select", "bucket": "C", "question": "What is the company name?", "phase4c_normalized_answer": "wrong", "refined_failure_source": "candidate_span_or_normalization_gap"},
        {"qid": "q_partial", "bucket": "C", "question": "In which city is the board located?", "phase4c_normalized_answer": "wrong", "refined_failure_source": "candidate_span_or_normalization_gap"},
        {"qid": "q_table", "bucket": "C", "question": "What segment share index is shown?", "phase4c_normalized_answer": "wrong", "refined_failure_source": "candidate_span_or_normalization_gap"},
        {"qid": "q_page", "bucket": "C", "question": "Mention the page number of the content Trimegestone.", "phase4c_normalized_answer": "wrong", "refined_failure_source": "candidate_span_or_normalization_gap"},
        {"qid": "q_ocr", "bucket": "C", "question": "What is the filing status code?", "phase4c_normalized_answer": "wrong", "refined_failure_source": "candidate_span_or_normalization_gap"},
        {"qid": "q_unclear", "bucket": "C", "question": "", "phase4c_normalized_answer": "wrong", "refined_failure_source": "candidate_span_or_normalization_gap"},
        {"qid": "q_reader", "bucket": "E", "question": "Reader case", "phase4c_normalized_answer": "wrong", "refined_failure_source": "reader_selection_gap"},
    ]
    detail_rows = [
        {
            "qid": "q_norm",
            "question": "In which city is the board?",
            "gold_answer_debug": {"normalized_gold_answers": ["nashville"], "gold_answer_forms_preview": ["Nashville"]},
            "phase4c_prediction": {"normalized_answer": "nashville tennessee", "answer_hit": False},
            "top_candidate_spans": [{"text_preview": "Board mailing address"}],
        },
        {
            "qid": "q_select",
            "question": "What is the company name?",
            "gold_answer_debug": {"normalized_gold_answers": ["acme corporation"], "gold_answer_forms_preview": ["Acme Corporation"]},
            "phase4c_prediction": {"normalized_answer": "wrong", "answer_hit": False},
            "top_candidate_spans": [{"text_preview": "Random appendix notes"}],
        },
        {
            "qid": "q_partial",
            "question": "In which city is the board located?",
            "gold_answer_debug": {"normalized_gold_answers": ["nashville tennessee"], "gold_answer_forms_preview": ["Nashville, Tennessee"]},
            "phase4c_prediction": {"normalized_answer": "wrong", "answer_hit": False},
            "top_candidate_spans": [{"text_preview": "The board is located in Nashville"}],
        },
        {
            "qid": "q_table",
            "question": "What segment share index is shown?",
            "gold_answer_debug": {"normalized_gold_answers": ["31"], "gold_answer_forms_preview": ["31"]},
            "phase4c_prediction": {"normalized_answer": "wrong", "answer_hit": False},
            "top_candidate_spans": [{"text_preview": "Segment table share (30)"}],
        },
        {
            "qid": "q_page",
            "question": "Mention the page number of the content Trimegestone.",
            "gold_answer_debug": {"normalized_gold_answers": ["12"], "gold_answer_forms_preview": ["12"]},
            "phase4c_prediction": {"normalized_answer": "wrong", "answer_hit": False},
            "top_candidate_spans": [{"text_preview": "Trimegestone content listing"}],
        },
        {
            "qid": "q_ocr",
            "question": "What is the filing status code?",
            "gold_answer_debug": {"normalized_gold_answers": ["approved"], "gold_answer_forms_preview": ["Approved"]},
            "phase4c_prediction": {"normalized_answer": "wrong", "answer_hit": False},
            "top_candidate_spans": [{"text_preview": "Filing status code appears in scanned header"}],
        },
    ]
    write_jsonl(source_dir / "failure_inspection_refined_cases.jsonl", refined_rows)
    write_jsonl(source_dir / "failure_inspection_cases.jsonl", detail_rows)

    summary = run_phase4d_candidate_span_gap_review(
        Namespace(
            source_refined_run_dir=source_dir,
            output_root=output_root,
            run_id="fixture",
            force=True,
        )
    )
    out_dir = output_root / "fixture"
    cases = {case["qid"]: case for case in read_jsonl(out_dir / "candidate_span_gap_cases.jsonl")}
    preview = json.loads((out_dir / "candidate_span_gap_preview.json").read_text(encoding="utf-8"))

    assert set(cases) == {"q_norm", "q_select", "q_partial", "q_table", "q_page", "q_ocr", "q_unclear"}
    assert cases["q_norm"]["gap_subtype"] == "normalization_or_metric_gap"
    assert cases["q_select"]["gap_subtype"] == "candidate_span_selection_gap"
    assert cases["q_partial"]["gap_subtype"] == "candidate_span_partial_context_gap"
    assert cases["q_table"]["gap_subtype"] == "table_or_index_span_gap"
    assert cases["q_page"]["gap_subtype"] == "page_number_or_content_lookup_gap"
    assert cases["q_ocr"]["gap_subtype"] == "ocr_or_parsing_gap"
    assert cases["q_unclear"]["gap_subtype"] == "unclear_mixed_gap"
    assert all(case["should_not_patch_specific_qid"] is True for case in cases.values())
    assert cases["q_unclear"]["is_generic_fix_candidate"] is False
    assert summary["phase"] == "Phase 4D-A.4"
    assert summary["task"] == "candidate_span_normalization_gap_final_review"
    assert summary["status"] == "success"
    assert summary["total_candidate_span_or_normalization_gap"] == 7
    assert summary["gap_subtype_counts"] == {
        "normalization_or_metric_gap": 1,
        "candidate_span_selection_gap": 1,
        "candidate_span_partial_context_gap": 1,
        "table_or_index_span_gap": 1,
        "page_number_or_content_lookup_gap": 1,
        "ocr_or_parsing_gap": 1,
        "unclear_mixed_gap": 1,
    }
    assert summary["recommended_next_action_counts"] == {
        "inspect_answer_normalization": 1,
        "improve_candidate_spans": 1,
        "improve_candidate_span_neighbor_context": 1,
        "improve_table_index_span_selection": 1,
        "improve_page_number_content_lookup": 1,
        "inspect_ocr_or_parsing": 1,
        "manual_review_required": 1,
    }
    assert summary["decision_guidance"] == {
        "candidate_id_reader_should_remain_postponed": True,
        "allow_next_repair_only_if_generic_pattern_concentrated": True,
        "stop_after_this_diagnostic_stage": True,
    }
    assert summary["does_not_modify_reader"] is True
    assert summary["does_not_run_answer_policy"] is True
    assert summary["does_not_train"] is True
    assert preview["records"]
    assert (out_dir / "candidate_span_gap_summary.json").is_file()
    assert "Decision Gate" in (out_dir / "candidate_span_gap_summary.md").read_text(encoding="utf-8")


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
    assert "--top-k" in result.stdout

    export_result = subprocess.run(
        [sys.executable, "scripts/export_phase4d_failure_inspection.py", "--help"],
        cwd=Path.cwd(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert export_result.returncode == 0
    assert "--run-dir" in export_result.stdout
    assert "--candidate-evidence" in export_result.stdout
    assert "--buckets" in export_result.stdout
    assert "--top-candidates" in export_result.stdout
    assert "--candidate-span-gap-review" in export_result.stdout
    assert "--source-refined-run-dir" in export_result.stdout

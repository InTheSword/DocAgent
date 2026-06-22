from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from docagent.retrieval.candidate_answer_extraction import (
    NUMERIC_TYPES,
    candidate_answer_artifact_has_gold_leakage,
    candidate_span_contains_answer,
    compute_candidate_answer_coverage,
    _answer_match,
    _normalize_answer,
)
from docagent.utils.jsonl import read_jsonl, write_jsonl


INSPECTION_BUCKETS = ("C", "D", "E")
TRUE_FAILURE_ACTION_KEYS = (
    "improve_candidate_spans",
    "improve_candidate_answer_extraction",
    "candidate_id_reader_or_reranking",
    "normalization_or_metric_fix",
    "no_action_final_answer_already_correct",
)
GAP_SUBTYPES = (
    "normalization_or_metric_gap",
    "candidate_span_selection_gap",
    "candidate_span_partial_context_gap",
    "table_or_index_span_gap",
    "page_number_or_content_lookup_gap",
    "ocr_or_parsing_gap",
    "unclear_mixed_gap",
)
GAP_RECOMMENDED_ACTIONS = {
    "normalization_or_metric_gap": "inspect_answer_normalization",
    "candidate_span_selection_gap": "improve_candidate_spans",
    "candidate_span_partial_context_gap": "improve_candidate_span_neighbor_context",
    "table_or_index_span_gap": "improve_table_index_span_selection",
    "page_number_or_content_lookup_gap": "improve_page_number_content_lookup",
    "ocr_or_parsing_gap": "inspect_ocr_or_parsing",
    "unclear_mixed_gap": "manual_review_required",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export Phase 4D-A.3 case-level failure inspection artifacts.")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--candidate-evidence", type=Path)
    parser.add_argument("--qa-jsonl", type=Path)
    parser.add_argument("--answer-results", type=Path)
    parser.add_argument("--candidate-span-gap-review", action="store_true")
    parser.add_argument("--source-refined-run-dir", type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--buckets", default="C,D,E")
    parser.add_argument("--max-cases-per-bucket", type=int, default=999)
    parser.add_argument("--top-spans", type=int, default=5)
    parser.add_argument("--top-candidates", type=int, default=20)
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def run_phase4d_failure_inspection(args: argparse.Namespace) -> dict[str, Any]:
    if args.run_dir is None or args.candidate_evidence is None or args.qa_jsonl is None:
        raise ValueError("--run-dir, --candidate-evidence, and --qa-jsonl are required unless --candidate-span-gap-review is set")
    requested_buckets = _parse_buckets(str(args.buckets))
    max_cases_per_bucket = max(0, int(args.max_cases_per_bucket))
    top_spans = max(0, int(args.top_spans))
    top_candidates = max(0, int(args.top_candidates))

    candidate_records = read_jsonl(args.candidate_evidence)
    qa_records = read_jsonl(args.qa_jsonl)
    answer_results = _read_optional_jsonl(args.answer_results)
    answer_boards = read_jsonl(args.run_dir / "candidate_answers.jsonl")
    topk_boards = _read_optional_jsonl(args.run_dir / "candidate_answers_topk.jsonl") or []
    bucket_records = _load_bucket_records(
        run_dir=args.run_dir,
        candidate_records=candidate_records,
        answer_boards=answer_boards,
        qa_records=qa_records,
        answer_results=answer_results,
    )

    output_dir = args.output_root / args.run_id
    if output_dir.exists() and any(output_dir.iterdir()) and not args.force:
        raise FileExistsError(f"Output directory exists; pass --force to overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    records_by_qid = {str(record.get("qid")): record for record in candidate_records}
    qa_by_qid = {str(record.get("qid")): record for record in qa_records}
    boards_by_qid = {str(board.get("qid")): board for board in answer_boards}
    topk_by_qid = {str(board.get("qid")): board for board in topk_boards}
    answer_results_by_qid = {str(row.get("qid")): row for row in (answer_results or [])}

    selected_counts = Counter({bucket: 0 for bucket in requested_buckets})
    cases: list[dict[str, Any]] = []
    for bucket_record in bucket_records:
        bucket = str(bucket_record.get("bucket") or "G")
        if bucket not in requested_buckets:
            continue
        if selected_counts[bucket] >= max_cases_per_bucket:
            continue
        qid = str(bucket_record.get("qid") or "")
        qa = qa_by_qid.get(qid, {})
        candidate_record = records_by_qid.get(qid, {})
        board = boards_by_qid.get(qid, {})
        topk_board = topk_by_qid.get(qid, {})
        answer_result = answer_results_by_qid.get(qid, {})
        cases.append(
            _build_case(
                bucket_record=bucket_record,
                qa=qa,
                candidate_record=candidate_record,
                board=board,
                topk_board=topk_board,
                answer_result=answer_result,
                top_spans=top_spans,
                top_candidates=top_candidates,
            )
        )
        selected_counts[bucket] += 1

    refined_cases = [_build_refined_case(case) for case in cases]
    paths = {
        "failure_inspection_cases": output_dir / "failure_inspection_cases.jsonl",
        "failure_inspection_preview": output_dir / "failure_inspection_preview.json",
        "failure_inspection_summary": output_dir / "failure_inspection_summary.json",
        "failure_inspection_summary_md": output_dir / "failure_inspection_summary.md",
        "failure_inspection_refined_cases": output_dir / "failure_inspection_refined_cases.jsonl",
        "failure_inspection_refined_summary": output_dir / "failure_inspection_refined_summary.json",
        "failure_inspection_refined_summary_md": output_dir / "failure_inspection_refined_summary.md",
        "bucket_C_cases": output_dir / "bucket_C_cases.jsonl",
        "bucket_D_cases": output_dir / "bucket_D_cases.jsonl",
        "bucket_E_cases": output_dir / "bucket_E_cases.jsonl",
    }
    write_jsonl(paths["failure_inspection_cases"], cases)
    write_jsonl(paths["failure_inspection_refined_cases"], refined_cases)
    for bucket in INSPECTION_BUCKETS:
        write_jsonl(paths[f"bucket_{bucket}_cases"], [case for case in cases if case.get("bucket") == bucket])

    summary = _build_summary(
        args=args,
        cases=cases,
        refined_cases=refined_cases,
        requested_buckets=requested_buckets,
        answer_boards=answer_boards,
        topk_boards=topk_boards,
        paths=paths,
        output_dir=output_dir,
    )
    refined_summary = _build_refined_summary(summary)
    _write_json(paths["failure_inspection_preview"], _build_preview(cases))
    _write_json(paths["failure_inspection_summary"], summary)
    _write_json(paths["failure_inspection_refined_summary"], refined_summary)
    paths["failure_inspection_summary_md"].write_text(_summary_markdown(summary), encoding="utf-8")
    paths["failure_inspection_refined_summary_md"].write_text(_refined_summary_markdown(refined_summary), encoding="utf-8")
    return summary


def run_phase4d_candidate_span_gap_review(args: argparse.Namespace) -> dict[str, Any]:
    if args.source_refined_run_dir is None:
        raise ValueError("--source-refined-run-dir is required with --candidate-span-gap-review")
    source_dir = args.source_refined_run_dir
    refined_cases = read_jsonl(source_dir / "failure_inspection_refined_cases.jsonl")
    detailed_cases = _read_optional_jsonl(source_dir / "failure_inspection_cases.jsonl") or []
    detailed_by_qid = {str(case.get("qid")): case for case in detailed_cases}
    output_dir = args.output_root / args.run_id
    if output_dir.exists() and any(output_dir.iterdir()) and not args.force:
        raise FileExistsError(f"Output directory exists; pass --force to overwrite: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    target_cases = [
        _build_candidate_span_gap_case(refined_case, detailed_by_qid.get(str(refined_case.get("qid")), {}))
        for refined_case in refined_cases
        if str(refined_case.get("refined_failure_source") or "") == "candidate_span_or_normalization_gap"
    ]
    paths = {
        "candidate_span_gap_cases": output_dir / "candidate_span_gap_cases.jsonl",
        "candidate_span_gap_preview": output_dir / "candidate_span_gap_preview.json",
        "candidate_span_gap_summary": output_dir / "candidate_span_gap_summary.json",
        "candidate_span_gap_summary_md": output_dir / "candidate_span_gap_summary.md",
    }
    write_jsonl(paths["candidate_span_gap_cases"], target_cases)
    _write_json(paths["candidate_span_gap_preview"], _candidate_span_gap_preview(target_cases))
    summary = _build_candidate_span_gap_summary(
        source_dir=source_dir,
        cases=target_cases,
        paths=paths,
        output_dir=output_dir,
    )
    _write_json(paths["candidate_span_gap_summary"], summary)
    paths["candidate_span_gap_summary_md"].write_text(_candidate_span_gap_summary_markdown(summary), encoding="utf-8")
    return summary


def _build_case(
    *,
    bucket_record: dict[str, Any],
    qa: dict[str, Any],
    candidate_record: dict[str, Any],
    board: dict[str, Any],
    topk_board: dict[str, Any],
    answer_result: dict[str, Any],
    top_spans: int,
    top_candidates: int,
) -> dict[str, Any]:
    gold_answers = _qa_answer_list(qa)
    normalized_gold = [_normalize_answer(answer) for answer in gold_answers if _normalize_answer(answer)]
    candidate_answers = list(board.get("candidate_answers") or [])
    topk_answers = list(topk_board.get("candidate_answers") or candidate_answers)
    span_coverage = candidate_span_contains_answer(candidate_record.get("candidate_spans") or [], gold_answers)
    all_coverage = compute_candidate_answer_coverage(candidate_answers, gold_answers)
    flags = {
        "candidate_span_answer_covered": span_coverage,
        "candidate_answer_covered": bool(all_coverage["covered"]),
        "top1_covered": bool(compute_candidate_answer_coverage(topk_answers, gold_answers, top_k=1)["covered"]),
        "top5_covered": bool(compute_candidate_answer_coverage(topk_answers, gold_answers, top_k=5)["covered"]),
        "top20_covered": bool(compute_candidate_answer_coverage(topk_answers, gold_answers, top_k=20)["covered"]),
    }
    bucket = str(bucket_record.get("bucket") or "G")
    diagnosis = _diagnose_case(
        bucket=bucket,
        qa=qa,
        candidate_record=candidate_record,
        candidate_answers=candidate_answers,
        topk_answers=topk_answers,
        coverage_flags=flags,
        all_coverage=all_coverage,
    )
    return {
        "qid": str(qa.get("qid") or bucket_record.get("qid") or ""),
        "doc_id": qa.get("doc_id") or candidate_record.get("doc_id") or bucket_record.get("doc_id"),
        "bucket": bucket,
        "reason": bucket_record.get("reason") or _reason_for_bucket(bucket),
        "question": qa.get("question") or candidate_record.get("question") or bucket_record.get("question"),
        "question_hints": candidate_record.get("question_hints") or board.get("question_hints") or {},
        "gold_answer_debug": {
            "gold_answer_count": len(gold_answers),
            "normalized_gold_answers": normalized_gold,
            "gold_answer_forms_preview": gold_answers[:5],
        },
        "phase4c_prediction": _prediction_debug(answer_result),
        "coverage_flags": flags,
        "top_candidate_spans": _top_candidate_spans(candidate_record, gold_answers, limit=top_spans),
        "top_candidate_answers": _top_candidate_answers(topk_answers, normalized_gold, limit=top_candidates),
        "diagnosis_hints": diagnosis,
    }


def _top_candidate_spans(candidate_record: dict[str, Any], gold_answers: list[str], *, limit: int) -> list[dict[str, Any]]:
    spans = list(candidate_record.get("candidate_spans") or [])
    rows: list[dict[str, Any]] = []
    for index, span in enumerate(spans[:limit], start=1):
        block_ids = span.get("block_ids") or []
        rows.append(
            {
                "candidate_id": span.get("candidate_id") or span.get("source_candidate_id") or f"c{index:04d}",
                "rank": int(span.get("rank") or index),
                "score": _safe_float(span.get("score")),
                "page": span.get("page"),
                "block_id": span.get("primary_block_id") or (block_ids[0] if block_ids else None),
                "contains_gold_answer": candidate_span_contains_answer([span], gold_answers),
                "text_preview": _truncate(str(span.get("text") or ""), limit=360),
            }
        )
    return rows


def _top_candidate_answers(candidate_answers: list[dict[str, Any]], normalized_gold: list[str], *, limit: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    sorted_answers = sorted(candidate_answers, key=lambda item: int(item.get("topk_rank") or item.get("rank") or 10**9))
    for index, answer in enumerate(sorted_answers[:limit], start=1):
        normalized_answer = str(answer.get("normalized_answer") or _normalize_answer(answer.get("answer_text") or ""))
        rows.append(
            {
                "candidate_answer_id": answer.get("candidate_answer_id") or f"a{index:04d}",
                "rank": int(answer.get("topk_rank") or answer.get("rank") or index),
                "answer_text": answer.get("answer_text"),
                "normalized_answer": normalized_answer,
                "answer_type": answer.get("answer_type"),
                "score": _safe_float(answer.get("score")),
                "source_candidate_id": answer.get("source_candidate_id"),
                "matches_gold": any(_answer_match(normalized_answer, gold) for gold in normalized_gold),
                "extraction_rule": answer.get("extraction_rule"),
                "filter_reasons": answer.get("filter_reasons") or [],
            }
        )
    return rows


def _diagnose_case(
    *,
    bucket: str,
    qa: dict[str, Any],
    candidate_record: dict[str, Any],
    candidate_answers: list[dict[str, Any]],
    topk_answers: list[dict[str, Any]],
    coverage_flags: dict[str, bool],
    all_coverage: dict[str, Any],
) -> dict[str, Any]:
    notes: list[str] = []
    if bucket == "C":
        likely = "candidate_span_gap"
        action = "improve_candidate_spans"
        subtype = _candidate_span_gap_subtype(qa=qa, candidate_record=candidate_record, notes=notes)
    elif bucket == "D":
        likely = "extraction_rule_gap"
        action = "improve_candidate_answer_extraction"
        subtype = _extraction_gap_subtype(qa=qa, candidate_record=candidate_record)
    elif bucket == "E":
        likely = "reader_or_candidate_selection_gap"
        action = "candidate_id_reader_or_reranking"
        subtype = _selection_gap_subtype(
            first_rank=all_coverage.get("first_rank"),
            candidate_answers=candidate_answers,
            topk_answers=topk_answers,
            coverage_flags=coverage_flags,
            notes=notes,
        )
    else:
        likely = "unclassified"
        action = "manual_inspection"
        subtype = "unclassified"
    return {
        "likely_failure_source": likely,
        "recommended_next_action": action,
        "subtype": subtype,
        "notes": notes,
    }


def _build_refined_case(case: dict[str, Any]) -> dict[str, Any]:
    prediction = case.get("phase4c_prediction") or {}
    flags = case.get("coverage_flags") or {}
    diagnosis = case.get("diagnosis_hints") or {}
    gold_debug = case.get("gold_answer_debug") or {}
    normalized_gold = [str(answer) for answer in (gold_debug.get("normalized_gold_answers") or [])]
    refined_source, refined_action = _refined_attribution(
        prediction=prediction,
        coverage_flags=flags,
        normalized_gold=normalized_gold,
    )
    return {
        "qid": case.get("qid"),
        "bucket": case.get("bucket"),
        "question": case.get("question"),
        "phase4c_answer_hit": bool(prediction.get("answer_hit")),
        "phase4c_normalized_answer": prediction.get("normalized_answer") or "",
        "candidate_span_answer_covered": bool(flags.get("candidate_span_answer_covered")),
        "candidate_answer_covered": bool(flags.get("candidate_answer_covered")),
        "top1_covered": bool(flags.get("top1_covered")),
        "top5_covered": bool(flags.get("top5_covered")),
        "top20_covered": bool(flags.get("top20_covered")),
        "original_likely_failure_source": diagnosis.get("likely_failure_source"),
        "original_recommended_next_action": diagnosis.get("recommended_next_action"),
        "refined_failure_source": refined_source,
        "refined_recommended_action": refined_action,
        "true_failure_action": _true_failure_action_bucket(refined_source, refined_action),
    }


def _refined_attribution(
    *,
    prediction: dict[str, Any],
    coverage_flags: dict[str, Any],
    normalized_gold: list[str],
) -> tuple[str, str]:
    if bool(prediction.get("answer_hit")):
        return "no_final_failure", "no_action_final_answer_already_correct"
    if _prediction_overlaps_gold(str(prediction.get("normalized_answer") or ""), normalized_gold):
        return "normalization_or_metric_gap", "inspect_answer_normalization"

    span_covered = bool(coverage_flags.get("candidate_span_answer_covered"))
    answer_covered = bool(coverage_flags.get("candidate_answer_covered"))
    top5_covered = bool(coverage_flags.get("top5_covered"))
    top20_covered = bool(coverage_flags.get("top20_covered"))
    if not span_covered and not answer_covered:
        return "candidate_span_or_normalization_gap", "inspect_candidate_spans_or_normalization"
    if span_covered and not answer_covered:
        return "extraction_rule_gap", "improve_candidate_answer_extraction"
    if answer_covered and top5_covered:
        return "reader_selection_gap", "candidate_id_reader_or_deterministic_selection"
    if answer_covered and top20_covered:
        return "candidate_ranking_gap", "improve_candidate_answer_ranking"
    if answer_covered:
        return "topk_filtering_gap", "improve_type_aware_topk_filtering"
    return "unclassified", "manual_inspection"


def _prediction_overlaps_gold(normalized_prediction: str, normalized_gold: list[str]) -> bool:
    prediction = str(normalized_prediction or "").strip()
    if not prediction:
        return False
    return any(gold and (prediction in gold or gold in prediction) for gold in normalized_gold)


def _true_failure_action_bucket(refined_source: str, refined_action: str) -> str:
    if refined_action == "no_action_final_answer_already_correct":
        return "no_action_final_answer_already_correct"
    if refined_source == "normalization_or_metric_gap":
        return "normalization_or_metric_fix"
    if refined_source == "extraction_rule_gap":
        return "improve_candidate_answer_extraction"
    if refined_source == "candidate_span_or_normalization_gap":
        return "improve_candidate_spans"
    if refined_source in {"reader_selection_gap", "candidate_ranking_gap", "topk_filtering_gap"}:
        return "candidate_id_reader_or_reranking"
    return "candidate_id_reader_or_reranking"


def _build_candidate_span_gap_case(refined_case: dict[str, Any], detailed_case: dict[str, Any]) -> dict[str, Any]:
    qid = str(refined_case.get("qid") or detailed_case.get("qid") or "")
    question = str(refined_case.get("question") or detailed_case.get("question") or "")
    gold_debug = detailed_case.get("gold_answer_debug") or {}
    normalized_gold = [str(answer) for answer in (gold_debug.get("normalized_gold_answers") or [])]
    gold_preview = [str(answer) for answer in (gold_debug.get("gold_answer_forms_preview") or [])]
    prediction = detailed_case.get("phase4c_prediction") or {}
    normalized_prediction = str(refined_case.get("phase4c_normalized_answer") or prediction.get("normalized_answer") or "")
    top_spans = list(detailed_case.get("top_candidate_spans") or [])
    subtype = _candidate_span_gap_subtype_a4(
        question=question,
        normalized_gold=normalized_gold,
        gold_preview=gold_preview,
        normalized_prediction=normalized_prediction,
        top_spans=top_spans,
    )
    return {
        "qid": qid,
        "bucket": refined_case.get("bucket"),
        "question": question,
        "phase4c_answer_hit": bool(refined_case.get("phase4c_answer_hit")),
        "phase4c_normalized_answer": normalized_prediction,
        "candidate_span_answer_covered": bool(refined_case.get("candidate_span_answer_covered")),
        "candidate_answer_covered": bool(refined_case.get("candidate_answer_covered")),
        "top1_covered": bool(refined_case.get("top1_covered")),
        "top5_covered": bool(refined_case.get("top5_covered")),
        "top20_covered": bool(refined_case.get("top20_covered")),
        "original_likely_failure_source": refined_case.get("original_likely_failure_source"),
        "refined_failure_source": refined_case.get("refined_failure_source"),
        "refined_recommended_action": refined_case.get("refined_recommended_action"),
        "gap_subtype": subtype,
        "recommended_next_action": GAP_RECOMMENDED_ACTIONS[subtype],
        "is_generic_fix_candidate": subtype != "unclear_mixed_gap",
        "should_not_patch_specific_qid": True,
        "gold_answer_debug": {
            "normalized_gold_answers": normalized_gold,
            "gold_answer_forms_preview": gold_preview[:5],
        },
        "top_candidate_spans": top_spans[:5],
    }


def _candidate_span_gap_subtype_a4(
    *,
    question: str,
    normalized_gold: list[str],
    gold_preview: list[str],
    normalized_prediction: str,
    top_spans: list[dict[str, Any]],
) -> str:
    span_text = " ".join(str(span.get("text_preview") or span.get("text") or "") for span in top_spans)
    joined_gold = " ".join([*normalized_gold, *gold_preview])
    normalized_span = _normalize_answer(span_text)
    normalized_question = _normalize_answer(question)
    if not question or not normalized_gold:
        return "unclear_mixed_gap"
    if _normalization_or_metric_gap(normalized_prediction, normalized_gold):
        return "normalization_or_metric_gap"
    combined = " ".join([normalized_question, _normalize_answer(joined_gold), normalized_span])
    if _has_page_lookup_signal(combined):
        return "page_number_or_content_lookup_gap"
    if _has_table_index_signal(combined):
        return "table_or_index_span_gap"
    if _has_partial_context_signal(normalized_question, normalized_gold, normalized_span):
        return "candidate_span_partial_context_gap"
    if _has_question_context_signal(normalized_question, normalized_span):
        return "ocr_or_parsing_gap"
    if top_spans:
        return "candidate_span_selection_gap"
    return "unclear_mixed_gap"


def _normalization_or_metric_gap(normalized_prediction: str, normalized_gold: list[str]) -> bool:
    prediction = str(normalized_prediction or "").strip()
    if _prediction_overlaps_gold(prediction, normalized_gold):
        return True
    prediction_numbers = _number_set(prediction)
    if prediction_numbers and any(prediction_numbers == _number_set(gold) for gold in normalized_gold):
        return True
    prediction_tokens = _content_tokens(prediction)
    return any(_token_overlap_ratio(prediction_tokens, _content_tokens(gold)) >= 0.75 for gold in normalized_gold)


def _has_page_lookup_signal(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "page number",
            "which page",
            "what page",
            "mentioned on which page",
            "content",
            "chapter",
            "section",
        )
    )


def _has_table_index_signal(text: str) -> bool:
    if any(term in text for term in ("index", "share", "rate", "segment", "table", "row", "column", "percentage", "percent")):
        return True
    return re.search(r"\(\s*\d+(?:\.\d+)?\s*\)", text) is not None


def _has_partial_context_signal(normalized_question: str, normalized_gold: list[str], normalized_span: str) -> bool:
    if not normalized_span:
        return False
    gold_tokens = set().union(*(_content_tokens(gold) for gold in normalized_gold))
    if gold_tokens and gold_tokens.intersection(_content_tokens(normalized_span)):
        return True
    if _number_set(" ".join(normalized_gold)).intersection(_number_set(normalized_span)):
        return True
    question_tokens = _content_tokens(normalized_question)
    return bool(question_tokens.intersection(_content_tokens(normalized_span))) and any(sep in normalized_span for sep in (":", "-", "located", "total", "name"))


def _has_question_context_signal(normalized_question: str, normalized_span: str) -> bool:
    question_tokens = _content_tokens(normalized_question)
    span_tokens = _content_tokens(normalized_span)
    return len(question_tokens.intersection(span_tokens)) >= 2


def _number_set(text: str) -> set[str]:
    values: set[str] = set()
    for match in re.findall(r"-?\d+(?:\.\d+)?", str(text or "")):
        try:
            number = float(match)
        except ValueError:
            continue
        values.add(str(int(number)) if number.is_integer() else str(number))
    return values


def _content_tokens(text: str) -> set[str]:
    stopwords = {
        "a",
        "an",
        "and",
        "are",
        "for",
        "in",
        "is",
        "of",
        "on",
        "or",
        "the",
        "to",
        "what",
        "which",
        "who",
        "with",
    }
    return {token for token in str(text or "").split() if len(token) > 2 and token not in stopwords}


def _token_overlap_ratio(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left.intersection(right)) / max(min(len(left), len(right)), 1)


def _candidate_span_gap_subtype(*, qa: dict[str, Any], candidate_record: dict[str, Any], notes: list[str]) -> str:
    gold_page = _gold_page_number(qa)
    top_pages = {_safe_int(page.get("page")) for page in (candidate_record.get("top_pages") or [])}
    question = str(qa.get("question") or "").lower()
    if gold_page is not None and top_pages and gold_page not in top_pages:
        notes.append("gold_page_not_in_top_pages")
        return "retrieval_gap"
    if any(term in question for term in ("page number", "which page", "what page", "content index")):
        return "page_number_or_content_index_handling"
    if any(term in question for term in ("index", "table", "row", "column")):
        return "table_or_index_span_selection"
    notes.append("gold_answer_not_found_in_candidate_span_text")
    return "candidate_span_selection_gap_or_ocr_gap"


def _extraction_gap_subtype(*, qa: dict[str, Any], candidate_record: dict[str, Any]) -> str:
    question = str(qa.get("question") or candidate_record.get("question") or "").lower()
    hints = candidate_record.get("question_hints") or {}
    fields = " ".join(str(item).lower() for item in (hints.get("field_hints") or []))
    text = f"{question} {fields}"
    if any(term in text for term in ("heading", "title")):
        return "heading_or_title"
    if any(term in text for term in ("city", "state", "located", "address")):
        return "city_state_location"
    if any(term in text for term in ("short form", "abbreviation", "quarter", "q1", "q2", "q3", "q4")):
        return "short_form_abbreviation_or_quarter"
    if any(term in text for term in ("organization", "company", "board", "agency", "name", "logo")):
        return "organization_or_name"
    if any(term in text for term in ("field", "value", "number", "id", "code", "contract")):
        return "key_value_or_field_value"
    if any(term in text for term in ("source", "footer", "cited")):
        return "source_or_footer"
    return "generic_text_phrase"


def _selection_gap_subtype(
    *,
    first_rank: Any,
    candidate_answers: list[dict[str, Any]],
    topk_answers: list[dict[str, Any]],
    coverage_flags: dict[str, bool],
    notes: list[str],
) -> str:
    numeric_count = sum(1 for answer in topk_answers if answer.get("answer_type") in NUMERIC_TYPES)
    type_distribution = Counter(str(answer.get("answer_type") or "unknown") for answer in topk_answers)
    same_type_max = max(type_distribution.values()) if type_distribution else 0
    if coverage_flags.get("top5_covered"):
        return "reader_selection_issue"
    try:
        rank = int(first_rank)
    except (TypeError, ValueError):
        rank = None
    if rank is not None and rank > 5:
        notes.append(f"gold_answer_rank={rank}")
        return "ranking_issue"
    if same_type_max >= 8:
        notes.append(f"topk_same_type_max={same_type_max}")
        return "candidate_selection_or_reranking_issue"
    if numeric_count >= max(6, len(topk_answers) // 2):
        notes.append(f"topk_numeric_count={numeric_count}")
        return "numeric_filtering_issue"
    if candidate_answers and not coverage_flags.get("top20_covered"):
        return "topk_retention_issue"
    return "reader_or_candidate_selection_issue"


def _prediction_debug(answer_result: dict[str, Any]) -> dict[str, Any]:
    answer = _first_present(
        answer_result,
        ("answer", "predicted_answer", "prediction", "final_answer", "model_answer", "response"),
    )
    metrics = answer_result.get("answer_metrics") or {}
    return {
        "answer": answer,
        "normalized_answer": _normalize_answer(answer) if answer is not None else "",
        "answer_hit": bool(metrics.get("answer_hit") or metrics.get("normalized_exact_match")),
        "selected_page": _first_present(answer_result, ("selected_page", "page", "final_page", "predicted_page")),
        "selected_block_id": _first_present(answer_result, ("selected_block_id", "block_id", "final_block_id", "predicted_block_id")),
    }


def _load_bucket_records(
    *,
    run_dir: Path,
    candidate_records: list[dict[str, Any]],
    answer_boards: list[dict[str, Any]],
    qa_records: list[dict[str, Any]],
    answer_results: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    path = run_dir / "candidate_answer_error_buckets.json"
    if path.exists():
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        return list(payload.get("records") or [])
    return _classify_records(
        candidate_records=candidate_records,
        answer_boards=answer_boards,
        qa_records=qa_records,
        answer_results=answer_results,
    )


def _classify_records(
    *,
    candidate_records: list[dict[str, Any]],
    answer_boards: list[dict[str, Any]],
    qa_records: list[dict[str, Any]],
    answer_results: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    records_by_qid = {str(record.get("qid")): record for record in candidate_records}
    boards_by_qid = {str(board.get("qid")): board for board in answer_boards}
    answer_results_by_qid = {str(row.get("qid")): row for row in (answer_results or [])}
    records: list[dict[str, Any]] = []
    for qa in qa_records:
        qid = str(qa.get("qid"))
        candidate_record = records_by_qid.get(qid, {})
        board = boards_by_qid.get(qid, {})
        gold_answers = _qa_answer_list(qa)
        span_covered = candidate_span_contains_answer(candidate_record.get("candidate_spans") or [], gold_answers)
        answer_coverage = compute_candidate_answer_coverage(board.get("candidate_answers") or [], gold_answers)
        answer_covered = bool(answer_coverage["covered"])
        bucket = "G"
        reason = "answer_results_unavailable"
        if not span_covered:
            bucket = "C"
            reason = "gold_answer_not_in_candidate_spans"
        elif not answer_covered:
            bucket = "D"
            reason = "gold_answer_in_candidate_spans_but_not_extracted"
        elif answer_results is not None:
            prediction = _prediction_debug(answer_results_by_qid.get(qid, {}))
            bucket = "F" if prediction["answer_hit"] else "E"
            reason = _reason_for_bucket(bucket)
        records.append(
            {
                "qid": qid,
                "doc_id": qa.get("doc_id"),
                "question": qa.get("question"),
                "bucket": bucket,
                "reason": reason,
            }
        )
    return records


def _build_summary(
    *,
    args: argparse.Namespace,
    cases: list[dict[str, Any]],
    refined_cases: list[dict[str, Any]],
    requested_buckets: list[str],
    answer_boards: list[dict[str, Any]],
    topk_boards: list[dict[str, Any]],
    paths: dict[str, Path],
    output_dir: Path,
) -> dict[str, Any]:
    bucket_counts = Counter({bucket: 0 for bucket in requested_buckets})
    diagnosis_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    subtype_counts: Counter[str] = Counter()
    for case in cases:
        bucket_counts[str(case.get("bucket"))] += 1
        diagnosis = case.get("diagnosis_hints") or {}
        diagnosis_counts[str(diagnosis.get("likely_failure_source") or "unknown")] += 1
        action_counts[str(diagnosis.get("recommended_next_action") or "unknown")] += 1
        subtype_counts[str(diagnosis.get("subtype") or "unknown")] += 1
    refined_source_counts = Counter(str(case.get("refined_failure_source") or "unknown") for case in refined_cases)
    refined_action_counts = Counter(str(case.get("refined_recommended_action") or "unknown") for case in refined_cases)
    true_action_counts = Counter({key: 0 for key in TRUE_FAILURE_ACTION_KEYS})
    true_action_counts.update(str(case.get("true_failure_action") or "candidate_id_reader_or_reranking") for case in refined_cases)
    return {
        "phase": "Phase 4D-A.3.1",
        "task": "case_level_failure_inspection",
        "status": "success",
        "source_run_dir": _path_for_summary(args.run_dir),
        "bucket_counts": dict(bucket_counts),
        "bucket_answer_hit_breakdown": _bucket_answer_hit_breakdown(cases, requested_buckets),
        "bucket_candidate_coverage_breakdown": _bucket_candidate_coverage_breakdown(cases, requested_buckets),
        "diagnosis_counts": dict(sorted(diagnosis_counts.items())),
        "recommended_next_action_counts": dict(sorted(action_counts.items())),
        "diagnosis_subtype_counts": dict(sorted(subtype_counts.items())),
        "refined_failure_source_counts": dict(sorted(refined_source_counts.items())),
        "refined_recommended_action_counts": dict(sorted(refined_action_counts.items())),
        "true_failure_action_counts": dict(sorted(true_action_counts.items())),
        "case_count": len(cases),
        "requested_buckets": requested_buckets,
        "max_cases_per_bucket": int(args.max_cases_per_bucket),
        "top_spans": int(args.top_spans),
        "top_candidates": int(args.top_candidates),
        "artifact_paths": {key: _relative_to(path, output_dir) for key, path in paths.items()},
        "inspection_contains_gold_for_debug_only": True,
        "inspection_artifacts_must_not_be_reader_input": True,
        "candidate_answers_remain_gold_free": not candidate_answer_artifact_has_gold_leakage(answer_boards),
        "candidate_answers_topk_remain_gold_free": not candidate_answer_artifact_has_gold_leakage(topk_boards),
        "does_not_modify_reader": True,
        "does_not_run_answer_policy": True,
        "does_not_train": True,
    }


def _build_refined_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "phase": "Phase 4D-A.3.1",
        "task": "failure_inspection_summary_refinement",
        "status": summary["status"],
        "source_run_dir": summary["source_run_dir"],
        "case_count": summary["case_count"],
        "bucket_counts": summary["bucket_counts"],
        "bucket_answer_hit_breakdown": summary["bucket_answer_hit_breakdown"],
        "bucket_candidate_coverage_breakdown": summary["bucket_candidate_coverage_breakdown"],
        "refined_failure_source_counts": summary["refined_failure_source_counts"],
        "refined_recommended_action_counts": summary["refined_recommended_action_counts"],
        "true_failure_action_counts": summary["true_failure_action_counts"],
        "inspection_contains_gold_for_debug_only": summary["inspection_contains_gold_for_debug_only"],
        "inspection_artifacts_must_not_be_reader_input": summary["inspection_artifacts_must_not_be_reader_input"],
        "does_not_modify_reader": summary["does_not_modify_reader"],
        "does_not_run_answer_policy": summary["does_not_run_answer_policy"],
        "does_not_train": summary["does_not_train"],
        "artifact_paths": {
            "failure_inspection_refined_cases": summary["artifact_paths"]["failure_inspection_refined_cases"],
            "failure_inspection_refined_summary": summary["artifact_paths"]["failure_inspection_refined_summary"],
            "failure_inspection_refined_summary_md": summary["artifact_paths"]["failure_inspection_refined_summary_md"],
        },
    }


def _bucket_answer_hit_breakdown(cases: list[dict[str, Any]], buckets: list[str]) -> dict[str, dict[str, int]]:
    breakdown = {
        bucket: {"total": 0, "final_answer_hit_true": 0, "final_answer_hit_false": 0}
        for bucket in buckets
    }
    for case in cases:
        bucket = str(case.get("bucket") or "")
        if bucket not in breakdown:
            continue
        breakdown[bucket]["total"] += 1
        hit_key = "final_answer_hit_true" if (case.get("phase4c_prediction") or {}).get("answer_hit") else "final_answer_hit_false"
        breakdown[bucket][hit_key] += 1
    return breakdown


def _bucket_candidate_coverage_breakdown(cases: list[dict[str, Any]], buckets: list[str]) -> dict[str, dict[str, int]]:
    breakdown = {
        bucket: {
            "candidate_answer_covered_true": 0,
            "candidate_answer_covered_false": 0,
            "top1_covered_true": 0,
            "top5_covered_true": 0,
            "top20_covered_true": 0,
        }
        for bucket in buckets
    }
    for case in cases:
        bucket = str(case.get("bucket") or "")
        if bucket not in breakdown:
            continue
        flags = case.get("coverage_flags") or {}
        answer_key = "candidate_answer_covered_true" if flags.get("candidate_answer_covered") else "candidate_answer_covered_false"
        breakdown[bucket][answer_key] += 1
        if flags.get("top1_covered"):
            breakdown[bucket]["top1_covered_true"] += 1
        if flags.get("top5_covered"):
            breakdown[bucket]["top5_covered_true"] += 1
        if flags.get("top20_covered"):
            breakdown[bucket]["top20_covered_true"] += 1
    return breakdown


def _build_preview(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        bucket = str(case.get("bucket") or "G")
        if len(by_bucket[bucket]) < 3:
            item = dict(case)
            item["top_candidate_spans"] = item.get("top_candidate_spans", [])[:2]
            item["top_candidate_answers"] = item.get("top_candidate_answers", [])[:5]
            by_bucket[bucket].append(item)
    return {"records": [case for bucket in sorted(by_bucket) for case in by_bucket[bucket]]}


def _candidate_span_gap_preview(cases: list[dict[str, Any]]) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    by_subtype: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        subtype = str(case.get("gap_subtype") or "unclear_mixed_gap")
        if len(by_subtype[subtype]) >= 2:
            continue
        item = dict(case)
        item["top_candidate_spans"] = item.get("top_candidate_spans", [])[:2]
        by_subtype[subtype].append(item)
    for subtype in GAP_SUBTYPES:
        records.extend(by_subtype.get(subtype, []))
    return {"records": records}


def _build_candidate_span_gap_summary(
    *,
    source_dir: Path,
    cases: list[dict[str, Any]],
    paths: dict[str, Path],
    output_dir: Path,
) -> dict[str, Any]:
    subtype_counts = Counter({subtype: 0 for subtype in GAP_SUBTYPES})
    action_counts = Counter({action: 0 for action in GAP_RECOMMENDED_ACTIONS.values()})
    for case in cases:
        subtype = str(case.get("gap_subtype") or "unclear_mixed_gap")
        action = str(case.get("recommended_next_action") or GAP_RECOMMENDED_ACTIONS["unclear_mixed_gap"])
        subtype_counts[subtype] += 1
        action_counts[action] += 1
    return {
        "phase": "Phase 4D-A.4",
        "task": "candidate_span_normalization_gap_final_review",
        "status": "success",
        "source_refined_run_dir": _path_for_summary(source_dir),
        "total_candidate_span_or_normalization_gap": len(cases),
        "gap_subtype_counts": {subtype: subtype_counts[subtype] for subtype in GAP_SUBTYPES},
        "recommended_next_action_counts": {
            action: action_counts[action]
            for action in (
                "inspect_answer_normalization",
                "improve_candidate_spans",
                "improve_candidate_span_neighbor_context",
                "improve_table_index_span_selection",
                "improve_page_number_content_lookup",
                "inspect_ocr_or_parsing",
                "manual_review_required",
            )
        },
        "decision_guidance": {
            "candidate_id_reader_should_remain_postponed": True,
            "allow_next_repair_only_if_generic_pattern_concentrated": True,
            "stop_after_this_diagnostic_stage": True,
        },
        "artifact_paths": {key: _relative_to(path, output_dir) for key, path in paths.items()},
        "does_not_modify_reader": True,
        "does_not_run_answer_policy": True,
        "does_not_train": True,
    }


def _candidate_span_gap_summary_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Phase 4D-A.4 Candidate Span / Normalization Gap Final Review",
            "",
            f"- status: {summary['status']}",
            f"- source_refined_run_dir: {summary['source_refined_run_dir']}",
            f"- total_candidate_span_or_normalization_gap: {summary['total_candidate_span_or_normalization_gap']}",
            f"- gap_subtype_counts: {json.dumps(summary['gap_subtype_counts'], sort_keys=True)}",
            f"- recommended_next_action_counts: {json.dumps(summary['recommended_next_action_counts'], sort_keys=True)}",
            "",
            "## Decision Gate",
            "",
            "If one subtype dominates and has a generic repair path, implement one narrow generic fix.",
            "If subtypes are dispersed, stop tuning on the 90-sample probe and run the same diagnostics on a larger unseen validation sample.",
            "Do not proceed to Candidate-ID Reader unless reader_selection_gap becomes dominant after candidate coverage issues are resolved.",
            "",
            "This diagnostic split is for audit and planning only. It does not modify Reader prompts, run AnswerPolicy, train models, or change candidate span / answer extraction logic.",
            "",
        ]
    )


def _summary_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Phase 4D-A.3.1 Failure Inspection",
            "",
            f"- status: {summary['status']}",
            f"- case_count: {summary['case_count']}",
            f"- bucket_counts: {json.dumps(summary['bucket_counts'], sort_keys=True)}",
            f"- bucket_answer_hit_breakdown: {json.dumps(summary['bucket_answer_hit_breakdown'], sort_keys=True)}",
            f"- bucket_candidate_coverage_breakdown: {json.dumps(summary['bucket_candidate_coverage_breakdown'], sort_keys=True)}",
            f"- diagnosis_counts: {json.dumps(summary['diagnosis_counts'], sort_keys=True)}",
            f"- recommended_next_action_counts: {json.dumps(summary['recommended_next_action_counts'], sort_keys=True)}",
            f"- refined_failure_source_counts: {json.dumps(summary['refined_failure_source_counts'], sort_keys=True)}",
            f"- true_failure_action_counts: {json.dumps(summary['true_failure_action_counts'], sort_keys=True)}",
            f"- inspection_contains_gold_for_debug_only: {summary['inspection_contains_gold_for_debug_only']}",
            f"- inspection_artifacts_must_not_be_reader_input: {summary['inspection_artifacts_must_not_be_reader_input']}",
            f"- candidate_answers_remain_gold_free: {summary['candidate_answers_remain_gold_free']}",
            f"- candidate_answers_topk_remain_gold_free: {summary['candidate_answers_topk_remain_gold_free']}",
            "",
            "This report is for audit and debugging only. It does not modify Reader prompts, run AnswerPolicy, train models, or change retrieval.",
            "",
        ]
    )


def _refined_summary_markdown(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Phase 4D-A.3.1 Refined Failure Inspection Summary",
            "",
            f"- status: {summary['status']}",
            f"- case_count: {summary['case_count']}",
            f"- bucket_counts: {json.dumps(summary['bucket_counts'], sort_keys=True)}",
            f"- refined_failure_source_counts: {json.dumps(summary['refined_failure_source_counts'], sort_keys=True)}",
            f"- refined_recommended_action_counts: {json.dumps(summary['refined_recommended_action_counts'], sort_keys=True)}",
            f"- true_failure_action_counts: {json.dumps(summary['true_failure_action_counts'], sort_keys=True)}",
            f"- inspection_contains_gold_for_debug_only: {summary['inspection_contains_gold_for_debug_only']}",
            "",
            "This refined summary combines bucket labels, final answer hit, candidate answer coverage, and top-k coverage for action attribution only.",
            "",
        ]
    )


def _parse_buckets(raw: str) -> list[str]:
    buckets = [item.strip().upper() for item in raw.split(",") if item.strip()]
    invalid = [bucket for bucket in buckets if bucket not in INSPECTION_BUCKETS]
    if invalid:
        raise ValueError(f"Unsupported inspection buckets: {invalid}. Supported: {list(INSPECTION_BUCKETS)}")
    return buckets or list(INSPECTION_BUCKETS)


def _qa_answer_list(record: dict[str, Any]) -> list[str]:
    answers = record.get("answers")
    if isinstance(answers, list):
        return [str(item) for item in answers]
    if answers:
        return [str(answers)]
    return []


def _gold_page_number(qa: dict[str, Any]) -> int | None:
    for key in ("gold_page_ordinal", "parsed_page_number"):
        if qa.get(key) is not None:
            return _safe_int(qa.get(key))
    if qa.get("answer_page_idx") is not None:
        page_idx = _safe_int(qa.get("answer_page_idx"))
        return page_idx + 1 if page_idx is not None else None
    return None


def _reason_for_bucket(bucket: str) -> str:
    return {
        "C": "gold_answer_not_in_candidate_spans",
        "D": "gold_answer_in_candidate_spans_but_not_extracted",
        "E": "gold_answer_in_candidate_answers_but_model_answer_wrong",
        "F": "gold_answer_in_candidate_answers_and_model_answer_correct",
    }.get(bucket, "unclassified")


def _first_present(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if row.get(key) is not None:
            return row.get(key)
    return None


def _read_optional_jsonl(path: Path | None) -> list[dict[str, Any]] | None:
    if path is None or not path.exists():
        return None
    return read_jsonl(path)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _path_for_summary(path: Path) -> str:
    return _relative_to(path, Path.cwd())


def _relative_to(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _truncate(text: str, *, limit: int) -> str:
    text = str(text or "").replace("\r", " ").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return round(float(value), 6)
    except (TypeError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.candidate_span_gap_review:
        summary = run_phase4d_candidate_span_gap_review(args)
        print(json.dumps({"status": summary["status"], "summary": summary["artifact_paths"]["candidate_span_gap_summary"]}, ensure_ascii=False))
        return 0
    summary = run_phase4d_failure_inspection(args)
    print(json.dumps({"status": summary["status"], "summary": summary["artifact_paths"]["failure_inspection_summary"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

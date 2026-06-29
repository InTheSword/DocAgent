from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.schemas import DocAgentSample, EvidenceBlock
from docagent.tools.table_tools import table_lookup_or_calculation
from docagent.utils.jsonl import read_jsonl, write_jsonl


EVALUATION_SCOPE = "local_subset_diagnostic_not_formal_benchmark"
SCRIPT_VERSION = "final-eval-runner-v1"
DEFAULT_OUTPUT_ROOT = ROOT / "outputs" / "final_eval" / "local_subset_diagnostic"


class InMemoryDocumentRepository:
    def __init__(self, sample: DocAgentSample) -> None:
        self.sample = sample

    def get_document(self, doc_id: str) -> dict[str, Any] | None:
        if doc_id != self.sample.doc_id:
            return None
        return {
            "doc_id": self.sample.doc_id,
            "original_name": f"{self.sample.source}:{self.sample.doc_id}",
            "page_count": max((_block_page(block) or 1) for block in self.sample.evidence) if self.sample.evidence else 1,
            "parser_backend": "sample_evidence",
            "parse_status": "ready",
        }

    def load_evidence_blocks(self, doc_id: str, *, include_page_blocks: bool = False) -> list[EvidenceBlock]:
        if doc_id != self.sample.doc_id:
            return []
        blocks = list(self.sample.evidence)
        if not include_page_blocks:
            blocks = [block for block in blocks if block.block_type != "page"]
        return blocks


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
    return f"final_eval_subset_{stamp}"


def write_json(path: Path, payload: dict[str, Any] | list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)]


def load_manifest(path: Path | None) -> dict[str, dict[str, Any]]:
    if path is None or not path.is_file():
        return {}
    rows = read_jsonl(path)
    return {str(row.get("sample_id") or row.get("qid")): row for row in rows}


def load_samples(path: Path | None) -> list[DocAgentSample]:
    if path is None or not path.is_file():
        return []
    return [DocAgentSample.from_dict(row) for row in read_jsonl(path)]


def _block_page(block: EvidenceBlock) -> int | None:
    if block.page_id is not None:
        return int(block.page_id)
    if block.location.page is not None:
        return int(block.location.page)
    return None


def gold_block_ids(manifest: dict[str, Any], sample: DocAgentSample | None = None) -> set[str]:
    ids = {str(item.get("block_id")) for item in manifest.get("gold_evidence") or [] if item.get("block_id")}
    if not ids and sample is not None:
        ids.update(str(item) for item in sample.metadata.get("gold_block_ids") or [])
    return ids


def gold_pages(manifest: dict[str, Any]) -> set[int]:
    pages = set()
    for item in manifest.get("gold_evidence") or []:
        value = item.get("page")
        if value is None:
            continue
        try:
            pages.add(int(value))
        except (TypeError, ValueError):
            continue
    return pages


def citation_block_ids(citations: list[dict[str, Any]]) -> set[str]:
    return {str(item.get("block_id")) for item in citations if item.get("block_id")}


def citation_pages(citations: list[dict[str, Any]]) -> set[int]:
    pages = set()
    for item in citations:
        value = item.get("page")
        if value is None:
            continue
        try:
            pages.add(int(value))
        except (TypeError, ValueError):
            continue
    return pages


def normalize_text(value: Any) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"[\$,]", "", text)
    text = re.sub(r"[^a-z0-9.%()/-]+", " ", text)
    return " ".join(text.split())


def parse_number(value: Any) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value or "")
    match = re.search(r"\(?-?\$?\d[\d,]*(?:\.\d+)?%?\)?", text)
    if not match:
        return None
    raw = match.group(0)
    negative = raw.startswith("(") and raw.endswith(")")
    cleaned = raw.strip("()").replace("$", "").replace(",", "").replace("%", "")
    try:
        parsed = float(cleaned)
    except ValueError:
        return None
    return -parsed if negative else parsed


def answer_metrics(prediction: str, answers: list[str], expected_answer_type: str) -> dict[str, Any]:
    prediction_text = normalize_text(prediction)
    normalized_answers = [normalize_text(answer) for answer in answers if normalize_text(answer)]
    exact_or_contains = any(answer and answer in prediction_text for answer in normalized_answers)
    payload: dict[str, Any] = {
        "answer_evaluated": bool(answers),
        "answer_hit": exact_or_contains,
        "normalized_prediction": prediction_text,
        "normalized_answers": normalized_answers,
    }
    if expected_answer_type == "numeric":
        expected_numbers = [parse_number(answer) for answer in answers]
        expected_numbers = [number for number in expected_numbers if number is not None]
        predicted_number = parse_number(prediction)
        numeric_hit = False
        numeric_abs_error = None
        if expected_numbers and predicted_number is not None:
            errors = [abs(predicted_number - expected) for expected in expected_numbers]
            numeric_abs_error = min(errors)
            tolerance = max(0.01, 0.001 * max(abs(value) for value in expected_numbers))
            numeric_hit = numeric_abs_error <= tolerance
        payload.update(
            {
                "numeric_evaluated": bool(expected_numbers),
                "predicted_number": predicted_number,
                "expected_numbers": expected_numbers,
                "numeric_abs_error": numeric_abs_error,
                "numeric_accuracy": numeric_hit,
                "answer_hit": exact_or_contains or numeric_hit,
            }
        )
    else:
        payload.update(
            {
                "numeric_evaluated": False,
                "predicted_number": None,
                "expected_numbers": [],
                "numeric_abs_error": None,
                "numeric_accuracy": False,
            }
        )
    return payload


def required_contract_fields(result: dict[str, Any]) -> list[str]:
    required = ["answer", "reasoning_summary", "evidence_used", "citations", "tools_used"]
    return [field for field in required if field not in result]


def run_tatqa_sample(sample: DocAgentSample, manifest: dict[str, Any]) -> dict[str, Any]:
    expected_tools = [str(item) for item in manifest.get("expected_tools") or []]
    expected_answer_type = str(manifest.get("expected_answer_type") or sample.answer_type)
    answers = as_list(manifest.get("answers") if "answers" in manifest else sample.answer)
    gold_ids = gold_block_ids(manifest, sample)
    gold_page_values = gold_pages(manifest)
    row: dict[str, Any] = {
        "sample_id": sample.qid,
        "dataset": "tatqa",
        "split": sample.split,
        "doc_id": sample.doc_id,
        "question": sample.question,
        "answers": answers,
        "expected_answer_type": expected_answer_type,
        "expected_tools": expected_tools,
        "gold_block_ids": sorted(gold_ids),
        "gold_pages": sorted(gold_page_values),
        "evaluation_mode": "manifest_readiness",
        "requires_model_answer": True,
        "tool_executed": False,
        "tool_status": "not_run",
        "prediction_answer": "",
        "tools_used": [],
        "citations": [],
        "format_valid": True,
        "missing_contract_fields": [],
    }
    should_run_table_tool = "table_lookup" in expected_tools or "simple_calculation" in expected_tools
    if should_run_table_tool:
        result = table_lookup_or_calculation(
            InMemoryDocumentRepository(sample),  # type: ignore[arg-type]
            sample.doc_id,
            sample.question,
            selected_tools=expected_tools,
        )
        citations = [item for item in result.get("citations") or [] if isinstance(item, dict)]
        missing_fields = required_contract_fields(result)
        row.update(
            {
                "evaluation_mode": "deterministic_table_tool",
                "requires_model_answer": False,
                "tool_executed": True,
                "tool_status": str(result.get("status") or ""),
                "prediction_answer": str(result.get("answer") or ""),
                "reasoning_summary": str(result.get("reasoning_summary") or ""),
                "tools_used": [str(item) for item in result.get("tools_used") or []],
                "citations": citations,
                "format_valid": not missing_fields,
                "missing_contract_fields": missing_fields,
                "structured_result": result.get("structured_result") or {},
                "warnings": result.get("warnings") or [],
                "error": result.get("error") or {},
            }
        )

    cited_ids = citation_block_ids(row["citations"])
    cited_pages = citation_pages(row["citations"])
    citation_block_hit = bool(gold_ids and cited_ids and gold_ids.intersection(cited_ids))
    citation_page_hit = bool(gold_page_values and cited_pages and gold_page_values.intersection(cited_pages))
    evidence_ready = bool(gold_ids or gold_page_values)
    metrics = answer_metrics(row["prediction_answer"], answers, expected_answer_type) if row["tool_executed"] else {}
    if not metrics:
        metrics = {
            "answer_evaluated": False,
            "answer_hit": False,
            "numeric_evaluated": False,
            "numeric_accuracy": False,
            "numeric_abs_error": None,
            "predicted_number": None,
            "expected_numbers": [],
            "normalized_prediction": "",
            "normalized_answers": [normalize_text(answer) for answer in answers],
        }
    row.update(
        {
            **metrics,
            "evidence_ready": evidence_ready,
            "citation_evaluated": row["tool_executed"] and bool(gold_ids or gold_page_values),
            "citation_block_hit": citation_block_hit,
            "citation_page_hit": citation_page_hit,
        }
    )
    row["pass_fail"] = "passed" if _tatqa_row_passes(row, citation_block_hit, citation_page_hit, metrics) else "failed"
    row["failure_reasons"] = _failure_reasons(row)
    row["failure_stage"] = _failure_stage(row["failure_reasons"])
    return row


def _tatqa_row_passes(
    row: dict[str, Any],
    citation_block_hit: bool,
    citation_page_hit: bool,
    metrics: dict[str, Any],
) -> bool:
    if not row.get("format_valid"):
        return False
    if not row.get("tool_executed"):
        return bool(row.get("evidence_ready"))
    if row.get("tool_status") != "success":
        return False
    if row.get("gold_block_ids") and not citation_block_hit:
        return False
    if row.get("gold_pages") and not citation_page_hit:
        return False
    return bool(metrics.get("answer_hit"))


def run_mpdocvqa_manifest_row(manifest: dict[str, Any]) -> dict[str, Any]:
    answers = as_list(manifest.get("answers"))
    gold_ids = gold_block_ids(manifest)
    gold_page_values = gold_pages(manifest)
    row = {
        "sample_id": str(manifest.get("sample_id") or ""),
        "dataset": "mp_docvqa",
        "split": str(manifest.get("split") or "val"),
        "doc_id": str(manifest.get("doc_id") or ""),
        "source_document": str(manifest.get("source_document") or ""),
        "question": str(manifest.get("question") or ""),
        "answers": answers,
        "expected_answer_type": str(manifest.get("expected_answer_type") or "extractive"),
        "expected_tools": [str(item) for item in manifest.get("expected_tools") or []],
        "gold_block_ids": sorted(gold_ids),
        "gold_pages": sorted(gold_page_values),
        "evaluation_mode": "page_manifest_readiness",
        "requires_mineru_or_retrieval": True,
        "requires_model_answer": True,
        "tool_executed": False,
        "tool_status": "not_run",
        "prediction_answer": "",
        "tools_used": [],
        "citations": [],
        "answer_evaluated": False,
        "answer_hit": False,
        "numeric_evaluated": False,
        "numeric_accuracy": False,
        "citation_evaluated": False,
        "citation_block_hit": False,
        "citation_page_hit": False,
        "format_valid": True,
        "evidence_ready": bool(answers and gold_page_values),
        "pass_fail": "passed" if answers and gold_page_values and manifest.get("doc_id") else "failed",
    }
    row["failure_reasons"] = _failure_reasons(row)
    row["failure_stage"] = _failure_stage(row["failure_reasons"])
    return row


def _failure_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("pass_fail") == "passed":
        return reasons
    if not row.get("format_valid"):
        reasons.append("format_invalid")
    if not row.get("evidence_ready"):
        reasons.append("evidence_not_ready")
    if row.get("tool_executed") and row.get("tool_status") != "success":
        error = row.get("error") or {}
        error_type = str(error.get("type") or row.get("tool_status") or "tool_failed")
        reasons.append(error_type)
    if row.get("citation_evaluated"):
        if row.get("gold_block_ids") and not row.get("citation_block_hit"):
            reasons.append("citation_block_miss")
        if row.get("gold_pages") and not row.get("citation_page_hit"):
            reasons.append("citation_page_miss")
    if row.get("answer_evaluated") and not row.get("answer_hit"):
        reasons.append("answer_miss")
    return list(dict.fromkeys(reasons or ["unknown_failure"]))


def _failure_stage(reasons: list[str]) -> str:
    if not reasons:
        return ""
    priority = [
        ("format", {"format_invalid"}),
        ("evidence_readiness", {"evidence_not_ready"}),
        ("tool_execution", {"table_lookup_unsupported", "simple_calculation_unsupported", "simple_calculation_failed"}),
        ("attribution", {"citation_block_miss", "citation_page_miss"}),
        ("answer_quality", {"answer_miss"}),
    ]
    reason_set = set(reasons)
    for stage, stage_reasons in priority:
        if reason_set.intersection(stage_reasons):
            return stage
    return "other"


def limit_rows(rows: list[Any], max_samples: int | None) -> list[Any]:
    if max_samples is None:
        return rows
    return rows[: max(0, int(max_samples))]


def summarize(rows: list[dict[str, Any]], *, run_id: str, artifact_dir: Path) -> dict[str, Any]:
    datasets = Counter(str(row.get("dataset") or "") for row in rows)
    modes = Counter(str(row.get("evaluation_mode") or "") for row in rows)
    pass_fail = Counter(str(row.get("pass_fail") or "") for row in rows)
    tools = Counter(tool for row in rows for tool in row.get("tools_used") or [])
    tool_statuses = Counter(str(row.get("tool_status") or "") for row in rows)
    failure_reasons = Counter(reason for row in rows for reason in row.get("failure_reasons") or [])
    failure_stages = Counter(str(row.get("failure_stage") or "") for row in rows if row.get("failure_stage"))
    case_count = len(rows)
    answer_evaluated_count = _count_true(rows, "answer_evaluated")
    numeric_evaluated_count = _count_true(rows, "numeric_evaluated")
    citation_evaluated_count = _count_true(rows, "citation_evaluated")
    return {
        "command": "run_final_eval_subset",
        "status": "success",
        "script_version": SCRIPT_VERSION,
        "evaluation_scope": EVALUATION_SCOPE,
        "quality_status": "diagnostic_only",
        "quality_status_semantics": "local subset readiness and deterministic-tool diagnostics, not formal benchmark acceptance",
        "run_id": run_id,
        "artifact_dir": safe_relpath(artifact_dir),
        "case_count": case_count,
        "passed_count": pass_fail.get("passed", 0),
        "failed_count": pass_fail.get("failed", 0),
        "pass_rate": _rate(pass_fail.get("passed", 0), case_count),
        "dataset_distribution": dict(sorted(datasets.items())),
        "evaluation_mode_distribution": dict(sorted(modes.items())),
        "tool_status_distribution": dict(sorted(tool_statuses.items())),
        "tools_used_distribution": dict(sorted(tools.items())),
        "failure_reason_distribution": dict(sorted(failure_reasons.items())),
        "failure_stage_distribution": dict(sorted(failure_stages.items())),
        "evidence_ready_count": _count_true(rows, "evidence_ready"),
        "evidence_ready_rate": _rate(_count_true(rows, "evidence_ready"), case_count),
        "tool_executed_count": _count_true(rows, "tool_executed"),
        "tool_success_count": sum(1 for row in rows if row.get("tool_executed") and row.get("tool_status") == "success"),
        "format_valid_count": _count_true(rows, "format_valid"),
        "format_valid_rate": _rate(_count_true(rows, "format_valid"), case_count),
        "answer_evaluated_count": answer_evaluated_count,
        "answer_hit_count": _count_true(rows, "answer_hit"),
        "answer_hit_rate": _rate(_count_true(rows, "answer_hit"), answer_evaluated_count),
        "numeric_evaluated_count": numeric_evaluated_count,
        "numeric_accuracy_count": _count_true(rows, "numeric_accuracy"),
        "numeric_accuracy_rate": _rate(_count_true(rows, "numeric_accuracy"), numeric_evaluated_count),
        "citation_evaluated_count": citation_evaluated_count,
        "citation_block_hit_count": _count_true(rows, "citation_block_hit"),
        "citation_page_hit_count": _count_true(rows, "citation_page_hit"),
        "citation_block_hit_rate": _rate(_count_true(rows, "citation_block_hit"), citation_evaluated_count),
        "citation_page_hit_rate": _rate(_count_true(rows, "citation_page_hit"), citation_evaluated_count),
        "requires_model_answer_count": _count_true(rows, "requires_model_answer"),
        "requires_mineru_or_retrieval_count": _count_true(rows, "requires_mineru_or_retrieval"),
        "final_llm_answer_quality_evaluated": False,
        "used_external_api": False,
        "used_qwen": False,
        "used_vlm": False,
        "used_training": False,
        "used_online_mineru_ocr": False,
        "used_full_e2e": False,
        "results_path": safe_relpath(artifact_dir / "results.jsonl"),
        "summary_path": safe_relpath(artifact_dir / "summary.json"),
        "summary_markdown_path": safe_relpath(artifact_dir / "summary.md"),
        "preview_path": safe_relpath(artifact_dir / "preview.json"),
        "manual_review_path": safe_relpath(artifact_dir / "manual_review.md"),
    }


def _count_true(rows: list[dict[str, Any]], key: str) -> int:
    return sum(1 for row in rows if row.get(key) is True)


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def write_manual_review(path: Path, rows: list[dict[str, Any]]) -> None:
    review_rows = [
        row
        for row in rows
        if row.get("pass_fail") == "failed" or row.get("requires_model_answer") or row.get("requires_mineru_or_retrieval")
    ][:50]
    lines = [
        "# Final Eval Local Subset Diagnostic",
        "",
        f"- evaluation_scope: `{EVALUATION_SCOPE}`",
        "- final_llm_answer_quality_evaluated: `false`",
        "- formal_benchmark_acceptance: `false`",
        "",
    ]
    if not review_rows:
        lines.append("No review rows were recorded.")
    for row in review_rows:
        lines.extend(
            [
                f"## {row.get('dataset')}:{row.get('sample_id')}",
                "",
                f"- pass_fail: {row.get('pass_fail')}",
                f"- evaluation_mode: {row.get('evaluation_mode')}",
                f"- question: {row.get('question')}",
                f"- expected_tools: {json.dumps(row.get('expected_tools') or [], ensure_ascii=False)}",
                f"- answer_hit: {row.get('answer_hit')}",
                f"- citation_block_hit: {row.get('citation_block_hit')}",
                f"- requires_model_answer: {row.get('requires_model_answer')}",
                f"- requires_mineru_or_retrieval: {row.get('requires_mineru_or_retrieval')}",
                "",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_summary_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Final Eval Local Subset Summary",
        "",
        "## Scope",
        "",
        f"- evaluation_scope: `{summary.get('evaluation_scope')}`",
        f"- quality_status: `{summary.get('quality_status')}`",
        "- formal_benchmark_acceptance: `false`",
        f"- final_llm_answer_quality_evaluated: `{str(summary.get('final_llm_answer_quality_evaluated')).lower()}`",
        f"- used_qwen: `{str(summary.get('used_qwen')).lower()}`",
        f"- used_online_mineru_ocr: `{str(summary.get('used_online_mineru_ocr')).lower()}`",
        f"- used_vlm: `{str(summary.get('used_vlm')).lower()}`",
        f"- used_training: `{str(summary.get('used_training')).lower()}`",
        "",
        "## Inputs",
        "",
        f"- run_id: `{summary.get('run_id')}`",
        f"- case_count: {summary.get('case_count')}",
        f"- passed_count: {summary.get('passed_count')}",
        f"- failed_count: {summary.get('failed_count')}",
        f"- pass_rate: {summary.get('pass_rate')}",
        "",
        "Dataset distribution:",
        *(_markdown_distribution(summary.get("dataset_distribution") or {})),
        "",
        "Evaluation mode distribution:",
        *(_markdown_distribution(summary.get("evaluation_mode_distribution") or {})),
        "",
        "## Evidence Readiness",
        "",
        f"- evidence_ready_count: {summary.get('evidence_ready_count')}",
        f"- evidence_ready_rate: {summary.get('evidence_ready_rate')}",
        f"- requires_model_answer_count: {summary.get('requires_model_answer_count')}",
        f"- requires_mineru_or_retrieval_count: {summary.get('requires_mineru_or_retrieval_count')}",
        "",
        "## Answer Quality",
        "",
        f"- answer_evaluated_count: {summary.get('answer_evaluated_count')}",
        f"- answer_hit_count: {summary.get('answer_hit_count')}",
        f"- answer_hit_rate: {summary.get('answer_hit_rate')}",
        f"- numeric_evaluated_count: {summary.get('numeric_evaluated_count')}",
        f"- numeric_accuracy_count: {summary.get('numeric_accuracy_count')}",
        f"- numeric_accuracy_rate: {summary.get('numeric_accuracy_rate')}",
        "",
        "## Attribution Quality",
        "",
        f"- citation_evaluated_count: {summary.get('citation_evaluated_count')}",
        f"- citation_block_hit_count: {summary.get('citation_block_hit_count')}",
        f"- citation_block_hit_rate: {summary.get('citation_block_hit_rate')}",
        f"- citation_page_hit_count: {summary.get('citation_page_hit_count')}",
        f"- citation_page_hit_rate: {summary.get('citation_page_hit_rate')}",
        "",
        "## Format Quality",
        "",
        f"- format_valid_count: {summary.get('format_valid_count')}",
        f"- format_valid_rate: {summary.get('format_valid_rate')}",
        "",
        "## Failure Taxonomy",
        "",
        "Failure stage distribution:",
        *(_markdown_distribution(summary.get("failure_stage_distribution") or {})),
        "",
        "Failure reason distribution:",
        *(_markdown_distribution(summary.get("failure_reason_distribution") or {})),
        "",
        "## Next Gates",
        "",
        "- Deterministic table failures remain local tool-quality work, not model acceptance evidence.",
        "- Text and MP-DocVQA cases require retrieval/MinerU evidence packs and Qwen AnswerPolicy evaluation.",
        "- Formal MP-DocVQA/TAT-QA benchmark status still requires the approved real parser/model evaluation path.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _markdown_distribution(distribution: dict[str, Any]) -> list[str]:
    if not distribution:
        return ["- none"]
    return [f"- {key}: {value}" for key, value in sorted(distribution.items())]


def run_final_eval_subset(
    *,
    output_root: Path = DEFAULT_OUTPUT_ROOT,
    run_id: str | None = None,
    tatqa_samples: Path | None = ROOT / "outputs" / "final_eval" / "tatqa_dev_subset" / "samples.jsonl",
    tatqa_manifest: Path | None = ROOT / "outputs" / "final_eval" / "tatqa_dev_subset" / "sample_manifest.jsonl",
    mpdocvqa_manifest: Path | None = ROOT / "outputs" / "final_eval" / "mpdocvqa_val_subset" / "sample_manifest.jsonl",
    dataset: str = "all",
    max_samples: int | None = None,
) -> dict[str, Any]:
    run_id = run_id or now_run_id()
    artifact_dir = output_root / run_id
    artifact_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    if dataset in {"all", "tatqa"}:
        manifest_by_id = load_manifest(tatqa_manifest)
        samples = limit_rows(load_samples(tatqa_samples), max_samples)
        rows.extend(run_tatqa_sample(sample, manifest_by_id.get(sample.qid, {})) for sample in samples)
    if dataset in {"all", "mpdocvqa", "mp_docvqa"}:
        mp_rows = list(load_manifest(mpdocvqa_manifest).values())
        mp_rows = limit_rows(mp_rows, max_samples)
        rows.extend(run_mpdocvqa_manifest_row(row) for row in mp_rows)

    summary = summarize(rows, run_id=run_id, artifact_dir=artifact_dir)
    write_jsonl(artifact_dir / "results.jsonl", rows)
    write_json(artifact_dir / "summary.json", summary)
    write_summary_markdown(artifact_dir / "summary.md", summary)
    write_json(artifact_dir / "preview.json", {"summary": summary, "results": rows[:5]})
    write_manual_review(artifact_dir / "manual_review.md", rows)
    return {
        **summary,
        "artifact_paths": [
            summary["results_path"],
            summary["summary_path"],
            summary["summary_markdown_path"],
            summary["preview_path"],
            summary["manual_review_path"],
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run local diagnostics over prepared final-evaluation subsets.")
    parser.add_argument("--dataset", choices=["all", "tatqa", "mpdocvqa", "mp_docvqa"], default="all")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_ROOT))
    parser.add_argument("--run-id")
    parser.add_argument("--tatqa-samples", default="outputs/final_eval/tatqa_dev_subset/samples.jsonl")
    parser.add_argument("--tatqa-manifest", default="outputs/final_eval/tatqa_dev_subset/sample_manifest.jsonl")
    parser.add_argument("--mpdocvqa-manifest", default="outputs/final_eval/mpdocvqa_val_subset/sample_manifest.jsonl")
    parser.add_argument("--max-samples", type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    summary = run_final_eval_subset(
        output_root=repo_path(args.output_dir) or DEFAULT_OUTPUT_ROOT,
        run_id=args.run_id,
        tatqa_samples=repo_path(args.tatqa_samples),
        tatqa_manifest=repo_path(args.tatqa_manifest),
        mpdocvqa_manifest=repo_path(args.mpdocvqa_manifest),
        dataset=str(args.dataset),
        max_samples=args.max_samples,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

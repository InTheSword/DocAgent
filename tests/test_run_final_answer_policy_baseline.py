from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docagent.models.base import GenerationResult
from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_final_answer_policy_baseline import run_final_answer_policy_baseline


class CandidatePolicy:
    mode = "candidate_test"

    def generate(self, **kwargs: Any) -> GenerationResult:
        block = kwargs["evidence_blocks"][0]
        parsed = {
            "answer": "vessel values divided by net borrowings",
            "reasoning_summary": "The cited paragraph defines LTV.",
            "citation_block_ids": [block.block_id],
            "evidence_used": [{"block_id": block.block_id, "text_preview": block.retrieval_text}],
        }
        return GenerationResult(
            raw_text=json.dumps(parsed),
            parsed=parsed,
            prompt_text="prompt",
            prompt_token_count=1,
            completion_token_count=1,
            finish_reason="stop",
            latency_ms=1.0,
            metadata={"parse_result": {"raw_json_ok": True, "schema_ok": True}},
        )


def _text_sample() -> DocAgentSample:
    block = EvidenceBlock(
        doc_id="tatqa_doc",
        block_id="tatqa_doc_p1",
        block_type="text",
        text="TORM defines LTV as vessel values divided by net borrowings.",
        page_id=1,
        location=EvidenceLocation(page=1, block_id="tatqa_doc_p1"),
    )
    return DocAgentSample(
        qid="text_q",
        source="tatqa",
        doc_id="tatqa_doc",
        question="How does TORM define LTV?",
        answer=["vessel values divided by net borrowings"],
        answer_type="extractive",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _table_sample() -> DocAgentSample:
    block = EvidenceBlock(
        doc_id="table_doc",
        block_id="table_doc_table",
        block_type="table",
        text="| Year | Value |\n| 2019 | 10 |",
        page_id=1,
        location=EvidenceLocation(page=1, block_id="table_doc_table", table_id="table_doc_table"),
    )
    return DocAgentSample(
        qid="table_q",
        source="tatqa",
        doc_id="table_doc",
        question="What is the 2019 value?",
        answer=["10"],
        answer_type="numeric",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _write_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    samples_path = tmp_path / "tatqa" / "samples.jsonl"
    manifest_path = tmp_path / "tatqa" / "sample_manifest.jsonl"
    mp_manifest_path = tmp_path / "mp" / "sample_manifest.jsonl"
    write_jsonl(samples_path, [_text_sample().to_dict(), _table_sample().to_dict()])
    write_jsonl(
        manifest_path,
        [
            {
                "sample_id": "text_q",
                "dataset": "tatqa",
                "doc_id": "tatqa_doc",
                "question": "How does TORM define LTV?",
                "answers": ["vessel values divided by net borrowings"],
                "expected_answer_type": "extractive",
                "expected_tools": ["retrieval", "local_fact_qa"],
                "gold_evidence": [{"doc_id": "tatqa_doc", "page": 1, "block_id": "tatqa_doc_p1", "block_type": "text"}],
            },
            {
                "sample_id": "table_q",
                "dataset": "tatqa",
                "doc_id": "table_doc",
                "question": "What is the 2019 value?",
                "answers": ["10"],
                "expected_answer_type": "numeric",
                "expected_tools": ["table_lookup"],
                "gold_evidence": [{"doc_id": "table_doc", "page": 1, "block_id": "table_doc_table", "block_type": "table"}],
            },
        ],
    )
    write_jsonl(
        mp_manifest_path,
        [
            {
                "sample_id": "mp_q",
                "dataset": "mp_docvqa",
                "doc_id": "mp_doc",
                "question": "What is the budget?",
                "answers": ["$100,000"],
                "expected_answer_type": "extractive",
                "expected_tools": ["retrieval", "local_fact_qa"],
                "gold_evidence": [{"doc_id": "mp_doc", "page": 6, "block_id": "mp_doc_page_6", "block_type": "page"}],
            }
        ],
    )
    return samples_path, manifest_path, mp_manifest_path


def test_answer_policy_baseline_writes_diagnostic_artifacts(tmp_path: Path) -> None:
    samples_path, manifest_path, mp_manifest_path = _write_inputs(tmp_path)

    summary = run_final_answer_policy_baseline(
        output_root=tmp_path / "runs",
        run_id="candidate_run",
        tatqa_samples=samples_path,
        tatqa_manifest=manifest_path,
        mpdocvqa_manifest=mp_manifest_path,
        answer_policy=CandidatePolicy(),
        preserve_input_order=True,
    )

    assert summary["status"] == "success"
    assert summary["evaluation_scope"] == "final_subset_answer_policy_baseline_not_formal_benchmark"
    assert summary["case_count"] == 3
    assert summary["evaluated_count"] == 1
    assert summary["passed_count"] == 1
    assert summary["skipped_count"] == 2
    assert summary["answer_hit_rate"] == 1.0
    assert summary["citation_block_hit_rate"] == 1.0
    assert summary["used_qwen"] is False
    assert summary["formal_benchmark_acceptance"] is False
    assert "manifest.json" in summary["artifact_paths"][-1]

    run_dir = tmp_path / "runs" / "candidate_run"
    assert (run_dir / "results.jsonl").is_file()
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "summary.md").is_file()
    assert (run_dir / "preview.json").is_file()
    assert (run_dir / "failures_sample.jsonl").is_file()
    assert (run_dir / "manifest.json").is_file()
    rows = {row["sample_id"]: row for row in read_jsonl(run_dir / "results.jsonl")}
    assert rows["text_q"]["pass_fail"] == "passed"
    assert rows["text_q"]["citation_block_hit"] is True
    assert rows["table_q"]["evaluation_mode"] == "skipped_deterministic_tool_case"
    assert rows["mp_q"]["evaluation_mode"] == "skipped_requires_raw_pdf_mineru_retrieval"


def test_answer_policy_baseline_blocks_missing_qwen_model(tmp_path: Path) -> None:
    samples_path, manifest_path, mp_manifest_path = _write_inputs(tmp_path)

    summary = run_final_answer_policy_baseline(
        output_root=tmp_path / "runs",
        run_id="blocked_run",
        tatqa_samples=samples_path,
        tatqa_manifest=manifest_path,
        mpdocvqa_manifest=mp_manifest_path,
        answer_policy_mode="base",
        base_model_path=str(tmp_path / "missing_model"),
    )

    assert summary["status"] == "blocked"
    assert summary["quality_status"] == "blocked"
    assert summary["resource_boundary"] == "server_required"
    assert summary["blocker"]["type"] == "missing_base_model_config"
    assert (tmp_path / "runs" / "blocked_run" / "summary.json").is_file()

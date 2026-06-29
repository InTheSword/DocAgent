from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docagent.models.base import GenerationResult
from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_final_answer_policy_training_gate import run_final_answer_policy_training_gate


class WrongAnswerPolicy:
    mode = "base"

    def generate(self, **kwargs: Any) -> GenerationResult:
        block = kwargs["evidence_blocks"][0]
        parsed = {
            "answer": "8",
            "reasoning_summary": "The selected table block contains the value.",
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


class HeuristicWrongAnswerPolicy(WrongAnswerPolicy):
    mode = "heuristic"


def _table_sample() -> DocAgentSample:
    block = EvidenceBlock(
        doc_id="table_doc",
        block_id="table_doc_table",
        block_type="table",
        text="| Year | Value |\n| 2019 | 10 |\n| 2018 | 8 |",
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
    write_jsonl(samples_path, [_table_sample().to_dict()])
    write_jsonl(
        manifest_path,
        [
            {
                "sample_id": "table_q",
                "dataset": "tatqa",
                "doc_id": "table_doc",
                "question": "What is the 2019 value?",
                "answers": ["10"],
                "expected_answer_type": "numeric",
                "expected_tools": ["table_lookup"],
                "gold_evidence": [{"doc_id": "table_doc", "page": 1, "block_id": "table_doc_table", "block_type": "table"}],
            }
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


def test_training_gate_builds_sft_candidates_for_qwen_failures(tmp_path: Path) -> None:
    samples_path, manifest_path, mp_manifest_path = _write_inputs(tmp_path)

    result = run_final_answer_policy_training_gate(
        output_root=tmp_path / "gate",
        run_id="gate_run",
        baseline_output_root=tmp_path / "baseline",
        review_output_root=tmp_path / "review",
        sft_candidate_output_root=tmp_path / "candidates",
        tatqa_samples=samples_path,
        tatqa_manifest=manifest_path,
        mpdocvqa_manifest=mp_manifest_path,
        answer_policy=WrongAnswerPolicy(),
        preserve_input_order=True,
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["used_qwen"] is True
    assert result["review"]["recommendation"] == "sft_data_design_candidate"
    assert result["sft_candidates"]["status"] == "success"
    assert result["sft_candidates"]["record_count"] == 1
    records = read_jsonl(tmp_path / "candidates" / "gate_run_sft_candidates" / "sft_candidates.jsonl")
    assert len(records) == 1
    assert records[0]["metadata"]["prediction_answer"] == "8"
    assert (tmp_path / "sync" / "gate_run" / "result.json").is_file()
    assert (tmp_path / "sync" / "gate_run" / "baseline_summary.json").is_file()
    assert (tmp_path / "sync" / "gate_run" / "review.json").is_file()


def test_training_gate_skips_sft_candidates_without_qwen(tmp_path: Path) -> None:
    samples_path, manifest_path, mp_manifest_path = _write_inputs(tmp_path)

    result = run_final_answer_policy_training_gate(
        output_root=tmp_path / "gate",
        run_id="heuristic_gate",
        baseline_output_root=tmp_path / "baseline",
        review_output_root=tmp_path / "review",
        sft_candidate_output_root=tmp_path / "candidates",
        tatqa_samples=samples_path,
        tatqa_manifest=manifest_path,
        mpdocvqa_manifest=mp_manifest_path,
        answer_policy=HeuristicWrongAnswerPolicy(),
        preserve_input_order=True,
    )

    assert result["status"] == "success"
    assert result["used_qwen"] is False
    assert result["review"]["recommendation"] == "needs_real_qwen_baseline"
    assert result["sft_candidates"]["status"] == "skipped"
    assert result["sft_candidates"]["record_count"] == 0
    assert not (tmp_path / "candidates" / "heuristic_gate_sft_candidates").exists()

from __future__ import annotations

import json
from pathlib import Path

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.build_answer_policy_sft_candidates import build_answer_policy_sft_candidates


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
        metadata={"gold_block_ids": [block.block_id], "derivation": ""},
    )


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    samples_path = tmp_path / "tatqa" / "samples.jsonl"
    manifest_path = tmp_path / "tatqa" / "sample_manifest.jsonl"
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
    return samples_path, manifest_path


def _write_baseline(tmp_path: Path, *, used_qwen: bool = True, rows_file: str = "results.jsonl") -> Path:
    run_dir = tmp_path / "baseline" / "qwen_run"
    summary = {
        "status": "success",
        "run_id": "qwen_run",
        "answer_policy_mode": "base" if used_qwen else "heuristic",
        "used_qwen": used_qwen,
        "evaluated_count": 1,
        "answer_hit_rate": 0.0,
        "citation_block_hit_rate": 1.0,
    }
    rows = [
        {
            "sample_id": "table_q",
            "dataset": "tatqa",
            "doc_id": "table_doc",
            "question": "What is the 2019 value?",
            "evaluation_mode": "answer_policy_with_tool_results",
            "pass_fail": "failed",
            "failure_stage": "answer_quality",
            "failure_reasons": ["answer_miss"],
            "answer_evaluated": True,
            "citation_evaluated": True,
            "selected_block_ids": ["table_doc_table"],
            "retrieved_block_ids": ["table_doc_table"],
            "prediction_answer": "8",
            "expected_tools": ["table_lookup"],
            "tool_executed": True,
            "tool_status": "success",
            "tool_answer": "10",
            "tool_results_compact": [
                {
                    "status": "success",
                    "tool": "table_lookup",
                    "answer": "10",
                    "citations": [{"block_id": "table_doc_table", "text_preview": "2019 | 10"}],
                }
            ],
        },
        {
            "sample_id": "mp_q",
            "dataset": "mp_docvqa",
            "pass_fail": "skipped",
            "evaluation_mode": "skipped_requires_raw_pdf_mineru_retrieval",
        },
    ]
    _write_json(run_dir / "summary.json", summary)
    _write_json(run_dir / "result.json", {"status": "success", "run_id": "qwen_run", "used_qwen": used_qwen, "metrics": summary})
    write_jsonl(run_dir / rows_file, rows)
    return run_dir


def test_build_sft_candidates_from_qwen_baseline_failures(tmp_path: Path) -> None:
    samples_path, manifest_path = _write_inputs(tmp_path)
    run_dir = _write_baseline(tmp_path, used_qwen=True)

    result = build_answer_policy_sft_candidates(
        baseline_run_dir=run_dir,
        output_root=tmp_path / "candidates",
        run_id="candidate_run",
        tatqa_samples=samples_path,
        tatqa_manifest=manifest_path,
    )

    assert result["status"] == "success"
    assert result["record_count"] == 1
    assert result["candidate_failure_reason_distribution"] == {"answer_miss": 1}
    assert result["skip_reason_distribution"] == {"non_tatqa_row": 1}
    records = read_jsonl(tmp_path / "candidates" / "candidate_run" / "sft_candidates.jsonl")
    assert len(records) == 1
    record = records[0]
    assert record["source"] == "answer_policy_baseline_sft_candidate"
    assert record["prompt_version"] == "docagent_answer_v2_candidate_citations"
    assert "## Tool Results" in record["messages"][1]["content"]
    assistant_target = json.loads(record["messages"][-1]["content"])
    assert assistant_target["answer"] == "10"
    assert assistant_target["citation_block_ids"] == ["table_doc_table"]
    assert record["metadata"]["prediction_answer"] == "8"
    assert record["metadata"]["tool_results_attached"] == 1
    assert (tmp_path / "candidates" / "candidate_run" / "summary.md").is_file()


def test_build_sft_candidates_blocks_non_qwen_baseline(tmp_path: Path) -> None:
    samples_path, manifest_path = _write_inputs(tmp_path)
    run_dir = _write_baseline(tmp_path, used_qwen=False)

    result = build_answer_policy_sft_candidates(
        baseline_run_dir=run_dir,
        output_root=tmp_path / "candidates",
        run_id="blocked_run",
        tatqa_samples=samples_path,
        tatqa_manifest=manifest_path,
    )

    assert result["status"] == "blocked"
    assert result["block_reason"] == "real_qwen_baseline_required"
    assert result["record_count"] == 0
    assert read_jsonl(tmp_path / "candidates" / "blocked_run" / "sft_candidates.jsonl") == []


def test_build_sft_candidates_reads_failure_sample_bundle(tmp_path: Path) -> None:
    samples_path, manifest_path = _write_inputs(tmp_path)
    run_dir = _write_baseline(tmp_path, used_qwen=True, rows_file="failures_sample.jsonl")

    result = build_answer_policy_sft_candidates(
        baseline_run_dir=run_dir,
        output_root=tmp_path / "candidates",
        run_id="sync_candidate_run",
        tatqa_samples=samples_path,
        tatqa_manifest=manifest_path,
    )

    assert result["status"] == "success"
    assert result["rows_scope"] == "failure_sample_only"
    assert result["record_count"] == 1

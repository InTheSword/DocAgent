from __future__ import annotations

import json
from pathlib import Path

from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_final_eval_subset import run_final_eval_subset


def _table_sample() -> DocAgentSample:
    doc_id = "tatqa_table_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id=f"{doc_id}_table",
        block_type="table",
        text="| December 31, 2019 | December 31, 2018 |\n| --- | --- |\n| Right of use assets | $33,014 | $8,620 |",
        table_html=(
            "<table><tr><th>December 31, 2019</th><th>December 31, 2018</th></tr>"
            "<tr><td>Right of use assets</td><td>$33,014</td><td>$8,620</td></tr></table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id=f"{doc_id}_table", table_id=f"{doc_id}_table"),
    )
    return DocAgentSample(
        qid="tatqa_table_q",
        source="tatqa",
        doc_id=doc_id,
        question="What is the company's 2019 right of use assets?",
        answer=["$33,014"],
        answer_type="numeric",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _text_sample() -> DocAgentSample:
    doc_id = "tatqa_text_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id=f"{doc_id}_paragraph_1",
        block_type="text",
        text="The company defines LTV as vessel values divided by net borrowings.",
        page_id=1,
        location=EvidenceLocation(page=1, block_id=f"{doc_id}_paragraph_1"),
    )
    return DocAgentSample(
        qid="tatqa_text_q",
        source="tatqa",
        doc_id=doc_id,
        question="How does the company define LTV?",
        answer=["vessel values divided by net borrowings"],
        answer_type="extractive",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _average_sample() -> DocAgentSample:
    doc_id = "tatqa_average_doc"
    block = EvidenceBlock(
        doc_id=doc_id,
        block_id=f"{doc_id}_table",
        block_type="table",
        text=(
            "| Fiscal year | % Change |\n"
            "| --- | --- |\n"
            "| Orders | 19,975 | 18,451 | 8 % | 7 % |"
        ),
        table_html=(
            "<table><tr><th>Fiscal year</th><th>% Change</th></tr>"
            "<tr><td>Orders</td><td>19,975</td><td>18,451</td><td>8 %</td><td>7 %</td></tr></table>"
        ),
        page_id=1,
        location=EvidenceLocation(page=1, block_id=f"{doc_id}_table", table_id=f"{doc_id}_table"),
    )
    return DocAgentSample(
        qid="tatqa_average_q",
        source="tatqa",
        doc_id=doc_id,
        question="What was the average orders for 2019 and 2018?",
        answer=["19213"],
        answer_type="numeric",
        evidence=[block],
        split="dev",
        metadata={"gold_block_ids": [block.block_id]},
    )


def _write_fixture_inputs(tmp_path: Path) -> tuple[Path, Path, Path]:
    samples = [_table_sample(), _average_sample(), _text_sample()]
    samples_path = tmp_path / "tatqa" / "samples.jsonl"
    manifest_path = tmp_path / "tatqa" / "sample_manifest.jsonl"
    mp_manifest_path = tmp_path / "mp" / "sample_manifest.jsonl"
    write_jsonl(samples_path, [sample.to_dict() for sample in samples])
    write_jsonl(
        manifest_path,
        [
            {
                "sample_id": "tatqa_table_q",
                "dataset": "tatqa",
                "split": "dev",
                "doc_id": "tatqa_table_doc",
                "question": "What is the company's 2019 right of use assets?",
                "answers": ["$33,014"],
                "expected_answer_type": "numeric",
                "expected_tools": ["table_lookup"],
                "gold_evidence": [
                    {
                        "doc_id": "tatqa_table_doc",
                        "page": 1,
                        "block_id": "tatqa_table_doc_table",
                        "block_type": "table",
                    }
                ],
            },
            {
                "sample_id": "tatqa_average_q",
                "dataset": "tatqa",
                "split": "dev",
                "doc_id": "tatqa_average_doc",
                "question": "What was the average orders for 2019 and 2018?",
                "answers": ["19213"],
                "expected_answer_type": "numeric",
                "expected_tools": ["table_lookup", "simple_calculation"],
                "gold_evidence": [
                    {
                        "doc_id": "tatqa_average_doc",
                        "page": 1,
                        "block_id": "tatqa_average_doc_table",
                        "block_type": "table",
                    }
                ],
            },
            {
                "sample_id": "tatqa_text_q",
                "dataset": "tatqa",
                "split": "dev",
                "doc_id": "tatqa_text_doc",
                "question": "How does the company define LTV?",
                "answers": ["vessel values divided by net borrowings"],
                "expected_answer_type": "extractive",
                "expected_tools": ["retrieval", "local_fact_qa"],
                "gold_evidence": [
                    {
                        "doc_id": "tatqa_text_doc",
                        "page": 1,
                        "block_id": "tatqa_text_doc_paragraph_1",
                        "block_type": "text",
                    }
                ],
            },
        ],
    )
    write_jsonl(
        mp_manifest_path,
        [
            {
                "sample_id": "mp_q",
                "dataset": "mp_docvqa",
                "split": "val",
                "doc_id": "mp_doc",
                "source_document": "mp_source",
                "question": "What is the budget estimate?",
                "answers": ["$100,000"],
                "expected_answer_type": "extractive",
                "expected_tools": ["retrieval", "local_fact_qa"],
                "gold_evidence": [
                    {
                        "doc_id": "mp_doc",
                        "page": 6,
                        "block_id": "mp_doc_page_6",
                        "block_type": "page",
                    }
                ],
            }
        ],
    )
    return samples_path, manifest_path, mp_manifest_path


def test_final_eval_runner_writes_local_diagnostic_artifacts(tmp_path: Path) -> None:
    samples_path, manifest_path, mp_manifest_path = _write_fixture_inputs(tmp_path)

    summary = run_final_eval_subset(
        output_root=tmp_path / "runs",
        run_id="fixture_run",
        tatqa_samples=samples_path,
        tatqa_manifest=manifest_path,
        mpdocvqa_manifest=mp_manifest_path,
        dataset="all",
    )

    assert summary["status"] == "success"
    assert summary["evaluation_scope"] == "local_subset_diagnostic_not_formal_benchmark"
    assert summary["case_count"] == 4
    assert summary["passed_count"] == 4
    assert summary["pass_rate"] == 1.0
    assert summary["tool_executed_count"] == 2
    assert summary["tool_success_count"] == 2
    assert summary["answer_evaluated_count"] == 2
    assert summary["answer_hit_count"] == 2
    assert summary["answer_hit_rate"] == 1.0
    assert summary["numeric_accuracy_count"] == 2
    assert summary["numeric_accuracy_rate"] == 1.0
    assert summary["citation_block_hit_count"] == 2
    assert summary["citation_page_hit_count"] == 2
    assert summary["citation_block_hit_rate"] == 1.0
    assert summary["failure_reason_distribution"] == {}
    assert summary["requires_model_answer_count"] == 2
    assert summary["requires_mineru_or_retrieval_count"] == 1
    assert summary["final_llm_answer_quality_evaluated"] is False
    assert summary["used_qwen"] is False
    assert "summary.md" in summary["summary_markdown_path"]
    assert summary["summary_markdown_path"] in summary["artifact_paths"]

    run_dir = tmp_path / "runs" / "fixture_run"
    assert (run_dir / "results.jsonl").is_file()
    assert (run_dir / "summary.json").is_file()
    assert (run_dir / "summary.md").is_file()
    assert (run_dir / "preview.json").is_file()
    assert (run_dir / "manual_review.md").is_file()
    summary_markdown = (run_dir / "summary.md").read_text(encoding="utf-8")
    assert "## Evidence Readiness" in summary_markdown
    assert "## Answer Quality" in summary_markdown
    assert "## Attribution Quality" in summary_markdown
    assert "## Format Quality" in summary_markdown
    assert "## Failure Taxonomy" in summary_markdown
    assert "formal_benchmark_acceptance: `false`" in summary_markdown

    rows = {row["sample_id"]: row for row in read_jsonl(run_dir / "results.jsonl")}
    assert rows["tatqa_table_q"]["evaluation_mode"] == "deterministic_table_tool"
    assert rows["tatqa_table_q"]["answer_hit"] is True
    assert rows["tatqa_table_q"]["failure_reasons"] == []
    assert rows["tatqa_table_q"]["failure_stage"] == ""
    assert rows["tatqa_average_q"]["structured_result"]["calculation"]["operation"] == "average"
    assert rows["tatqa_average_q"]["answer_hit"] is True
    assert rows["tatqa_text_q"]["evaluation_mode"] == "manifest_readiness"
    assert rows["tatqa_text_q"]["requires_model_answer"] is True
    assert rows["mp_q"]["evaluation_mode"] == "page_manifest_readiness"


def test_final_eval_runner_cli_smoke(tmp_path: Path) -> None:
    samples_path, manifest_path, mp_manifest_path = _write_fixture_inputs(tmp_path)
    output_root = tmp_path / "cli_runs"

    from scripts.run_final_eval_subset import main

    exit_code = main(
        [
            "--dataset",
            "all",
            "--output-dir",
            str(output_root),
            "--run-id",
            "cli_fixture",
            "--tatqa-samples",
            str(samples_path),
            "--tatqa-manifest",
            str(manifest_path),
            "--mpdocvqa-manifest",
            str(mp_manifest_path),
        ]
    )

    assert exit_code == 0
    summary = json.loads((output_root / "cli_fixture" / "summary.json").read_text(encoding="utf-8"))
    assert summary["case_count"] == 4
    assert (output_root / "cli_fixture" / "summary.md").is_file()

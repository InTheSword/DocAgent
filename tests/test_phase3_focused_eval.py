from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest

from docagent.eval.phase3_focused import (
    DEFAULT_SEED,
    fixed_evidence_hash,
    run_focused_evaluation,
    select_stable_subset,
    stable_sample_key,
    validate_benchmark_contract,
    validate_no_forbidden_paths,
)
from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import read_jsonl, write_jsonl


def _block(doc_id: str, block_id: str, text: str, *, page: int = 1, block_type: str = "text") -> dict:
    return EvidenceBlock(
        doc_id=doc_id,
        block_id=block_id,
        block_type=block_type,
        text=text,
        page_id=page,
        location=EvidenceLocation(page=page, block_id=block_id),
    ).to_dict()


def _sample_records() -> list[dict]:
    return [
        {
            "qid": "q_date",
            "source": "phase3_fixture",
            "doc_id": "doc_invoice",
            "question": "What is the invoice date?",
            "answer": "March 12, 2020",
            "answer_type": "extractive",
            "evidence": [
                _block("doc_invoice", "invoice_date_block", "Invoice Date: March 12, 2020"),
                _block("doc_invoice", "invoice_total_block", "Total: $42.00"),
            ],
            "metadata": {"gold_block_ids": ["invoice_date_block"]},
        },
        {
            "qid": "q_total",
            "source": "phase3_fixture",
            "doc_id": "doc_invoice",
            "question": "What was the total amount?",
            "answer": "$42.00",
            "answer_type": "numeric",
            "evidence": [
                _block("doc_invoice", "invoice_date_block", "Invoice Date: March 12, 2020"),
                _block("doc_invoice", "invoice_total_block", "Total: $42.00"),
            ],
            "metadata": {"gold_block_ids": ["invoice_total_block"]},
        },
    ]


def _args(tmp_path: Path, input_path: Path) -> Namespace:
    return Namespace(
        benchmark_input=input_path.relative_to(tmp_path).as_posix(),
        output_root="outputs/evaluation/phase3_focused_eval",
        run_id="fixture-run",
        force=True,
        seed=DEFAULT_SEED,
        retrieval_limit=2,
        answer_limit=2,
        top_k=2,
        bm25_top_n=4,
        dense_top_n=4,
        fusion_top_n=4,
        rrf_k=60,
        dense_backend="hash",
        dense_model_path="",
        dense_device="cpu",
        dense_fp16=False,
        reranker_backend="keyword",
        reranker_model_path="",
        reranker_device="cpu",
        reranker_fp16=False,
        answer_backend="heuristic",
        base_model_path="",
        sft_adapter_path="outputs/checkpoints/sft",
        grpo_adapter_path="outputs/checkpoints/grpo",
        qwen_device="cpu",
        qwen_torch_dtype="float32",
        max_prompt_tokens=1024,
        max_new_tokens=128,
        allow_mock_backends=True,
    )


def test_benchmark_contract_rejects_pre_retrieved_and_missing_gold(tmp_path: Path) -> None:
    path = tmp_path / "data" / "benchmark" / "mp_docvqa_dev_sft_retrieved_clean.jsonl"
    write_jsonl(path, _sample_records())
    samples = [DocAgentSample.from_dict(record) for record in read_jsonl(path)]
    contract = validate_benchmark_contract(samples, input_path=path)
    assert contract.status == "invalid"
    assert contract.role == "pre_retrieved_reader_data"
    assert any("forbidden primary benchmark role" in error for error in contract.errors)

    records = _sample_records()
    records[0]["metadata"] = {}
    candidate_path = tmp_path / "phase3_candidate.jsonl"
    write_jsonl(candidate_path, records)
    contract = validate_benchmark_contract(
        [DocAgentSample.from_dict(record) for record in read_jsonl(candidate_path)],
        input_path=candidate_path,
    )
    assert contract.status == "invalid"
    assert any("missing metadata.gold_block_ids" in error for error in contract.errors)


def test_stable_subset_uses_qid_hash_not_file_prefix() -> None:
    samples = [
        DocAgentSample.from_dict(
            {
                "qid": f"q{index}",
                "source": "fixture",
                "doc_id": "doc",
                "question": f"Question {index}?",
                "answer": "answer",
                "answer_type": "extractive",
                "evidence": [_block("doc", f"b{index}", "answer")],
                "metadata": {"gold_block_ids": [f"b{index}"]},
            }
        )
        for index in range(6)
    ]
    selected = select_stable_subset(samples, limit=3, seed="fixed-seed")
    expected = sorted(samples, key=lambda sample: (stable_sample_key(sample.qid, "fixed-seed"), sample.qid))[:3]
    assert [sample.qid for sample in selected] == [sample.qid for sample in expected]
    assert [sample.qid for sample in selected] != ["q0", "q1", "q2"]


def test_run_focused_evaluation_fixture_outputs_contracts(tmp_path: Path) -> None:
    input_path = tmp_path / "phase3_candidate.jsonl"
    write_jsonl(input_path, _sample_records())

    summary = run_focused_evaluation(_args(tmp_path, input_path), root=tmp_path)

    run_dir = tmp_path / "outputs" / "evaluation" / "phase3_focused_eval" / "fixture-run"
    fixed_path = run_dir / "answer_policy" / "fixed_evidence.jsonl"
    fixed_records = read_jsonl(fixed_path)
    assert summary["status"] == "success"
    assert summary["result_type"] == "fixed subset evaluation, not formal benchmark"
    assert summary["answer_policy"]["fixed_evidence_sha256"] == fixed_evidence_hash(fixed_records)
    assert (run_dir / "retrieval" / "bm25_metrics.json").is_file()
    assert (run_dir / "retrieval" / "hybrid_metrics.json").is_file()
    assert (run_dir / "answer_policy" / "comparison.json").is_file()

    sft_rows = read_jsonl(run_dir / "answer_policy" / "sft_results.jsonl")
    grpo_rows = read_jsonl(run_dir / "answer_policy" / "grpo_results.jsonl")
    assert [row["evidence_block_ids"] for row in sft_rows] == [row["evidence_block_ids"] for row in grpo_rows]

    run_manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    benchmark_manifest = json.loads((run_dir / "benchmark_manifest.json").read_text(encoding="utf-8"))
    assert not validate_no_forbidden_paths(run_manifest)
    assert not validate_no_forbidden_paths(benchmark_manifest)


def test_real_backends_are_required_unless_mock_flag(tmp_path: Path) -> None:
    input_path = tmp_path / "phase3_candidate.jsonl"
    write_jsonl(input_path, _sample_records())
    args = _args(tmp_path, input_path)
    args.allow_mock_backends = False

    with pytest.raises(RuntimeError, match="hash dense backend"):
        run_focused_evaluation(args, root=tmp_path)

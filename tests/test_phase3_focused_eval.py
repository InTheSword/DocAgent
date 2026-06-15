from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from docagent.eval.phase3_focused import (
    DEFAULT_SEED,
    fixed_evidence_hash,
    load_corpus_blocks,
    qid_hash,
    run_focused_evaluation,
    select_stable_subset,
    stable_sample_key,
    validate_benchmark_contract,
    validate_reader_artifact_contract,
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


def _qa_records_without_reader_evidence() -> list[dict]:
    records = _sample_records()
    for record in records:
        record["evidence"] = []
    return records


def _corpus_records() -> list[dict]:
    return [
        _block("doc_invoice", "invoice_date_block", "Invoice Date: March 12, 2020"),
        _block("doc_invoice", "invoice_total_block", "Total: $42.00"),
        _block("doc_invoice", "invoice_vendor_block", "Vendor: Example Co."),
    ]


def _args(tmp_path: Path, input_path: Path, corpus_path: Path | None = None) -> Namespace:
    return Namespace(
        benchmark_input=input_path.relative_to(tmp_path).as_posix(),
        qa_input=None,
        corpus_input=corpus_path.relative_to(tmp_path).as_posix() if corpus_path else None,
        output_root="outputs/evaluation/phase3_focused_eval",
        run_id="fixture-run",
        force=True,
        validate_only=False,
        answer_only=False,
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


def test_cli_help_subprocess_starts() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_phase3_focused_eval.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--corpus-input" in result.stdout
    assert "--answer-only" in result.stdout


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


def test_query_conditioned_evidence_is_not_retrieval_corpus(tmp_path: Path) -> None:
    input_path = tmp_path / "phase3_candidate.jsonl"
    write_jsonl(input_path, _sample_records())
    samples = [DocAgentSample.from_dict(record) for record in read_jsonl(input_path)]

    contract = validate_benchmark_contract(samples, input_path=input_path)

    assert contract.status == "invalid"
    assert contract.corpus_source == "embedded_query_evidence"
    assert contract.corpus_is_query_independent is False
    assert any("--corpus-input" in error for error in contract.errors)


def test_same_doc_multiple_evidence_signatures_are_reported(tmp_path: Path) -> None:
    records = _sample_records()
    records[1]["evidence"] = [
        _block("doc_invoice", "invoice_total_block", "Total: $42.00"),
        _block("doc_invoice", "invoice_vendor_block", "Vendor: Example Co."),
    ]
    input_path = tmp_path / "phase3_candidate.jsonl"
    write_jsonl(input_path, records)
    samples = [DocAgentSample.from_dict(record) for record in read_jsonl(input_path)]

    contract = validate_benchmark_contract(samples, input_path=input_path)

    assert contract.status == "invalid"
    assert contract.repeated_doc_audit
    assert contract.repeated_doc_audit["inconsistent_repeated_doc_count"] == 1
    assert contract.repeated_doc_audit["inconsistent_doc_ids"] == ["doc_invoice"]


def test_independent_qa_and_corpus_contract_passes(tmp_path: Path) -> None:
    qa_path = tmp_path / "phase3_qa.jsonl"
    corpus_path = tmp_path / "phase3_corpus.jsonl"
    write_jsonl(qa_path, _qa_records_without_reader_evidence())
    write_jsonl(corpus_path, _corpus_records())
    samples = [DocAgentSample.from_dict(record) for record in read_jsonl(qa_path)]
    blocks = load_corpus_blocks(corpus_path)

    contract = validate_benchmark_contract(samples, input_path=qa_path, corpus_blocks=blocks, corpus_input_path=corpus_path)
    second_contract = validate_benchmark_contract(
        samples,
        input_path=qa_path,
        corpus_blocks=load_corpus_blocks(corpus_path),
        corpus_input_path=corpus_path,
    )

    assert contract.status == "ready"
    assert contract.corpus_source == "independent_corpus_input"
    assert contract.corpus_is_query_independent is True
    assert contract.gold_block_coverage["coverage_rate"] == 1.0
    assert contract.corpus_hash == second_contract.corpus_hash
    assert contract.qid_hash == qid_hash(["q_date", "q_total"])


def test_gold_block_missing_from_independent_corpus_fails(tmp_path: Path) -> None:
    qa_path = tmp_path / "phase3_qa.jsonl"
    corpus_path = tmp_path / "phase3_corpus.jsonl"
    write_jsonl(qa_path, _qa_records_without_reader_evidence())
    write_jsonl(corpus_path, [_block("doc_invoice", "invoice_date_block", "Invoice Date: March 12, 2020")])
    samples = [DocAgentSample.from_dict(record) for record in read_jsonl(qa_path)]

    contract = validate_benchmark_contract(
        samples,
        input_path=qa_path,
        corpus_blocks=load_corpus_blocks(corpus_path),
        corpus_input_path=corpus_path,
    )

    assert contract.status == "invalid"
    assert contract.gold_block_coverage["coverage_rate"] == 0.5
    assert any("invoice_total_block" in error for error in contract.errors)


def test_reader_artifact_is_ready_but_not_retrieval_benchmark(tmp_path: Path) -> None:
    path = tmp_path / "mp_docvqa_dev_sft_retrieved_clean.jsonl"
    write_jsonl(path, _sample_records())
    samples = [DocAgentSample.from_dict(record) for record in read_jsonl(path)]

    retrieval_contract = validate_benchmark_contract(samples, input_path=path)
    reader_contract = validate_reader_artifact_contract(samples, input_path=path)

    assert retrieval_contract.status == "invalid"
    assert retrieval_contract.role == "pre_retrieved_reader_data"
    assert reader_contract.status == "ready"
    assert reader_contract.corpus_source == "provided_reader_evidence"


def test_run_focused_evaluation_fixture_outputs_contracts(tmp_path: Path) -> None:
    input_path = tmp_path / "phase3_qa.jsonl"
    corpus_path = tmp_path / "phase3_corpus.jsonl"
    write_jsonl(input_path, _qa_records_without_reader_evidence())
    write_jsonl(corpus_path, _corpus_records())

    summary = run_focused_evaluation(_args(tmp_path, input_path, corpus_path), root=tmp_path)

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
    assert benchmark_manifest["retrieval_contract"]["corpus_is_query_independent"] is True


def test_real_backends_are_required_unless_mock_flag(tmp_path: Path) -> None:
    input_path = tmp_path / "phase3_candidate.jsonl"
    corpus_path = tmp_path / "phase3_corpus.jsonl"
    write_jsonl(input_path, _qa_records_without_reader_evidence())
    write_jsonl(corpus_path, _corpus_records())
    args = _args(tmp_path, input_path, corpus_path)
    args.allow_mock_backends = False

    with pytest.raises(RuntimeError, match="hash dense backend"):
        run_focused_evaluation(args, root=tmp_path)


def test_contract_failure_returns_nonzero_exit_code(tmp_path: Path) -> None:
    input_path = tmp_path / "phase3_candidate.jsonl"
    write_jsonl(input_path, _sample_records())

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_phase3_focused_eval.py",
            "--benchmark-input",
            str(input_path),
            "--validate-only",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["status"] == "failed"
    assert payload["retrieval_evaluation"] == "blocked"


def test_answer_only_runs_when_retrieval_is_blocked(tmp_path: Path) -> None:
    input_path = tmp_path / "phase3_reader.jsonl"
    write_jsonl(input_path, _sample_records())
    args = _args(tmp_path, input_path)
    args.answer_only = True

    summary = run_focused_evaluation(args, root=tmp_path)

    assert summary["retrieval_evaluation"] == "blocked"
    assert summary["answer_policy_evaluation"] == "ready"
    run_dir = tmp_path / "outputs" / "evaluation" / "phase3_focused_eval" / "fixture-run"
    fixed_records = read_jsonl(run_dir / "answer_policy" / "fixed_evidence.jsonl")
    assert all(record["metadata"]["reader_evidence_source"] == "provided_reader_evidence" for record in fixed_records)

from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from docagent.eval.phase3_focused import (
    DEFAULT_SEED,
    corpus_hash,
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


FALSE_POSITIVE_OCR_TEXT = "/ a the / / / the / source:\nhttps://www.industrydocuments.ucsf.edu/docs/sybx0223"


def _args(tmp_path: Path, input_path: Path, corpus_path: Path | None = None) -> Namespace:
    return Namespace(
        benchmark_input=input_path.relative_to(tmp_path).as_posix(),
        benchmark_manifest=None,
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
    assert "--benchmark-manifest" in result.stdout
    assert "--answer-only" in result.stdout


def test_forbidden_path_scanner_allows_semantic_document_text_fields() -> None:
    payload = {
        "fixed_evidence": [
            {
                "answer": r"C:\Users\x\a.jpg",
                "reason": "/leading slash OCR text",
                "evidence": [
                    {
                        "text": FALSE_POSITIVE_OCR_TEXT,
                        "content": r"C:\Users\x\a.jpg",
                        "table_html": '<a href="https://example.test/table">source</a>',
                        "visual_summary": "/root/private/a.jpg",
                    }
                ],
            }
        ]
    }
    original_payload = json.loads(json.dumps(payload))

    assert validate_no_forbidden_paths(payload, where="fixed_evidence") == []
    assert payload == original_payload


@pytest.mark.parametrize(
    ("payload", "expected_reason"),
    [
        ({"image_path": "/root/private/a.jpg"}, "absolute_path"),
        ({"image_path": r"C:\Users\x\a.jpg"}, "windows_absolute_path"),
        ({"download_url": "https://example.test/a.zip?X-Amz-Signature=abc"}, "signed_url_or_token"),
        ({"headers": {"Authorization": "Bearer secret"}}, "credential_field"),
        ({"api_token": "secret"}, "credential_field"),
        ({"mineru_token": "secret"}, "credential_field"),
    ],
)
def test_forbidden_path_scanner_rejects_structured_paths_urls_and_tokens(
    payload: dict,
    expected_reason: str,
) -> None:
    hits = validate_no_forbidden_paths(payload)

    assert hits
    assert hits[0]["reason"] == expected_reason


def test_forbidden_path_scanner_allows_relative_structured_path() -> None:
    assert validate_no_forbidden_paths({"image_path": "images/a.jpg"}) == []


def test_fixed_evidence_hash_is_unchanged_by_security_scan() -> None:
    records = [
        {
            "qid": "q_source",
            "evidence": [{"block_id": "b1", "text": FALSE_POSITIVE_OCR_TEXT}],
            "answer": r"C:\Users\x\a.jpg",
        }
    ]
    original_records = json.loads(json.dumps(records))
    before_hash = fixed_evidence_hash(records)

    assert validate_no_forbidden_paths(records, where="fixed_evidence") == []
    assert records == original_records
    assert fixed_evidence_hash(records) == before_hash


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


def _write_regression_manifest(
    tmp_path: Path,
    *,
    qa_path: Path,
    corpus_path: Path,
    qids: list[str] | None = None,
    corpus_records: list[dict] | None = None,
) -> Path:
    qids = qids or [record["qid"] for record in read_jsonl(qa_path)]
    corpus_records = corpus_records or read_jsonl(corpus_path)
    manifest_path = tmp_path / "globocan_africa_2022_regression_benchmark_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "artifact_role": "real_document_regression",
                "source_qa_role": "globocan_scenario_acceptance",
                "evaluation_scope": "scenario_regression",
                "formal_benchmark": False,
                "primary_benchmark": False,
                "qa_artifact": qa_path.relative_to(tmp_path).as_posix(),
                "corpus_artifact": corpus_path.relative_to(tmp_path).as_posix(),
                "corpus_is_query_independent": True,
                "qid_hash": qid_hash(qids),
                "corpus_hash": corpus_hash([EvidenceBlock.from_dict(record) for record in corpus_records]),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return manifest_path


def test_regression_manifest_controls_focused_eval_contract_role(tmp_path: Path) -> None:
    qa_path = tmp_path / "scenario_qa.jsonl"
    corpus_path = tmp_path / "globocan_africa_2022_regression_corpus.jsonl"
    write_jsonl(qa_path, _qa_records_without_reader_evidence())
    write_jsonl(corpus_path, _corpus_records())
    manifest_path = _write_regression_manifest(tmp_path, qa_path=qa_path, corpus_path=corpus_path)
    args = _args(tmp_path, qa_path, corpus_path)
    args.benchmark_manifest = manifest_path.relative_to(tmp_path).as_posix()
    args.retrieval_only = True

    summary = run_focused_evaluation(args, root=tmp_path)

    run_dir = tmp_path / "outputs" / "evaluation" / "phase3_focused_eval" / "fixture-run"
    benchmark_manifest = json.loads((run_dir / "benchmark_manifest.json").read_text(encoding="utf-8"))
    assert summary["benchmark_role"] == "real_document_regression"
    assert summary["source_qa_role"] == "globocan_scenario_acceptance"
    assert summary["evaluation_scope"] == "scenario_regression"
    assert summary["formal_benchmark"] is False
    assert summary["primary_benchmark"] is False
    assert "real-document scenario regression" in summary["result_type"]
    assert benchmark_manifest["reader_contract"] is None
    assert benchmark_manifest["retrieval_contract"]["artifact_role"] == "real_document_regression"
    assert benchmark_manifest["retrieval_contract"]["evaluation_scope"] == "scenario_regression"


def test_regression_manifest_hash_mismatch_fails_with_metadata_error(tmp_path: Path) -> None:
    qa_path = tmp_path / "scenario_qa.jsonl"
    corpus_path = tmp_path / "globocan_africa_2022_regression_corpus.jsonl"
    write_jsonl(qa_path, _qa_records_without_reader_evidence())
    write_jsonl(corpus_path, _corpus_records())
    manifest_path = _write_regression_manifest(tmp_path, qa_path=qa_path, corpus_path=corpus_path, qids=["wrong"])
    args = _args(tmp_path, qa_path, corpus_path)
    args.benchmark_manifest = manifest_path.relative_to(tmp_path).as_posix()
    args.validate_only = True

    with pytest.raises(RuntimeError, match="invalid evaluation contract metadata: qid_hash mismatch"):
        run_focused_evaluation(args, root=tmp_path)


def test_regression_manifest_corpus_hash_mismatch_fails_with_metadata_error(tmp_path: Path) -> None:
    qa_path = tmp_path / "scenario_qa.jsonl"
    corpus_path = tmp_path / "globocan_africa_2022_regression_corpus.jsonl"
    write_jsonl(qa_path, _qa_records_without_reader_evidence())
    write_jsonl(corpus_path, _corpus_records())
    wrong_corpus_records = [
        _block("doc_invoice", "invoice_date_block", "Changed text"),
        _block("doc_invoice", "invoice_total_block", "Total: $42.00"),
        _block("doc_invoice", "invoice_vendor_block", "Vendor: Example Co."),
    ]
    manifest_path = _write_regression_manifest(
        tmp_path,
        qa_path=qa_path,
        corpus_path=corpus_path,
        corpus_records=wrong_corpus_records,
    )
    args = _args(tmp_path, qa_path, corpus_path)
    args.benchmark_manifest = manifest_path.relative_to(tmp_path).as_posix()
    args.validate_only = True

    with pytest.raises(RuntimeError, match="invalid evaluation contract metadata: corpus_hash mismatch"):
        run_focused_evaluation(args, root=tmp_path)


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
    records = _sample_records()
    records[0]["evidence"][0]["text"] = FALSE_POSITIVE_OCR_TEXT
    write_jsonl(input_path, records)
    args = _args(tmp_path, input_path)
    args.answer_only = True

    summary = run_focused_evaluation(args, root=tmp_path)

    assert summary["retrieval_evaluation"] == "blocked"
    assert summary["answer_policy_evaluation"] == "ready"
    run_dir = tmp_path / "outputs" / "evaluation" / "phase3_focused_eval" / "fixture-run"
    fixed_records = read_jsonl(run_dir / "answer_policy" / "fixed_evidence.jsonl")
    assert all(record["metadata"]["reader_evidence_source"] == "provided_reader_evidence" for record in fixed_records)
    assert fixed_records[0]["evidence"][0]["text"] == FALSE_POSITIVE_OCR_TEXT


def test_answer_only_missing_evidence_fails_reader_contract(tmp_path: Path) -> None:
    input_path = tmp_path / "phase3_reader.jsonl"
    write_jsonl(input_path, _qa_records_without_reader_evidence())
    args = _args(tmp_path, input_path)
    args.answer_only = True

    with pytest.raises(Exception) as exc_info:
        run_focused_evaluation(args, root=tmp_path)

    payload = getattr(exc_info.value, "payload", {})
    assert payload["status"] == "failed"
    assert payload["answer_policy_evaluation"] == "blocked"
    assert "reader evidence artifact is invalid" in payload["exception"]


def test_full_mode_retrieval_miss_is_quality_result_not_input_contract_failure(tmp_path: Path) -> None:
    qa_path = tmp_path / "phase3_qa.jsonl"
    corpus_path = tmp_path / "phase3_corpus.jsonl"
    write_jsonl(
        qa_path,
        [
            {
                "qid": "q_vendor",
                "source": "phase3_fixture",
                "doc_id": "doc_invoice",
                "question": "What is the vendor name?",
                "answer": "Gold Corp",
                "answer_type": "extractive",
                "evidence": [],
                "metadata": {"gold_block_ids": ["invoice_gold_block"]},
            }
        ],
    )
    write_jsonl(
        corpus_path,
        [
            _block("doc_invoice", "invoice_vendor_block", "Vendor: Example Co."),
            _block("doc_invoice", "invoice_gold_block", "Unrelated footer Gold Corp"),
        ],
    )
    args = _args(tmp_path, qa_path, corpus_path)
    args.top_k = 1
    args.retrieval_limit = 1
    args.answer_limit = 1

    summary = run_focused_evaluation(args, root=tmp_path)

    run_dir = tmp_path / "outputs" / "evaluation" / "phase3_focused_eval" / "fixture-run"
    fixed_records = read_jsonl(run_dir / "answer_policy" / "fixed_evidence.jsonl")
    benchmark_manifest = json.loads((run_dir / "benchmark_manifest.json").read_text(encoding="utf-8"))
    fixed_ids = [block["block_id"] for block in fixed_records[0]["evidence"]]
    assert summary["status"] == "success"
    assert "invoice_gold_block" not in fixed_ids
    assert benchmark_manifest["reader_contract"]["status"] == "ready"
    assert benchmark_manifest["reader_contract"]["gold_block_coverage"]["coverage_rate"] == 0.0

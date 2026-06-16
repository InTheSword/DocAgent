from __future__ import annotations

import json
from pathlib import Path

import pytest

from docagent.eval.phase3_focused import validate_benchmark_contract
from docagent.schemas import DocAgentSample, EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.build_real_document_benchmark import build_contract


def _block(block_id: str, *, text: str = "Invoice Date March 12 2020", boilerplate: bool = False) -> dict:
    return EvidenceBlock(
        doc_id="doc1",
        page_id=1,
        block_id=block_id,
        block_type="text",
        text=text,
        location=EvidenceLocation(page=1, block_id=block_id),
        metadata={"is_boilerplate": boilerplate, "exclude_from_retrieval": boilerplate},
    ).to_dict()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    document_dir = tmp_path / "doc"
    document_dir.mkdir()
    (document_dir / "source").mkdir()
    (document_dir / "source" / "original.pdf").write_bytes(b"%PDF-1.4\n/Type /Page\n")
    write_jsonl(document_dir / "evidence_blocks.jsonl", [_block("b1"), _block("b2", text="header", boilerplate=True)])
    (document_dir / "ingestion_report.json").write_text("{}", encoding="utf-8")
    (document_dir / "structure_quality.json").write_text("{}", encoding="utf-8")
    qa_path = tmp_path / "qa.jsonl"
    write_jsonl(
        qa_path,
        [
            {
                "qid": "q1",
                "doc_id": "doc1",
                "question": "What is the invoice date?",
                "answers": ["March 12 2020"],
                "answer_type": "text",
                "source_qa_role": "globocan_scenario_acceptance",
                "gold_pages": [1],
                "gold_block_ids": ["b1"],
                "evidence_note": "date line",
                "verified": True,
            },
            {
                "qid": "draft",
                "doc_id": "doc1",
                "question": "Draft?",
                "answers": ["draft"],
                "answer_type": "text",
                "source_qa_role": "globocan_scenario_acceptance",
                "gold_pages": [1],
                "gold_block_ids": ["b1"],
                "verified": False,
            },
        ],
    )
    output_dir = tmp_path / "out"
    return document_dir, qa_path, output_dir


def test_real_document_contract_excludes_draft_and_boilerplate(tmp_path: Path) -> None:
    document_dir, qa_path, output_dir = _fixture(tmp_path)

    payload = build_contract(
        document_dir=document_dir,
        qa_path=qa_path,
        output_dir=output_dir,
        benchmark_id="fixture_doc",
    )

    qa_records = read_jsonl(output_dir / "fixture_doc_qa.jsonl")
    corpus_records = read_jsonl(output_dir / "fixture_doc_corpus.jsonl")
    manifest = json.loads((output_dir / "fixture_doc_benchmark_manifest.json").read_text(encoding="utf-8"))

    assert payload["status"] == "success"
    assert [record["qid"] for record in qa_records] == ["q1"]
    assert [record["block_id"] for record in corpus_records] == ["b1"]
    assert manifest["draft_sample_count"] == 1
    assert manifest["artifact_role"] == "real_document_regression"
    assert manifest["source_qa_role"] == "globocan_scenario_acceptance"
    assert manifest["evaluation_scope"] == "scenario_regression"
    assert manifest["formal_benchmark"] is False
    assert manifest["primary_benchmark"] is False
    assert manifest["verified_qa_count"] == 1
    assert manifest["corpus_is_query_independent"] is True
    assert manifest["gold_block_coverage"]["coverage_rate"] == 1.0
    assert manifest["retrieval_contract"]["artifact_role"] == "real_document_regression"
    assert manifest["retrieval_contract"]["source_qa_role"] == "globocan_scenario_acceptance"
    assert manifest["retrieval_contract"]["evaluation_scope"] == "scenario_regression"
    assert manifest["retrieval_contract"]["formal_benchmark"] is False
    assert manifest["retrieval_contract"]["primary_benchmark"] is False
    assert qa_records[0]["evidence"] == []
    assert qa_records[0]["metadata"]["source_qa_role"] == "globocan_scenario_acceptance"


def test_real_document_contract_rejects_duplicate_blocks(tmp_path: Path) -> None:
    document_dir, qa_path, output_dir = _fixture(tmp_path)
    write_jsonl(document_dir / "evidence_blocks.jsonl", [_block("b1"), _block("b1", text="duplicate")])

    with pytest.raises(RuntimeError, match="duplicate block_id"):
        build_contract(document_dir=document_dir, qa_path=qa_path, output_dir=output_dir, benchmark_id="fixture_doc")


def test_real_document_contract_rejects_duplicate_qids(tmp_path: Path) -> None:
    document_dir, qa_path, output_dir = _fixture(tmp_path)
    records = read_jsonl(qa_path)
    records[1]["verified"] = True
    records[1]["qid"] = "q1"
    write_jsonl(qa_path, records)

    with pytest.raises(RuntimeError, match="duplicate qid"):
        build_contract(document_dir=document_dir, qa_path=qa_path, output_dir=output_dir, benchmark_id="fixture_doc")


def test_real_document_contract_rejects_missing_gold(tmp_path: Path) -> None:
    document_dir, qa_path, output_dir = _fixture(tmp_path)
    records = read_jsonl(qa_path)
    records[0]["gold_block_ids"] = ["missing"]
    write_jsonl(qa_path, records)

    with pytest.raises(RuntimeError, match="gold block missing"):
        build_contract(document_dir=document_dir, qa_path=qa_path, output_dir=output_dir, benchmark_id="fixture_doc")


def test_scenario_qa_cannot_be_forced_to_formal_primary_benchmark(tmp_path: Path) -> None:
    document_dir, qa_path, output_dir = _fixture(tmp_path)
    build_contract(document_dir=document_dir, qa_path=qa_path, output_dir=output_dir, benchmark_id="fixture_doc")
    qa_records = read_jsonl(output_dir / "fixture_doc_qa.jsonl")
    corpus_records = read_jsonl(output_dir / "fixture_doc_corpus.jsonl")

    contract = validate_benchmark_contract(
        [DocAgentSample.from_dict(record) for record in qa_records],
        input_path=qa_path,
        corpus_blocks=[EvidenceBlock.from_dict(record) for record in corpus_records],
        corpus_input_path=output_dir / "fixture_doc_corpus.jsonl",
        artifact_role="formal_retrieval_benchmark",
        source_qa_role="globocan_scenario_acceptance",
        evaluation_scope="primary_retrieval",
        formal_benchmark=True,
        primary_benchmark=True,
    )

    assert contract.status == "invalid"
    assert any("forbidden primary benchmark role: globocan_scenario_acceptance" in error for error in contract.errors)


def test_globocan_existing_qa_is_contract_compatible() -> None:
    document_dir = Path("data/real_documents/globocan_africa_2022/docagent_documents/fe3465edd3da60d2")
    qa_path = Path("data/real_documents/globocan_africa_2022/qa/scenario_qa.jsonl")
    if not document_dir.exists() or not qa_path.exists():
        pytest.skip("local GLOBOCAN artifacts are not present")

    payload = build_contract(
        document_dir=document_dir,
        qa_path=qa_path,
        output_dir=Path("outputs/tests/globocan_contract"),
        benchmark_id="globocan_test",
    )

    assert payload["metrics"]["sample_count"] == 8
    assert payload["metrics"]["gold_block_coverage"]["coverage_rate"] == 1.0

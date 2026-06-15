from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from docagent.eval.phase3_focused import load_corpus_blocks, validate_benchmark_contract
from docagent.schemas import DocAgentSample
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.build_phase3_mpdocvqa_retrieval_benchmark import (
    BuildError,
    BuildInputs,
    build_benchmark,
    write_outputs,
)


def _imdb_record(
    qid: str,
    *,
    question: str,
    answer: str,
    image_name: list[str],
    answer_page_idx: int | None,
    doc_pages: list[str] | None = None,
    ocr_tokens: list[list[str]] | None = None,
    doc_id: str = "docA",
    total_doc_pages: int | None = 2,
) -> dict:
    record = {
        "question_id": qid,
        "question": question,
        "valid_answers": [answer],
        "image_id": doc_id,
        "image_name": image_name,
        "imdb_doc_pages": doc_pages or ["docA_p1", "docA_p2"],
        "ocr_tokens": ocr_tokens
        or [
            ["Invoice", "Date", "March", "12", "2020"],
            ["Total", "$42.00"],
        ],
    }
    if answer_page_idx is not None:
        record["answer_page_idx"] = answer_page_idx
    if total_doc_pages is not None:
        record["total_doc_pages"] = total_doc_pages
    return record


def _write_fixture_sources(tmp_path: Path) -> tuple[Path, Path]:
    imdb_path = tmp_path / "imdb_dev.jsonl"
    qa_path = tmp_path / "source_qa.jsonl"
    write_jsonl(
        imdb_path,
        [
            _imdb_record(
                "q_date",
                question="What is the invoice date?",
                answer="March 12, 2020",
                image_name=["docA_p1"],
                answer_page_idx=0,
            ),
            _imdb_record(
                "q_total",
                question="What is the total?",
                answer="$42.00",
                image_name=["docA_p2"],
                answer_page_idx=0,
            ),
            _imdb_record(
                "q_vendor",
                question="Who is the vendor?",
                answer="Example Co.",
                image_name=["docB_p1"],
                answer_page_idx=0,
                doc_pages=["docB_p1"],
                ocr_tokens=[["Vendor", "Example", "Co."]],
                doc_id="docB",
                total_doc_pages=1,
            ),
        ],
    )
    write_jsonl(
        qa_path,
        [
            {
                "qid": "q_date",
                "source": "mp_docvqa",
                "doc_id": "docA",
                "question": "What is the invoice date?",
                "answer": "March 12, 2020",
                "answer_type": "extractive",
                "evidence": [
                    {
                        "doc_id": "docA",
                        "page_id": 1,
                        "block_id": "docA_p1_official_ocr",
                        "block_type": "text",
                        "text": "query conditioned page",
                        "location": {"page": 1, "block_id": "docA_p1_official_ocr"},
                        "metadata": {},
                    }
                ],
                "metadata": {"gold_block_ids": ["docA_p1_official_ocr"]},
            },
            {
                "qid": "q_total",
                "source": "mp_docvqa",
                "doc_id": "docA",
                "question": "What is the total?",
                "answer": "$42.00",
                "answer_type": "extractive",
                "evidence": [
                    {
                        "doc_id": "docA",
                        "page_id": 2,
                        "block_id": "docA_p2_official_ocr",
                        "block_type": "text",
                        "text": "query conditioned page",
                        "location": {"page": 2, "block_id": "docA_p2_official_ocr"},
                        "metadata": {},
                    }
                ],
                "metadata": {"gold_block_ids": ["docA_p2_official_ocr"]},
            },
        ],
    )
    return imdb_path, qa_path


def _build(tmp_path: Path, *, limit: int | None = None, seed: str = "fixture-seed"):
    imdb_path, qa_path = _write_fixture_sources(tmp_path)
    return build_benchmark(
        BuildInputs(
            source_imdb=imdb_path,
            source_ocr_root=None,
            source_qa=qa_path,
            split="dev",
            limit=limit,
            seed=seed,
        )
    )


def test_multi_question_same_doc_generates_one_query_independent_corpus(tmp_path: Path) -> None:
    result = _build(tmp_path)

    assert not result.errors
    assert result.manifest["sample_count"] == 2
    assert result.manifest["document_count"] == 1
    assert [block.block_id for block in result.corpus_blocks] == [
        "docA_p1_official_ocr",
        "docA_p2_official_ocr",
    ]
    assert all("question" not in block.metadata for block in result.corpus_blocks)
    assert result.manifest["corpus_is_query_independent"] is True


def test_complete_page_aggregation_uses_imdb_doc_pages_not_query_pages(tmp_path: Path) -> None:
    result = _build(tmp_path)

    assert not result.errors
    assert result.manifest["page_coverage"]["mean"] == 1.0
    assert result.manifest["page_coverage"]["full_page_coverage_count"] == 1
    assert {block.metadata["page_id"] for block in result.corpus_blocks} == {"docA_p1", "docA_p2"}


def test_missing_record_page_ocr_can_be_read_from_source_ocr_root(tmp_path: Path) -> None:
    imdb_path, qa_path = _write_fixture_sources(tmp_path)
    records = read_jsonl(imdb_path)
    records[0]["ocr_tokens"] = [["Invoice", "Date", "March", "12", "2020"]]
    records[1]["ocr_tokens"] = [["Total", "$42.00"]]
    write_jsonl(imdb_path, records[:1])
    ocr_root = tmp_path / "official_ocr"
    ocr_root.mkdir()
    (ocr_root / "docA_p2.txt").write_text("Total $42.00", encoding="utf-8")
    write_jsonl(qa_path, read_jsonl(qa_path)[:1])

    result = build_benchmark(
        BuildInputs(
            source_imdb=imdb_path,
            source_ocr_root=ocr_root,
            source_qa=qa_path,
            split="dev",
            limit=None,
            seed="fixture-seed",
        )
    )

    assert not result.errors
    assert {block.block_id for block in result.corpus_blocks} == {
        "docA_p1_official_ocr",
        "docA_p2_official_ocr",
    }
    assert any(block.text == "Total $42.00" for block in result.corpus_blocks)


def test_canonical_block_id_and_manifest_hash_are_stable(tmp_path: Path) -> None:
    first = _build(tmp_path / "first")
    second = _build(tmp_path / "second")

    assert not first.errors
    assert not second.errors
    assert first.manifest["corpus_hash"] == second.manifest["corpus_hash"]
    assert first.manifest["qid_hash"] == second.manifest["qid_hash"]
    assert all(block.block_id.endswith("_official_ocr") for block in first.corpus_blocks)


def test_duplicate_block_id_is_rejected(tmp_path: Path) -> None:
    imdb_path = tmp_path / "imdb_dev.jsonl"
    write_jsonl(
        imdb_path,
        [
            _imdb_record(
                "q_dup",
                question="What is duplicated?",
                answer="x",
                image_name=["docA_p1"],
                answer_page_idx=0,
                doc_pages=["docA_p1", "docA_p1"],
                total_doc_pages=2,
            )
        ],
    )

    result = build_benchmark(
        BuildInputs(
            source_imdb=imdb_path,
            source_ocr_root=None,
            source_qa=None,
            split="dev",
            limit=None,
            seed="fixture-seed",
        )
    )

    assert any("duplicate page id" in error for error in result.errors)


def test_gold_block_coverage_must_be_complete(tmp_path: Path) -> None:
    result = _build(tmp_path)

    assert not result.errors
    assert result.manifest["gold_block_coverage"]["coverage_rate"] == 1.0


def test_gold_block_missing_fails_without_pseudo_mapping(tmp_path: Path) -> None:
    imdb_path, qa_path = _write_fixture_sources(tmp_path)
    records = read_jsonl(qa_path)
    records[0]["metadata"]["gold_block_ids"] = ["missing_gold_block"]
    write_jsonl(qa_path, records)

    result = build_benchmark(
        BuildInputs(
            source_imdb=imdb_path,
            source_ocr_root=None,
            source_qa=qa_path,
            split="dev",
            limit=None,
            seed="fixture-seed",
        )
    )

    assert any("gold block not found in corpus" in error for error in result.errors)


def test_builder_does_not_infer_gold_from_answer_text(tmp_path: Path) -> None:
    imdb_path = tmp_path / "imdb_dev.jsonl"
    write_jsonl(
        imdb_path,
        [
            _imdb_record(
                "q_no_gold",
                question="What is the invoice date?",
                answer="March 12, 2020",
                image_name=["docA_p1"],
                answer_page_idx=None,
            )
        ],
    )

    result = build_benchmark(
        BuildInputs(
            source_imdb=imdb_path,
            source_ocr_root=None,
            source_qa=None,
            split="dev",
            limit=None,
            seed="fixture-seed",
        )
    )

    assert any("does not infer gold from answer text" in error for error in result.errors)


def test_deterministic_sampling_uses_seed(tmp_path: Path) -> None:
    first = _build(tmp_path / "first", limit=1, seed="same-seed")
    second = _build(tmp_path / "second", limit=1, seed="same-seed")

    assert not first.errors
    assert not second.errors
    assert [record["qid"] for record in first.qa_records] == [record["qid"] for record in second.qa_records]
    assert len(first.qa_records) == 1


def test_qa_artifact_does_not_embed_query_conditioned_evidence(tmp_path: Path) -> None:
    result = _build(tmp_path)

    assert not result.errors
    assert all(record["evidence"] == [] for record in result.qa_records)
    assert all("gold_block_ids" in record for record in result.qa_records)


def test_runner_validator_accepts_builder_outputs(tmp_path: Path) -> None:
    result = _build(tmp_path)
    assert not result.errors
    qa_path = tmp_path / "phase3_mpdocvqa_qa.jsonl"
    corpus_path = tmp_path / "phase3_mpdocvqa_corpus.jsonl"
    manifest_path = tmp_path / "phase3_mpdocvqa_manifest.json"
    write_outputs(result, output_qa=qa_path, output_corpus=corpus_path, output_manifest=manifest_path)

    samples = [DocAgentSample.from_dict(record) for record in read_jsonl(qa_path)]
    blocks = load_corpus_blocks(corpus_path)
    contract = validate_benchmark_contract(samples, input_path=qa_path, corpus_blocks=blocks, corpus_input_path=corpus_path)

    assert contract.status == "ready"
    assert contract.corpus_is_query_independent is True
    assert contract.gold_block_coverage["coverage_rate"] == 1.0
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["corpus_hash"] == contract.corpus_hash


def test_cli_build_and_validate_only(tmp_path: Path) -> None:
    imdb_path, qa_path = _write_fixture_sources(tmp_path)
    output_qa = tmp_path / "phase3_qa.jsonl"
    output_corpus = tmp_path / "phase3_corpus.jsonl"
    output_manifest = tmp_path / "phase3_manifest.json"
    root = Path(__file__).resolve().parents[1]

    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_phase3_mpdocvqa_retrieval_benchmark.py",
            "--source-imdb",
            str(imdb_path),
            "--source-qa",
            str(qa_path),
            "--output-qa",
            str(output_qa),
            "--output-corpus",
            str(output_corpus),
            "--output-manifest",
            str(output_manifest),
            "--split",
            "dev",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert output_qa.is_file()
    assert output_corpus.is_file()
    assert output_manifest.is_file()

    validate_only = subprocess.run(
        [
            sys.executable,
            "scripts/build_phase3_mpdocvqa_retrieval_benchmark.py",
            "--source-imdb",
            str(imdb_path),
            "--source-qa",
            str(qa_path),
            "--validate-only",
        ],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert validate_only.returncode == 0, validate_only.stdout + validate_only.stderr
    assert json.loads(validate_only.stdout)["status"] == "success"


def test_missing_source_qa_qid_fails(tmp_path: Path) -> None:
    imdb_path, qa_path = _write_fixture_sources(tmp_path)
    records = read_jsonl(qa_path)
    records[0]["qid"] = "missing_qid"
    write_jsonl(qa_path, records)

    with pytest.raises(BuildError, match="source-imdb is missing"):
        build_benchmark(
            BuildInputs(
                source_imdb=imdb_path,
                source_ocr_root=None,
                source_qa=qa_path,
                split="dev",
                limit=None,
                seed="fixture-seed",
            )
        )

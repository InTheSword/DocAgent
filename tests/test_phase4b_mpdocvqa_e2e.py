from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_phase4b_mpdocvqa_e2e import parse_args, run_phase4b_e2e


DOC_A = "docA__window"
DOC_B = "docB__window"


def _block(doc_id: str, block_id: str, page: int, text: str, *, order: int) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id=doc_id,
        block_id=block_id,
        block_type="text",
        text=text,
        page_id=page,
        location=EvidenceLocation(page=page, block_id=block_id, bbox=[0, 0, 10, 10]),
        metadata={"reading_order": order},
    )


def _page(doc_id: str, block_id: str, page: int, text: str, child_ids: list[str]) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id=doc_id,
        block_id=block_id,
        block_type="page",
        text=text,
        page_id=page,
        location=EvidenceLocation(page=page, block_id=block_id),
        metadata={"child_block_ids": child_ids},
    )


def _write_window(
    ingestion_root: Path,
    *,
    doc_id: str,
    source_doc_id: str,
    page_texts: list[list[str]],
    qa_specs: list[dict[str, Any]],
) -> None:
    work_dir = ingestion_root / doc_id
    internal_doc_id = f"internal_{doc_id}"
    internal_dir = work_dir / "documents" / internal_doc_id
    internal_dir.mkdir(parents=True)

    child_blocks: list[EvidenceBlock] = []
    page_blocks: list[EvidenceBlock] = []
    page_identity: list[dict[str, Any]] = []
    for page_number, texts in enumerate(page_texts, start=1):
        child_ids: list[str] = []
        page_parts: list[str] = []
        for offset, text in enumerate(texts, start=1):
            block_id = f"{internal_doc_id}_p{page_number:03d}_b{offset:04d}"
            child_ids.append(block_id)
            page_parts.append(text)
            child_blocks.append(_block(internal_doc_id, block_id, page_number, text, order=offset))
        page_id = f"{internal_doc_id}_p{page_number:03d}_page"
        page_blocks.append(_page(internal_doc_id, page_id, page_number, "\n".join(page_parts), child_ids))
        page_identity.append(
            {
                "doc_id": doc_id,
                "source_doc_id": source_doc_id,
                "source_page_id": f"{source_doc_id}_p{page_number}",
                "page_window_ordinal": page_number,
                "pdf_page_number": page_number,
                "parsed_page_number": page_number,
                "page_aggregate_id": page_id,
                "child_block_ids": child_ids,
                "mapping_valid": True,
                "mapping_errors": [],
            }
        )

    qa_mapping: list[dict[str, Any]] = []
    page_by_ordinal = {record["page_window_ordinal"]: record for record in page_identity}
    for spec in qa_specs:
        page_record = page_by_ordinal[spec["gold_page_ordinal"]]
        qa_mapping.append(
            {
                "qid": spec["qid"],
                "doc_id": doc_id,
                "source_doc_id": source_doc_id,
                "answer_page_idx": spec["gold_page_ordinal"] - 1,
                "gold_page_id": page_record["source_page_id"],
                "gold_page_ordinal": spec["gold_page_ordinal"],
                "parsed_page_number": page_record["parsed_page_number"],
                "page_aggregate_id": page_record["page_aggregate_id"],
                "child_block_ids": page_record["child_block_ids"],
                "mapping_valid": True,
                "mapping_errors": [],
            }
        )

    write_jsonl(internal_dir / "evidence_blocks.jsonl", [block.to_dict() for block in child_blocks])
    write_jsonl(internal_dir / "page_documents.jsonl", [block.to_dict() for block in page_blocks])
    write_jsonl(work_dir / "page_identity_mapping.jsonl", page_identity)
    write_jsonl(work_dir / "qa_page_mapping.jsonl", qa_mapping)
    (work_dir / "acceptance_report.json").write_text(
        json.dumps(
            {
                "status": "success",
                "doc_id": doc_id,
                "source_doc_id": source_doc_id,
                "expected_page_count": len(page_blocks),
                "parsed_page_count": len(page_blocks),
                "page_document_count": len(page_blocks),
                "gold_page_mapping_valid_count": len(qa_mapping),
                "persisted_absolute_path_count": 0,
                "no_mock_fallback": True,
                "failures": [],
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    sample_root = tmp_path / "sample"
    ingestion_root = tmp_path / "ingestion"
    output_root = tmp_path / "eval"
    sample_root.mkdir()
    qa_records = [
        {
            "qid": "q_alpha",
            "doc_id": DOC_A,
            "source_doc_id": "docA",
            "question": "Where is alpha total?",
            "answers": ["Alpha Total"],
            "answer_type": "extractive",
            "gold_page_ordinal": 1,
        },
        {
            "qid": "q_beta",
            "doc_id": DOC_A,
            "source_doc_id": "docA",
            "question": "Where is beta invoice code?",
            "answers": ["Beta Code"],
            "answer_type": "extractive",
            "gold_page_ordinal": 2,
        },
        {
            "qid": "q_gamma",
            "doc_id": DOC_B,
            "source_doc_id": "docB",
            "question": "Where is gamma meeting amount?",
            "answers": ["Gamma Amount"],
            "answer_type": "extractive",
            "gold_page_ordinal": 1,
        },
    ]
    write_jsonl(sample_root / "qa.jsonl", qa_records)
    _write_window(
        ingestion_root,
        doc_id=DOC_A,
        source_doc_id="docA",
        page_texts=[
            ["Alpha Total appears on this page."],
            ["Beta Code is printed here.", "Supplemental beta table details."],
        ],
        qa_specs=[qa_records[0], qa_records[1]],
    )
    _write_window(
        ingestion_root,
        doc_id=DOC_B,
        source_doc_id="docB",
        page_texts=[["Gamma Amount appears in this meeting invoice."]],
        qa_specs=[qa_records[2]],
    )
    return sample_root, ingestion_root, output_root


def _args(sample_root: Path, ingestion_root: Path, output_root: Path, *extra: str):
    return parse_args(
        [
            "--sample-root",
            str(sample_root),
            "--ingestion-root",
            str(ingestion_root),
            "--output-root",
            str(output_root),
            "--doc-id",
            DOC_A,
            "--doc-id",
            DOC_B,
            *extra,
        ]
    )


def test_validate_only_loads_gate2_contract_without_models(tmp_path: Path) -> None:
    sample_root, ingestion_root, output_root = _fixture(tmp_path)
    args = _args(sample_root, ingestion_root, output_root, "--validate-only")

    payload = run_phase4b_e2e(args)

    assert payload["status"] == "success"
    assert payload["validate_only"] is True
    assert payload["document_count"] == 2
    assert payload["page_count"] == 3
    assert payload["qa_count"] == 3
    assert payload["gold_page_mapping_valid_count"] == 3
    assert payload["models_loaded"] is False
    assert not output_root.exists()


def test_retrieval_only_writes_doc_scoped_page_metrics_and_fixed_evidence(tmp_path: Path) -> None:
    sample_root, ingestion_root, output_root = _fixture(tmp_path)
    args = _args(
        sample_root,
        ingestion_root,
        output_root,
        "--run-id",
        "retrieval",
        "--dense-backend",
        "hash",
        "--reranker-backend",
        "keyword",
        "--allow-mock-backends",
        "--retrieval-only",
        "--force",
        "--max-context-blocks",
        "1",
    )

    summary = run_phase4b_e2e(args)
    run_dir = output_root / "retrieval"
    retrieval_rows = read_jsonl(run_dir / "page_retrieval_results.jsonl")
    fixed_rows = read_jsonl(run_dir / "fixed_evidence.jsonl")
    metrics = json.loads((run_dir / "page_retrieval_metrics.json").read_text(encoding="utf-8"))

    assert summary["status"] == "success"
    assert summary["answer_metrics"]["status"] == "skipped"
    assert summary["resource_plan"]["retrieval_models_released"] is True
    assert summary["resource_plan"]["retrieval_released_before_answer_policy"] is True
    assert {row["mode"] for row in retrieval_rows} == {"bm25", "hybrid"}
    assert metrics["bm25"]["sample_count"] == metrics["hybrid"]["sample_count"] == 3
    assert metrics["hybrid"]["recall_at_1"] == 1.0
    for row in retrieval_rows:
        assert set(row["ranking"]).issubset(set(row["corpus_page_ids"]))
        assert row["query_rewrite"] == "none"
        assert row["retrieval_scope"] == "selected_document_window"
    assert all("answers" not in json.dumps(row) for row in fixed_rows)
    assert all("gold_page" not in json.dumps(row) for row in fixed_rows)
    assert any(row["truncation_applied"] for row in fixed_rows)
    assert summary["fixed_evidence_hash"]
    assert all("\\" not in value and ":" not in value for value in summary["artifact_paths"].values())


def test_full_mock_answer_policy_writes_answer_metrics_and_sqlite_trace(tmp_path: Path) -> None:
    sample_root, ingestion_root, output_root = _fixture(tmp_path)
    args = _args(
        sample_root,
        ingestion_root,
        output_root,
        "--run-id",
        "full",
        "--dense-backend",
        "hash",
        "--reranker-backend",
        "keyword",
        "--answer-backend",
        "heuristic",
        "--qwen-device",
        "cpu",
        "--allow-mock-backends",
        "--force",
    )

    summary = run_phase4b_e2e(args)
    run_dir = output_root / "full"
    answer_rows = read_jsonl(run_dir / "answer_results.jsonl")
    answer_metrics = json.loads((run_dir / "answer_metrics.json").read_text(encoding="utf-8"))

    assert summary["status"] == "success"
    assert answer_metrics["sample_count"] == 3
    assert answer_metrics["completed_count"] == 3
    assert answer_metrics["valid_json_rate"] == 1.0
    assert answer_metrics["format_valid_rate"] == 1.0
    assert answer_metrics["final_location_in_evidence_rate"] == 1.0
    assert len(answer_rows) == 3
    with sqlite3.connect(run_dir / "docagent.sqlite") as conn:
        assert conn.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0] == 3
        assert conn.execute("SELECT COUNT(*) FROM tool_traces").fetchone()[0] >= 15
    assert summary["trace_counts"]["qa_runs"] == 3
    assert summary["artifact_paths"]["sqlite"] == "docagent.sqlite"
    assert (run_dir / "summary.md").is_file()


def test_cli_help_starts() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "scripts/run_phase4b_mpdocvqa_e2e.py", "--help"],
        cwd=root,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--retrieval-only" in result.stdout
    assert "--allow-mock-backends" in result.stdout

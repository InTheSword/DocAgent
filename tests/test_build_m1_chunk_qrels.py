from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from docagent.schemas import Chunk, EvidenceLocation
from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.build_m1_chunk_qrels import build_candidates, freeze_qrels, run


def _chunk(block_id: str, text: str, *, order: int, page: int = 2) -> Chunk:
    return Chunk(
        doc_id="doc",
        block_id=block_id,
        block_type="text",
        text=text,
        page_id=page,
        location=EvidenceLocation(page=page, block_id=block_id),
        metadata={
            "content_type": "body",
            "reading_order": order,
            "source_page_numbers": [page],
            "content_hash": f"hash-{block_id}",
            "exclude_from_retrieval": False,
        },
    )


def _sample(verbatim: str) -> dict:
    return {
        "sample_id": "S1",
        "document_file": "sample.pdf",
        "question": "What happened?",
        "gold_evidence_groups": [
            {
                "group_id": "g1",
                "evidence_type": "text",
                "physical_pages": [2],
                "source_locator": "p2",
                "verbatim_content": verbatim,
            }
        ],
    }


def _manifest() -> dict:
    return {
        "corpus_id": "corpus-v1",
        "chunk_contract_version": "docagent_chunk_v3",
        "documents": [
            {
                "document_file": "sample.pdf",
                "doc_id": "doc",
                "source_pdf_sha256": "pdf-hash",
            }
        ],
    }


def test_candidates_include_exact_single_chunk_and_hash_binding() -> None:
    chunks = [_chunk("c1", "The reported value was 42.", order=1)]

    rows, queue, decisions = build_candidates(
        samples=[_sample("The reported value was 42.")],
        manifest=_manifest(),
        documents_by_file={"sample.pdf": _manifest()["documents"][0]},
        chunks_by_doc={"doc": chunks},
        max_window=4,
    )

    group = rows[0]["evidence_groups"][0]
    assert group["candidate_class"] == "exact_single"
    assert group["review_status"] == "unreviewed"
    assert group["candidates"][0]["chunk_ids"] == ["c1"]
    assert group["candidates"][0]["chunk_content_hashes"] == {"c1": "hash-c1"}
    assert queue[0]["source_evidence"]["verbatim_content"] == "The reported value was 42."
    assert decisions[0]["decision"] is None


def test_candidates_find_minimal_adjacent_multi_chunk_window() -> None:
    chunks = [
        _chunk("c1", "The first required fact.", order=1),
        _chunk("c2", "The second required fact.", order=2),
        _chunk("c3", "Unrelated appendix.", order=3),
    ]

    rows, _, _ = build_candidates(
        samples=[_sample("The first required fact. The second required fact.")],
        manifest=_manifest(),
        documents_by_file={"sample.pdf": _manifest()["documents"][0]},
        chunks_by_doc={"doc": chunks},
        max_window=4,
    )

    group = rows[0]["evidence_groups"][0]
    assert group["candidate_class"] == "exact_multi"
    assert group["candidates"][0]["chunk_ids"] == ["c1", "c2"]


def test_freeze_fails_closed_when_review_decisions_are_missing() -> None:
    rows, _, _ = build_candidates(
        samples=[_sample("The value is 42.")],
        manifest=_manifest(),
        documents_by_file={"sample.pdf": _manifest()["documents"][0]},
        chunks_by_doc={"doc": [_chunk("c1", "The value is 42.", order=1)]},
        max_window=4,
    )

    with pytest.raises(ValueError, match="do not cover"):
        freeze_qrels(rows, [], {"doc": [_chunk("c1", "The value is 42.", order=1)]})


def test_freeze_validates_review_binding_and_selected_hashes() -> None:
    chunk = _chunk("c1", "The value is 42.", order=1)
    rows, _, decisions = build_candidates(
        samples=[_sample("The value is 42.")],
        manifest=_manifest(),
        documents_by_file={"sample.pdf": _manifest()["documents"][0]},
        chunks_by_doc={"doc": [chunk]},
        max_window=4,
    )
    decision = decisions[0]
    decision.update(
        {
            "decision": "accept_candidate",
            "primary_chunk_ids": ["c1"],
            "selected_chunk_hashes": {"c1": "wrong"},
            "reviewer": "reviewer-1",
            "reviewed_at": "2026-08-02T00:00:00Z",
            "rationale": "Exact source span verified.",
        }
    )

    with pytest.raises(ValueError, match="stale selected chunk hashes"):
        freeze_qrels(rows, [decision], {"doc": [chunk]})

    decision["selected_chunk_hashes"] = {"c1": "hash-c1"}
    frozen = freeze_qrels(rows, [decision], {"doc": [chunk]})
    assert frozen[0]["review_status"] == "reviewed"
    assert frozen[0]["evaluation_eligible"] is True
    assert frozen[0]["evidence_groups"][0]["primary_chunk_ids"] == ["c1"]


def test_run_without_reviews_writes_candidates_but_not_frozen_qrels(tmp_path: Path) -> None:
    chunk = _chunk("c1", "The value is 42.", order=1)
    chunks_path = tmp_path / "chunks.jsonl"
    samples_path = tmp_path / "samples.jsonl"
    manifest_path = tmp_path / "manifest.json"
    output_dir = tmp_path / "output"
    sync_dir = tmp_path / "sync"
    write_jsonl(chunks_path, [chunk.to_dict()])
    write_jsonl(samples_path, [_sample("The value is 42."), {"sample_id": "route", "document_file": None}])
    manifest = _manifest()
    manifest["documents"][0]["evidence_blocks_path"] = str(chunks_path)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = run(
        Namespace(
            samples=str(samples_path),
            corpus_manifest=str(manifest_path),
            output_dir=str(output_dir),
            sync_dir=str(sync_dir),
            run_id="test-run",
            max_window=4,
            review_decisions="",
        )
    )

    summary = json.loads((output_dir / "summary.json").read_text(encoding="utf-8"))
    assert result["status"] == "success"
    assert summary["milestone_status"] == "ready"
    assert summary["document_bound_sample_count"] == 1
    assert summary["non_document_sample_count"] == 1
    assert not (output_dir / "frozen_chunk_qrels.jsonl").exists()
    assert len(read_jsonl(output_dir / "qrels_review_queue.jsonl")) == 1


def test_direct_cli_help_can_import_project_package() -> None:
    completed = subprocess.run(
        [sys.executable, "scripts/build_m1_chunk_qrels.py", "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert "Build reviewable M1 Chunk qrels candidates" in completed.stdout

from __future__ import annotations

import json
import sys
from pathlib import Path

from docagent.utils.jsonl import read_jsonl, write_jsonl
from scripts.run_mpdocvqa_full_workflow_diagnostic import (
    CommandResult,
    build_parser,
    run_mpdocvqa_full_workflow_diagnostic,
)


def write_manifest(path: Path) -> None:
    write_jsonl(
        path,
        [
            {
                "sample_id": "mp_hit",
                "dataset": "mp_docvqa",
                "doc_id": "source_doc",
                "ingested_doc_id": "ingested_doc",
                "source_document": "source",
                "question": "What is on page 2?",
                "answers": ["alpha"],
                "expected_answer_type": "extractive",
                "gold_pages": [2],
                "evidence_ready": True,
            },
            {
                "sample_id": "mp_miss",
                "dataset": "mp_docvqa",
                "doc_id": "source_doc",
                "ingested_doc_id": "ingested_doc",
                "source_document": "source",
                "question": "What is on page 3?",
                "answers": ["bravo"],
                "expected_answer_type": "extractive",
                "gold_pages": [3],
                "evidence_ready": True,
            },
            {
                "sample_id": "mp_not_ready",
                "dataset": "mp_docvqa",
                "ingested_doc_id": "ingested_doc",
                "question": "Skipped?",
                "answers": ["skip"],
                "gold_pages": [4],
                "evidence_ready": False,
            },
        ],
    )


def cli_payload(*, answer: str, candidate_page: int, citation_page: int) -> dict:
    block_id = f"p{candidate_page}_text"
    return {
        "status": "success",
        "doc_id": "ingested_doc",
        "task_type": "local_fact_qa",
        "answer": answer,
        "reasoning_summary": "supported by retrieved evidence",
        "citations": [{"doc_id": "ingested_doc", "page": citation_page, "block_id": f"p{citation_page}_text", "block_type": "text"}],
        "full_model_path": True,
        "used_llm_router": True,
        "used_llm_query_rewriter": True,
        "used_qwen_answer_policy": True,
        "retriever_mode": "hybrid_rerank",
        "retriever": {"mode": "hybrid_rerank", "uses_dense": True, "uses_reranker": True},
        "retrieval_candidate_count": 1,
        "citation_count": 1,
        "workflow_trace": [
            {
                "step": "retrieve_evidence",
                "candidates": [{"block_id": block_id, "page": candidate_page, "final_rank": 1}],
            },
            {"step": "build_evidence_context", "selected_block_ids": [block_id]},
            {"step": "generate_answer"},
            {"step": "finalize"},
        ],
    }


def test_run_mpdocvqa_full_workflow_diagnostic_uses_cli_full_path(tmp_path: Path) -> None:
    manifest = tmp_path / "sample_evidence_manifest.jsonl"
    write_manifest(manifest)
    db_path = tmp_path / "docagent.db"
    db_path.write_text("", encoding="utf-8")
    seen_commands: list[list[str]] = []

    def fake_runner(command: list[str], _cwd: Path, _timeout: int) -> CommandResult:
        seen_commands.append(command)
        question = command[command.index("--question") + 1]
        if "page 2" in question:
            payload = cli_payload(answer="alpha", candidate_page=2, citation_page=2)
        else:
            payload = cli_payload(answer="wrong", candidate_page=1, citation_page=1)
        return CommandResult(0, json.dumps(payload), "")

    args = build_parser().parse_args(
        [
            "--python-executable",
            sys.executable,
            "--router-llm-env-file",
            ".secrets/router_llm.env",
            "--base-model-path",
            "/models/qwen",
            "--answer-output-contract",
            "v3_refs",
            "--adapter-path",
            "/adapters/promptfix",
            "--dense-model-path",
            "/models/bge",
            "--reranker-model-path",
            "/models/reranker",
            "--limit",
            "2",
        ]
    )
    result = run_mpdocvqa_full_workflow_diagnostic(
        evidence_manifest=manifest,
        db_path=db_path,
        output_root=tmp_path / "out",
        run_id="mp_full",
        limit=2,
        args=args,
        command_runner=fake_runner,
        sync_output_root=tmp_path / "sync",
    )

    assert result["status"] == "success"
    assert result["selected_sample_count"] == 2
    assert result["evaluated_count"] == 2
    assert result["pass_rate"] == 0.5
    assert result["retrieved_gold_page_hit_rate"] == 0.5
    assert result["bucket_counts"] == {"passed": 1, "retrieval_gold_page_miss": 1}
    assert result["used_qwen_answer_policy_count"] == 2
    assert result["used_dense_retrieval_count"] == 2
    assert result["used_reranker_count"] == 2
    assert result["recommendation"]["next_action"] == "compare_cli_hybrid_retrieval_rows_before_training"
    assert len(seen_commands) == 2
    first_command = seen_commands[0]
    assert "--full-model-path" in first_command
    assert first_command[first_command.index("--retriever-mode") + 1] == "hybrid_rerank"
    assert first_command[first_command.index("--answer-policy") + 1] == "base"
    assert first_command[first_command.index("--answer-output-contract") + 1] == "v3_refs"
    assert first_command[first_command.index("--adapter-path") + 1] == "/adapters/promptfix"
    assert first_command[first_command.index("--db-path") + 1] == str(db_path)
    assert first_command[first_command.index("--doc-id") + 1] == "ingested_doc"
    assert result["answer_output_contract"] == "v3_refs"
    assert result["adapter_path"] == "/adapters/promptfix"

    rows = read_jsonl(tmp_path / "out" / "mp_full" / "results.jsonl")
    assert [row["bucket"] for row in rows] == ["passed", "retrieval_gold_page_miss"]
    assert (tmp_path / "sync" / "mp_full" / "summary.json").is_file()

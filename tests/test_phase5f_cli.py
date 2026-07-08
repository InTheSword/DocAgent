from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from docagent.models.base import HeuristicAnswerPolicy
from docagent.ingestion.document_registry import DocumentRecord
from docagent.retrieval.dense_index import DenseIndex
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository, TraceRepository
from scripts import docagent_cli


ROOT = Path(__file__).resolve().parents[1]


def test_answer_output_contract_argument_builds_qwen_policy() -> None:
    args = docagent_cli.build_parser().parse_args(["--answer-policy", "base", "--answer-output-contract", "v3_refs"])
    args = docagent_cli._apply_execution_profile(args)

    policy = docagent_cli._build_answer_policy(
        answer_policy=args.answer_policy,
        base_model_path=args.base_model_path,
        adapter_path=args.adapter_path,
        device="cpu",
        torch_dtype=args.torch_dtype,
        max_prompt_tokens=args.max_prompt_tokens,
        max_new_tokens=args.max_new_tokens,
        answer_output_contract=args.answer_output_contract,
    )

    assert policy.config.answer_output_contract == "v3_refs"
    assert docagent_cli._answer_policy_metadata(policy)["answer_output_contract"] == "v3_refs"


def test_user_best_profile_expands_to_best_delivery_defaults() -> None:
    args = docagent_cli.build_parser().parse_args(["--file", "sample.pdf", "--question", "What is this?"])

    resolved = docagent_cli._apply_execution_profile(args)

    assert resolved.execution_profile == "user_best"
    assert resolved.parser == "mineru_api"
    assert resolved.live_api is True
    assert resolved.allow_llm_router is True
    assert resolved.enable_query_planning is True
    assert resolved.full_model_path is True
    assert resolved.retriever_mode == "hybrid_rerank"
    assert resolved.dense_backend == "bge"
    assert resolved.reranker_backend == "cross_encoder"
    assert resolved.answer_policy == "sft"
    assert resolved.answer_output_contract == "v3_refs"
    assert resolved.visual_summary_mode == "auto"
    assert resolved.visual_qa_mode == "auto"
    assert resolved.enable_evidence_recovery is True
    assert resolved.max_visual_summary_images == 3
    assert resolved.adapter_path == docagent_cli.DEFAULT_BEST_ANSWER_POLICY_ADAPTER_PATH


def test_explicit_cli_arguments_override_user_best_profile() -> None:
    args = docagent_cli.build_parser().parse_args(
        [
            "--execution-profile",
            "user_best",
            "--file",
            "sample.pdf",
            "--question",
            "What is this?",
            "--parser",
            "text",
            "--retriever-mode",
            "bm25",
            "--answer-policy",
            "base",
            "--answer-output-contract",
            "candidate_citations",
            "--disable-evidence-recovery",
        ]
    )

    resolved = docagent_cli._apply_execution_profile(args)

    assert resolved.parser == "text"
    assert resolved.retriever_mode == "bm25"
    assert resolved.answer_policy == "base"
    assert resolved.answer_output_contract == "candidate_citations"
    assert resolved.adapter_path is None
    assert resolved.enable_evidence_recovery is False


def test_self_test_profile_keeps_lightweight_defaults() -> None:
    args = docagent_cli.build_parser().parse_args(["--execution-profile", "self_test", "--doc-id", "doc1", "--question", "What is this?"])

    resolved = docagent_cli._apply_execution_profile(args)

    assert resolved.parser == "auto"
    assert resolved.live_api is False
    assert resolved.allow_llm_router is False
    assert resolved.enable_query_planning is False
    assert resolved.full_model_path is False
    assert resolved.retriever_mode == "bm25"
    assert resolved.answer_policy == "heuristic"
    assert resolved.answer_output_contract == "candidate_citations"
    assert resolved.visual_summary_mode == "caption"
    assert resolved.visual_qa_mode == "off"
    assert resolved.enable_evidence_recovery is False


def test_progress_plain_writes_to_stderr_without_stdout(capsys) -> None:
    args = SimpleNamespace(progress="plain")

    docagent_cli._emit_progress(args, "retrieve_evidence", top_k=20)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "[docagent] retrieve_evidence" in captured.err


def test_progress_jsonl_marks_progress_event(capsys) -> None:
    args = SimpleNamespace(progress="jsonl")

    docagent_cli._emit_progress(args, "retrieve_evidence", top_k=20)

    captured = capsys.readouterr()
    assert captured.out == ""
    event = json.loads(captured.err)
    assert event["event"] == "progress"
    assert event["stage"] == "retrieve_evidence"
    assert event["top_k"] == 20


def test_progress_off_is_silent(capsys) -> None:
    args = SimpleNamespace(progress="off")

    docagent_cli._emit_progress(args, "retrieve_evidence", top_k=20)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def _repository_with_document(tmp_path: Path) -> Path:
    db_path = tmp_path / "docagent.sqlite"
    conn = connect(db_path)
    repository = DocumentRepository(conn)
    repository.upsert_document(
        DocumentRecord(
            doc_id="doc1",
            sha256="a" * 64,
            original_name="invoice.pdf",
            mime_type="application/pdf",
            file_size=123,
            file_path=str(tmp_path / "documents" / "doc1" / "source" / "original.pdf"),
            document_dir=str(tmp_path / "documents" / "doc1"),
            page_count=2,
            parser_backend="mineru_existing",
            parse_status="parsed",
            index_status="not_started",
        )
    )
    repository.save_evidence_blocks(
        [
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_page",
                block_type="page",
                text="Invoice Date: March 12, 2020. Total: 42 USD.",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_page"),
                metadata={"child_block_ids": ["doc1_p001_date", "doc1_p001_table"]},
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p002_page",
                block_type="page",
                text="Second page contains supporting notes.",
                page_id=2,
                location=EvidenceLocation(page=2, block_id="doc1_p002_page"),
                metadata={"child_block_ids": ["doc1_p002_text"]},
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_date",
                block_type="text",
                text="Invoice Date: March 12, 2020",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_date"),
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_table",
                block_type="table",
                text="Year Revenue 2020 10 2021 15",
                table_html=(
                    "<table>"
                    "<tr><th>Year</th><th>Revenue</th></tr>"
                    "<tr><td>2020</td><td>10</td></tr>"
                    "<tr><td>2021</td><td>15</td></tr>"
                    "</table>"
                ),
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_table"),
                metadata={"table_caption": "Annual revenue"},
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p002_text",
                block_type="text",
                text="Payment terms are due on receipt.",
                page_id=2,
                location=EvidenceLocation(page=2, block_id="doc1_p002_text"),
            ),
        ]
    )
    conn.close()
    return db_path


def _run_cli(tmp_path: Path, *args: str) -> dict:
    cli_args = list(args)
    if "--execution-profile" not in cli_args:
        cli_args = ["--execution-profile", "self_test", *cli_args]
    completed = subprocess.run(
        [sys.executable, "scripts/docagent_cli.py", *cli_args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    output = completed.stdout.strip()
    assert output.startswith("{")
    assert output.endswith("}")
    return json.loads(output)


def test_list_documents_outputs_json_with_doc_id_and_page_count(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--list-documents",
        "--limit",
        "20",
    )

    assert payload["status"] == "success"
    assert payload["mode"] == "list_documents"
    assert payload["documents"][0]["doc_id"] == "doc1"
    assert payload["documents"][0]["page_count"] == 2


def test_check_index_reports_missing_without_question(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--document-root",
        str(tmp_path / "documents"),
        "--doc-id",
        "doc1",
        "--check-index",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["mode"] == "document_index"
    assert payload["index_action"] == "check"
    assert payload["index_ready"] is False
    assert payload["index_built"] is False
    assert payload["index_status"]["status"] == "missing"
    assert payload["question"] == ""


def test_prepare_index_builds_and_reuses_hash_dense_index(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    first = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--document-root",
        str(tmp_path / "documents"),
        "--doc-id",
        "doc1",
        "--prepare-index",
        "--output-dir",
        str(tmp_path / "cli"),
    )
    second = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--document-root",
        str(tmp_path / "documents"),
        "--doc-id",
        "doc1",
        "--prepare-index",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert first["status"] == "success"
    assert first["index_ready"] is True
    assert first["index_built"] is True
    assert first["index_reused"] is False
    assert first["dense_backend"] == "hash"
    assert Path(first["index_status"]["metadata_path"]).is_file()
    assert Path(first["index_status"]["embeddings_path"]).is_file()
    assert second["status"] == "success"
    assert second["index_ready"] is True
    assert second["index_built"] is False
    assert second["index_reused"] is True


def test_local_fact_qa_cli_payload_preserves_evidence_recovery(tmp_path: Path, monkeypatch) -> None:
    db_path = _repository_with_document(tmp_path)
    conn = connect(db_path)
    repository = DocumentRepository(conn)
    trace_repository = TraceRepository(conn)

    def fake_local_fact_qa(*args, **kwargs):
        return {
            "status": "success",
            "answer": "Insufficient evidence.",
            "citations": [],
            "supporting_evidence_ids": [],
            "tools_used": ["local_fact_qa"],
            "workflow_trace": [],
            "warnings": [],
            "evidence_recovery": {"enabled": True, "status": "exhausted"},
        }

    monkeypatch.setattr(docagent_cli, "local_fact_qa", fake_local_fact_qa)
    try:
        payload = docagent_cli._run_local_fact_qa(
            repository=repository,
            trace_repository=trace_repository,
            db_path=db_path,
            document_root=tmp_path / "documents",
            doc_id="doc1",
            question="What is this?",
            router_plan={},
            dry_run=False,
            run_id="run1",
            answer_policy=HeuristicAnswerPolicy(),
            enable_evidence_recovery=True,
        )
    finally:
        conn.close()

    assert payload["evidence_recovery"]["status"] == "exhausted"


def test_user_best_index_check_does_not_require_answer_policy_adapter(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--execution-profile",
        "user_best",
        "--dense-backend",
        "hash",
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--check-index",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["execution_profile"] == "user_best"
    assert payload["dense_backend"] == "hash"
    assert payload["error"] == {}


def test_user_best_profile_missing_resources_returns_clear_error(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--execution-profile",
        "user_best",
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "What is the invoice date?",
        "--adapter-path",
        str(tmp_path / "missing_adapter"),
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "error"
    assert payload["error"]["type"] == "user_best_resources_missing"
    assert payload["execution_profile"] == "user_best"
    assert payload["answer_policy_mode"] == "sft"
    assert payload["answer_output_contract"] == "v3_refs"
    assert any(item.startswith("adapter_path:") for item in payload["missing_resources"])


def test_stdout_text_format_is_user_readable_without_internal_ids(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/docagent_cli.py",
            "--execution-profile",
            "self_test",
            "--stdout-format",
            "text",
            "--db-path",
            str(db_path),
            "--doc-id",
            "doc1",
            "--question",
            "Show the text from page 1.",
            "--output-dir",
            str(tmp_path / "cli"),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    output = completed.stdout
    assert "Invoice Date" in output
    assert "Sources:" in output
    assert "page 1" in output
    assert "Trace:" in output
    assert "doc1_p001" not in output
    assert "block_id" not in output
    assert "image_path" not in output


def test_retriever_initialization_failure_does_not_mark_qwen_used(monkeypatch, tmp_path: Path) -> None:
    def fail_build_indexed_retriever(**_kwargs):
        raise RuntimeError("dense index build failed")

    monkeypatch.setattr(docagent_cli, "_build_indexed_retriever", fail_build_indexed_retriever)

    payload = docagent_cli._run_local_fact_qa(
        repository=object(),
        trace_repository=None,
        db_path=tmp_path / "docagent.db",
        document_root=tmp_path,
        doc_id="doc1",
        question="What financial year is mentioned?",
        router_plan={"task_type": "local_fact_qa"},
        dry_run=False,
        run_id="run1",
        retriever_mode="hybrid_rerank",
        answer_policy=SimpleNamespace(mode="base"),
    )

    assert payload["status"] == "error"
    assert payload["error"]["type"] == "retriever_initialization_failed"
    assert payload["answer_policy_mode"] == "base"
    assert payload["used_qwen_answer_policy"] is False
    assert payload["used_external_answer_api"] is False


def test_doc_id_document_statistics_routes_to_deterministic_tools(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "How many pages and tables are in this document?",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "document_statistics"
    assert payload["router_plan"]["task_type"] == "document_statistics"
    assert set(payload["tools_used"]) == {"count_pages", "count_tables"}
    assert "2 pages" in payload["answer"]
    assert Path(payload["artifact_dir"], "summary.json").is_file()
    summary = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["used_external_api"] is False
    assert summary["used_vlm"] is False
    assert summary["used_training"] is False
    assert summary["used_full_e2e"] is False


def test_doc_id_page_lookup_returns_page_text(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "Show the text from page 1.",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "page_lookup"
    assert payload["tools_used"] == ["get_page_text"]
    assert "Invoice Date" in payload["answer"]
    assert payload["citations"][0]["page"] == 1


def test_doc_id_page_lookup_missing_page_returns_structured_error(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "Show page 99.",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "error"
    assert payload["task_type"] == "page_lookup"
    assert payload["error"]["type"] == "page_not_found"
    json.dumps(payload)


def test_doc_id_local_fact_qa_dry_run_returns_unified_json(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "What is the invoice date?",
        "--dry-run",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "local_fact_qa"
    assert payload["tools_used"] == ["local_fact_qa"]
    assert payload["answer"] == ""
    assert payload["answer_policy_mode"] == "heuristic"
    assert payload["used_qwen_answer_policy"] is False
    assert payload["used_external_answer_api"] is False
    assert payload["retrieval_candidate_count"] == len(payload["supporting_evidence_ids"])
    assert payload["citation_count"] == len(payload["citations"])
    assert "dry_run_no_answer_generated" in payload["warnings"]
    assert payload["supporting_evidence_ids"]


def test_doc_id_local_fact_qa_can_use_configured_hybrid_rerank_retriever(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--document-root",
        str(tmp_path / "documents"),
        "--doc-id",
        "doc1",
        "--question",
        "What is the invoice date?",
        "--retriever-mode",
        "hybrid_rerank",
        "--dense-backend",
        "hash",
        "--build-dense-index-if-missing",
        "--reranker-backend",
        "keyword",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "local_fact_qa"
    assert payload["retriever_mode"] == "hybrid_rerank"
    assert payload["retriever"]["uses_dense"] is True
    assert payload["retriever"]["uses_reranker"] is True
    assert payload["retriever"]["dense"]["backend"] == "hash"
    assert payload["retriever"]["reranker"]["backend"] == "keyword"
    assert any(step.get("step") == "retrieve_evidence" for step in payload["workflow_trace"])

    summary = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["retriever_mode"] == "hybrid_rerank"
    assert summary["used_dense_retrieval"] is True
    assert summary["used_reranker"] is True
    trace = json.loads(Path(payload["artifact_dir"], "trace.json").read_text(encoding="utf-8"))
    assert trace["retriever"]["mode"] == "hybrid_rerank"
    assert any(step.get("step") == "retrieve_evidence" for step in trace["workflow_trace"])


def test_hybrid_rerank_retriever_metadata_save_failure_is_non_blocking(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)
    conn = connect(db_path)
    repository = DocumentRepository(conn)

    def fail_save_index_metadata(**_kwargs):
        raise RuntimeError("metadata database is temporarily locked")

    repository.save_index_metadata = fail_save_index_metadata  # type: ignore[method-assign]

    try:
        retriever, metadata = docagent_cli._build_indexed_retriever(
            repository=repository,
            doc_id="doc1",
            document_root=tmp_path / "documents",
            mode="hybrid_rerank",
            dense_backend="hash",
            dense_model_path="",
            dense_device="cpu",
            dense_fp16=False,
            build_dense_index_if_missing=True,
            reranker_backend="keyword",
            reranker_model_path="",
            reranker_device="cpu",
            reranker_fp16=False,
            query_plan=None,
        )
        result = retriever.retrieve(doc_id="doc1", question="What is the invoice date?", top_k=2)
    finally:
        conn.close()

    assert metadata["mode"] == "hybrid_rerank"
    assert metadata["dense"]["backend"] == "hash"
    assert metadata["dense"]["repository_metadata_save_error"]["type"] == "RuntimeError"
    assert metadata["uses_dense"] is True
    assert metadata["uses_reranker"] is True
    assert result.candidates


def test_bge_retriever_rebuilds_stale_legacy_dense_index(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = _repository_with_document(tmp_path)
    conn = connect(db_path)
    repository = DocumentRepository(conn)
    blocks = repository.load_evidence_blocks("doc1")
    index_dir = tmp_path / "documents" / "doc1"
    stale_embeddings = np.zeros((len(blocks), 2), dtype=np.float32)
    stale_embeddings[:, 0] = 1.0
    DenseIndex(
        blocks=blocks,
        embeddings=stale_embeddings,
        model_id="stale-model",
        backend="numpy",
    ).save(index_dir)

    class FakeDenseEncoder:
        model_id = "/models/current-bge"

        def __init__(self, _config):
            pass

        def encode_documents(self, texts):
            array = np.zeros((len(texts), 3), dtype=np.float32)
            for index in range(len(texts)):
                array[index, index % 3] = 1.0
            return array

        def encode_queries(self, texts):
            array = np.zeros((len(texts), 3), dtype=np.float32)
            array[:, 0] = 1.0
            return array

    monkeypatch.setattr(docagent_cli, "DenseEncoder", FakeDenseEncoder)

    try:
        retriever, metadata = docagent_cli._build_indexed_retriever(
            repository=repository,
            doc_id="doc1",
            document_root=tmp_path / "documents",
            mode="hybrid_rerank",
            dense_backend="bge",
            dense_model_path="/models/current-bge",
            dense_device="cpu",
            dense_fp16=False,
            build_dense_index_if_missing=True,
            reranker_backend="keyword",
            reranker_model_path="",
            reranker_device="cpu",
            reranker_fp16=False,
            query_plan=None,
        )
        result = retriever.retrieve(doc_id="doc1", question="What is the invoice date?", top_k=2)
    finally:
        conn.close()

    model_metadata = index_dir / f"index_metadata_{docagent_cli._safe_model_id('/models/current-bge')}.json"
    assert metadata["dense"]["index_built"] is True
    assert metadata["dense"]["legacy_index_reused"] is False
    assert metadata["dense"]["stale_legacy_index_model_id"] == "stale-model"
    assert model_metadata.is_file()
    assert result.candidates


def test_local_fact_qa_retriever_initialization_failure_keeps_planner_diagnostics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = _repository_with_document(tmp_path)
    conn = connect(db_path)
    repository = DocumentRepository(conn)
    trace_repository = TraceRepository(conn)

    def fail_build_retriever(**_kwargs):
        raise RuntimeError("dense index artifact is corrupt")

    monkeypatch.setattr(docagent_cli, "_build_indexed_retriever", fail_build_retriever)

    try:
        payload = docagent_cli._run_local_fact_qa(
            repository=repository,
            trace_repository=trace_repository,
            db_path=db_path,
            document_root=tmp_path / "documents",
            doc_id="doc1",
            question="What is the invoice date?",
            router_plan={"task_type": "local_fact_qa"},
            dry_run=False,
            run_id="retriever_failure_keeps_diagnostics",
            enable_query_planning=True,
            query_planner_mode="rule",
            retriever_mode="hybrid_rerank",
            dense_backend="hash",
            dense_model_path="",
            dense_device="cpu",
            dense_fp16=False,
            build_dense_index_if_missing=True,
            reranker_backend="keyword",
            reranker_model_path="",
            reranker_device="cpu",
            reranker_fp16=False,
            answer_policy=HeuristicAnswerPolicy(),
        )
    finally:
        conn.close()

    assert payload["status"] == "error"
    assert payload["error"]["type"] == "retriever_initialization_failed"
    assert payload["error"]["cause"]["message"] == "dense index artifact is corrupt"
    assert payload["query_planner"]["enabled"] is True
    assert payload["query_planner_execution"]["query_planner_mode"] == "rule"
    assert payload["retriever"]["mode"] == "hybrid_rerank"
    assert payload["retriever"]["requested_mode"] == "hybrid_rerank"
    assert payload["retriever"]["uses_dense"] is True
    assert payload["retriever"]["uses_reranker"] is True
    assert payload["retriever"]["initialization_status"] == "failed"


def test_full_model_path_missing_llm_config_returns_structured_error(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "What is the invoice date?",
        "--full-model-path",
        "--router-llm-env-file",
        str(tmp_path / "missing-router.env"),
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "error"
    assert payload["error"]["type"] == "llm_planning_config_missing"
    assert payload["full_model_path"] is True
    assert "full_model_path_requires_llm_planning_config" in payload["warnings"]
    assert payload["answer_policy_mode"] == "heuristic"
    summary = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["full_model_path"] is True
    assert summary["used_llm_router"] is False
    assert summary["used_llm_query_rewriter"] is False


def test_file_argument_missing_file_returns_structured_error(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)
    file_path = tmp_path / "missing.pdf"

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--file",
        str(file_path),
        "--question",
        "What is this document about?",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "error"
    assert payload["error"]["type"] == "file_not_found"
    assert payload["source"]["was_ingested"] is False
    assert payload["source"]["reused_existing"] is False
    assert payload["router_plan"] == {}
    assert Path(payload["artifact_dir"], "result.json").is_file()


def test_document_summary_question_runs_summary_tool(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "Summarize this document.",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "document_summary"
    assert payload["router_plan"]["selected_tools"] == ["document_summary"]
    assert payload["tools_used"] == ["document_summary"]
    assert payload["summary"]["key_points"]
    assert payload["citations"]
    assert payload["error"] == {}


def test_structured_extraction_dates_runs_deterministic_tool(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "List all dates mentioned in this document.",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "structured_extraction"
    assert payload["router_plan"]["selected_tools"] == ["extract_all_dates"]
    assert payload["tools_used"] == ["extract_all_dates"]
    assert payload["structured_result"]["item_count"] >= 1
    assert payload["structured_result"]["counts_by_type"]["date"] >= 1
    assert any(item["value"] == "March 12, 2020" for item in payload["structured_result"]["items"])
    assert payload["citations"]
    assert Path(payload["artifact_dir"], "trace.json").is_file()


def test_structured_extraction_tables_runs_deterministic_tool(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "Extract all tables from this document.",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "structured_extraction"
    assert payload["router_plan"]["selected_tools"] == ["extract_all_tables"]
    assert payload["tools_used"] == ["extract_all_tables"]
    assert payload["structured_result"]["counts_by_type"]["table"] == 1
    assert payload["structured_result"]["items"][0]["block_id"] == "doc1_p001_table"
    assert payload["citations"][0]["block_id"] == "doc1_p001_table"


def test_table_lookup_question_returns_value_with_citation(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "What was the revenue in 2020?",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "table_lookup_or_calculation"
    assert payload["tools_used"] == ["table_lookup"]
    assert "10" in payload["answer"]
    assert payload["reasoning_summary"]
    assert payload["evidence_used"][0]["doc_id"] == "doc1"
    assert payload["citations"][0]["block_id"] == "doc1_p001_table"
    assert payload["citations"][0]["block_type"] == "table"
    assert payload["citations"][0]["table_caption"] == "Annual revenue"


def test_table_calculation_question_returns_traceable_result(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        tmp_path,
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "What is the difference between 2020 and 2021 revenue?",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["status"] == "success"
    assert payload["task_type"] == "table_lookup_or_calculation"
    assert payload["tools_used"] == ["table_lookup", "simple_calculation"]
    assert "5" in payload["answer"]
    assert payload["structured_result"]["operation"] == "simple_calculation"
    assert payload["structured_result"]["calculation"]["expression"] == "15.0 - 10.0"
    assert payload["citations"][0]["block_id"] == "doc1_p001_table"

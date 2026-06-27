from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from docagent.ingestion.document_registry import DocumentRecord
from docagent.retrieval.hybrid_retriever import HybridRetriever
from docagent.retrieval.query_fusion import fuse_queries
from docagent.retrieval.query_generator_rule import generate_rule_queries
from docagent.retrieval.query_planner import plan_queries
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository


ROOT = Path(__file__).resolve().parents[1]


class FakeLLMClient:
    def __init__(self, response: str | list[str]) -> None:
        self.responses = [response] if isinstance(response, str) else list(response)
        self.calls: list[dict] = []

    def complete(self, *, system_prompt: str, user_payload: dict):
        self.calls.append({"system_prompt": system_prompt, "user_payload": user_payload})
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]


def test_rule_extractor_page_question_generates_page_query() -> None:
    queries = generate_rule_queries("Show the text from page 1.", task_type="page_lookup")

    assert "page 1" in queries
    assert "text page 1" in queries


def test_rule_extractor_table_question_generates_table_query() -> None:
    queries = generate_rule_queries("What is the revenue in the table?", task_type="table_lookup_or_calculation")

    assert any(query.startswith("table") for query in queries)
    assert any("revenue" in query for query in queries)


def test_rule_extractor_statistics_question_generates_metadata_query() -> None:
    queries = generate_rule_queries("How many pages are in this document?", task_type="document_statistics")

    assert any(query.startswith("metadata") for query in queries)
    assert any(query.startswith("document statistics") for query in queries)


def test_mock_llm_valid_json_list_is_used_in_hybrid_plan() -> None:
    fake = FakeLLMClient('["cancer incidence Africa", "mortality rate Africa cancer"]')

    plan = plan_queries(
        question="What is this document about?",
        task_type="local_fact_qa",
        document_profile={"page_count": 2, "table_count": 1, "image_count": 0},
        mode="hybrid",
        llm_client=fake,
    )

    assert fake.calls
    assert fake.calls[0]["user_payload"] == {"question": "What is this document about?"}
    assert "task_type" not in fake.calls[0]["user_payload"]
    assert "document_profile" not in fake.calls[0]["user_payload"]
    assert "rule_queries" not in fake.calls[0]["user_payload"]
    assert "3 to 5" in fake.calls[0]["system_prompt"]
    assert "Do not repeat the original question as a query" in fake.calls[0]["system_prompt"]
    assert plan.llm_status == "used"
    assert "cancer incidence Africa" in plan.llm_queries
    assert plan.llm_retry_count == 0
    assert len(plan.llm_attempts) == 1
    assert plan.final_queries[: len(plan.rule_queries)] == plan.rule_queries[: len(plan.final_queries)]
    assert plan.query_sources["rule"]
    assert "cancer incidence Africa" in plan.query_sources["llm"]
    assert "cancer incidence Africa" in plan.llm_unique_queries
    assert plan.llm_added_unique_query_count == len(plan.llm_unique_queries)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ('["invoice date", "financial year"]', ["invoice date", "financial year"]),
        ('```json\n["invoice date", "financial year"]\n```', ["invoice date", "financial year"]),
        ('Here are the retrieval queries:\n["invoice date", "financial year"]', ["invoice date", "financial year"]),
        ('{"queries": ["invoice date", "financial year"]}', ["invoice date", "financial year"]),
        ('{"final_queries": ["invoice date", "financial year"]}', ["invoice date", "financial year"]),
        ('{"retrieval_queries": ["invoice date", "financial year"]}', ["invoice date", "financial year"]),
    ],
)
def test_llm_query_expander_parses_supported_output_formats(response: str, expected: list[str]) -> None:
    plan = _plan_with_llm_response(response)

    assert plan.llm_status == "used"
    assert plan.llm_queries == expected
    assert plan.final_queries[: len(plan.rule_queries)] == plan.rule_queries[: len(plan.final_queries)]
    assert all(query in plan.final_queries for query in expected)


def test_llm_query_expander_rejects_echoed_router_like_payload() -> None:
    echoed = json.dumps(
        {
            "question": "What is the invoice date?",
            "task_type": "local_fact_qa",
            "document_profile": {"page_count": 5, "table_count": 0, "image_count": 0},
            "rule_queries": ["what is the invoice date", "What is the invoice date?"],
        }
    )

    plan = _plan_with_llm_response(echoed)

    assert plan.llm_status == "echoed_payload"
    assert plan.llm_error_type == "query_planner_llm_echoed_payload"
    assert plan.llm_queries == []
    assert "query_planner_llm_echoed_payload" in plan.warnings
    assert plan.final_queries == plan.rule_queries[: len(plan.final_queries)]


def test_llm_query_expander_parses_loose_query_object() -> None:
    response = json.dumps(
        {
            "question": "latest invoice date",
            "invoice issue date query": "invoice date field retrieval",
        }
    )

    plan = _plan_with_llm_response(response)
    payload = plan.to_dict()

    assert plan.llm_status == "used"
    assert payload["llm_error_type"] == ""
    assert plan.llm_queries == ["latest invoice date", "invoice date field retrieval"]
    assert "query_planner_llm_loose_object_parsed" in plan.llm_normalization_warnings
    assert plan.final_queries[: len(plan.rule_queries)] == plan.rule_queries[: len(plan.final_queries)]
    assert all(query in plan.final_queries for query in plan.llm_queries)


def test_llm_query_expander_warns_when_llm_only_repeats_rule_query() -> None:
    plan = _plan_with_llm_response('["What is the invoice date?"]')
    payload = plan.to_dict()

    assert plan.llm_status == "used"
    assert plan.llm_retry_count == 1
    assert len(payload["llm_attempts"]) == 2
    assert plan.llm_queries == ["What is the invoice date?"]
    assert plan.query_sources["llm"] == []
    assert payload["llm_unique_queries"] == []
    assert payload["llm_duplicate_queries"] == ["What is the invoice date?"]
    assert payload["llm_added_unique_query_count"] == 0
    assert "query_planner_llm_no_unique_queries" in plan.warnings


def test_llm_query_expander_retries_duplicate_first_attempt_and_uses_unique_retry() -> None:
    fake = FakeLLMClient(
        [
            '{"queries": ["What is the invoice date?"]}',
            '{"queries": ["invoice issue date", "billing date", "date field"]}',
        ]
    )

    plan = plan_queries(
        question="What is the invoice date?",
        task_type="local_fact_qa",
        mode="hybrid",
        llm_client=fake,
    )
    payload = plan.to_dict()

    assert len(fake.calls) == 2
    assert fake.calls[0]["user_payload"] == {"question": "What is the invoice date?"}
    assert fake.calls[1]["user_payload"] == {
        "question": "What is the invoice date?",
        "avoid_exact_queries": ["what is the invoice date", "What is the invoice date?"],
    }
    assert "task_type" not in fake.calls[1]["user_payload"]
    assert "document_profile" not in fake.calls[1]["user_payload"]
    assert "RouterPlan" not in fake.calls[1]["user_payload"]
    assert "avoid_exact_queries" in fake.calls[1]["system_prompt"]
    assert plan.llm_retry_count == 1
    assert payload["llm_attempts"][0]["duplicate_queries"] == ["What is the invoice date?"]
    assert payload["llm_attempts"][0]["unique_queries"] == []
    assert payload["llm_attempts"][1]["unique_queries"] == ["invoice issue date", "billing date", "date field"]
    assert plan.llm_queries == ["invoice issue date", "billing date", "date field"]
    assert plan.query_sources["llm"] == ["invoice issue date", "billing date", "date field"]
    assert plan.llm_added_unique_query_count == 3
    assert "query_planner_llm_no_unique_queries" not in plan.warnings


def test_llm_query_expander_warns_when_retry_is_still_duplicate() -> None:
    fake = FakeLLMClient(
        [
            '{"queries": ["What is the invoice date?"]}',
            '{"queries": ["what is the invoice date?"]}',
        ]
    )

    plan = plan_queries(
        question="What is the invoice date?",
        task_type="local_fact_qa",
        mode="hybrid",
        llm_client=fake,
    )
    payload = plan.to_dict()

    assert len(fake.calls) == 2
    assert plan.llm_retry_count == 1
    assert plan.query_sources["llm"] == []
    assert payload["llm_unique_queries"] == []
    assert payload["llm_duplicate_queries"] == ["what is the invoice date?"]
    assert payload["llm_added_unique_query_count"] == 0
    assert "query_planner_llm_no_unique_queries" in plan.warnings


def test_llm_query_expander_records_unique_queries_added_by_fusion() -> None:
    plan = _plan_with_llm_response('["invoice issue date", "billing date"]')
    payload = plan.to_dict()

    assert plan.llm_status == "used"
    assert plan.query_sources["llm"] == ["invoice issue date", "billing date"]
    assert payload["llm_unique_queries"] == ["invoice issue date", "billing date"]
    assert payload["llm_duplicate_queries"] == []
    assert payload["llm_added_unique_query_count"] == 2
    assert payload["llm_retry_count"] == 0
    assert len(payload["llm_attempts"]) == 1
    assert plan.final_queries[: len(plan.rule_queries)] == plan.rule_queries[: len(plan.final_queries)]
    assert plan.final_queries[-2:] == ["invoice issue date", "billing date"]


def test_llm_query_expander_does_not_parse_context_object_as_loose_queries() -> None:
    response = json.dumps(
        {
            "document_profile": {"page_count": 5},
            "rule_queries": ["what is the invoice date"],
        }
    )

    plan = _plan_with_llm_response(response)

    assert plan.llm_status == "echoed_payload"
    assert plan.llm_error_type == "query_planner_llm_echoed_payload"
    assert plan.llm_queries == []
    assert plan.final_queries == plan.rule_queries[: len(plan.final_queries)]


def test_llm_query_expander_filters_non_strings_and_dedups() -> None:
    plan = _plan_with_llm_response('["invoice date", 123, "", "Invoice Date", "```bad```", "financial year"]')

    assert plan.llm_status == "used"
    assert plan.llm_queries == ["invoice date", "financial year"]
    assert "query_planner_llm_non_string_filtered" in plan.llm_normalization_warnings
    assert "query_planner_llm_empty_query_filtered" in plan.llm_normalization_warnings
    assert "query_planner_llm_duplicate_query_filtered" in plan.llm_normalization_warnings
    assert "query_planner_llm_markdown_query_filtered" in plan.llm_normalization_warnings


def test_llm_query_expander_limits_and_truncates_queries() -> None:
    long_query = "x" * 240
    response = json.dumps([long_query, *[f"query {index}" for index in range(20)]])

    plan = _plan_with_llm_response(response)

    assert len(plan.llm_queries) == 8
    assert len(plan.llm_queries[0]) == 200
    assert "query_planner_llm_query_truncated" in plan.llm_normalization_warnings


def test_llm_query_diagnostics_redact_sensitive_preview() -> None:
    response = 'api_key=sk-secretvalue token=my-token Authorization: Bearer bearer-secret\n["invoice date"]'

    plan = _plan_with_llm_response(response)
    payload = plan.to_dict()

    assert plan.llm_status == "used"
    assert payload["llm_parsed_queries_preview"] == ["invoice date"]
    preview = payload["llm_raw_response_preview"]
    assert "sk-secretvalue" not in preview
    assert "my-token" not in preview
    assert "bearer-secret" not in preview
    attempt_preview = payload["llm_attempts"][0]["raw_response_preview"]
    assert "sk-secretvalue" not in attempt_preview
    assert "my-token" not in attempt_preview
    assert "bearer-secret" not in attempt_preview
    assert len(preview) <= 1000


def test_invalid_json_falls_back_to_rule_queries() -> None:
    fake = FakeLLMClient("not json")

    plan = plan_queries(
        question="What is the invoice date?",
        task_type="local_fact_qa",
        mode="hybrid",
        llm_client=fake,
    )

    assert plan.llm_queries == []
    assert plan.final_queries == plan.rule_queries[: len(plan.final_queries)]
    assert "query_planner_llm_invalid_output" in plan.warnings
    assert plan.llm_error_type == "query_planner_llm_invalid_output"


def test_empty_llm_response_falls_back_to_rule_queries() -> None:
    fake = FakeLLMClient("[]")

    plan = plan_queries(
        question="What is the invoice date?",
        task_type="local_fact_qa",
        mode="llm",
        llm_client=fake,
    )

    assert plan.final_queries == plan.rule_queries[: len(plan.final_queries)]
    assert "query_planner_fallback_rule_queries" in plan.warnings
    assert "query_planner_llm_empty_queries" in plan.warnings


def test_llm_mode_uses_only_llm_queries_when_successful() -> None:
    plan = plan_queries(
        question="What is the invoice date?",
        task_type="local_fact_qa",
        mode="llm",
        llm_client=FakeLLMClient('["invoice date", "billing date"]'),
    )

    assert plan.final_queries == ["invoice date", "billing date"]
    assert plan.query_sources["rule"] == []
    assert plan.query_sources["llm"] == ["invoice date", "billing date"]


def test_rule_mode_does_not_call_llm() -> None:
    fake = FakeLLMClient('["invoice date"]')

    plan = plan_queries(
        question="What is the invoice date?",
        task_type="local_fact_qa",
        mode="rule",
        llm_client=fake,
    )

    assert fake.calls == []
    assert plan.llm_status == "skipped"
    assert plan.llm_queries == []
    assert plan.final_queries == plan.rule_queries[: len(plan.final_queries)]
    assert plan.query_sources["llm"] == []


def test_query_fusion_dedups_limits_and_preserves_rule_priority() -> None:
    fused = fuse_queries(
        ["page 1", "revenue", "Revenue"],
        ["mortality", "page 1", "incidence", "extra1", "extra2", "extra3", "extra4", "extra5"],
        limit=4,
    )

    assert fused == ["page 1", "revenue", "mortality", "incidence"]


def test_hybrid_retriever_uses_query_plan_for_multi_query_bm25() -> None:
    blocks = [
        _block("b1", "Invoice Date: March 12, 2020"),
        _block("b2", "Payment terms are due on receipt."),
    ]
    plan = plan_queries(
        question="When is payment due?",
        task_type="local_fact_qa",
        mode="hybrid",
        llm_client=FakeLLMClient('["payment terms due receipt"]'),
    )

    result = HybridRetriever(blocks).retrieve_result(
        doc_id="doc1",
        question="When is payment due?",
        top_k=1,
        mode="bm25",
        query_plan=plan,
    )

    assert result.candidates[0].block.block_id == "b2"
    assert result.metadata["query_planner"]["final_queries"] == plan.final_queries


def test_cli_query_planner_disabled_by_default(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
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

    assert "query_planner" not in payload
    summary = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["used_query_planning"] is False


def test_cli_hybrid_query_planner_records_rule_fallback_when_llm_unconfigured(tmp_path: Path) -> None:
    db_path = _repository_with_document(tmp_path)

    payload = _run_cli(
        "--db-path",
        str(db_path),
        "--doc-id",
        "doc1",
        "--question",
        "What is the invoice date?",
        "--dry-run",
        "--enable-query-planning",
        "--query-planner-mode",
        "hybrid",
        "--output-dir",
        str(tmp_path / "cli"),
    )

    assert payload["query_planner"]["enabled"] is True
    assert payload["query_planner"]["mode"] == "hybrid"
    assert payload["query_planner"]["rule_queries"]
    assert payload["query_planner"]["final_queries"]
    assert payload["query_planner"]["llm_status"] == "not_configured"
    assert "query_planning_enabled" in payload["warnings"]
    summary = json.loads(Path(payload["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["used_query_planning"] is True
    assert summary["query_planner_mode"] == "hybrid"


def _block(block_id: str, text: str) -> EvidenceBlock:
    return EvidenceBlock(
        doc_id="doc1",
        block_id=block_id,
        block_type="text",
        text=text,
        page_id=1,
        location=EvidenceLocation(page=1, block_id=block_id),
    )


def _plan_with_llm_response(response: str):
    return plan_queries(
        question="What is the invoice date?",
        task_type="local_fact_qa",
        mode="hybrid",
        llm_client=FakeLLMClient(response),
    )


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
            page_count=1,
            parser_backend="mineru_existing",
            parse_status="parsed",
            index_status="not_started",
        )
    )
    repository.save_evidence_blocks(
        [
            _block("doc1_p001_date", "Invoice Date: March 12, 2020"),
            _block("doc1_p001_payment", "Payment terms are due on receipt."),
        ]
    )
    conn.close()
    return db_path


def _run_cli(*args: str) -> dict:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("DOCAGENT_ROUTER_LLM_")
    }
    completed = subprocess.run(
        [sys.executable, "scripts/docagent_cli.py", *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
    output = completed.stdout.strip()
    assert output.startswith("{")
    assert output.endswith("}")
    return json.loads(output)

from __future__ import annotations

import json
from pathlib import Path

from docagent.ingestion.document_registry import DocumentRecord
from docagent.router.llm_client import load_router_llm_config
from docagent.router.llm_router import plan_route_with_optional_llm
from docagent.schemas import EvidenceBlock, EvidenceLocation
from docagent.storage.db import connect
from docagent.storage.repositories import DocumentRepository
from scripts import docagent_cli


AVAILABLE_TOOLS = [
    "local_fact_qa",
    "count_pages",
    "count_blocks",
    "count_tables",
    "count_images",
    "get_page_text",
    "list_pages",
]


class FakeRouterLLMClient:
    def __init__(self, response: str):
        self.response = response
        self.calls: list[dict] = []

    def complete(self, *, system_prompt: str, user_payload: dict) -> str:
        self.calls.append({"system_prompt": system_prompt, "user_payload": user_payload})
        return self.response


def _payload(question: str, *, allow_llm: bool = False) -> dict:
    return {
        "doc_id": "doc1",
        "question": question,
        "available_tools": AVAILABLE_TOOLS,
        "document_profile": {
            "page_count": 2,
            "block_count": 5,
            "table_count": 1,
            "image_count": 0,
            "has_ocr": True,
            "has_tables": True,
            "has_images": False,
        },
        "options": {
            "allow_external_llm_router": allow_llm,
            "prefer_deterministic_tools": True,
            "max_tool_calls": 4,
        },
    }


def _decision_json(**overrides) -> str:
    payload = {
        "task_type": "local_fact_qa",
        "query_rewrite": "invoice date",
        "selected_tools": ["local_fact_qa"],
    }
    payload.update(overrides)
    return json.dumps(payload)


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
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_page",
                block_type="page",
                text="Invoice Date: March 12, 2020.",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_page"),
            ),
            EvidenceBlock(
                doc_id="doc1",
                block_id="doc1_p001_text",
                block_type="text",
                text="Invoice Date: March 12, 2020.",
                page_id=1,
                location=EvidenceLocation(page=1, block_id="doc1_p001_text"),
            ),
        ]
    )
    conn.close()
    return db_path


def test_default_rule_only_does_not_call_llm() -> None:
    fake_client = FakeRouterLLMClient(_decision_json())

    result = plan_route_with_optional_llm(_payload("Tell me about it"), llm_client=fake_client)

    assert fake_client.calls == []
    assert result["router_source"] == "rule"
    assert "llm_router_disabled" in result["warnings"]


def test_high_confidence_document_statistics_does_not_call_llm_even_with_high_threshold() -> None:
    fake_client = FakeRouterLLMClient(_decision_json(task_type="local_fact_qa"))

    result = plan_route_with_optional_llm(
        _payload("How many pages are in this document?", allow_llm=True),
        threshold=0.99,
        llm_client=fake_client,
    )

    assert fake_client.calls == []
    assert result["router_source"] == "rule"
    assert result["task_type"] == "document_statistics"


def test_missing_llm_config_returns_structured_not_configured() -> None:
    result = plan_route_with_optional_llm(_payload("Tell me about it", allow_llm=True), env={})

    assert result["router_source"] == "rule_after_llm_failure"
    assert "llm_router_not_configured" in result["warnings"]
    assert result["llm_router"]["status"] == "not_configured"
    assert result["llm_router"]["error"]["type"] == "llm_router_not_configured"


def test_router_llm_env_file_is_loaded_without_key_in_repr(tmp_path: Path) -> None:
    env_file = tmp_path / "router_llm.env"
    env_file.write_text(
        "\n".join(
            [
                "DOCAGENT_ROUTER_LLM_API_KEY=fake-secret-key",
                "DOCAGENT_ROUTER_LLM_BASE_URL=https://example.test/compatible-mode/v1",
                "DOCAGENT_ROUTER_LLM_MODEL=fake-router-model",
                "DOCAGENT_ROUTER_LLM_TIMEOUT_SECONDS=12",
            ]
        ),
        encoding="utf-8",
    )

    config, warnings = load_router_llm_config(env_file=env_file, env={})

    assert warnings == []
    assert config is not None
    assert config.api_key == "fake-secret-key"
    assert config.model == "fake-router-model"
    assert config.timeout_seconds == 12
    assert "fake-secret-key" not in repr(config)
    assert config.masked_api_key() == "fake...-key"


def test_missing_router_llm_env_file_does_not_use_global_env(tmp_path: Path) -> None:
    config, warnings = load_router_llm_config(
        env_file=tmp_path / "missing.env",
        env={
            "DOCAGENT_ROUTER_LLM_API_KEY": "global-fake-key",
            "DOCAGENT_ROUTER_LLM_BASE_URL": "https://example.test/compatible-mode/v1",
            "DOCAGENT_ROUTER_LLM_MODEL": "global-model",
        },
    )

    assert config is None
    assert "llm_router_env_file_not_found" in warnings
    assert "llm_router_not_configured" in warnings


def test_valid_mock_llm_output_can_replace_low_confidence_rule_plan() -> None:
    fake_client = FakeRouterLLMClient(_decision_json())

    result = plan_route_with_optional_llm(
        _payload("Tell me about it", allow_llm=True),
        llm_client=fake_client,
    )

    assert result["router_source"] == "llm_fallback"
    assert result["task_type"] == "local_fact_qa"
    assert result["selected_tools"] == ["local_fact_qa"]
    assert result["requires_retrieval"] is True
    assert result["requires_visual_understanding"] is False
    assert result["confidence"] == 0.65
    assert "llm_router_used" in result["warnings"]
    assert "llm_router_confidence_defaulted" in result["warnings"]
    assert result["llm_router"]["normalization_warnings"] == ["llm_router_confidence_defaulted"]
    assert fake_client.calls[0]["user_payload"]["question"] == "Tell me about it"
    assert "document_text" not in fake_client.calls[0]["user_payload"]


def test_llm_task_type_only_canonicalizes_full_router_plan() -> None:
    fake_client = FakeRouterLLMClient(json.dumps({"task_type": "local_fact_qa"}))

    result = plan_route_with_optional_llm(
        _payload("Tell me about it", allow_llm=True),
        llm_client=fake_client,
    )

    assert result["router_source"] == "llm_fallback"
    assert result["task_type"] == "local_fact_qa"
    assert result["selected_tools"] == ["local_fact_qa"]
    assert result["requires_retrieval"] is True
    assert result["target_evidence_types"] == ["text", "table"]
    assert result["reason"].startswith("LLM fallback selected")
    assert "llm_router_selected_tools_inferred" in result["warnings"]


def test_llm_task_type_and_query_rewrite_passes_without_selected_tools() -> None:
    fake_client = FakeRouterLLMClient(json.dumps({"task_type": "local_fact_qa", "query_rewrite": "invoice date"}))

    result = plan_route_with_optional_llm(
        _payload("Tell me about it", allow_llm=True),
        llm_client=fake_client,
    )

    assert result["router_source"] == "llm_fallback"
    assert result["query_rewrite"] == "invoice date"
    assert result["selected_tools"] == ["local_fact_qa"]


def test_confidence_string_percent_and_labels_are_normalized() -> None:
    cases = [
        ("0.8", 0.8),
        ("80%", 0.8),
        ("high", 0.85),
        ("medium", 0.65),
        ("low", 0.35),
    ]
    for raw_confidence, expected in cases:
        fake_client = FakeRouterLLMClient(_decision_json(confidence=raw_confidence))

        result = plan_route_with_optional_llm(
            _payload("Tell me about it", allow_llm=True),
            llm_client=fake_client,
        )

        assert result["router_source"] == "llm_fallback"
        assert result["confidence"] == expected
        assert "llm_router_validation_failed" not in result["warnings"]


def test_unparseable_confidence_warns_without_validation_failure() -> None:
    fake_client = FakeRouterLLMClient(_decision_json(confidence="very sure"))

    result = plan_route_with_optional_llm(
        _payload("Tell me about it", allow_llm=True),
        llm_client=fake_client,
    )

    assert result["router_source"] == "llm_fallback"
    assert result["confidence"] == 0.65
    assert "llm_router_confidence_ignored" in result["warnings"]
    assert result["llm_router"]["validation_errors"] == []


def test_fenced_json_and_explanatory_text_are_extracted() -> None:
    responses = [
        '```json\n{"task_type": "local_fact_qa"}\n```',
        'Routing decision follows:\n{"task_type": "local_fact_qa", "query_rewrite": "date"}\nDone.',
        '```json\n{"task_type": "local_fact_qa"}\n```\nDone.',
    ]
    for response in responses:
        fake_client = FakeRouterLLMClient(response)

        result = plan_route_with_optional_llm(
            _payload("Tell me about it", allow_llm=True),
            llm_client=fake_client,
        )

        assert result["router_source"] == "llm_fallback"
        assert result["task_type"] == "local_fact_qa"


def test_invalid_mock_llm_json_falls_back_to_rule_plan() -> None:
    fake_client = FakeRouterLLMClient("not json")

    result = plan_route_with_optional_llm(
        _payload("Tell me about it", allow_llm=True),
        llm_client=fake_client,
    )

    assert result["router_source"] == "rule_after_llm_failure"
    assert "llm_router_invalid_json" in result["warnings"]
    assert result["llm_router"]["status"] == "invalid_json"
    assert result["llm_router"]["raw_response_preview"] == "not json"


def test_mock_llm_illegal_task_type_fails_validation_and_falls_back() -> None:
    fake_client = FakeRouterLLMClient(json.dumps({"task_type": "visual_pixel_qa"}))

    result = plan_route_with_optional_llm(
        _payload("Tell me about it", allow_llm=True),
        llm_client=fake_client,
    )

    assert result["router_source"] == "rule_after_llm_failure"
    assert "llm_router_validation_failed" in result["warnings"]
    assert "unsupported_task_type" in result["llm_router"]["validation_errors"]


def test_mock_llm_unavailable_tool_can_fallback_to_inferred_tool() -> None:
    fake_client = FakeRouterLLMClient(_decision_json(selected_tools=["missing_tool"]))

    result = plan_route_with_optional_llm(
        _payload("Tell me about it", allow_llm=True),
        llm_client=fake_client,
    )

    assert result["router_source"] == "llm_fallback"
    assert result["selected_tools"] == ["local_fact_qa"]
    assert "llm_router_selected_tools_unavailable" in result["warnings"]


def test_mock_llm_unavailable_tool_fails_when_no_fallback_tool_exists() -> None:
    fake_client = FakeRouterLLMClient(_decision_json(task_type="document_statistics", selected_tools=["missing_tool"]))
    payload = _payload("Tell me about it", allow_llm=True)
    payload["available_tools"] = ["local_fact_qa"]

    result = plan_route_with_optional_llm(payload, llm_client=fake_client)

    assert result["router_source"] == "rule_after_llm_failure"
    assert "llm_router_validation_failed" in result["warnings"]
    assert "selected_tool_unavailable" in result["llm_router"]["validation_errors"]


def test_mock_llm_cannot_enable_visual_understanding() -> None:
    fake_client = FakeRouterLLMClient(_decision_json(requires_visual_understanding=True))

    result = plan_route_with_optional_llm(
        _payload("Tell me about it", allow_llm=True),
        llm_client=fake_client,
    )

    assert result["router_source"] == "rule_after_llm_failure"
    assert "visual_understanding_not_allowed" in result["llm_router"]["validation_errors"]


def test_llm_router_diagnostics_redact_sensitive_preview() -> None:
    fake_client = FakeRouterLLMClient(
        '{"task_type": "local_fact_qa", "query_rewrite": "Authorization: Bearer secret-token token=abc api_key=xyz"}'
    )

    result = plan_route_with_optional_llm(
        _payload("Tell me about it", allow_llm=True),
        llm_client=fake_client,
    )

    preview = result["llm_router"]["parsed_decision_preview"]["query_rewrite"]
    raw_preview = result["llm_router"]["raw_response_preview"]
    assert "secret-token" not in preview
    assert "token=abc" not in preview
    assert "api_key=xyz" not in preview
    assert "secret-token" not in raw_preview
    assert "token=abc" not in raw_preview
    assert "api_key=xyz" not in raw_preview


def test_visual_boundary_does_not_call_llm() -> None:
    fake_client = FakeRouterLLMClient(_decision_json(requires_visual_understanding=True))

    result = plan_route_with_optional_llm(
        _payload("What does the chart color mean?", allow_llm=True),
        llm_client=fake_client,
    )

    assert fake_client.calls == []
    assert result["router_source"] == "rule"
    assert "visual_understanding_unsupported" in result["warnings"]


def test_cli_without_allow_llm_router_passes_rule_only_option(tmp_path: Path, monkeypatch) -> None:
    db_path = _repository_with_document(tmp_path)
    captured: dict = {}

    def fake_plan_route(payload: dict, **kwargs) -> dict:
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return {
            "task_type": "document_statistics",
            "selected_tools": ["count_pages"],
            "requires_retrieval": False,
            "requires_full_scan": False,
            "requires_table_tool": False,
            "requires_calculation": False,
            "requires_visual_understanding": False,
            "target_evidence_types": ["metadata"],
            "query_rewrite": "",
            "confidence": 0.95,
            "reason": "fake rule plan",
            "fallback_used": False,
            "warnings": [],
            "router_source": "rule",
        }

    monkeypatch.setattr(docagent_cli, "plan_route_with_optional_llm", fake_plan_route)
    args = docagent_cli.build_parser().parse_args(
        [
            "--execution-profile",
            "self_test",
            "--db-path",
            str(db_path),
            "--doc-id",
            "doc1",
            "--question",
            "How many pages are in this document?",
            "--output-dir",
            str(tmp_path / "cli"),
        ]
    )

    result = docagent_cli.run_cli(args)

    assert result["status"] == "success"
    assert captured["payload"]["options"]["allow_external_llm_router"] is False
    assert result["router_plan"]["router_source"] == "rule"


def test_cli_allow_llm_router_records_router_source(tmp_path: Path, monkeypatch) -> None:
    db_path = _repository_with_document(tmp_path)
    env_file = tmp_path / "router_llm.env"
    env_file.write_text("DOCAGENT_ROUTER_LLM_API_KEY=fake\n", encoding="utf-8")
    captured: dict = {}

    def fake_plan_route(payload: dict, **kwargs) -> dict:
        captured["payload"] = payload
        captured["kwargs"] = kwargs
        return {
            "task_type": "document_statistics",
            "selected_tools": ["count_pages"],
            "requires_retrieval": False,
            "requires_full_scan": False,
            "requires_table_tool": False,
            "requires_calculation": False,
            "requires_visual_understanding": False,
            "target_evidence_types": ["metadata"],
            "query_rewrite": "",
            "confidence": 0.9,
            "reason": "fake llm fallback plan",
            "fallback_used": True,
            "warnings": ["llm_router_used"],
            "router_source": "llm_fallback",
            "llm_router": {"status": "used"},
        }

    monkeypatch.setattr(docagent_cli, "plan_route_with_optional_llm", fake_plan_route)
    args = docagent_cli.build_parser().parse_args(
        [
            "--execution-profile",
            "self_test",
            "--db-path",
            str(db_path),
            "--doc-id",
            "doc1",
            "--question",
            "Tell me about it",
            "--output-dir",
            str(tmp_path / "cli"),
            "--allow-llm-router",
            "--router-llm-threshold",
            "0.8",
            "--router-llm-model",
            "fake-model",
            "--router-llm-env-file",
            str(env_file),
        ]
    )

    result = docagent_cli.run_cli(args)

    assert result["status"] == "success"
    assert captured["payload"]["options"]["allow_external_llm_router"] is True
    assert captured["kwargs"]["threshold"] == 0.8
    assert captured["kwargs"]["env_file"] == env_file
    assert captured["kwargs"]["model_override"] == "fake-model"
    assert result["router_plan"]["router_source"] == "llm_fallback"
    summary = json.loads(Path(result["artifact_dir"], "summary.json").read_text(encoding="utf-8"))
    assert summary["used_external_api"] is True

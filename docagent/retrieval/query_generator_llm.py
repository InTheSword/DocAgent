from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from docagent.router.llm_client import OpenAICompatibleRouterClient, RouterLLMError, load_router_llm_config


SYSTEM_PROMPT = """You are a query planning assistant for document retrieval.

Your task is to rewrite a user question into multiple retrieval queries.

Rules:
- Output ONLY a JSON array of strings.
- Do NOT explain.
- Do NOT answer the question.
- Do NOT include reasoning.
- Each query must be short and search-oriented.
- Focus on keywords for retrieval.

Example output:
["cancer incidence Africa", "Africa cancer statistics 2022", "mortality rate Africa cancer"]"""


def generate_llm_queries(
    *,
    question: str,
    task_type: str,
    document_profile: Mapping[str, Any] | None,
    rule_queries: list[str],
    llm_client: Any | None = None,
    env_file: Path | None = None,
    model_override: str | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    """Return LLM-expanded retrieval queries and structured diagnostics."""
    diagnostics: dict[str, Any] = {
        "status": "not_started",
        "warnings": [],
        "error": {},
    }
    if llm_client is None:
        config, warnings = load_router_llm_config(env_file=env_file, env=env, model_override=model_override)
        if config is None:
            diagnostics["status"] = "not_configured"
            diagnostics["warnings"] = warnings or ["query_planner_llm_not_configured"]
            diagnostics["error"] = {
                "type": "query_planner_llm_not_configured",
                "message": "Router LLM config is incomplete; using rule queries only.",
            }
            return [], diagnostics
        llm_client = OpenAICompatibleRouterClient(config)

    payload = {
        "question": question,
        "task_type": task_type,
        "document_profile": _light_profile(document_profile or {}),
        "rule_queries": list(rule_queries),
    }
    try:
        raw = llm_client.complete(system_prompt=SYSTEM_PROMPT, user_payload=payload)
    except RouterLLMError as exc:
        diagnostics["status"] = "api_error"
        diagnostics["warnings"] = ["query_planner_llm_api_error"]
        diagnostics["error"] = {"type": "query_planner_llm_api_error", "message": str(exc)}
        return [], diagnostics

    queries = _parse_json_string_array(raw)
    if not queries:
        diagnostics["status"] = "invalid_output"
        diagnostics["warnings"] = ["query_planner_llm_invalid_output"]
        diagnostics["error"] = {
            "type": "query_planner_llm_invalid_output",
            "message": "Query planner LLM did not return a non-empty JSON array of strings.",
        }
        return [], diagnostics

    diagnostics["status"] = "used"
    return queries, diagnostics


def _parse_json_string_array(raw: str) -> list[str]:
    try:
        payload = json.loads(str(raw or "").strip())
    except json.JSONDecodeError:
        return []
    if not isinstance(payload, list):
        return []
    result = []
    for item in payload:
        if not isinstance(item, str):
            continue
        normalized = " ".join(item.split()).strip()
        if normalized:
            result.append(normalized)
    return result


def _light_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: profile.get(key)
        for key in ("page_count", "table_count", "image_count")
        if key in profile
    }

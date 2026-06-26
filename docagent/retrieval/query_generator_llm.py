from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

from docagent.router.llm_client import OpenAICompatibleRouterClient, RouterLLMError, load_router_llm_config


RAW_RESPONSE_PREVIEW_LIMIT = 1000
MAX_LLM_QUERIES = 8
MAX_QUERY_CHARS = 200
QUERY_OBJECT_KEYS = ("queries", "final_queries", "retrieval_queries")

SYSTEM_PROMPT = """You are a retrieval query generator.

Rules:
- Output ONLY a JSON array of strings.
- Do NOT output Markdown.
- Do NOT explain.
- Do NOT answer the question.
- Do NOT include reasoning.
- Each query must be short, search-oriented, and preserve key terms.

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
        "llm_error_type": None,
        "llm_raw_response_preview": "",
        "llm_parsed_queries_preview": [],
        "llm_normalization_warnings": [],
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
            diagnostics["llm_error_type"] = "query_planner_llm_not_configured"
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
        diagnostics["llm_error_type"] = "query_planner_llm_api_error"
        return [], diagnostics

    diagnostics["llm_raw_response_preview"] = _safe_preview(raw)
    queries, normalization_warnings = _parse_query_response(raw)
    diagnostics["llm_normalization_warnings"] = normalization_warnings
    diagnostics["llm_parsed_queries_preview"] = [_safe_preview(query) for query in queries[:MAX_LLM_QUERIES]]
    if not queries:
        diagnostics["status"] = "invalid_output"
        diagnostics["warnings"] = ["query_planner_llm_invalid_output"]
        diagnostics["error"] = {
            "type": "query_planner_llm_invalid_output",
            "message": "Query planner LLM did not return a non-empty JSON array of strings.",
        }
        diagnostics["llm_error_type"] = "query_planner_llm_invalid_output"
        return [], diagnostics

    diagnostics["status"] = "used"
    return queries, diagnostics


def _parse_query_response(raw: str) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    payload = _extract_first_json_payload(str(raw or ""))
    if payload is None:
        return [], warnings

    if not isinstance(payload, list):
        if not isinstance(payload, dict):
            return [], warnings
        for key in QUERY_OBJECT_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                payload = value
                warnings.append(f"query_planner_llm_used_{key}")
                break
        else:
            return [], warnings
    return _clean_queries(payload, warnings), warnings


def _extract_first_json_payload(raw: str) -> Any | None:
    candidates = []
    stripped = raw.strip()
    if stripped:
        candidates.append(stripped)
    fenced = _strip_markdown_fence(stripped)
    if fenced and fenced != stripped:
        candidates.append(fenced)
    candidates.extend(_json_snippets(raw))

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None


def _strip_markdown_fence(text: str) -> str:
    match = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", text.strip(), flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else text


def _json_snippets(text: str) -> list[str]:
    snippets: list[str] = []
    for index, char in enumerate(text):
        if char not in "[{":
            continue
        snippet = _balanced_json_from(text, index)
        if snippet:
            snippets.append(snippet)
    return snippets


def _balanced_json_from(text: str, start: int) -> str:
    stack: list[str] = []
    in_string = False
    escape = False
    pairs = {"[": "]", "{": "}"}
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
            continue
        if char in pairs:
            stack.append(pairs[char])
            continue
        if stack and char == stack[-1]:
            stack.pop()
            if not stack:
                return text[start : index + 1]
    return ""


def _clean_queries(items: list[Any], warnings: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, str):
            warnings.append("query_planner_llm_non_string_filtered")
            continue
        normalized = " ".join(item.split()).strip()
        if not normalized:
            warnings.append("query_planner_llm_empty_query_filtered")
            continue
        if "```" in normalized:
            warnings.append("query_planner_llm_markdown_query_filtered")
            continue
        if len(normalized) > MAX_QUERY_CHARS:
            normalized = normalized[:MAX_QUERY_CHARS].rstrip()
            warnings.append("query_planner_llm_query_truncated")
        key = normalized.casefold()
        if key in seen:
            warnings.append("query_planner_llm_duplicate_query_filtered")
            continue
        result.append(normalized)
        seen.add(key)
        if len(result) >= MAX_LLM_QUERIES:
            break
    return result


def _safe_preview(value: Any) -> str:
    text = str(value)
    redactions = [
        (r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;}]+", r"\1***"),
        (r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,;}]+", r"\1***"),
        (r"(?i)(token\s*[:=]\s*)[^\s,;}]+", r"\1***"),
        (r"(?i)(bearer\s+)[a-z0-9._-]+", r"\1***"),
        (r"(?i)(sk-[a-z0-9_-]{6,})", "***"),
    ]
    for pattern, replacement in redactions:
        text = re.sub(pattern, replacement, text)
    return text[:RAW_RESPONSE_PREVIEW_LIMIT]


def _light_profile(profile: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: profile.get(key)
        for key in ("page_count", "table_count", "image_count")
        if key in profile
    }

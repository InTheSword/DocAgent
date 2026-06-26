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
ECHO_PAYLOAD_KEYS = {
    "question",
    "task_type",
    "document_profile",
    "rule_queries",
    "available_tools",
    "router_plan",
    "selected_tools",
}

SYSTEM_PROMPT = """You are a Query Rewriter in a document retrieval system.

Your task is to rewrite the user question into multiple short retrieval queries.

Rules:
- Output ONLY a JSON array of strings.
- Do NOT output a JSON object.
- Do NOT output Markdown.
- Do NOT explain.
- Do NOT answer the question.
- Do NOT include reasoning.
- Do NOT repeat the input payload.
- Each query must be short, specific, suitable for BM25 / dense retrieval, and preserve key terms.

Example output:
["cancer incidence Africa", "Africa cancer statistics 2022", "mortality rate Africa cancer"]"""


def generate_llm_queries(
    *,
    question: str,
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

    payload = {"question": question}
    try:
        raw = llm_client.complete(system_prompt=SYSTEM_PROMPT, user_payload=payload)
    except RouterLLMError as exc:
        diagnostics["status"] = "api_error"
        diagnostics["warnings"] = ["query_planner_llm_api_error"]
        diagnostics["error"] = {"type": "query_planner_llm_api_error", "message": str(exc)}
        diagnostics["llm_error_type"] = "query_planner_llm_api_error"
        return [], diagnostics

    diagnostics["llm_raw_response_preview"] = _safe_preview(raw)
    queries, normalization_warnings, output_error_type = _parse_query_response(raw)
    diagnostics["llm_normalization_warnings"] = normalization_warnings
    diagnostics["llm_parsed_queries_preview"] = [_safe_preview(query) for query in queries[:MAX_LLM_QUERIES]]
    if not queries:
        error_type = output_error_type or "query_planner_llm_invalid_output"
        diagnostics["status"] = "echoed_payload" if error_type == "query_planner_llm_echoed_payload" else "invalid_output"
        diagnostics["warnings"] = [error_type]
        diagnostics["error"] = {
            "type": error_type,
            "message": _error_message(error_type),
        }
        diagnostics["llm_error_type"] = error_type
        return [], diagnostics

    diagnostics["status"] = "used"
    return queries, diagnostics


def _parse_query_response(raw: str) -> tuple[list[str], list[str], str | None]:
    warnings: list[str] = []
    payload = _extract_first_json_payload(str(raw or ""))
    if payload is None:
        return [], warnings, "query_planner_llm_invalid_output"

    if not isinstance(payload, list):
        if not isinstance(payload, dict):
            return [], warnings, "query_planner_llm_invalid_output"
        if _looks_like_echo_payload(payload):
            warnings.append("query_planner_llm_echoed_payload")
            return [], warnings, "query_planner_llm_echoed_payload"
        for key in QUERY_OBJECT_KEYS:
            value = payload.get(key)
            if isinstance(value, list):
                payload = value
                warnings.append(f"query_planner_llm_used_{key}")
                break
        else:
            return [], warnings, "query_planner_llm_invalid_output"
    queries = _clean_queries(payload, warnings)
    if not queries:
        return [], warnings, "query_planner_llm_empty_queries"
    return queries, warnings, None


def _looks_like_echo_payload(payload: Mapping[str, Any]) -> bool:
    keys = set(payload.keys())
    if any(key in keys for key in QUERY_OBJECT_KEYS):
        return False
    return bool(keys & ECHO_PAYLOAD_KEYS)


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


def _error_message(error_type: str) -> str:
    messages = {
        "query_planner_llm_echoed_payload": "Query rewriter echoed the input payload; using rule queries only.",
        "query_planner_llm_empty_queries": "Query rewriter returned no usable query strings; using rule queries only.",
        "query_planner_llm_invalid_output": "Query rewriter did not return a valid JSON array of strings.",
    }
    return messages.get(error_type, "Query rewriter output could not be used; using rule queries only.")

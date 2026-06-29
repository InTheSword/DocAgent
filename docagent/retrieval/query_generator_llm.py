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
ECHO_STRONG_CONTEXT_KEYS = {"document_profile", "rule_queries", "router_plan", "available_tools", "selected_tools"}
ECHO_ROUTER_KEYS = {"question", "task_type", "document_profile", "rule_queries", "available_tools", "router_plan", "selected_tools"}
LOOSE_OBJECT_SKIP_KEYS = {
    "task_type",
    "document_profile",
    "rule_queries",
    "available_tools",
    "router_plan",
    "selected_tools",
}
QUERY_LIKE_KEY_RE = re.compile(r"\b(query|search|retrieval|keyword|date|invoice|field)\b", flags=re.IGNORECASE)
EXPLANATION_RE = re.compile(r"\b(here are|the following|i have|this query|these queries|because|explanation)\b", flags=re.IGNORECASE)

SYSTEM_PROMPT = """You are a query rewriter for a document retrieval system.

Return ONLY a valid JSON object with exactly one key: "queries".
The value must be an array of 3 to 5 short retrieval query strings.

Rules:
- Do not answer the question.
- Do not explain.
- Do not use Markdown.
- Do not repeat the original question as a query.
- Each query must be keyword-like and suitable for BM25 / dense retrieval.
- Generate semantically useful alternatives using key phrases, synonyms, field names, dates, amounts, entities, or topic terms.
- If the question is not in English, include English translation keyword queries suitable for English OCR text.
- Do not output question, task_type, document_profile, rule_queries, tools, retrieved evidence, OCR text, or document content.

Bad:
{"queries": ["What date or financial year is mentioned in the shareholder notice about unclaimed dividend?"]}

Good:
{"queries": ["unclaimed dividend financial year", "shareholder notice unclaimed dividend", "unpaid dividend transfer date", "financial year dividend notice"]}"""

REPAIR_SYSTEM_PROMPT = """You are a query rewriter for a document retrieval system.

Return ONLY a valid JSON object with exactly one key: "queries".
The value must be an array of 3 to 5 short retrieval query strings.

Rules:
- Generate retrieval queries that are NOT identical or near-identical to avoid_exact_queries.
- Use short keyword phrases, not full questions.
- Do not answer the question.
- Do not explain.
- Do not use Markdown.
- Each query must be keyword-like and suitable for BM25 / dense retrieval.
- If the question is not in English, return English translation keyword queries and avoid only same-language paraphrases.
- Return only {"queries": [...]}.
- Do not output question, task_type, document_profile, rule_queries, tools, retrieved evidence, OCR text, or document content.

Bad:
{"queries": ["What date or financial year is mentioned in the shareholder notice about unclaimed dividend?"]}

Good:
{"queries": ["unclaimed dividend financial year", "shareholder notice unclaimed dividend", "unpaid dividend transfer date", "financial year dividend notice"]}"""


def generate_llm_queries(
    *,
    question: str,
    avoid_exact_queries: list[str] | None = None,
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

    payload: dict[str, Any] = {"question": question}
    if avoid_exact_queries:
        payload["avoid_exact_queries"] = list(dict.fromkeys(str(item) for item in avoid_exact_queries if str(item).strip()))
    system_prompt = REPAIR_SYSTEM_PROMPT if payload.get("avoid_exact_queries") else SYSTEM_PROMPT
    try:
        raw = llm_client.complete(system_prompt=system_prompt, user_payload=payload)
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
            payload = _loose_object_queries(payload, warnings)
    queries = _clean_queries(payload, warnings)
    if not queries:
        return [], warnings, "query_planner_llm_empty_queries"
    return queries, warnings, None


def _looks_like_echo_payload(payload: Mapping[str, Any]) -> bool:
    keys = set(payload.keys())
    if any(key in keys for key in QUERY_OBJECT_KEYS):
        return False
    if keys & ECHO_STRONG_CONTEXT_KEYS:
        return True
    router_like_count = len(keys & ECHO_ROUTER_KEYS)
    return router_like_count >= 2 and "task_type" in keys


def _loose_object_queries(payload: Mapping[str, Any], warnings: list[str]) -> list[str]:
    queries: list[str] = []
    for key, value in payload.items():
        key_text = str(key or "").strip()
        collected_value = False
        if key_text in LOOSE_OBJECT_SKIP_KEYS:
            warnings.append("query_planner_llm_context_field_ignored")
            continue
        if isinstance(value, str):
            value_text = " ".join(value.split()).strip()
            if value_text and not _looks_explanatory(value_text):
                queries.append(value_text)
                collected_value = True
        elif isinstance(value, list):
            warnings.append("query_planner_llm_nested_list_ignored")
        elif isinstance(value, Mapping):
            warnings.append("query_planner_llm_nested_object_ignored")
        if not collected_value and QUERY_LIKE_KEY_RE.search(key_text) and key_text not in LOOSE_OBJECT_SKIP_KEYS:
            if key_text and not _looks_explanatory(key_text):
                queries.append(key_text)
    if queries:
        warnings.append("query_planner_llm_loose_object_parsed")
    return queries


def _looks_explanatory(text: str) -> bool:
    if EXPLANATION_RE.search(text):
        return True
    return len(text.split()) > 16


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
        "query_planner_llm_invalid_output": "Query rewriter did not return a valid query list.",
    }
    return messages.get(error_type, "Query rewriter output could not be used; using rule queries only.")

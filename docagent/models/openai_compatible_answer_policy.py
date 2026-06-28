from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from docagent.models.base import GenerationError, GenerationResult
from docagent.models.output_parser import parse_generation_output
from docagent.schemas import EvidenceBlock
from docagent.workflow.prompts import compile_answer_prompt, fallback_chat_prompt


@dataclass(frozen=True)
class OpenAICompatibleAnswerPolicyConfig:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: float = 60.0
    temperature: float = 0.0
    max_tokens: int = 1024
    max_reason_chars: int | None = 300
    append_no_think: bool = True
    max_chars_per_block: int = 1200
    max_total_chars: int | None = None
    rank_aware_context: bool = False


class OpenAICompatibleAnswerPolicy:
    mode = "openai_compatible"

    def __init__(self, config: OpenAICompatibleAnswerPolicyConfig) -> None:
        self.config = config

    def generate(
        self,
        *,
        question: str,
        evidence_blocks: list[EvidenceBlock],
        tool_results: list[dict[str, Any]] | None = None,
        answer_type: str | None = None,
        qid: str | None = None,
    ) -> GenerationResult:
        if not self.config.api_key:
            raise GenerationError("OpenAI-compatible answer API key is missing")
        start = time.perf_counter()
        bundle = compile_answer_prompt(
            question=question,
            evidence_blocks=evidence_blocks,
            tool_results=tool_results,
            answer_type=answer_type,
            append_no_think=self.config.append_no_think,
            max_chars_per_block=self.config.max_chars_per_block,
            max_total_chars=self.config.max_total_chars,
            rank_aware_context=self.config.rank_aware_context,
        )
        response = self._post_chat_completions(
            {
                "model": self.config.model,
                "messages": bundle.messages,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
            }
        )
        try:
            choice = response["choices"][0]
            message = choice.get("message") or {}
            raw_text = str(message.get("content") or "")
            finish_reason = choice.get("finish_reason")
        except (KeyError, IndexError, TypeError) as exc:
            raise GenerationError("OpenAI-compatible answer response missing choices[0].message.content") from exc
        parse_result = parse_generation_output(raw_text, max_reason_chars=self.config.max_reason_chars)
        usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
        prompt_text = fallback_chat_prompt(bundle.messages)
        return GenerationResult(
            raw_text=raw_text,
            parsed=parse_result.parsed,
            prompt_text=prompt_text,
            prompt_token_count=_optional_int(usage.get("prompt_tokens")) or len(prompt_text.split()),
            completion_token_count=_optional_int(usage.get("completion_tokens")),
            finish_reason=str(finish_reason or ""),
            latency_ms=(time.perf_counter() - start) * 1000,
            metadata={
                "policy_mode": self.mode,
                "provider": self.mode,
                "model": self.config.model,
                "qid": qid,
                "parse_result": parse_result.to_dict(),
                "temperature": self.config.temperature,
                "timeout_seconds": self.config.timeout_seconds,
                "base_url_host": masked_base_url(self.config.base_url),
                **bundle.metadata,
            },
        )

    def _post_chat_completions(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            _chat_completions_url(self.config.base_url),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            preview = exc.read().decode("utf-8", errors="replace")[:500]
            raise GenerationError(f"OpenAI-compatible answer API HTTP {exc.code}: {preview}") from exc
        except Exception as exc:
            raise GenerationError(f"OpenAI-compatible answer API request failed: {exc}") from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise GenerationError("OpenAI-compatible answer API returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise GenerationError("OpenAI-compatible answer API returned non-object JSON")
        return parsed


def masked_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}"


def _chat_completions_url(base_url: str) -> str:
    trimmed = base_url.rstrip("/")
    if trimmed.endswith("/chat/completions"):
        return trimmed
    return f"{trimmed}/chat/completions"


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None

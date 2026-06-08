from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from docagent.schemas import EvidenceBlock
from docagent.workflow.answer_policy import heuristic_answer
from docagent.workflow.prompts import build_answer_messages, fallback_chat_prompt


@dataclass
class GenerationResult:
    raw_text: str
    parsed: dict[str, Any] | None
    prompt_text: str
    prompt_token_count: int | None
    completion_token_count: int | None
    finish_reason: str | None
    latency_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


class AnswerPolicy(Protocol):
    mode: str

    def generate(
        self,
        *,
        question: str,
        evidence_blocks: list[EvidenceBlock],
        tool_results: list[dict[str, Any]] | None = None,
        answer_type: str | None = None,
        qid: str | None = None,
    ) -> GenerationResult:
        ...


class AnswerPolicyError(RuntimeError):
    pass


class ModelLoadError(AnswerPolicyError):
    pass


class GenerationError(AnswerPolicyError):
    pass


class HeuristicAnswerPolicy:
    mode = "heuristic"

    def generate(
        self,
        *,
        question: str,
        evidence_blocks: list[EvidenceBlock],
        tool_results: list[dict[str, Any]] | None = None,
        answer_type: str | None = None,
        qid: str | None = None,
    ) -> GenerationResult:
        start = time.perf_counter()
        messages = build_answer_messages(
            question=question,
            evidence_blocks=evidence_blocks,
            tool_results=tool_results,
            answer_type=answer_type,
        )
        prompt_text = fallback_chat_prompt(messages)
        parsed = heuristic_answer(question, evidence_blocks)
        raw_text = json.dumps(parsed, ensure_ascii=False)
        return GenerationResult(
            raw_text=raw_text,
            parsed=parsed,
            prompt_text=prompt_text,
            prompt_token_count=len(prompt_text.split()),
            completion_token_count=len(raw_text.split()),
            finish_reason="heuristic",
            latency_ms=(time.perf_counter() - start) * 1000,
            metadata={"policy_mode": self.mode, "qid": qid},
        )

from __future__ import annotations

from typing import Any

from docagent.models.base import AnswerPolicy, HeuristicAnswerPolicy
from docagent.models.qwen_answer_policy import QwenAnswerPolicy, QwenAnswerPolicyConfig


def build_answer_policy(config: dict[str, Any]) -> AnswerPolicy:
    backend = str(config.get("backend", "heuristic"))
    if backend == "heuristic":
        return HeuristicAnswerPolicy()
    if backend == "qwen":
        return QwenAnswerPolicy(QwenAnswerPolicyConfig(**{key: value for key, value in config.items() if key != "backend"}))
    raise ValueError(f"unsupported answer policy backend: {backend}")

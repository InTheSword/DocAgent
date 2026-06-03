from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from docagent.rewards.combined import docqa_reward

try:
    from swift.plugin import ORM, orms
except ModuleNotFoundError:  # Allows local syntax and unit-style checks without ms-swift.
    class ORM:  # type: ignore[no-redef]
        pass

    orms: dict[str, Any] = {}


def _item(values: Any, index: int, default: Any = None) -> Any:
    if isinstance(values, list):
        return values[index] if index < len(values) else default
    return values if values is not None else default


def _json_loads_maybe(value: Any, default: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str):
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def extract_json_object(text: str) -> dict[str, Any] | None:
    text = str(text).strip()
    if "</think>" in text:
        text = text.rsplit("</think>", maxsplit=1)[-1].strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            parsed, _ = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


class DocAgentDocQAReward(ORM):
    def __call__(self, completions: list[str], **kwargs: Any) -> list[float]:
        rewards: list[float] = []
        for index, completion in enumerate(completions):
            prediction = extract_json_object(completion)
            if prediction is None:
                rewards.append(0.0)
                continue

            gold_answer = _item(kwargs.get("gold_answer"), index, "")
            gold_location = _json_loads_maybe(_item(kwargs.get("gold_location"), index, {}), {})
            answer_type = str(_item(kwargs.get("answer_type"), index, "extractive") or "extractive")
            rewards.append(float(docqa_reward(prediction, gold_answer, gold_location, answer_type)))
        return rewards


orms["docagent_docqa"] = DocAgentDocQAReward

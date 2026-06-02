from __future__ import annotations

import re
from collections import Counter


def normalize_text(text: str) -> str:
    text = str(text).lower().strip()
    text = re.sub(r"[^a-z0-9\u4e00-\u9fff.%+-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def exact_match(prediction: str, gold: str) -> bool:
    return normalize_text(prediction) == normalize_text(gold)


def token_f1(prediction: str, gold: str) -> float:
    pred_tokens = normalize_text(prediction).split()
    gold_tokens = normalize_text(gold).split()
    if not pred_tokens or not gold_tokens:
        return 0.0
    overlap = Counter(pred_tokens) & Counter(gold_tokens)
    num_same = sum(overlap.values())
    if num_same == 0:
        return 0.0
    precision = num_same / len(pred_tokens)
    recall = num_same / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def _to_number(value: str) -> float | None:
    match = re.search(r"-?\(?\$?\d[\d,]*(?:\.\d+)?%?\)?", str(value))
    if not match:
        return None
    raw = match.group(0)
    negative = raw.startswith("(") and raw.endswith(")")
    raw = raw.replace("$", "").replace(",", "").replace("(", "").replace(")", "")
    percent = raw.endswith("%")
    raw = raw.rstrip("%")
    try:
        number = float(raw)
    except ValueError:
        return None
    if negative:
        number = -number
    if percent:
        return number
    return number


def numeric_match(prediction: str, gold: str, tolerance: float = 1e-3) -> bool:
    pred_num = _to_number(prediction)
    gold_num = _to_number(gold)
    if pred_num is None or gold_num is None:
        return False
    return abs(pred_num - gold_num) <= tolerance * max(abs(gold_num), 1.0)


from __future__ import annotations

from typing import Any


def location_reward(predicted: dict[str, Any], gold: dict[str, Any] | None) -> float:
    if not gold:
        return 0.0
    for key in ("page", "block_id", "table_id"):
        if gold.get(key) is not None and predicted.get(key) == gold.get(key):
            return 1.0
    return 0.0


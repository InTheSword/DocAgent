from __future__ import annotations


def recall_at_k(rankings: list[list[str]], gold_ids: list[set[str]], k: int = 5) -> float:
    if not rankings:
        return 0.0
    hits = 0
    for ranking, gold in zip(rankings, gold_ids):
        hits += int(bool(set(ranking[:k]) & gold))
    return hits / len(rankings)


def mrr_at_k(rankings: list[list[str]], gold_ids: list[set[str]], k: int = 5) -> float:
    if not rankings:
        return 0.0
    total = 0.0
    for ranking, gold in zip(rankings, gold_ids):
        for idx, block_id in enumerate(ranking[:k], start=1):
            if block_id in gold:
                total += 1.0 / idx
                break
    return total / len(rankings)


from __future__ import annotations


def normalize_query(query: str) -> str:
    return " ".join(str(query or "").split()).strip()


def fuse_queries(
    rule_queries: list[str],
    llm_queries: list[str],
    *,
    limit: int = 8,
) -> list[str]:
    """Deduplicate retrieval queries while preserving rule-query priority."""
    fused: list[str] = []
    seen: set[str] = set()
    for query in [*rule_queries, *llm_queries]:
        normalized = normalize_query(query)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        fused.append(normalized)
        seen.add(key)
        if len(fused) >= limit:
            break
    return fused

"""Outcome-aware rank adjustment; outcomes are metadata, not proof of quality."""

from rag.variants.v2_hybrid import retrieve as hybrid_retrieve


def retrieve(query: str, index: list[dict], k: int = 5):
    ranked = hybrid_retrieve(query, index, k=max(k, min(len(index), 20)))
    adjusted = []
    for item, score in ranked:
        outcome = str(item.get("outcome", "")).lower()
        bonus = 0.15 if any(word in outcome for word in ("won", "replied", "hired")) else 0
        adjusted.append((item, score + bonus))
    return sorted(adjusted, key=lambda row: row[1], reverse=True)[:k]

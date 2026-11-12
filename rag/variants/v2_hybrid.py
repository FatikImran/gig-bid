"""BM25-style lexical ranking fused with token-cosine ranking."""

from __future__ import annotations

import math
import re
from collections import Counter


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9+#.]+", text.lower())


def _text(item: dict) -> str:
    return " ".join(
        str(item.get(field, "")) for field in ("title", "summary", "source", "outcome", "skills")
    )


def retrieve(query: str, index: list[dict], k: int = 5):
    if k < 1:
        raise ValueError("k must be positive")
    query_terms = _tokens(query)
    if not query_terms:
        return []
    documents = [_tokens(_text(item)) for item in index]
    query_counts = Counter(query_terms)
    avg_len = sum(map(len, documents)) / max(1, len(documents))
    df = Counter(term for doc in documents for term in set(doc))
    scored: list[tuple[dict, float, float]] = []
    for item, doc in zip(index, documents):
        counts = Counter(doc)
        bm25 = 0.0
        for term, query_count in query_counts.items():
            frequency = counts[term]
            if frequency:
                idf = math.log(1 + (len(documents) - df[term] + 0.5) / (df[term] + 0.5))
                bm25 += (
                    query_count
                    * idf
                    * frequency
                    * 2.2
                    / (frequency + 1.2 * (0.25 + 0.75 * len(doc) / max(1, avg_len)))
                )
        cosine = sum(min(query_counts[t], counts[t]) for t in query_counts) / math.sqrt(
            max(1, sum(query_counts.values()) * len(doc))
        )
        scored.append((item, bm25, cosine))
    bm_order = {
        str(item.get("evidence_id")): rank
        for rank, (item, _, _) in enumerate(
            sorted(scored, key=lambda row: row[1], reverse=True), start=1
        )
    }
    cosine_order = {
        str(item.get("evidence_id")): rank
        for rank, (item, _, _) in enumerate(
            sorted(scored, key=lambda row: row[2], reverse=True), start=1
        )
    }
    fused = []
    for item, _, _ in scored:
        key = str(item.get("evidence_id"))
        score = 1 / (60 + bm_order[key]) + 1 / (60 + cosine_order[key])
        fused.append((item, score))
    return sorted(fused, key=lambda row: row[1], reverse=True)[:k]

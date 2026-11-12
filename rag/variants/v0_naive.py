"""Reproducible token-vector cosine baseline.

This dependency-free baseline is lexical rather than neural; the limitation is
reported in the data card and evaluation results.
"""

from __future__ import annotations

import math
import re
from collections import Counter


def _tokens(text: str) -> Counter[str]:
    return Counter(re.findall(r"[a-z0-9+#.]+", text.lower()))


def _document(item: dict) -> str:
    return " ".join(
        str(item.get(field, "")) for field in ("title", "summary", "source", "outcome", "skills")
    )


def retrieve(query: str, index: list[dict], k: int = 5):
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if k < 1:
        raise ValueError("k must be positive")
    query_vector = _tokens(query)
    query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
    results = []
    for item in index:
        document_vector = _tokens(_document(item))
        document_norm = math.sqrt(sum(value * value for value in document_vector.values()))
        dot = sum(value * document_vector.get(term, 0) for term, value in query_vector.items())
        score = dot / (query_norm * document_norm) if query_norm and document_norm else 0.0
        results.append((item, score))
    return sorted(results, key=lambda row: row[1], reverse=True)[:k]

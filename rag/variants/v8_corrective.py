"""Corrective retrieval with an explicit low-evidence result."""

from rag.variants.v2_hybrid import retrieve as hybrid_retrieve


def retrieve(query: str, index: list[dict], k: int = 5, minimum_score: float = 0.01):
    ranked = hybrid_retrieve(query, index, k)
    return [(item, score) for item, score in ranked if score >= minimum_score]

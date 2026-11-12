"""Requirement-decomposed retrieval using deterministic token overlap."""

from __future__ import annotations

from typing import Any

from rag.variants.v0_naive import retrieve


def retrieve_requirements(requirements: list[str], index: list[dict[str, Any]], k: int = 5):
    ranked: dict[str, tuple[dict[str, Any], float]] = {}
    for requirement in requirements:
        for rank, (item, score) in enumerate(retrieve(requirement, index, k), start=1):
            evidence_id = str(item.get("evidence_id", ""))
            previous = ranked.get(evidence_id)
            combined = score + 1.0 / rank
            if previous is None or combined > previous[1]:
                ranked[evidence_id] = (item, combined)
    return sorted(ranked.values(), key=lambda pair: pair[1], reverse=True)[:k]

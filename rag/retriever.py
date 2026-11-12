from __future__ import annotations

from collections.abc import Callable
from typing import Any

from rag.variants.v0_naive import retrieve as v0
from rag.variants.v1_decomposed import retrieve_requirements as v1
from rag.variants.v2_hybrid import retrieve as v2
from rag.variants.v3_reranked import retrieve as v3
from rag.variants.v4_outcome import retrieve as v4
from rag.variants.v8_corrective import retrieve as v8

VARIANTS: dict[str, Callable[..., list[tuple[dict[str, Any], float]]]] = {
    "V0": v0,
    "V2": v2,
    "V3": v3,
    "V4": v4,
    "V8": v8,
}


def retrieve(
    variant: str,
    query: str,
    evidence: list[dict[str, Any]],
    k: int = 5,
    requirements: list[str] | None = None,
) -> list[tuple[dict[str, Any], float]]:
    if variant == "V1":
        return v1(requirements or [query], evidence, k)
    if variant not in VARIANTS:
        raise ValueError(f"Unknown RAG variant: {variant}")
    return VARIANTS[variant](query, evidence, k)

from __future__ import annotations

import re
from typing import Any

_WORD = re.compile(r"[a-z0-9+#.]+", re.IGNORECASE)
_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "can",
    "for",
    "from",
    "have",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "our",
    "the",
    "this",
    "to",
    "with",
    "you",
    "your",
}


def _terms(text: str) -> set[str]:
    return {word.lower() for word in _WORD.findall(text) if word.lower() not in _STOPWORDS}


def verify_claims(draft: str, evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Classify sentences against portfolio evidence without treating retrieval as proof."""
    if not isinstance(draft, str):
        raise TypeError("draft must be a string")
    if not isinstance(evidence, list):
        raise TypeError("evidence must be a list")
    checks = []
    for sentence in (part.strip() for part in re.split(r"(?<=[.!?])\s+", draft) if part.strip()):
        claim_terms = _terms(sentence)
        best_id: str | None = None
        best_overlap = 0.0
        for item in evidence:
            corpus = " ".join(
                str(item.get(field, "")) for field in ("title", "summary", "skills", "outcome")
            )
            terms = _terms(corpus)
            overlap = len(claim_terms & terms) / max(1, len(claim_terms))
            if overlap > best_overlap:
                best_overlap = overlap
                best_id = str(item.get("evidence_id", "")) or None
        if best_overlap >= 0.5:
            status = "supported"
        elif best_overlap >= 0.25:
            status = "partly_supported"
        else:
            status = "unsupported"
        checks.append(
            {
                "claim": sentence,
                "status": status,
                "evidence_ids": [best_id] if best_id and status != "unsupported" else [],
                "rationale": f"Token overlap with retrieved portfolio evidence: {best_overlap:.2f}.",
            }
        )
    return checks


def remove_unsupported_claims(
    draft: str, checks: list[dict[str, Any]]
) -> tuple[str, list[dict[str, Any]]]:
    kept = [check for check in checks if check["status"] == "supported"]
    allowed = {check["claim"] for check in kept}
    filtered = " ".join(
        part.strip() for part in re.split(r"(?<=[.!?])\s+", draft) if part.strip() in allowed
    )
    return filtered, kept

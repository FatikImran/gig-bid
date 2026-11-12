from __future__ import annotations

import re

from agent.handoffs import ComplianceVerdict
from agent.settings import marketplace_policy

_EMAIL_OR_PHONE = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)",
    re.IGNORECASE,
)


def check(text: str, evidence_ids: list[str]) -> ComplianceVerdict:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Proposal text cannot be empty")
    prohibited = marketplace_policy()["compliance"]["prohibited_terms"]
    folded_text = text.casefold()
    violations = []
    if any(term.casefold() in folded_text for term in prohibited):
        violations.append("Prohibited guarantee or off-platform contact language.")
    if _EMAIL_OR_PHONE.search(text):
        violations.append("Personal contact details or off-platform messaging reference.")
    if not evidence_ids:
        violations.append("No portfolio evidence is linked to the proposal.")
    return ComplianceVerdict(
        allowed=not violations,
        violations=violations,
        sanitized_text=text.strip(),
    )

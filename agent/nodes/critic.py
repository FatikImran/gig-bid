from __future__ import annotations

from agent.handoffs import Critique
from rag.verify import verify_claims


def critique(draft: str, evidence: list[dict], revision_count: int = 0) -> Critique:
    if revision_count > 2:
        raise ValueError("Critic revision limit is two")
    checks = verify_claims(draft, evidence)
    issues = [
        f"Unsupported or partly supported claim: {item['claim']}"
        for item in checks
        if item["status"] != "supported"
    ]
    return Critique(approved=not issues, issues=issues, revision_count=revision_count)

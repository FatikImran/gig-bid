from __future__ import annotations

from agent.handoffs import Critique
from agent.model_runtime import enabled, generate
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
    if enabled() and draft.strip():
        review = generate(
            "critic",
            {"draft": draft, "evidence": evidence},
            {
                "type": "object",
                "properties": {
                    "issues": {
                        "type": "array",
                        "maxItems": 2,
                        "items": {"type": "string", "maxLength": 120},
                    }
                },
                "required": ["issues"],
                "additionalProperties": False,
            },
        )
        issues.extend(review["issues"])
    return Critique(approved=not issues, issues=issues, revision_count=revision_count)

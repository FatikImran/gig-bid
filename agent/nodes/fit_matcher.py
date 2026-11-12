from __future__ import annotations

from typing import Any

from agent.handoffs import FitReport
from agent.sample_data import freelancers, portfolio_items
from agent.settings import agent_config
from rag.retriever import retrieve


def match(
    job: dict[str, Any], persona_id: str | None = None
) -> tuple[FitReport, list[dict[str, Any]]]:
    profile = next(
        (item for item in freelancers() if not persona_id or item["freelancer_id"] == persona_id),
        None,
    )
    if profile is None:
        raise ValueError(f"Unknown persona: {persona_id}")
    required = [str(skill) for skill in job.get("required_skills", [])]
    profile_skills = {str(skill).casefold() for skill in profile.get("skills", [])}
    matched = [skill for skill in required if skill.casefold() in profile_skills]
    missing = [skill for skill in required if skill.casefold() not in profile_skills]
    evidence = [
        item for item in portfolio_items() if item.get("freelancer_id") == profile["freelancer_id"]
    ]
    retrieved: dict[str, dict[str, Any]] = {}
    queries = required or [str(job.get("title", ""))]
    for query in queries:
        config = agent_config()["rag"]
        for item, _score in retrieve(
            config["variant"],
            query,
            evidence,
            k=max(1, min(config["top_k"], len(evidence))),
        ):
            retrieved[str(item["evidence_id"])] = item
    score = len(matched) / max(1, len(required))
    selected = list(retrieved.values())
    return FitReport(
        score=score,
        matched_skills=matched,
        missing_skills=missing,
        evidence_ids=[str(item["evidence_id"]) for item in selected],
    ), selected

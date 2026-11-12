from __future__ import annotations

from typing import Any

from agent.handoffs import JobSpec


def analyze(job: dict[str, Any]) -> JobSpec:
    if not isinstance(job.get("job_id"), str) or not job["job_id"].strip():
        raise ValueError("job_id is required")
    if not isinstance(job.get("title"), str) or not job["title"].strip():
        raise ValueError("title is required")
    budget = job.get("budget") or {}
    if not isinstance(budget, dict):
        raise TypeError("budget must be an object")
    return JobSpec(
        job_id=job["job_id"],
        title=job["title"],
        deliverables=[job["title"]],
        required_skills=[str(skill) for skill in job.get("required_skills", [])],
        budget_min=budget.get("min"),
        budget_max=budget.get("max"),
        budget_type=budget.get("type", "unspecified"),
        duration_days=job.get("duration_days"),
        screening_questions=[str(question) for question in job.get("screening_questions", [])],
    )

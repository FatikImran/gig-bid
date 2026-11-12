from __future__ import annotations

from typing import Any


def deduplicate(job_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    result = []
    for job in job_items:
        job_id = job.get("job_id")
        if not isinstance(job_id, str) or not job_id.strip():
            raise ValueError("Every job must have a non-empty job_id")
        if job_id not in seen:
            seen.add(job_id)
            result.append(job)
    return result

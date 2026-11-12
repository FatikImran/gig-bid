from __future__ import annotations

from typing import Any

from agent.handoffs import JobSpec, PriceQuote


def quote(job: JobSpec, profile: dict[str, Any], connects_cost: int = 0) -> PriceQuote:
    hourly = job.budget_type == "hourly"
    floor = float(
        profile.get("hourly_rate_usd", 0)
        if hourly
        else profile.get("minimum_project_budget_usd", 0)
    )
    minimum = float(job.budget_min or 0)
    maximum = float(job.budget_max or 0)
    amount = max(floor, minimum)
    if maximum > 0:
        amount = min(amount, maximum)
    return PriceQuote(
        amount=amount,
        connects_cost=max(0, connects_cost),
        unit="hourly" if hourly else "fixed",
        rationale=(
            f"Profile {'hourly rate' if hourly else 'project floor'} ${floor:.0f}, "
            f"constrained to the listed {'hourly rate' if hourly else 'project'} budget "
            f"${minimum:.0f}-${maximum:.0f}."
        ),
    )

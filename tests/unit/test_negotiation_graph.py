from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent.graphs.negotiation_graph import build_negotiation_graph
from agent.handoffs import NegotiationPlan
from agent.nodes.client_liaison import classify_message

PROFILE = {
    "freelancer_id": "synthetic-test-profile",
    "hourly_rate_usd": 25,
    "minimum_project_budget_usd": 200,
}


def _recommend(message: str, budget: dict[str, object] | None = None) -> dict:
    job = {
        "job_id": "synthetic-negotiation-job",
        "budget": budget or {"type": "fixed", "min": 100, "max": 600},
    }
    return build_negotiation_graph().invoke(
        {"message": message, "job": job, "profile": PROFILE}
    )["decision"]


def test_below_floor_offer_counters_at_the_profile_minimum():
    decision = _recommend("Could you do $150 for this project?")

    assert decision["action"] == "counter"
    assert decision["recommended_amount"] == 200
    assert decision["recommended_amount"] >= decision["profile_floor"]
    assert "minimum" in decision["reply"]


def test_offer_at_floor_is_accepted_and_classified_as_negotiation():
    message = "I can offer $200 for the project."

    assert classify_message(message) == "negotiation"
    decision = _recommend(message)
    assert decision["action"] == "accept"
    assert decision["recommended_amount"] == 200


def test_hourly_offer_is_parsed_and_checked_against_hourly_floor():
    decision = _recommend(
        "I can pay $20/hr.",
        {"type": "hourly", "min": 15, "max": 40},
    )

    assert decision["action"] == "counter"
    assert decision["unit"] == "hourly"
    assert decision["recommended_amount"] == 25


def test_offer_unit_mismatch_requires_clarification():
    decision = _recommend(
        "I can offer $250/hour.",
        {"type": "fixed", "min": 100, "max": 600},
    )

    assert decision["action"] == "clarify"
    assert "hourly" in decision["reply"]


def test_floor_above_listing_ceiling_walks_away_without_countering():
    decision = _recommend(
        "I can offer $150 for this project.",
        {"type": "fixed", "min": 50, "max": 100},
    )

    assert decision["action"] == "walk_away"
    assert decision["recommended_amount"] is None


def test_missing_offer_requests_clarification():
    decision = _recommend("Can you share more about the project?")

    assert decision["action"] == "clarify"
    assert decision["offered_amount"] is None


def test_negotiation_handoff_rejects_below_floor_counters():
    with pytest.raises(ValidationError):
        NegotiationPlan(
            action="counter",
            offered_amount=100,
            recommended_amount=199,
            unit="fixed",
            profile_floor=200,
            budget_ceiling=500,
            reason="Synthetic validation case.",
        )

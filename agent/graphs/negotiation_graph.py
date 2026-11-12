from __future__ import annotations

import re
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agent.handoffs import NegotiationDecision, NegotiationPlan

_OFFER_PATTERN = re.compile(
    r"(?:"
    r"(?:US\$|\$)\s*(?P<currency_amount>\d[\d,]*(?:\.\d{1,2})?)"
    r"(?P<currency_unit>\s*(?:/\s*(?:hr|h)|per\s+hour|hourly))?"
    r"|(?P<plain_amount>\d[\d,]*(?:\.\d{1,2})?)\s*(?:USD|dollars?)"
    r"(?P<plain_unit>\s*(?:/\s*(?:hr|h)|per\s+hour|hourly))?"
    r"|(?P<rate_amount>\d[\d,]*(?:\.\d{1,2})?)"
    r"(?P<rate_unit>\s*(?:/\s*(?:hr|h)|per\s+hour|hourly))"
    r")",
    re.IGNORECASE,
)


class NegotiationState(TypedDict, total=False):
    message: str
    job: dict[str, Any]
    profile: dict[str, Any]
    offered_amount: float | None
    offer_unit: str | None
    plan: dict[str, Any]
    decision: dict[str, Any]


def _parse_offer(state: NegotiationState) -> dict[str, Any]:
    match = _OFFER_PATTERN.search(state["message"])
    job = state["job"]
    budget = job.get("budget") or {}
    default_unit = "hourly" if budget.get("type") == "hourly" else "fixed"
    if match is None:
        return {"offered_amount": None, "offer_unit": default_unit}

    amount = next(
        float(match.group(name).replace(",", ""))
        for name in ("currency_amount", "plain_amount", "rate_amount")
        if match.group(name) is not None
    )
    explicit_unit = next(
        (
            match.group(name)
            for name in ("currency_unit", "plain_unit", "rate_unit")
            if match.group(name)
        ),
        None,
    )
    offer_unit = (
        "hourly"
        if explicit_unit
        and re.search(
            r"/\s*h(?:r)?\b|per\s+hour|hourly", explicit_unit, re.IGNORECASE
        )
        else default_unit
    )
    return {"offered_amount": amount, "offer_unit": offer_unit}


def _plan(state: NegotiationState) -> dict[str, Any]:
    job = state["job"]
    profile = state["profile"]
    budget = job.get("budget") or {}
    unit = "hourly" if budget.get("type") == "hourly" else "fixed"
    floor = float(
        profile.get("hourly_rate_usd", 0)
        if unit == "hourly"
        else profile.get("minimum_project_budget_usd", 0)
    )
    maximum = float(budget.get("max") or 0)
    ceiling = maximum if maximum > 0 else None
    offered = state.get("offered_amount")
    offer_unit = state.get("offer_unit", unit)

    if floor <= 0:
        raise ValueError("The selected profile must define a positive rate floor")
    if offered is None:
        action = "clarify"
        recommended = None
        reason = "The client message did not include a parseable monetary offer."
    elif offer_unit != unit:
        action = "clarify"
        recommended = None
        reason = "The stated offer unit conflicts with the listing budget unit."
    elif ceiling is not None and floor > ceiling:
        action = "walk_away"
        recommended = None
        reason = "The profile floor exceeds the listing's maximum budget."
    elif ceiling is not None and offered > ceiling:
        action = "clarify"
        recommended = None
        reason = "The offer exceeds the listing's stated maximum; confirm the revised scope and budget."
    elif offered < floor:
        action = "counter"
        recommended = floor
        reason = "The offer is below the selected profile's minimum rate."
    else:
        action = "accept"
        recommended = offered
        reason = "The offer meets the profile floor and does not exceed the listed budget."

    plan = NegotiationPlan(
        action=action,
        offered_amount=offered,
        offer_unit=offer_unit,
        recommended_amount=recommended,
        unit=unit,
        profile_floor=floor,
        budget_ceiling=ceiling,
        reason=reason,
    )
    return {"plan": plan.model_dump()}


def _format_amount(amount: float, unit: str) -> str:
    suffix = "/hour" if unit == "hourly" else "total"
    return f"${amount:,.2f} {suffix}"


def _draft_reply(state: NegotiationState) -> dict[str, Any]:
    plan = NegotiationPlan.model_validate(state["plan"])
    if plan.action == "accept":
        reply = (
            f"Thanks for the offer. I can proceed at "
            f"{_format_amount(plan.recommended_amount or 0, plan.unit)}, "
            "subject to confirming the deliverables and milestones here."
        )
    elif plan.action == "counter":
        reply = (
            f"Thanks for sharing the offer. My minimum for this scope is "
            f"{_format_amount(plan.profile_floor, plan.unit)}. If that works, "
            "I can confirm the deliverables and milestones here."
        )
    elif plan.action == "walk_away":
        reply = (
            "Thanks for discussing the project. The listed budget is below my minimum for this "
            "scope, so I cannot proceed at these terms. I can revisit if the scope or budget changes."
        )
    elif plan.offer_unit != plan.unit:
        reply = (
            "Thanks for the offer. Could you confirm whether this is an hourly rate or a fixed "
            "project amount before I respond?"
        )
    elif plan.offered_amount is not None and plan.budget_ceiling is not None:
        reply = (
            "Thanks for the offer. It differs from the listing's stated maximum; could you confirm "
            "the revised scope and budget before I respond?"
        )
    else:
        reply = (
            "Thanks for the message. Could you confirm the proposed amount and expected scope "
            "before I respond?"
        )
    decision = NegotiationDecision(**plan.model_dump(), reply=reply)
    return {"decision": decision.model_dump()}


def build_negotiation_graph():
    graph = StateGraph(NegotiationState)
    graph.add_node("parse_offer", _parse_offer)
    graph.add_node("apply_walkaway_rules", _plan)
    graph.add_node("draft_reply", _draft_reply)
    graph.add_edge(START, "parse_offer")
    graph.add_edge("parse_offer", "apply_walkaway_rules")
    graph.add_edge("apply_walkaway_rules", "draft_reply")
    graph.add_edge("draft_reply", END)
    return graph.compile()

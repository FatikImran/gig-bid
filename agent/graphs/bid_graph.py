from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt

from agent.handoffs import BidDecision
from agent.nodes.analyst import analyze as analyze_job
from agent.nodes.compliance import check as compliance_check
from agent.nodes.critic import critique
from agent.nodes.fit_matcher import match as match_fit
from agent.nodes.pricing import quote
from agent.nodes.risk_assessor import assess as assess_risk
from agent.nodes.writer import draft
from agent.sample_data import freelancers
from agent.settings import agent_config
from rag.verify import remove_unsupported_claims, verify_claims


class BidState(TypedDict, total=False):
    job: dict[str, Any]
    persona_id: str
    job_spec: dict[str, Any]
    risk_report: dict[str, Any]
    fit_report: dict[str, Any]
    evidence: list[dict[str, Any]]
    decision: dict[str, Any]
    price_quote: dict[str, Any]
    proposal_draft: dict[str, Any]
    claim_verification: list[dict[str, Any]]
    critique: dict[str, Any]
    compliance_verdict: dict[str, Any]
    revision_count: int
    approval_status: str
    external_action: str
    errors: Annotated[list[str], lambda left, right: left + right]


def _dispatch(state: BidState) -> list[Send]:
    if "job" not in state:
        raise ValueError("Bid graph requires a job")
    return [
        Send("job_analyst", state),
        Send("risk_assessor", state),
        Send("fit_matcher", state),
    ]


def _job_analyst(state: BidState) -> dict:
    return {"job_spec": analyze_job(state["job"]).model_dump()}


def _risk_assessor(state: BidState) -> dict:
    return {"risk_report": assess_risk(state["job"]).model_dump()}


def _fit_matcher(state: BidState) -> dict:
    report, evidence = match_fit(state["job"], state.get("persona_id"))
    return {"fit_report": report.model_dump(), "evidence": evidence}


def _decide(state: BidState) -> dict:
    job = state["job"]
    risk = state["risk_report"]
    fit = state["fit_report"]
    profile = next(
        (item for item in freelancers() if item["freelancer_id"] == state.get("persona_id")),
        freelancers()[0],
    )
    budget = job.get("budget") or {}
    thresholds = agent_config()["thresholds"]
    if risk["score"] >= thresholds["maximum_risk_score"]:
        decision = BidDecision(action="skip", reasons=["High-risk policy signal detected."])
    elif fit["score"] < thresholds["minimum_fit_score"]:
        decision = BidDecision(
            action="watch", reasons=["Portfolio skill coverage is below threshold."]
        )
    elif budget.get("max", 0) < (
        profile["hourly_rate_usd"]
        if budget.get("type") == "hourly"
        else profile["minimum_project_budget_usd"]
    ):
        decision = BidDecision(
            action="skip", reasons=["Budget is below the freelancer's stated floor."]
        )
    else:
        decision = BidDecision(
            action="bid",
            reasons=["Skill coverage meets threshold and no high-risk signal matched."],
        )
    return {"decision": decision.model_dump(), "revision_count": 0}


def _route_decision(state: BidState) -> str:
    return "price" if state["decision"]["action"] == "bid" else "finish"


def _price(state: BidState) -> dict:
    profile = next(
        (item for item in freelancers() if item["freelancer_id"] == state.get("persona_id")),
        freelancers()[0],
    )
    quote_result = quote(
        analyze_job(state["job"]),
        profile,
        int(state["job"].get("connects_cost", 0)),
    )
    return {"price_quote": quote_result.model_dump()}


def _write(state: BidState) -> dict:
    proposal = draft(
        analyze_job(state["job"]),
        state.get("evidence", []),
    ).model_dump()
    return {"proposal_draft": proposal}


def _verify(state: BidState) -> dict:
    text = state["proposal_draft"]["cover_letter"]
    checks = verify_claims(text, state.get("evidence", []))
    filtered, supported = remove_unsupported_claims(text, checks)
    if filtered:
        state_draft = {
            **state["proposal_draft"],
            "cover_letter": filtered,
            "evidence_ids": sorted(
                {evidence_id for item in supported for evidence_id in item["evidence_ids"]}
            ),
        }
    else:
        state_draft = {
            **state["proposal_draft"],
            "cover_letter": "",
            "evidence_ids": [],
        }
    return {"proposal_draft": state_draft, "claim_verification": checks}


def _critic(state: BidState) -> dict:
    revision = state.get("revision_count", 0)
    result = critique(
        state["proposal_draft"]["cover_letter"],
        state.get("evidence", []),
        revision,
    )
    return {
        "critique": result.model_dump(),
        "revision_count": revision + (0 if result.approved else 1),
    }


def _route_critic(state: BidState) -> str:
    if state["critique"]["approved"]:
        return "compliance"
    if state.get("revision_count", 0) < agent_config()["budgets"]["max_revisions"]:
        return "writer"
    return "compliance"


def _compliance(state: BidState) -> dict:
    verdict = compliance_check(
        state["proposal_draft"]["cover_letter"],
        state["proposal_draft"].get("evidence_ids", []),
    )
    return {"compliance_verdict": verdict.model_dump()}


def _route_compliance(state: BidState) -> str:
    return "approval" if state["compliance_verdict"]["allowed"] else "finish"


def _approval(state: BidState) -> dict:
    decision = interrupt(
        {
            "kind": "proposal_approval",
            "job": state["job"],
            "draft": state["proposal_draft"],
            "evidence": state.get("evidence", []),
            "risk_report": state["risk_report"],
            "price_quote": state.get("price_quote"),
            "dry_run": {
                "connects_cost": (state.get("price_quote") or {}).get("connects_cost", 0),
                "external_write_enabled": False,
            },
        }
    )
    if not isinstance(decision, dict) or decision.get("approved") is not True:
        return {"approval_status": "rejected"}
    return {"approval_status": "approved"}


def _post_approval(state: BidState) -> dict:
    return {"external_action": "approved_locally; external submission is disabled"}


def build_bid_graph(checkpointer=None):
    """Build the bid workflow with parallel analysis and an interrupt approval gate."""
    graph = StateGraph(BidState)
    graph.add_node("job_analyst", _job_analyst)
    graph.add_node("risk_assessor", _risk_assessor)
    graph.add_node("fit_matcher", _fit_matcher)
    graph.add_node("decision", _decide)
    graph.add_node("price", _price)
    graph.add_node("writer", _write)
    graph.add_node("claim_verification", _verify)
    graph.add_node("critic", _critic)
    graph.add_node("compliance", _compliance)
    graph.add_node("approval", _approval)
    graph.add_node("post_approval", _post_approval)
    graph.add_conditional_edges(START, _dispatch)
    for branch in ("job_analyst", "risk_assessor", "fit_matcher"):
        graph.add_edge(branch, "decision")
    graph.add_conditional_edges("decision", _route_decision, {"price": "price", "finish": END})
    graph.add_edge("price", "writer")
    graph.add_edge("writer", "claim_verification")
    graph.add_edge("claim_verification", "critic")
    graph.add_conditional_edges(
        "critic",
        _route_critic,
        {"writer": "writer", "compliance": "compliance"},
    )
    graph.add_conditional_edges(
        "compliance",
        _route_compliance,
        {"approval": "approval", "finish": END},
    )
    graph.add_conditional_edges(
        "approval",
        lambda state: "post_approval" if state.get("approval_status") == "approved" else END,
        {"post_approval": "post_approval", END: END},
    )
    graph.add_edge("post_approval", END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())

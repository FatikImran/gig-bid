from __future__ import annotations

from typing import Any

from agent.handoffs import (
    BidDecision,
    FitReport,
    JobSpec,
    PriceQuote,
    ProposalDraft,
)
from agent.nodes.compliance import check as compliance_check
from agent.nodes.risk_assessor import assess as assess_risk
from agent.sample_data import freelancers, portfolio_items
from agent.settings import agent_config
from rag.retriever import retrieve
from rag.verify import remove_unsupported_claims, verify_claims


def _job_spec(job: dict[str, Any]) -> JobSpec:
    budget = job.get("budget") or {}
    return JobSpec(
        job_id=str(job["job_id"]),
        title=str(job["title"]),
        deliverables=[str(job["title"])],
        required_skills=[str(skill) for skill in job.get("required_skills", [])],
        budget_min=budget.get("min"),
        budget_max=budget.get("max"),
        budget_type=budget.get("type", "unspecified"),
        duration_days=job.get("duration_days"),
        screening_questions=[str(question) for question in job.get("screening_questions", [])],
    )


def analyze_job(job: dict[str, Any], persona_id: str | None = None) -> dict[str, Any]:
    """Create a deterministic, auditable recommendation; this does not contact a marketplace."""
    spec = _job_spec(job)
    profiles = freelancers()
    profile = next(
        (item for item in profiles if not persona_id or item["freelancer_id"] == persona_id),
        profiles[0],
    )
    evidence_index = [
        item for item in portfolio_items() if item.get("freelancer_id") == profile["freelancer_id"]
    ]
    risk = assess_risk(job)
    required = [skill.lower() for skill in spec.required_skills]
    profile_skills = {skill.lower() for skill in profile.get("skills", [])}
    matched = [skill for skill in spec.required_skills if skill.lower() in profile_skills]
    missing = [skill for skill in spec.required_skills if skill.lower() not in profile_skills]
    fit_score = len(matched) / max(1, len(required))

    retrieved: dict[str, dict[str, Any]] = {}
    queries = spec.required_skills or [spec.title]
    rag_config = agent_config()["rag"]
    for query in queries:
        for item, _score in retrieve(
            rag_config["variant"],
            query,
            evidence_index,
            k=min(rag_config["top_k"], len(evidence_index) or 1),
        ):
            retrieved[str(item["evidence_id"])] = item
    selected_evidence = list(retrieved.values())
    fit = FitReport(
        score=fit_score,
        matched_skills=matched,
        missing_skills=missing,
        evidence_ids=[str(item["evidence_id"]) for item in selected_evidence],
    )
    thresholds = agent_config()["thresholds"]
    if risk.score >= thresholds["maximum_risk_score"]:
        decision = BidDecision(action="skip", reasons=["High-risk policy signal detected."])
    elif fit_score < thresholds["minimum_fit_score"]:
        decision = BidDecision(
            action="watch", reasons=["Portfolio skill coverage is below threshold."]
        )
    elif spec.budget_max is not None and spec.budget_max < (
        profile["hourly_rate_usd"]
        if spec.budget_type == "hourly"
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

    budget_min = spec.budget_min or 0
    budget_max = spec.budget_max or 0
    quote_floor = (
        float(profile["hourly_rate_usd"])
        if spec.budget_type == "hourly"
        else float(profile["minimum_project_budget_usd"])
    )
    proposed = max(quote_floor, budget_min)
    if budget_max:
        proposed = min(proposed, budget_max)
    quote = PriceQuote(
        amount=proposed,
        connects_cost=max(0, int(job.get("connects_cost", 0))),
        unit="hourly" if spec.budget_type == "hourly" else "fixed",
        rationale=(
            f"Uses the profile {'hourly rate' if spec.budget_type == 'hourly' else 'project floor'} "
            f"(${quote_floor}) constrained to the listed job budget (${budget_min}-${budget_max})."
        ),
    )

    proposal = _draft_proposal(spec, selected_evidence)
    checks = verify_claims(proposal.cover_letter, selected_evidence)
    filtered_text, supported_checks = remove_unsupported_claims(proposal.cover_letter, checks)
    if filtered_text:
        proposal = proposal.model_copy(
            update={
                "cover_letter": filtered_text,
                "evidence_ids": sorted(
                    {
                        evidence_id
                        for check in supported_checks
                        for evidence_id in check["evidence_ids"]
                    }
                ),
            }
        )
    else:
        proposal = proposal.model_copy(
            update={
                "cover_letter": "I do not have verified portfolio evidence to support a proposal for this job.",
                "evidence_ids": [],
            }
        )
    compliance = compliance_check(proposal.cover_letter, proposal.evidence_ids)
    return {
        "job_spec": spec.model_dump(),
        "risk_report": risk.model_dump(),
        "fit_report": fit.model_dump(),
        "decision": decision.model_dump(),
        "price_quote": quote.model_dump(),
        "evidence": selected_evidence,
        "claim_verification": checks,
        "proposal_draft": proposal.model_dump(),
        "compliance_verdict": compliance.model_dump(),
        "persona": profile,
        "dry_run": {
            "action": "create_proposal_draft",
            "amount_usd": quote.amount,
            "connects_cost": quote.connects_cost,
            "external_write_enabled": False,
        },
    }


def _draft_proposal(spec: JobSpec, evidence: list[dict[str, Any]]) -> ProposalDraft:
    if not evidence:
        text = "I do not have verified portfolio evidence to support a proposal for this job."
        return ProposalDraft(job_id=spec.job_id, cover_letter=text)
    best = evidence[0]
    text = f"My portfolio includes {best['title']}. {best['summary']}"
    return ProposalDraft(
        job_id=spec.job_id,
        cover_letter=text,
        screening_answers=[],
        evidence_ids=[str(best["evidence_id"])],
    )

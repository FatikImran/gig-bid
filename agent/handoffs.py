from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class JobSpec(StrictModel):
    job_id: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=300)
    deliverables: list[str] = Field(default_factory=list, max_length=30)
    required_skills: list[str] = Field(default_factory=list, max_length=50)
    budget_min: float | None = Field(default=None, ge=0)
    budget_max: float | None = Field(default=None, ge=0)
    budget_type: Literal["fixed", "hourly", "unspecified"] = "unspecified"
    duration_days: int | None = Field(default=None, ge=1)
    screening_questions: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_budget(self) -> JobSpec:
        if (
            self.budget_min is not None
            and self.budget_max is not None
            and self.budget_min > self.budget_max
        ):
            raise ValueError("budget_min cannot exceed budget_max")
        return self


class RiskReport(StrictModel):
    score: float = Field(ge=0, le=1)
    flags: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1, max_length=2000)


class FitReport(StrictModel):
    score: float = Field(ge=0, le=1)
    matched_skills: list[str] = Field(default_factory=list)
    missing_skills: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class BidDecision(StrictModel):
    action: Literal["bid", "skip", "watch"]
    reasons: list[str] = Field(min_length=1)


class PriceQuote(StrictModel):
    amount: float = Field(ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    unit: Literal["fixed", "hourly"] = "fixed"
    connects_cost: int = Field(ge=0)
    rationale: str = Field(min_length=1)


class ProposalDraft(StrictModel):
    job_id: str
    cover_letter: str = Field(min_length=1, max_length=5000)
    screening_answers: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    status: Literal["pending_review", "approved", "rejected"] = "pending_review"


class ClaimCheck(StrictModel):
    claim: str
    status: Literal["supported", "partly_supported", "unsupported"]
    evidence_ids: list[str] = Field(default_factory=list)
    rationale: str


class Critique(StrictModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    revision_count: int = Field(default=0, ge=0, le=2)


class ComplianceVerdict(StrictModel):
    allowed: bool
    violations: list[str] = Field(default_factory=list)
    sanitized_text: str


class NegotiationPlan(StrictModel):
    action: Literal["accept", "counter", "walk_away", "clarify"]
    offered_amount: float | None = Field(default=None, ge=0)
    offer_unit: Literal["fixed", "hourly"] | None = None
    recommended_amount: float | None = Field(default=None, ge=0)
    unit: Literal["fixed", "hourly"]
    profile_floor: float = Field(ge=0)
    budget_ceiling: float | None = Field(default=None, ge=0)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_recommendation(self) -> NegotiationPlan:
        if self.action == "counter" and (
            self.recommended_amount is None or self.recommended_amount < self.profile_floor
        ):
            raise ValueError("A counteroffer cannot be below the profile floor")
        if self.action == "accept" and self.recommended_amount != self.offered_amount:
            raise ValueError("An accepted offer must match the client's offered amount")
        return self


class NegotiationDecision(NegotiationPlan):
    reply: str = Field(min_length=1, max_length=2000)

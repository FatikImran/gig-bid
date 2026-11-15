"""Draft a proposal with private portfolio evidence and request an Upwork preview."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from langgraph.types import Command
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from agent.graphs.bid_graph import build_bid_graph
from agent.upwork_marketplace import (
    UpworkMarketplaceError,
    UpworkMCPAdapter,
    configured_upwork_marketplace,
)

PORTFOLIO_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "processed" / "upwork-portfolio.json"
)


class ResumeEvidence(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=128)
    freelancer_id: Literal["local-owner"]
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1, max_length=2000)
    skills: list[str] = Field(min_length=1, max_length=50)
    outcome: str = Field(max_length=1000)
    source: Literal["Owner-provided résumé"]


def load_resume_evidence(path: Path) -> dict[str, ResumeEvidence]:
    try:
        records = TypeAdapter(list[ResumeEvidence]).validate_json(path.read_bytes())
    except (OSError, ValidationError):
        raise ValueError(
            "A valid local owner portfolio is required at data/processed/upwork-portfolio.json."
        ) from None
    evidence = {record.evidence_id: record for record in records}
    if not evidence or len(evidence) != len(records):
        raise ValueError("The owner portfolio must contain unique evidence IDs.")
    return evidence


def build_owner_draft(graph, job, evidence: ResumeEvidence, bid: float, unit: str, config):
    if job["applied"]:
        raise UpworkMarketplaceError("Upwork shows an existing application for this listing.")
    if job["connects_cost"] is None or not job["upwork_reference"]:
        raise UpworkMarketplaceError("Upwork must provide the job reference and Connects cost.")
    if job["budget"]["type"] not in {"unspecified", unit}:
        raise ValueError("The bid unit does not match the listing's contract type.")

    result = graph.invoke(
        {
            "job": job,
            "owner_offer": {
                "amount": bid,
                "unit": unit,
                "evidence": [evidence.model_dump()],
            },
        },
        config=config,
    )
    if "approval" not in graph.get_state(config).next:
        reasons = (
            result.get("compliance_verdict", {}).get("violations") or result["decision"]["reasons"]
        )
        raise UpworkMarketplaceError("Draft blocked. " + " ".join(reasons))
    return result


def preview_summary(response: dict[str, Any]) -> dict[str, Any]:
    preview = response.get("preview")
    fields = {**response, **preview} if isinstance(preview, dict) else response
    preview_id = fields.get("preview_id") or fields.get("previewId")
    questions = fields.get("screening_questions")
    return {
        "ready": isinstance(preview_id, str) and bool(preview_id),
        "connects_cost": fields.get("connects_cost")
        if type(fields.get("connects_cost")) is int
        else None,
        "connects_balance": fields.get("connects_balance")
        if type(fields.get("connects_balance")) is int
        else None,
        "can_apply": fields.get("can_apply") if isinstance(fields.get("can_apply"), bool) else None,
        "screening_questions": [item for item in questions if isinstance(item, str)][:20]
        if isinstance(questions, list)
        else [],
    }


async def find_eligible_jobs(query: str) -> None:
    marketplace = configured_upwork_marketplace()
    if query:
        try:
            jobs = await marketplace.search_jobs(query)
        except UpworkMarketplaceError as exc:
            if exc.code != "UPSTREAM":
                raise
            print("Keyword search failed. Trying Upwork's Best Match feed.", flush=True)
        else:
            await _check_eligible_jobs(marketplace, jobs)
            return

    try:
        jobs = await marketplace.personalized_jobs()
    except UpworkMarketplaceError as exc:
        if exc.code != "UPSTREAM":
            raise
        jobs = []
    if not jobs:
        print("Best Match did not return listings. Trying Upwork's recent listings.", flush=True)
        jobs = await marketplace.search_jobs()
    await _check_eligible_jobs(marketplace, jobs)


async def _check_eligible_jobs(marketplace: UpworkMCPAdapter, jobs: list[dict[str, Any]]) -> None:
    checked = 0
    unaffordable = 0
    for result in jobs[:3]:
        if result["applied"]:
            continue
        detail = await marketplace.get_job(result["job_id"])
        checked += 1
        balance, cost = detail.get("connects_balance"), detail.get("connects_cost")
        if balance is not None and cost is not None and balance < cost:
            unaffordable += 1
        if (
            detail["can_apply"] is True
            and detail["connects_cost"] is not None
            and detail["upwork_reference"]
        ):
            print(f"Eligible listing: {detail['title']}")
            print(f"Upwork job ID: {detail['upwork_reference']}")
            print(f"Connects: {detail['connects_cost']}")
            if detail["upwork_url"]:
                print(detail["upwork_url"])
            return
    print(f"Upwork did not mark any of the {checked} checked listings eligible for this account.")
    if checked and unaffordable == checked:
        print("The reported Connects balance was below the listed cost for every checked listing.")


async def prepare_preview(job_id: str, evidence: ResumeEvidence, bid: float, unit: str) -> None:
    marketplace = configured_upwork_marketplace()
    job = await marketplace.get_job(job_id)
    graph = build_bid_graph()
    thread_id = uuid4().hex
    config = {"configurable": {"thread_id": thread_id}}
    result = build_owner_draft(graph, job, evidence, bid, unit, config)

    cover_letter = result["proposal_draft"]["cover_letter"]
    print(f"\nJob: {job['title']}\nEvidence: {evidence.title}")
    print(
        f"Bid: ${bid:.2f}{'/hr' if unit == 'hourly' else ''} USD\nListed Connects cost: {job['connects_cost']}"
    )
    if job["can_apply"] is False:
        print("Upwork reports that this account cannot currently apply to the listing.")
    print(f"\nCover letter to send for preview:\n{cover_letter}\n")
    print("The preview request sends this letter and bid to Upwork. It does not submit a proposal.")
    if input("Type PREVIEW to approve the preview request: ").strip() != "PREVIEW":
        graph.invoke(Command(resume={"approved": False}), config=config)
        print("Draft closed without requesting a preview.")
        return

    approved = graph.invoke(Command(resume={"approved": True}), config=config)
    preview = await marketplace.create_proposal_draft(
        {
            "job_reference": job["upwork_reference"],
            "cover_letter": cover_letter,
            "charged_amount": bid,
        },
        idempotency_key=thread_id,
        approved=approved.get("approval_status") == "approved",
        dry_run=False,
    )
    print("\nUpwork preview response. Review it locally. No proposal confirmation was requested.")
    print(json.dumps(preview, indent=2, ensure_ascii=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", nargs="?", help="Upwork job ID or listing URL")
    parser.add_argument("--evidence", help="The résumé project's evidence ID")
    parser.add_argument("--bid", type=float, help="Bid in USD")
    parser.add_argument("--unit", choices=("hourly", "fixed"))
    parser.add_argument("--list-evidence", action="store_true")
    parser.add_argument("--find-eligible", metavar="QUERY", nargs="?", const="")
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Check invitations and proposals without requesting a preview",
    )
    args = parser.parse_args()
    try:
        if args.find_eligible is not None:
            asyncio.run(find_eligible_jobs(args.find_eligible.strip()))
            return 0
        if args.list_evidence:
            for item in load_resume_evidence(PORTFOLIO_PATH).values():
                print(f"{item.evidence_id}: {item.title}")
            return 0
        job = (args.job or "").strip()
        if not job:
            parser.error("Enter a job ID or listing URL.")
        if "://" in job:
            url = urlsplit(job)
            if url.scheme != "https" or url.netloc != "www.upwork.com":
                parser.error("Use an HTTPS listing URL on www.upwork.com.")
            job = url._replace(query="", fragment="").geturl()
        if args.preflight_only:
            asyncio.run(check_preview_preflight(job))
            return 0
        evidence = load_resume_evidence(PORTFOLIO_PATH)
        if not args.evidence or not args.unit or args.bid is None:
            parser.error("Provide --evidence, --bid and --unit, or use --preflight-only.")
        if not math.isfinite(args.bid) or args.bid <= 0:
            parser.error("The bid must be a positive amount.")
        if args.evidence not in evidence:
            parser.error("Unknown evidence ID. Use --list-evidence to see the options.")
        asyncio.run(prepare_preview(job, evidence[args.evidence], args.bid, args.unit))
    except (UpworkMarketplaceError, LookupError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nStopped. GigBid does not confirm Upwork submissions.", file=sys.stderr)
        return 1
    return 0


async def check_preview_preflight(job_id: str) -> None:
    marketplace = configured_upwork_marketplace()
    job = await marketplace.get_job(job_id)
    reference = job["upwork_reference"]
    if not reference:
        raise UpworkMarketplaceError("Upwork must provide a numeric job reference.")
    if job["can_apply"] is False:
        print("Upwork reports this account cannot currently apply to this listing.")
        balance, cost = job.get("connects_balance"), job.get("connects_cost")
        if balance is not None and cost is not None and balance < cost:
            print(f"The listing requires {cost} Connects. The account has {balance:g}.")
    await marketplace.check_previous_application(reference)
    print("Upwork invitation and prior-proposal checks passed. No preview was requested.")


if __name__ == "__main__":
    raise SystemExit(main())

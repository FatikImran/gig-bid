from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from agent.marketplace_port import create_marketplace_port
from agent.sample_data import client_history, jobs

mcp = FastMCP("GigBid Marketplace")
DB_PATH = Path(os.getenv("GIGBID_DB_PATH", "data/processed/gigbid.sqlite3"))
_last_requests: list[float] = []


class ProposalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=128)
    cover_letter: str = Field(min_length=1, max_length=5000)
    evidence_ids: list[str] = Field(min_length=1, max_length=30)
    amount: float = Field(gt=0, le=1_000_000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    approved: bool
    dry_run: bool = True


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str = Field(min_length=1, max_length=128)
    client_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=3000)
    idempotency_key: str = Field(min_length=8, max_length=128)
    approved: bool


def _rate_limit(max_per_minute: int = 20) -> None:
    now = time.monotonic()
    _last_requests[:] = [stamp for stamp in _last_requests if now - stamp < 60]
    if len(_last_requests) >= max_per_minute:
        raise RuntimeError("Local marketplace rate limit exceeded")
    _last_requests.append(now)


def search_jobs(query: str = "") -> list[dict[str, Any]]:
    _rate_limit()
    if len(query) > 500:
        raise ValueError("query cannot exceed 500 characters")
    terms = query.casefold().split()
    return [
        job
        for job in jobs()
        if not terms
        or all(term in f"{job['title']} {job['description']}".casefold() for term in terms)
    ]


def get_job(job_id: str) -> dict[str, Any]:
    _rate_limit()
    result = next((job for job in jobs() if job["job_id"] == job_id), None)
    if result is None:
        raise ValueError("Job not found")
    return result


def get_client_history(client_id: str) -> dict[str, Any]:
    _rate_limit()
    result = next((client for client in client_history() if client["client_id"] == client_id), None)
    if result is None:
        raise ValueError("Client history not found")
    return result


def get_connects_balance() -> dict[str, Any]:
    """Return a clearly marked sample balance; the scaffold has no live marketplace."""
    _rate_limit()
    return {
        "balance": None,
        "source": "not_configured",
        "message": "Connects balance is unavailable without GigSim",
    }


def list_messages(client_id: str) -> list[dict[str, Any]]:
    _rate_limit()
    if not client_id.strip():
        raise ValueError("client_id cannot be empty")
    return []


def create_proposal_draft(request: ProposalInput) -> dict[str, Any]:
    _rate_limit()
    job = get_job(request.job_id)
    preview = {
        "job_id": request.job_id,
        "cover_letter": request.cover_letter,
        "evidence_ids": request.evidence_ids,
        "amount": request.amount,
        "currency": job.get("budget", {}).get("currency", "USD"),
        "connects_cost": job.get("connects_cost", 0),
        "dry_run": request.dry_run,
    }
    if not request.approved:
        raise PermissionError("Human approval is required before a proposal write")
    digest = hashlib.sha256(json.dumps(preview, sort_keys=True).encode()).hexdigest()
    if request.dry_run:
        return {"preview": preview, "idempotency_digest": digest, "external_write": False}
    raise RuntimeError(
        "External proposal submission is disabled: no GigSim service or live adapter is configured."
    )


def submit_proposal(job_id: str, idempotency_key: str, approved: bool, dry_run: bool = True):
    if len(idempotency_key) < 8:
        raise ValueError("idempotency_key must contain at least 8 characters")
    if not approved:
        raise PermissionError("Human approval is required")
    get_job(job_id)
    if dry_run:
        return {
            "job_id": job_id,
            "action": "submit_proposal",
            "dry_run": True,
            "external_write": False,
        }
    raise RuntimeError("Submission is disabled because no marketplace adapter is configured")


def send_message(
    client_id: str, message: str, idempotency_key: str, approved: bool, dry_run: bool = True
):
    if not client_id.strip() or not message.strip() or len(message) > 3000:
        raise ValueError("client_id and a message of at most 3000 characters are required")
    if len(idempotency_key) < 8:
        raise ValueError("idempotency_key must contain at least 8 characters")
    if not approved:
        raise PermissionError("Human approval is required")
    preview = {"client_id": client_id, "message": message, "dry_run": dry_run}
    if dry_run:
        return {"preview": preview, "external_write": False}
    raise RuntimeError("Message sending is disabled because no marketplace adapter is configured")


async def _marketplace():
    return create_marketplace_port()


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
async def marketplace_search_jobs(
    query: Annotated[str, Field(max_length=500)] = "",
) -> list[dict[str, Any]]:
    """Search the configured marketplace adapter, which may be local GigSim or sample fixtures."""
    _rate_limit()
    return await (await _marketplace()).search_jobs(query)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
async def marketplace_get_job(
    job_id: Annotated[str, Field(min_length=1, max_length=128)],
) -> dict[str, Any]:
    """Load a job through the configured marketplace adapter."""
    _rate_limit()
    return await (await _marketplace()).get_job(job_id)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
async def marketplace_get_client_history(
    client_id: Annotated[str, Field(min_length=1, max_length=128)],
) -> dict[str, Any]:
    """Load client history through the configured marketplace adapter."""
    _rate_limit()
    return await (await _marketplace()).get_client_history(client_id)


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
async def marketplace_get_connects_balance() -> dict[str, Any]:
    """Get Connects balance where a marketplace adapter is configured."""
    _rate_limit()
    return await (await _marketplace()).get_connects_balance()


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
async def marketplace_list_messages(
    client_id: Annotated[str, Field(min_length=1, max_length=128)],
) -> list[dict[str, Any]]:
    """List messages for a client through the configured marketplace adapter."""
    _rate_limit()
    return await (await _marketplace()).list_messages(client_id)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True})
async def marketplace_create_proposal_draft(
    job_id: Annotated[str, Field(min_length=1, max_length=128)],
    cover_letter: Annotated[str, Field(min_length=1, max_length=5000)],
    evidence_ids: Annotated[list[str], Field(min_length=1, max_length=30)],
    amount: Annotated[float, Field(gt=0, le=1_000_000)],
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
    approved: bool,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Preview or create an approved proposal through the configured marketplace adapter."""
    _rate_limit()
    request = ProposalInput(
        job_id=job_id,
        cover_letter=cover_letter,
        evidence_ids=evidence_ids,
        amount=amount,
        idempotency_key=idempotency_key,
        approved=approved,
        dry_run=dry_run,
    )
    if not request.dry_run:
        raise PermissionError("Marketplace MCP writes are disabled; use the authenticated API approval workflow")
    port = await _marketplace()
    job = await port.get_job(request.job_id)
    payload = {
        "job_id": request.job_id,
        "client_id": str(job["client_id"]),
        "cover_letter": request.cover_letter,
        "screening_answers": [],
        "evidence_ids": request.evidence_ids,
        "amount": request.amount,
    }
    return await port.create_proposal_draft(
        payload,
        request.idempotency_key,
        request.approved,
        dry_run=request.dry_run,
    )


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True})
async def marketplace_submit_proposal(
    job_id: Annotated[str, Field(min_length=1, max_length=128)],
    cover_letter: Annotated[str, Field(min_length=1, max_length=5000)],
    evidence_ids: Annotated[list[str], Field(min_length=1, max_length=30)],
    amount: Annotated[float, Field(gt=0, le=1_000_000)],
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
    approved: bool,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Submit an approved proposal; dry-run previews the payload without spending Connects."""
    _rate_limit()
    request = ProposalInput(
        job_id=job_id,
        cover_letter=cover_letter,
        evidence_ids=evidence_ids,
        amount=amount,
        idempotency_key=idempotency_key,
        approved=approved,
        dry_run=dry_run,
    )
    if not request.dry_run:
        raise PermissionError("Marketplace MCP writes are disabled; use the authenticated API approval workflow")
    port = await _marketplace()
    job = await port.get_job(request.job_id)
    payload = {
        "job_id": request.job_id,
        "client_id": str(job["client_id"]),
        "cover_letter": request.cover_letter,
        "screening_answers": [],
        "evidence_ids": request.evidence_ids,
        "amount": request.amount,
    }
    return await port.create_proposal_draft(
        payload, request.idempotency_key, request.approved, dry_run=True
    )


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True})
async def marketplace_send_message(
    client_id: Annotated[str, Field(min_length=1, max_length=128)],
    job_id: Annotated[str, Field(min_length=1, max_length=128)],
    message: Annotated[str, Field(min_length=1, max_length=3000)],
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128)],
    approved: bool,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Send an approved message or return its dry-run preview."""
    _rate_limit()
    message_request = MessageInput(
        job_id=job_id,
        client_id=client_id,
        message=message,
        idempotency_key=idempotency_key,
        approved=approved,
    )
    if not dry_run:
        raise PermissionError("Marketplace MCP writes are disabled; use the authenticated API approval workflow")
    payload = {
        "job_id": message_request.job_id,
        "client_id": message_request.client_id,
        "message": message_request.message,
    }
    port = await _marketplace()
    if dry_run:
        if not approved:
            raise PermissionError("Human approval is required")
        return {"preview": payload, "idempotency_key": idempotency_key, "external_write": False}
    return await port.send_message(payload, idempotency_key, approved)


if __name__ == "__main__":
    mcp.run()

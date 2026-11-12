from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

mcp = FastMCP("GigBid Workspace")
_holds: dict[str, dict[str, str]] = {}
_email_drafts: dict[str, dict[str, str]] = {}


class EmailDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient: str = Field(min_length=3, max_length=254)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=5000)


def available_slots(days: int = 7, duration_minutes: int = 30) -> list[dict[str, str]]:
    if not 1 <= days <= 30:
        raise ValueError("days must be between 1 and 30")
    if duration_minutes not in {15, 30, 45, 60}:
        raise ValueError("duration_minutes must be 15, 30, 45, or 60")
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    slots = []
    for day_offset in range(1, days + 1):
        date = now + timedelta(days=day_offset)
        if date.weekday() > 4:
            continue
        for hour in (10, 14, 16):
            start = date.replace(hour=hour)
            slots.append(
                {
                    "start": start.isoformat(),
                    "end": (start + timedelta(minutes=duration_minutes)).isoformat(),
                    "timezone": "UTC",
                    "status": "available",
                }
            )
    return slots


def create_tentative_hold(start: str, end: str, approved: bool) -> dict[str, str]:
    if not approved:
        raise PermissionError("Human approval is required to create a calendar hold")
    try:
        start_at = datetime.fromisoformat(start)
        end_at = datetime.fromisoformat(end)
    except ValueError as exc:
        raise ValueError("start and end must be ISO-8601 timestamps") from exc
    if start_at.tzinfo is None or end_at.tzinfo is None or end_at <= start_at:
        raise ValueError("A valid timezone-aware time range is required")
    hold_id = str(uuid4())
    hold = {
        "hold_id": hold_id,
        "start": start_at.isoformat(),
        "end": end_at.isoformat(),
        "status": "tentative",
    }
    _holds[hold_id] = hold
    return hold


def create_email_draft(recipient: str, subject: str, body: str) -> dict[str, str]:
    draft = EmailDraft(recipient=recipient, subject=subject, body=body)
    draft_id = str(uuid4())
    result = {"draft_id": draft_id, **draft.model_dump(), "status": "draft_only"}
    _email_drafts[draft_id] = result
    return result


@mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True})
def workspace_available_slots(
    days: Annotated[int, Field(ge=1, le=30)] = 7,
    duration_minutes: Annotated[int, Field(ge=15, le=60, multiple_of=15)] = 30,
) -> list[dict[str, str]]:
    """List free sample calendar slots in UTC; no calendar account is connected."""
    return available_slots(days, duration_minutes)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False})
def workspace_create_tentative_hold(
    start: Annotated[str, Field(min_length=1, max_length=64)],
    end: Annotated[str, Field(min_length=1, max_length=64)],
    approved: bool,
) -> dict[str, str]:
    """Create an in-memory tentative hold after explicit user approval."""
    return create_tentative_hold(start, end, approved)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False})
def workspace_create_email_draft(
    recipient: Annotated[str, Field(min_length=3, max_length=254)],
    subject: Annotated[str, Field(min_length=1, max_length=200)],
    body: Annotated[str, Field(min_length=1, max_length=5000)],
) -> dict[str, str]:
    """Create a local email draft only; sending is not available."""
    return create_email_draft(recipient, subject, body)


if __name__ == "__main__":
    mcp.run()

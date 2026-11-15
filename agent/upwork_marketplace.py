"""Map authenticated Upwork MCP reads and proposal previews to GigBid."""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp import ClientSession
from mcp.types import TextContent

from agent.upwork_oauth import LOCAL_TENANT, EncryptedOAuthStorage, create_upwork_client, error_kind


class UpworkMarketplaceError(RuntimeError):
    """An Upwork operation that GigBid could not safely complete."""

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


def _amount(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("amount")
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def _job(raw: dict[str, Any], requested_id: str | None = None) -> dict[str, Any]:
    upstream_id = raw.get("id") or raw.get("job_id") or raw.get("ciphertext")
    if requested_id is None and (
        not isinstance(upstream_id, (str, int)) or isinstance(upstream_id, bool)
    ):
        raise UpworkMarketplaceError("Upwork returned a job without an ID.")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise UpworkMarketplaceError("Upwork returned a job without a title.")

    budget = raw.get("budget")
    budget_fields = budget if isinstance(budget, dict) else {}
    job_type = (
        str(raw.get("job_type") or budget_fields.get("type") or "").casefold().replace("-", "_")
    )
    if job_type == "hourly":
        minimum = _amount(
            budget_fields.get("min", raw.get("rate_min", raw.get("hourly_budget_min")))
        )
        maximum = _amount(
            budget_fields.get("max", raw.get("rate_max", raw.get("hourly_budget_max")))
        )
    else:
        minimum = _amount(budget_fields.get("min", budget))
        maximum = _amount(budget_fields.get("max", budget))
    connects = _amount(raw.get("connects_cost", raw.get("connect_price")))
    skills = raw.get("skills", raw.get("required_skills", []))
    description = raw.get("description") or raw.get("description_snippet") or raw.get("snippet")
    url = raw.get("url")
    parsed_url = urlsplit(url) if isinstance(url, str) else None
    safe_url = (
        url
        if parsed_url and (parsed_url.scheme, parsed_url.netloc) == ("https", "www.upwork.com")
        else None
    )
    return {
        "job_id": requested_id or str(upstream_id),
        "title": title,
        "description": description if isinstance(description, str) else "",
        "required_skills": [skill for skill in skills if isinstance(skill, str)]
        if isinstance(skills, list)
        else [],
        "budget": {
            "min": minimum,
            "max": maximum,
            "currency": budget_fields.get("currency") or "USD",
            "type": job_type if job_type in {"hourly", "fixed"} else "unspecified",
        },
        "connects_cost": int(connects) if connects is not None and connects.is_integer() else None,
        "connects_balance": _amount(raw.get("connects_balance")),
        "data_provenance": "upwork_live",
        "upwork_url": safe_url,
        "upwork_reference": str(upstream_id)
        if str(upstream_id).isascii() and str(upstream_id).isdigit()
        else None,
        "applied": raw.get("applied") is True,
        "can_apply": raw["can_apply"] if isinstance(raw.get("can_apply"), bool) else None,
    }


_DETAIL_WRAPPERS = (
    "job",
    "job_posting",
    "jobPosting",
    "marketplaceJobPosting",
    "content",
    "job_details",
    "jobDetails",
    "posting",
    "data",
    "result",
)


def _detail_fields(data: dict[str, Any], depth: int = 0) -> dict[str, Any] | None:
    if isinstance(data.get("title"), str) and data["title"].strip():
        return data
    if depth == 3:
        return None
    for key in _DETAIL_WRAPPERS:
        child = data.get(key)
        if isinstance(child, dict) and (fields := _detail_fields(child, depth + 1)) is not None:
            return {**data, **fields}
    return None


def _detail_shape(data: dict[str, Any], path: str = "root", depth: int = 0) -> str:
    names = ", ".join(
        sorted(key for key in data if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", key))[:30]
    )
    levels = [f"{path}: {names}"]
    if depth == 3:
        return levels[0]
    for key in _DETAIL_WRAPPERS:
        if isinstance(data.get(key), dict):
            child_path = key if depth == 0 else f"{path}.{key}"
            levels.append(_detail_shape(data[key], child_path, depth + 1))
    return "; ".join(levels)


def _application_page(data: Any, action: str) -> tuple[list[dict[str, Any]], str | None]:
    keys = (
        ("invitations", "freelancerInvitations", "jobInvitations", "invites")
        if action == "invitations"
        else ("proposals", "freelancerProposals", "jobProposals", "applications")
    ) + ("data", "results", "nodes", "edges", "items", "records")
    resource = "invitations?" if action == "invitations" else "(?:proposals?|applications?)"
    wrapper = re.compile(rf"(?:{resource})(?:list|connection)?(?:v\d+)?$", re.IGNORECASE)
    page: dict[str, Any] = {}
    levels = []
    for _ in range(5):
        if not isinstance(data, dict):
            break
        levels.append(
            ", ".join(
                sorted(key for key in data if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", key))[:20]
            )
        )
        page.update(data)
        children = (*keys, *(key for key in data if wrapper.search(key.replace("_", ""))))
        data = next(
            (data[key] for key in children if isinstance(data.get(key), (list, dict))), None
        )
    if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
        shape = " / ".join(levels) or type(data).__name__
        raise UpworkMarketplaceError(f"Upwork returned an unrecognized {action} page ({shape}).")
    rows = [row.get("node", row) for row in data]
    if any(not isinstance(row, dict) for row in rows):
        raise UpworkMarketplaceError("Upwork returned an invalid prior application record.")

    info = page.get("pageInfo", page.get("page_info", {}))
    if not isinstance(info, dict):
        raise UpworkMarketplaceError("Upwork returned invalid prior-application pagination.")
    has_more = info.get(
        "hasNextPage", info.get("has_next_page", page.get("hasMore", page.get("has_more")))
    )
    cursor = info.get("endCursor", info.get("end_cursor", page.get("next_cursor")))
    if has_more is False or (has_more is None and not cursor and len(rows) < 25):
        return rows, None
    if not isinstance(cursor, str) or not cursor:
        raise UpworkMarketplaceError("Upwork did not supply the next prior-application page.")
    return rows, cursor


class UpworkMCPAdapter:
    def __init__(self, client: MultiServerMCPClient, org_uid: str | None = None):
        self.client = client
        self.org_uid = org_uid

    async def _call(self, session: ClientSession, name: str, arguments: dict[str, Any]) -> Any:
        result = await session.call_tool(f"upwork__{name}", arguments)
        content = "\n".join(item.text for item in result.content if isinstance(item, TextContent))
        data = result.structuredContent
        if data is None:
            try:
                data = json.loads(content)
            except ValueError:
                if not result.isError:
                    raise UpworkMarketplaceError(
                        f"Upwork returned invalid JSON for {name}."
                    ) from None
        if result.isError or (
            isinstance(data, dict) and (data.get("status") == "error" or data.get("error_code"))
        ):
            error = data.get("error") if isinstance(data, dict) else None
            fields = error if isinstance(error, dict) else (data if isinstance(data, dict) else {})
            code = fields.get("error_code", fields.get("code"))
            if isinstance(code, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}", code):
                raise UpworkMarketplaceError(
                    f"Upwork rejected the {name} request ({code}).", code=code
                )
            reason = (
                " ".join(str(fields.get(key, "")) for key in ("message", "reason", "error"))
                + content
            )
            if re.search(r"(?:insufficient|not enough)\s+connects", reason, re.IGNORECASE):
                raise UpworkMarketplaceError(
                    "Upwork reports insufficient Connects for this listing."
                )
            raise UpworkMarketplaceError(
                f"Upwork rejected the {name} request without a recognized error code."
            )
        return data

    @asynccontextmanager
    async def _account_session(self) -> AsyncIterator[tuple[ClientSession, str]]:
        try:
            async with asyncio.timeout(60), self.client.session("upwork") as session:
                org_uid = self.org_uid
                if org_uid is None:
                    accounts = await self._call(session, "list_accounts", {})
                    if isinstance(accounts, dict):
                        accounts = accounts.get("accounts")
                    if not isinstance(accounts, list):
                        raise UpworkMarketplaceError("Upwork returned an unexpected account list.")
                    eligible = [
                        item["org_uid"]
                        for item in accounts
                        if isinstance(item, dict)
                        and item.get("role") == "TALENT"
                        and not item.get("suspended")
                        and isinstance(item.get("org_uid"), str)
                        and item["org_uid"]
                    ]
                    if len(eligible) != 1:
                        raise UpworkMarketplaceError(
                            "Upwork browsing requires exactly one eligible freelancer profile or a configured UPWORK_ORG_UID."
                        )
                    org_uid = eligible[0]
                yield session, org_uid
        except UpworkMarketplaceError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Do not expose provider response text, request URLs or credentials to the UI.
            group = exc
            while isinstance(group, BaseExceptionGroup) and len(group.exceptions) == 1:
                group = group.exceptions[0]
            if isinstance(group, UpworkMarketplaceError):
                raise group from None
            raise UpworkMarketplaceError(
                f"Upwork MCP request failed ({error_kind(exc)})."
            ) from None

    async def _operation(self, tool: str, action: str, params: dict[str, Any]) -> Any:
        async with self._account_session() as (session, org_uid):
            return await self._call(
                session, tool, {"action": action, "org_uid": org_uid, "params": params}
            )

    async def search_jobs(self, query: str = "") -> list[dict[str, Any]]:
        query = query.strip()
        params: dict[str, Any] = {"limit": 5, "include_full_details": not query}
        if query:
            params["query"] = query
        data = await self._operation("find_jobs", "search", params)
        rows = data.get("jobs") if isinstance(data, dict) else data
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise UpworkMarketplaceError("Upwork returned an unexpected job-search response.")
        return [_job(row) for row in rows]

    async def get_job(self, job_id: str) -> dict[str, Any]:
        data = await self._operation("find_jobs", "get", {"id": job_id})
        if not isinstance(data, dict):
            raise UpworkMarketplaceError("Upwork returned an unexpected job-detail response.")
        if "job" in data and data["job"] is None:
            raise LookupError("Upwork job not found")
        fields = _detail_fields(data)
        if fields is None:
            raise UpworkMarketplaceError(
                f"Upwork returned an unexpected job-detail response ({_detail_shape(data)})."
            )
        envelope = data.get("data")
        posting = envelope.get("marketplaceJobPosting") if isinstance(envelope, dict) else None
        if isinstance(posting, dict) and "id" in posting:
            fields = {**fields, "id": posting["id"]}
        return _job(fields, requested_id=job_id)

    async def get_connects_balance(self) -> dict[str, Any]:
        data = await self._operation("get_profile", "connects_balance", {})
        if not isinstance(data, dict) or _amount(data.get("balance")) is None:
            raise UpworkMarketplaceError("Upwork returned an unexpected Connects response.")
        return {"balance": data["balance"], "source": "upwork_live"}

    async def get_client_history(self, client_id: str) -> dict[str, Any]:
        raise UpworkMarketplaceError("Upwork client history is scoped to a job lookup.")

    async def list_messages(self, client_id: str) -> list[dict[str, Any]]:
        raise UpworkMarketplaceError("Upwork messages require a verified conversation room ID.")

    async def create_proposal_draft(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool, dry_run: bool = True
    ) -> dict[str, Any]:
        if not approved:
            raise PermissionError("Human approval is required")
        if not idempotency_key or len(idempotency_key) < 8:
            raise ValueError("A valid idempotency key is required")
        if dry_run:
            return {"preview": payload, "idempotency_key": idempotency_key, "external_write": False}

        reference = payload.get("job_reference")
        if not isinstance(reference, str) or not re.fullmatch(r"[0-9]+", reference):
            raise UpworkMarketplaceError(
                "An Upwork numeric job reference is required for the preview."
            )
        letter = payload.get("cover_letter")
        amount = _amount(payload.get("charged_amount"))
        if not isinstance(letter, str) or not letter.strip() or len(letter) > 5000 or not amount:
            raise UpworkMarketplaceError("The preview requires a cover letter and a positive bid.")
        params = {"job_reference": reference, "cover_letter": letter, "charged_amount": amount}
        async with self._account_session() as (session, org_uid):
            await self._check_previous_application(session, org_uid, reference)
            result = await self._call(
                session,
                "manage_proposals",
                {
                    "action": "create",
                    "org_uid": org_uid,
                    "params": params,
                },
            )
        if not isinstance(result, dict):
            raise UpworkMarketplaceError("Upwork returned an unexpected proposal preview.")
        return result

    async def _check_previous_application(
        self, session: ClientSession, org_uid: str, reference: str
    ) -> None:
        checks = [("invitations", {"job_posting_id": reference})]
        checks.extend(
            ("list", {"status": status})
            for status in (
                "Pending",
                "Accepted",
                "Activated",
                "Declined",
                "Offered",
                "Hired",
            )
        )
        for action, filters in checks:
            params = {**filters, "limit": 25}
            for _ in range(2):
                data = await self._call(
                    session,
                    "list_freelancer_proposals",
                    {
                        "action": action,
                        "org_uid": org_uid,
                        "params": params,
                    },
                )
                try:
                    rows, cursor = _application_page(data, action)
                except UpworkMarketplaceError as exc:
                    check = filters.get("status", "invitations")
                    raise UpworkMarketplaceError(
                        f"Prior application check ({check}): {exc}"
                    ) from None
                if action == "invitations" and rows:
                    raise UpworkMarketplaceError("Check this job's existing invitation on Upwork.")
                for row in rows:
                    job = row.get("jobPosting", row.get("job_posting", row.get("job")))
                    job_id = job.get("id") if isinstance(job, dict) else None
                    job_id = job_id or row.get("job_posting_id") or row.get("job_id")
                    if not re.fullmatch(r"[0-9]+", str(job_id)):
                        raise UpworkMarketplaceError(
                            "An existing proposal has an unrecognized job ID."
                        )
                    if str(job_id) == reference:
                        raise UpworkMarketplaceError("This job already has a proposal on Upwork.")
                if cursor is None:
                    break
                params["cursor"] = cursor
            else:
                raise UpworkMarketplaceError("The prior-application check exceeded its page limit.")

    async def check_previous_application(self, reference: str) -> None:
        async with self._account_session() as (session, org_uid):
            await self._check_previous_application(session, org_uid, reference)

    async def submit_proposal(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool
    ) -> dict[str, Any]:
        raise UpworkMarketplaceError("Confirm proposal submission on Upwork.")

    async def send_message(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool
    ) -> dict[str, Any]:
        raise UpworkMarketplaceError("Upwork MCP does not expose a message-draft action.")


def configured_upwork_marketplace() -> UpworkMCPAdapter:
    key = os.getenv("GIGBID_OAUTH_ENCRYPTION_KEY", "")
    if not key:
        raise UpworkMarketplaceError(
            "Set the local OAuth encryption key and run Upwork setup first."
        )
    path = Path(os.getenv("GIGBID_DB_PATH", "data/processed/gigbid.sqlite3"))
    try:
        storage = EncryptedOAuthStorage(path, LOCAL_TENANT, key)
    except ValueError:
        raise UpworkMarketplaceError("The local OAuth encryption key is invalid.") from None
    return UpworkMCPAdapter(create_upwork_client(storage), os.getenv("UPWORK_ORG_UID") or None)


async def _check_jobs() -> None:
    adapter = configured_upwork_marketplace()
    jobs = await adapter.search_jobs()
    print(f"Upwork job search returned {len(jobs)} listings.")
    if jobs:
        details = await adapter.get_job(jobs[0]["job_id"])
        print("Upwork job detail loaded.")
        print(f"Description present: {bool(details['description'])}.")
        print(f"Connects cost available: {details['connects_cost'] is not None}.")


if __name__ == "__main__":
    try:
        asyncio.run(_check_jobs())
    except (UpworkMarketplaceError, LookupError) as exc:
        print(exc, file=sys.stderr)
        raise SystemExit(1) from None

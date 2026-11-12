from __future__ import annotations

import os
from typing import Any, Protocol
from urllib.parse import quote, urlparse

import httpx

from agent.sample_data import client_history, jobs


class MarketplacePort(Protocol):
    async def search_jobs(self, query: str = "") -> list[dict[str, Any]]: ...
    async def get_job(self, job_id: str) -> dict[str, Any]: ...
    async def get_client_history(self, client_id: str) -> dict[str, Any]: ...
    async def get_connects_balance(self) -> dict[str, Any]: ...
    async def list_messages(self, client_id: str) -> list[dict[str, Any]]: ...
    async def create_proposal_draft(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool, dry_run: bool = True
    ) -> dict[str, Any]: ...
    async def submit_proposal(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool
    ) -> dict[str, Any]: ...
    async def send_message(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool
    ) -> dict[str, Any]: ...


class GigSimAdapter:
    """Local fixture adapter; it is not the instructor's GigSim service."""

    async def search_jobs(self, query: str = "") -> list[dict[str, Any]]:
        if not isinstance(query, str) or len(query) > 500:
            raise ValueError("query must be text of at most 500 characters")
        terms = query.casefold().split()
        return [
            item
            for item in jobs()
            if not terms
            or all(term in f"{item['title']} {item['description']}".casefold() for term in terms)
        ]

    async def get_job(self, job_id: str) -> dict[str, Any]:
        if not job_id:
            raise ValueError("job_id cannot be empty")
        result = next((item for item in jobs() if item["job_id"] == job_id), None)
        if result is None:
            raise LookupError(f"Unknown sample job: {job_id}")
        return result

    async def get_client_history(self, client_id: str) -> dict[str, Any]:
        result = next((item for item in client_history() if item["client_id"] == client_id), None)
        if result is None:
            raise LookupError(f"Unknown sample client: {client_id}")
        return result

    async def get_connects_balance(self) -> dict[str, Any]:
        return {"balance": None, "source": "not_configured"}

    async def list_messages(self, client_id: str) -> list[dict[str, Any]]:
        if not client_id.strip():
            raise ValueError("client_id cannot be empty")
        return []

    async def create_proposal_draft(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool, dry_run: bool = True
    ) -> dict[str, Any]:
        if not approved:
            raise PermissionError("Human approval is required")
        if not idempotency_key or len(idempotency_key) < 8:
            raise ValueError("A valid idempotency key is required")
        if not dry_run:
            raise RuntimeError("The included sample adapter has no marketplace write endpoint")
        return {"preview": payload, "idempotency_key": idempotency_key, "external_write": False}

    async def submit_proposal(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool
    ) -> dict[str, Any]:
        del payload, idempotency_key
        if not approved:
            raise PermissionError("Human approval is required")
        raise RuntimeError("No simulator write endpoint is configured")

    async def send_message(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool
    ) -> dict[str, Any]:
        del payload, idempotency_key
        if not approved:
            raise PermissionError("Human approval is required")
        raise RuntimeError("No simulator message endpoint is configured")


class LocalGigSimRESTAdapter:
    """REST adapter for this repository's local simulator only."""

    def __init__(
        self,
        endpoint: str,
        access_token: str,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1", "gigsim"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Local GigSim endpoint must use an allowed local hostname over HTTP")
        if not access_token.strip():
            raise ValueError("Local GigSim bearer token is required")
        self.endpoint = endpoint.rstrip("/")
        self.access_token = access_token
        self.timeout = timeout
        self.transport = transport

    async def _request(
        self, method: str, path: str, *, params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None
    ) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.request(
                method,
                f"{self.endpoint}{path}",
                params=params,
                json=payload,
                headers={"Authorization": f"Bearer {self.access_token}"},
            )
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise TypeError("Local GigSim returned invalid JSON") from exc

    async def search_jobs(self, query: str = "") -> list[dict[str, Any]]:
        result = await self._request("GET", "/api/jobs", params={"query": query})
        if not isinstance(result, list):
            raise TypeError("Local GigSim search returned an invalid result")
        return result

    async def get_job(self, job_id: str) -> dict[str, Any]:
        result = await self._request("GET", f"/api/jobs/{quote(job_id, safe='')}")
        if not isinstance(result, dict):
            raise TypeError("Local GigSim get_job returned an invalid result")
        return result

    async def get_client_history(self, client_id: str) -> dict[str, Any]:
        result = await self._request("GET", f"/api/clients/{client_id}/history")
        if not isinstance(result, dict):
            raise TypeError("Local GigSim client history returned an invalid result")
        return result

    async def get_connects_balance(self) -> dict[str, Any]:
        result = await self._request("GET", "/api/connects")
        if not isinstance(result, dict):
            raise TypeError("Local GigSim Connects response is invalid")
        return result

    async def list_messages(self, client_id: str) -> list[dict[str, Any]]:
        result = await self._request(
            "GET", f"/api/clients/{quote(client_id, safe='')}/messages"
        )
        if not isinstance(result, list):
            raise TypeError("Local GigSim messages response is invalid")
        return result

    async def create_proposal_draft(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool, dry_run: bool = True
    ) -> dict[str, Any]:
        if not approved:
            raise PermissionError("Human approval is required")
        if dry_run:
            return {
                "preview": payload,
                "idempotency_key": idempotency_key,
                "external_write": False,
            }
        return await self.submit_proposal(payload, idempotency_key, approved)

    async def submit_proposal(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool
    ) -> dict[str, Any]:
        if not approved:
            raise PermissionError("Human approval is required")
        return await self._request(
            "POST",
            "/api/proposals",
            payload={**payload, "idempotency_key": idempotency_key, "approved": True},
        )

    async def send_message(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool
    ) -> dict[str, Any]:
        if not approved:
            raise PermissionError("Human approval is required")
        return await self._request(
            "POST",
            "/api/messages",
            payload={**payload, "idempotency_key": idempotency_key, "approved": True},
        )


class UpworkMCPAdapter:
    """Official MCP client adapter; requires an OAuth access token obtained by the user."""

    def __init__(self, endpoint: str, access_token: str):
        if not endpoint.startswith("https://"):
            raise ValueError("Upwork MCP endpoint must use HTTPS")
        if not access_token.strip():
            raise ValueError("Upwork OAuth access token is required")
        self.endpoint = endpoint
        self.access_token = access_token
        self._client = None

    async def _get_tool(self, name: str):
        if self._client is None:
            try:
                from langchain_mcp_adapters.client import MultiServerMCPClient
            except ImportError as exc:
                raise RuntimeError(
                    "Install langchain-mcp-adapters to use the live adapter"
                ) from exc
            self._client = MultiServerMCPClient(
                {
                    "upwork": {
                        "transport": "streamable_http",
                        "url": self.endpoint,
                        "headers": {"Authorization": f"Bearer {self.access_token}"},
                    }
                }
            )
        tools = await self._client.get_tools()
        tool = next((candidate for candidate in tools if candidate.name == name), None)
        if tool is None:
            raise RuntimeError(f"Configured Upwork server does not expose required tool: {name}")
        return tool

    async def _call(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        tool = await self._get_tool(tool_name)
        return await tool.ainvoke(arguments)

    async def search_jobs(self, query: str = "") -> list[dict[str, Any]]:
        result = await self._call("search_jobs", {"query": query})
        if not isinstance(result, list):
            raise TypeError("Upwork search_jobs returned an invalid result")
        return result

    async def get_job(self, job_id: str) -> dict[str, Any]:
        result = await self._call("get_job", {"job_id": job_id})
        if not isinstance(result, dict):
            raise TypeError("Upwork get_job returned an invalid result")
        return result

    async def get_client_history(self, client_id: str) -> dict[str, Any]:
        result = await self._call("get_client_history", {"client_id": client_id})
        if not isinstance(result, dict):
            raise TypeError("Upwork client history returned an invalid result")
        return result

    async def get_connects_balance(self) -> dict[str, Any]:
        result = await self._call("get_connects_balance", {})
        if not isinstance(result, dict):
            raise TypeError("Upwork Connects balance returned an invalid result")
        return result

    async def list_messages(self, client_id: str) -> list[dict[str, Any]]:
        result = await self._call("list_messages", {"client_id": client_id})
        if not isinstance(result, list):
            raise TypeError("Upwork list_messages returned an invalid result")
        return result

    async def create_proposal_draft(
        self, payload: dict[str, Any], idempotency_key: str, approved: bool, dry_run: bool = True
    ) -> dict[str, Any]:
        if not approved:
            raise PermissionError("Human approval is required")
        if not idempotency_key or len(idempotency_key) < 8:
            raise ValueError("A valid idempotency key is required")
        # Live write tool names and payload shape must be checked against the user's OAuth tool list.
        if not dry_run:
            raise RuntimeError(
                "Live write is deliberately disabled until OAuth/tool scopes are verified"
            )
        return {"preview": payload, "idempotency_key": idempotency_key, "external_write": False}


def create_marketplace_port() -> MarketplacePort:
    mode = os.getenv("GIGBID_MARKETPLACE_MODE", "gigsim").casefold()
    if mode == "gigsim":
        endpoint = os.getenv("GIGSIM_BASE_URL", "").strip()
        if endpoint:
            return LocalGigSimRESTAdapter(
                endpoint,
                os.getenv("GIGSIM_API_TOKEN", "local-gigsim-token"),
            )
        return GigSimAdapter()
    if mode == "upwork":
        return UpworkMCPAdapter(
            os.getenv("UPWORK_MCP_URL", "https://mcp.upwork.com/mcp"),
            os.getenv("UPWORK_ACCESS_TOKEN", ""),
        )
    raise ValueError("GIGBID_MARKETPLACE_MODE must be 'gigsim' or 'upwork'")

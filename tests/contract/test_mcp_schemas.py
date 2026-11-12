from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers.marketplace import server as marketplace_server
from mcp_servers.portfolio import server as portfolio_server
from mcp_servers.workspace import server as workspace_server

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "tests" / "contract" / "mcp_tool_schemas.json"
SERVERS = {
    "marketplace": marketplace_server.mcp,
    "portfolio": portfolio_server.mcp,
    "workspace": workspace_server.mcp,
}


async def _server_snapshot(server: Any) -> dict[str, Any]:
    async with create_connected_server_and_client_session(server) as session:
        result = await session.list_tools()
    return {
        tool.name: {
            "description": tool.description,
            "input_schema": tool.inputSchema,
            "annotations": (
                tool.annotations.model_dump(exclude_none=True) if tool.annotations else None
            ),
        }
        for tool in result.tools
    }


async def _snapshot() -> dict[str, Any]:
    return {name: await _server_snapshot(server) for name, server in SERVERS.items()}


def test_mcp_tool_signatures_match_contract_snapshot():
    actual = asyncio.run(_snapshot())
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert actual == expected


def test_mcp_tools_work_over_in_memory_transport(monkeypatch):
    write_calls: list[str] = []

    class FakeMarketplace:
        async def search_jobs(self, query: str = "") -> list[dict[str, Any]]:
            return [{"job_id": "mcp-test-job", "query": query}]

        async def get_job(self, job_id: str) -> dict[str, Any]:
            return {"job_id": job_id, "client_id": "mcp-test-client"}

        async def submit_proposal(
            self, payload: dict[str, Any], idempotency_key: str, approved: bool
        ) -> dict[str, Any]:
            write_calls.append("submit_proposal")
            return {"idempotency_key": idempotency_key, "payload": payload}

        async def create_proposal_draft(
            self,
            payload: dict[str, Any],
            idempotency_key: str,
            approved: bool,
            *,
            dry_run: bool = True,
        ) -> dict[str, Any]:
            write_calls.append("create_proposal_draft")
            return {"idempotency_key": idempotency_key, "payload": payload}

        async def send_message(
            self, payload: dict[str, Any], idempotency_key: str, approved: bool
        ) -> dict[str, Any]:
            write_calls.append("send_message")
            return {"idempotency_key": idempotency_key, "payload": payload}

    monkeypatch.setattr(marketplace_server, "create_marketplace_port", FakeMarketplace)

    async def exercise_tools() -> None:
        async with create_connected_server_and_client_session(
            marketplace_server.mcp
        ) as session:
            search = await session.call_tool(
                "marketplace_search_jobs", {"query": "python"}
            )
            assert search.isError is False
            assert "mcp-test-job" in str(search.content)

            rejected = await session.call_tool(
                "marketplace_submit_proposal",
                {
                    "job_id": "mcp-test-job",
                    "cover_letter": "A grounded proposal.",
                    "evidence_ids": ["evidence-001"],
                    "amount": 100,
                    "idempotency_key": "mcp-test-key",
                    "approved": False,
                    "dry_run": False,
                },
            )
            assert rejected.isError is True

            approved_but_direct = await session.call_tool(
                "marketplace_submit_proposal",
                {
                    "job_id": "mcp-test-job",
                    "cover_letter": "A grounded proposal.",
                    "evidence_ids": ["evidence-001"],
                    "amount": 100,
                    "idempotency_key": "mcp-test-key",
                    "approved": True,
                    "dry_run": False,
                },
            )
            assert approved_but_direct.isError is True
            assert "approval workflow" in str(approved_but_direct.content)

            draft_write = await session.call_tool(
                "marketplace_create_proposal_draft",
                {
                    "job_id": "mcp-test-job",
                    "cover_letter": "A grounded proposal.",
                    "evidence_ids": ["evidence-001"],
                    "amount": 100,
                    "idempotency_key": "mcp-draft-key",
                    "approved": True,
                    "dry_run": False,
                },
            )
            assert draft_write.isError is True

            message_write = await session.call_tool(
                "marketplace_send_message",
                {
                    "client_id": "mcp-test-client",
                    "job_id": "mcp-test-job",
                    "message": "A reviewed reply.",
                    "idempotency_key": "mcp-message-key",
                    "approved": True,
                    "dry_run": False,
                },
            )
            assert message_write.isError is True
            assert write_calls == []

    asyncio.run(exercise_tools())

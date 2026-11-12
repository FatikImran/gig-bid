from __future__ import annotations

import asyncio
import os
from typing import Any

AGENT_TOOL_ALLOWLISTS = {
    "scout": {"marketplace_search_jobs", "marketplace_get_job"},
    "analyst": set(),
    "risk_assessor": {"marketplace_get_client_history", "marketplace_get_job"},
    "fit_matcher": {
        "search_portfolio_evidence",
        "get_case_study_tool",
        "workspace_available_slots",
        "github_search_code",
        "github_get_file_contents",
    },
    "pricing": {"marketplace_search_jobs", "marketplace_get_connects_balance"},
    "writer": {
        "search_portfolio_evidence",
        "get_case_study_tool",
        "github_search_code",
        "github_get_file_contents",
    },
    "critic": {"search_portfolio_evidence", "get_case_study_tool"},
    "compliance": set(),
    "client_liaison": {
        "marketplace_list_messages",
        "workspace_available_slots",
        "workspace_create_email_draft",
    },
}


async def tools_for_agent(agent_name: str) -> list[Any]:
    if agent_name not in AGENT_TOOL_ALLOWLISTS:
        raise ValueError(f"Unknown agent: {agent_name}")
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as exc:
        raise RuntimeError("langchain-mcp-adapters is required to connect MCP servers") from exc
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    servers = {
        "portfolio": {
            "transport": "stdio",
            "command": os.getenv("PYTHON", "python"),
            "args": [os.path.join(root, "mcp_servers", "portfolio", "server.py")],
        },
        "marketplace": {
            "transport": "stdio",
            "command": os.getenv("PYTHON", "python"),
            "args": [os.path.join(root, "mcp_servers", "marketplace", "server.py")],
        },
        "workspace": {
            "transport": "stdio",
            "command": os.getenv("PYTHON", "python"),
            "args": [os.path.join(root, "mcp_servers", "workspace", "server.py")],
        },
    }
    github_url = os.getenv("GITHUB_MCP_URL", "").strip()
    github_token = os.getenv("GITHUB_MCP_TOKEN", "").strip()
    if github_url or github_token:
        if not github_url.startswith("https://") or not github_token:
            raise ValueError("GITHUB_MCP_URL and GITHUB_MCP_TOKEN must both be configured over HTTPS")
        servers["github"] = {
            "transport": "streamable_http",
            "url": github_url,
            "headers": {"Authorization": f"Bearer {github_token}"},
        }
    client = MultiServerMCPClient(servers)
    all_tools = await asyncio.wait_for(client.get_tools(), timeout=10)
    allowed = AGENT_TOOL_ALLOWLISTS[agent_name]
    return [tool for tool in all_tools if tool.name in allowed]

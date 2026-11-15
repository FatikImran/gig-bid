"""Authorize a local GigBid client and inspect Upwork's account-specific MCP schema."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sqlite3
import sys
import webbrowser
from contextlib import closing
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from time import monotonic
from urllib.parse import parse_qs, urlsplit

import httpx
from cryptography.fernet import Fernet, InvalidToken
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp.client.auth import OAuthClientProvider
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken
from mcp.types import TextContent

UPWORK_MCP_URL = "https://mcp.upwork.com/mcp"
CALLBACK_HOST = "127.0.0.1"
CALLBACK_PORT = 8765
CALLBACK_PATH = "/callback"
CALLBACK_URL = f"http://{CALLBACK_HOST}:{CALLBACK_PORT}{CALLBACK_PATH}"
LOCAL_TENANT = "local-user"
TOOL_HELP_NAMES = (
    "find_jobs",
    "get_profile",
    "list_freelancer_proposals",
    "manage_proposals",
    "get_messages",
    "send_message",
)


class EncryptedOAuthStorage:
    """MCP SDK storage for one tenant's Upwork tokens and client registration."""

    def __init__(self, database: Path, tenant_id: str, key: str | bytes):
        self.database = database
        self.tenant_id = tenant_id
        self.cipher = Fernet(key)
        database.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(database)) as conn, conn:
            conn.execute(
                """CREATE TABLE IF NOT EXISTS upwork_oauth (
                    tenant_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    ciphertext BLOB NOT NULL,
                    PRIMARY KEY (tenant_id, kind)
                )"""
            )

    def _load(self, kind: str) -> str | None:
        with closing(sqlite3.connect(self.database)) as conn:
            row = conn.execute(
                "SELECT ciphertext FROM upwork_oauth WHERE tenant_id = ? AND kind = ?",
                (self.tenant_id, kind),
            ).fetchone()
        if row is None:
            return None
        try:
            tenant_id, stored_kind, value = json.loads(self.cipher.decrypt(row[0]))
        except InvalidToken:
            raise ValueError(
                "The Upwork OAuth store could not be decrypted with this key."
            ) from None
        if (tenant_id, stored_kind) != (self.tenant_id, kind):
            raise ValueError(
                "The Upwork OAuth record belongs to a different tenant or credential type."
            )
        return value

    def _save(self, kind: str, value: str) -> None:
        ciphertext = self.cipher.encrypt(json.dumps([self.tenant_id, kind, value]).encode())
        with closing(sqlite3.connect(self.database)) as conn, conn:
            conn.execute(
                """INSERT INTO upwork_oauth (tenant_id, kind, ciphertext) VALUES (?, ?, ?)
                ON CONFLICT (tenant_id, kind) DO UPDATE SET ciphertext = excluded.ciphertext""",
                (self.tenant_id, kind, ciphertext),
            )

    async def get_tokens(self) -> OAuthToken | None:
        value = self._load("tokens")
        return OAuthToken.model_validate_json(value) if value is not None else None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._save("tokens", tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        value = self._load("client")
        return OAuthClientInformationFull.model_validate_json(value) if value is not None else None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._save("client", client_info.model_dump_json())


class LoopbackCallback(HTTPServer):
    def __init__(self, port: int = CALLBACK_PORT):
        super().__init__((CALLBACK_HOST, port), CallbackHandler)
        self.timeout = 0.25
        self.expected_state: str | None = None
        self.callback: tuple[str, str] | None = None
        self.denied = False

    async def redirect(self, url: str) -> None:
        target = urlsplit(url)
        states = parse_qs(target.query).get("state", [])
        if (target.scheme, target.netloc) != ("https", "www.upwork.com") or len(states) != 1:
            raise RuntimeError("Unexpected Upwork authorization redirect.")
        self.expected_state = states[0]
        print("Complete the sign-in and consent request in your browser.", file=sys.stderr)
        if not await asyncio.to_thread(webbrowser.open, url):
            raise RuntimeError("Could not open your default browser.")

    async def receive(self) -> tuple[str, str]:
        deadline = monotonic() + 180
        while self.callback is None and not self.denied and monotonic() < deadline:
            await asyncio.to_thread(self.handle_request)
        if self.denied:
            raise PermissionError("Upwork authorization was declined or rejected.")
        if self.callback is None:
            raise TimeoutError("The Upwork OAuth callback did not arrive within three minutes.")
        return self.callback


class CallbackHandler(BaseHTTPRequestHandler):
    server: LoopbackCallback
    timeout = 2

    def log_message(self, _format: str, *args: object) -> None:
        # The callback path includes an authorization code and state.
        return

    def do_GET(self) -> None:
        target = urlsplit(self.path)
        query = parse_qs(target.query)
        states = query.get("state", [])
        codes = query.get("code", [])
        if (
            target.path != CALLBACK_PATH
            or self.server.expected_state is None
            or len(states) != 1
            or not states[0].isascii()
            or not secrets.compare_digest(states[0], self.server.expected_state)
        ):
            self.send_error(400, "Invalid Upwork OAuth callback")
            return

        self.server.expected_state = None
        if len(codes) != 1 or "error" in query:
            self.server.denied = True
            self.send_error(400, "Upwork authorization was declined or rejected")
            return

        self.server.callback = (codes[0], states[0])
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(
            b"Authorization received. Return to the GigBid terminal to see the result."
        )


def create_upwork_client(
    storage: EncryptedOAuthStorage, callback: LoopbackCallback | None = None
) -> MultiServerMCPClient:
    auth = OAuthClientProvider(
        server_url=UPWORK_MCP_URL,
        client_metadata=OAuthClientMetadata(
            redirect_uris=[CALLBACK_URL], token_endpoint_auth_method="none", client_name="GigBid"
        ),
        storage=storage,
        redirect_handler=callback.redirect if callback else None,
        callback_handler=callback.receive if callback else None,
    )
    return MultiServerMCPClient(
        {"upwork": {"transport": "streamable_http", "url": UPWORK_MCP_URL, "auth": auth}}
    )


async def inspect_tools(storage: EncryptedOAuthStorage, tool_help: list[str]) -> None:
    with LoopbackCallback() as callback:
        client = create_upwork_client(storage, callback)
        async with asyncio.timeout(240), client.session("upwork") as session:
            tools = []
            page = await session.list_tools()
            tools.extend(page.tools)
            while page.nextCursor:
                page = await session.list_tools(cursor=page.nextCursor)
                tools.extend(page.tools)

            if tool_help:
                help_tool = next(
                    (
                        tool.name
                        for tool in tools
                        if tool.name in {"upwork__get_tool_help", "get_tool_help"}
                    ),
                    None,
                )
                if help_tool is None:
                    raise RuntimeError("Upwork did not advertise a tool-help endpoint.")
                schemas = {}
                for name in tool_help:
                    result = await session.call_tool(help_tool, {"tool_name": name})
                    if result.isError:
                        raise RuntimeError(f"Upwork did not return tool help for {name}.")
                    help_text = "\n".join(
                        item.text for item in result.content if isinstance(item, TextContent)
                    )
                    schemas[name] = result.structuredContent or help_text
                print(json.dumps(schemas, indent=2))
                return

            print(
                json.dumps(
                    [tool.model_dump(mode="json", by_alias=True) for tool in tools], indent=2
                )
            )


def error_kind(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        return ", ".join(error_kind(child) for child in error.exceptions)
    if isinstance(error, httpx.HTTPStatusError):
        return f"HTTP {error.response.status_code}"
    return type(error).__name__


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tool-help",
        action="append",
        default=[],
        choices=TOOL_HELP_NAMES,
        help="Inspect an official tool's action schema. Repeat for multiple tools.",
    )
    args = parser.parse_args()
    key = os.getenv("GIGBID_OAUTH_ENCRYPTION_KEY", "")
    if not key:
        parser.error("Set GIGBID_OAUTH_ENCRYPTION_KEY first. See docs/UPWORK_SETUP.md.")
    path = Path(os.getenv("GIGBID_DB_PATH", "data/processed/gigbid.sqlite3"))
    try:
        storage = EncryptedOAuthStorage(path, LOCAL_TENANT, key)

        # Check the key before contacting Upwork or attempting any new registration.
        async def run() -> None:
            await storage.get_tokens()
            await storage.get_client_info()
            await inspect_tools(storage, args.tool_help)

        asyncio.run(run())
    # Provider messages can embed OAuth credentials. Print types and HTTP status codes only.
    except Exception as exc:  # noqa: BLE001
        print(
            f"Upwork MCP connection failed ({error_kind(exc)}). See docs/UPWORK_SETUP.md.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

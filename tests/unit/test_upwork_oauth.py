import asyncio

import httpx
import pytest
from cryptography.fernet import Fernet
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from agent.upwork_oauth import EncryptedOAuthStorage, LoopbackCallback


@pytest.mark.asyncio
async def test_oauth_credentials_are_encrypted_and_tenant_scoped(tmp_path):
    database = tmp_path / "oauth.sqlite3"
    key = Fernet.generate_key()
    storage = EncryptedOAuthStorage(database, "tenant-a", key)
    tokens = OAuthToken(access_token="sample-access-token", refresh_token="sample-refresh-token")
    registration = OAuthClientInformationFull(
        client_id="sample-client-id", client_secret="sample-client-secret", redirect_uris=None
    )
    await storage.set_tokens(tokens)
    await storage.set_client_info(registration)

    persisted = database.read_bytes()
    for value in (tokens.access_token, tokens.refresh_token, registration.client_secret):
        assert value.encode() not in persisted

    reopened = EncryptedOAuthStorage(database, "tenant-a", key)
    assert await reopened.get_tokens() == tokens
    assert await reopened.get_client_info() == registration
    assert await EncryptedOAuthStorage(database, "tenant-b", key).get_tokens() is None
    with pytest.raises(ValueError, match="could not be decrypted"):
        await EncryptedOAuthStorage(database, "tenant-a", Fernet.generate_key()).get_tokens()


@pytest.mark.asyncio
async def test_loopback_callback_requires_matching_oauth_state():
    with LoopbackCallback(port=0) as callback:
        callback.expected_state = "expected-state"
        host, port = callback.server_address
        received = asyncio.create_task(callback.receive())
        async with httpx.AsyncClient(base_url=f"http://{host}:{port}", timeout=4) as client:
            rejected = await client.get("/callback", params={"state": "wrong", "code": "bad"})
            assert rejected.status_code == 400
            assert not received.done()
            accepted = await client.get(
                "/callback", params={"state": "expected-state", "code": "sample-code"}
            )
            assert accepted.status_code == 200
            assert "sample-code" not in accepted.text
        assert await asyncio.wait_for(received, timeout=4) == ("sample-code", "expected-state")

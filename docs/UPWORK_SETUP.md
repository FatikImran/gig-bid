# Upwork MCP setup for GigBid

GigBid's local setup command uses the official Upwork MCP endpoint with Streamable HTTP, OAuth
authorization-code flow, PKCE, and a callback bound to `127.0.0.1:8765`. It stores the registration,
access token and refresh token encrypted in SQLite under the local user's tenant ID. It requests
tool schemas and does not apply to jobs, send messages, or spend Connects.

Upwork requires the account owner to sign in and consent. Upwork's FAQ currently says custom hosted
agents cannot register their callback URLs and that MCP does not accept Upwork API keys. Keep the
public Railway app in GigSim mode while using this local setup.

[Upwork MCP setup and FAQ](https://www.upwork.com/ai/mcp)

## Account owner steps on Windows

1. Sign in to an Upwork freelancer account in your default browser, or create an account if needed.
2. Open PowerShell in the GigBid repository. The packages are installed in this workspace's existing
   Python environment. On a fresh machine, run `python -m pip install -e ".[dev]"` first.
3. Generate a local encryption key and run the setup command in that terminal.

   ```powershell
   $env:GIGBID_OAUTH_ENCRYPTION_KEY = python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   python -m agent.upwork_oauth
   ```

4. Complete Upwork's consent screen. The command prints the advertised tools after connecting.
   Keep the same terminal for follow-up commands. If you need to reuse the encrypted store in a
   future session, save the key in your password manager and set it again with
   `$env:GIGBID_OAUTH_ENCRYPTION_KEY = Read-Host 'GigBid OAuth encryption key' -MaskInput` in
   PowerShell 7. The default database is `data/processed/gigbid.sqlite3`.
5. If setup succeeds, inspect the live action schemas for the freelancer workflow.

   ```powershell
   python -m agent.upwork_oauth --tool-help find_jobs
   python -m agent.upwork_oauth --tool-help manage_proposals
   python -m agent.upwork_oauth --tool-help send_message
   ```

   Share only tool names and parameter schemas, or the exact error text with credentials and URLs
   containing OAuth query parameters removed. Keep the encryption key, `code`, access token,
   refresh token, account identifiers, and browser cookies private.

## If the authorization page resets

If the browser shows `upstream connect error` while it is still on `www.upwork.com`, the local
callback has not run. Stop the waiting command with **Ctrl+C**, close that authorization tab, and
check that normal Upwork sign-in works in the same browser. Then run `python -m agent.upwork_oauth`
again in the same PowerShell window. Reuse the existing encryption key. The command generates a
fresh OAuth request and opens a new tab.

If normal sign-in also fails, use [Upwork's troubleshooting guide](https://support.upwork.com/hc/en-us/articles/52410257170835-Upwork-Troubleshooting-Guide-How-to-fix-technical-issues)
to check the browser or network. If normal sign-in works but the authorization page resets again,
send the error text and timestamp with the query string removed. An OAuth error shown on
`www.upwork.com` and a connection error after redirecting to `127.0.0.1` point to different stages.

## Verification and deployment

- If port `8765` is in use, close the program using it and rerun the command. If Upwork rejects
  registration or the callback, capture the rejection message. A provider-side rejection needs
  Upwork support or the instructor's guidance for grading A4.
- Disconnect from Upwork under **Account Settings → Connected Apps** if you want to revoke consent.
- The setup command establishes the OAuth and discovery path. The FastAPI/React live workflow still
  needs role and account selection, mapping the authenticated tool schemas to the marketplace port,
  and end-to-end verification. Do not switch Railway to Upwork mode for this step.
- Upwork's proposal workflow returns a preview after the draft action. GigBid must show that
  preview after its own approval step and leave the final confirmation with the account owner.
  Confirm messaging semantics against the authenticated schema before enabling any live message
  action.

[Official Upwork MCP workflow](https://github.com/upwork/upwork-agent-plugin/tree/master/skills/upwork-workflows)

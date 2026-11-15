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
   python -m agent.upwork_oauth --tool-help find_jobs --tool-help get_profile --tool-help list_freelancer_proposals --tool-help manage_proposals --tool-help get_messages --tool-help send_message > data/processed/upwork-tool-help.json
   ```

   The command requests the tool schemas in one MCP session. Share only tool names and parameter
   schemas, or the exact error text with credentials and URLs
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

## Preview an owner-approved proposal locally

The terminal workflow loads `data/processed/upwork-portfolio.json`, which is Git-ignored. Start it
in the same PowerShell session used to authorize Upwork. To see the available evidence IDs, run:

```powershell
python -m agent.live_proposal --list-evidence
```

Choose a relevant listing, a portfolio project that matches it, and your own bid. Set `--unit` to
`hourly` or `fixed` to match the listing. This example uses placeholders for the URL and bid:

```powershell
python -m agent.live_proposal "YOUR_UPWORK_LISTING_URL" --evidence owner-raahnuma --bid YOUR_BID --unit hourly
```

Review the cover letter and exact bid. Type `PREVIEW` only if you want those details sent to
Upwork for preview. GigBid checks previous proposals and invitations before calling the preview
tool. It displays Upwork's response locally. The workflow stops before submission confirmation.
Upwork may ask for screening answers or other application details. Keep the preview payload and
IDs private, and share only the outcome or a sanitized error when reporting a test.

If the prior-application check fails, run `python -m agent.live_proposal "UPWORK_JOB_ID" --preflight-only`
to check the listing, invitations, and previous proposals without sending a cover letter or
requesting a preview. Error diagnostics include field names only.

To find a candidate that Upwork marks eligible, run `python -m agent.live_proposal --find-eligible "n8n workflow automation"`.
The command checks up to three listings and falls back to recent listings once if Upwork's
keyword search reports an upstream error. Pass `--find-eligible` alone to go straight to recent
listings. These checks perform read operations only.

### Approve in the web app

In the PowerShell terminal with your Upwork OAuth encryption key, start the API with a temporary
local bearer token:

```powershell
$env:GIGBID_MARKETPLACE_MODE = 'upwork'
$env:GIGBID_API_TOKEN = python -c "import secrets; print(secrets.token_urlsafe(32))"
$env:GIGBID_CORS_ORIGINS = 'http://127.0.0.1:5173'
$env:GIGBID_API_TOKEN
python -m uvicorn apps.api.main:app --host 127.0.0.1 --port 8000
```

From a second project terminal, run:

```powershell
$env:VITE_API_URL = 'http://127.0.0.1:8000'
npm.cmd --prefix apps/web run dev -- --host 127.0.0.1 --port 5173 --strictPort
```

Open the local UI at `http://127.0.0.1:5173`, enter the temporary API token, and search the inbox.
Open a listing, choose an evidence project, enter your bid, and prepare a draft. Save any cover
letter edits before clicking **Approve and request Upwork preview**. GigBid displays the available
preview details and opens the listing for further review on Upwork. The app has no submission
confirmation action. Some applications need screening answers or additional terms, which this web
preview workflow reports so you can review them on Upwork.

### Prepare a reply for Upwork Messages

Open **Messages** in the local app and paste a message you received. Draft and review the reply,
then approve it to enable **Copy approved reply**. Open the original conversation in Upwork to
paste, review, and decide whether to send. Upwork MCP can send messages directly, so GigBid uses a
manual handoff for draft-only messaging.

## Verification and deployment

- In the same PowerShell window, run `python -m agent.upwork_marketplace` to verify job search and
  one job detail. The command reports counts and field availability. If your login expires, rerun
  `python -m agent.upwork_oauth` in that terminal to renew authorization.
- To test the inbox in a real browser automatically, run `npm.cmd --prefix apps/web run test:upwork`
  in the same terminal. Playwright starts a loopback API and web server, signs in with a temporary
  local bearer token, checks the listing grid, and opens one listing through the live API. The test
  reads listings and does not save screenshots or traces. If Chromium is missing, run
  `npm.cmd --prefix apps/web exec -- playwright install chromium` first.
- To browse live listings in the local web app, set `$env:GIGBID_MARKETPLACE_MODE = 'upwork'` and
  start the API bound to localhost from the authorized terminal. Set a private `GIGBID_API_TOKEN`
  for that session and use it in the local UI. The live browser view shows job details without
  generating recommendations or drafts from the synthetic personas. Live proposal previews use
  the local owner portfolio and an explicit approval.
- If port `8765` is in use, close the program using it and rerun the command. If Upwork rejects
  registration or the callback, capture the rejection message. A provider-side rejection needs
  Upwork support or the instructor's guidance for grading A4.
- Disconnect from Upwork under **Account Settings → Connected Apps** if you want to revoke consent.
- GigBid automatically selects one eligible freelancer profile. If your Upwork account returns more
  than one eligible profile, supply the intended freelancer organization ID in `UPWORK_ORG_UID` in
  your local session. Keep Railway in GigSim mode.
- Upwork's proposal workflow returns a preview after the draft action. GigBid must show that
  preview after its own approval step and leave the final confirmation with the account owner.
  The authenticated `send_message` schema sends directly. GigBid's live flow keeps messages local
  until a draft-only workflow is available.

[Official Upwork MCP workflow](https://github.com/upwork/upwork-agent-plugin/tree/master/skills/upwork-workflows)

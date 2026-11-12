# MCP tool inventory

All owned MCP servers use the official Python SDK `FastMCP` and are launchable with
`python -m mcp_servers.<name>.server`. They run over stdio for local development. Tools are typed,
bounded, and annotated; CI snapshots their input schemas and annotations. The application API is
bearer-token protected. The local Marketplace MCP server now uses the same configured
`MarketplacePort` as the API and can read from the local simulator. Its write-intent tools default
to dry-run and reject every non-dry-run call—even one carrying `approved=true`—so a direct MCP call
cannot bypass the authenticated API's persistent human-approval interrupt. Agents do not receive
marketplace write tools in their allowlists. The API can then invoke the local simulator after the
user approves a proposal or message; the instructor-provided GigSim service is not included.

| Tool | Server | Access | Annotations | Authentication | Behavior |
|---|---|---|---|---|---|
| `search_portfolio_evidence` | Portfolio | Read | Read-only, idempotent | Local stdio | Retrieve sample evidence with metadata and score |
| `get_case_study_tool` | Portfolio | Read | Read-only, idempotent | Local stdio | Load a full case by evidence ID |
| `list_portfolio_skills` | Portfolio | Read | Read-only, idempotent | Local stdio | List skills present in sample profile |
| `marketplace_search_jobs` | Marketplace | Read | Read-only, idempotent | Local stdio; upstream adapter auth | Search via configured marketplace port |
| `marketplace_get_job` | Marketplace | Read | Read-only, idempotent | Local stdio; upstream adapter auth | Read a job through the configured port |
| `marketplace_get_client_history` | Marketplace | Read | Read-only, idempotent | Local stdio; upstream adapter auth | Read synthetic or upstream client history |
| `marketplace_get_connects_balance` | Marketplace | Read | Read-only, idempotent | Local stdio; upstream adapter auth | Read configured balance or not-configured result |
| `marketplace_list_messages` | Marketplace | Read | Read-only, idempotent | Local stdio; upstream adapter auth | List messages through configured port |
| `marketplace_create_proposal_draft` | Marketplace | Write intent | Not read-only, destructive, idempotent | Human approval field; no live auth | Dry-run preview; non-dry-run is rejected |
| `marketplace_submit_proposal` | Marketplace | Write intent | Not read-only, destructive, idempotent | Human approval field; no live auth | Dry-run only; non-dry-run is rejected |
| `marketplace_send_message` | Marketplace | Write intent | Not read-only, destructive, idempotent | Human approval field; no live auth | Dry-run only; non-dry-run is rejected |
| `workspace_available_slots` | Workspace | Read | Read-only, idempotent | Local stdio | Sample UTC availability |
| `workspace_create_tentative_hold` | Workspace | Write | Not read-only, non-destructive, non-idempotent | Explicit approval bool | In-memory hold only |
| `workspace_create_email_draft` | Workspace | Write | Not read-only, non-destructive, non-idempotent | Local stdio | Local draft only; never sends |

`portfolio://case/{case_id}` is a resource template; the server also includes the
“Answer a screening question” prompt. In-memory MCP calls and schema snapshot tests are under
`tests/contract/test_mcp_schemas.py`; the snapshot is
[`tests/contract/mcp_tool_schemas.json`](../tests/contract/mcp_tool_schemas.json). The optional
Portfolio MCP checkout/install instructions are in
[`mcp_servers/portfolio/README.md`](../mcp_servers/portfolio/README.md). The optional
GitHub server is the official GitHub MCP endpoint; its trust rationale is that it is the first-party
repository API integration, but access is disabled unless an owner supplies a read-scoped token.
The client filters all tools by agent allowlist and only grants GitHub code/file reads to the
Fit Matcher and Writer. For the official Upwork MCP server, configure `UPWORK_MCP_URL` and an
OAuth-issued `UPWORK_ACCESS_TOKEN`; live writes remain disabled until the owner completes OAuth
and verifies the upstream tool schemas and draft-confirmation semantics.

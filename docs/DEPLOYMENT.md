# Deployment and service setup guide

## Recommendation

For this assignment prototype, use **Railway** only after connecting a private GitHub repository:
it can host Docker-based API/worker services, persistent storage, environment variables, and a
public web endpoint in one project. For a production multi-user product, do not deploy this
single-token SQLite prototype as-is; first add real identity/OAuth, move application state and
checkpoints to managed Postgres, and store tenant secrets in a managed secret store.

Deployment cannot be completed from this workspace: it has no public GitHub remote, Railway/Render
account, domain, GitHub token, Upwork OAuth app, or reviewer credentials. Never paste such secrets
into this chat or commit them.

## Before making a public link

1. Create a private GitHub repository and push the source; change it to public only when you have
   reviewed the data and secrets.
2. Replace the development token. Generate a long random token locally and keep it in a password
   manager. The reviewer token should be delivered only in the private classroom submission comment.
3. Configure HTTPS and set `GIGBID_API_TOKEN`, `GIGBID_DB_PATH`, and exact
   `GIGBID_CORS_ORIGINS` in the host's secret/environment settings.
4. Attach persistent storage at `/app/data/processed` for the API, verify API and LangGraph SQLite
   checkpoints survive restart, and keep only one API replica while SQLite is used.
5. Build the React app with `VITE_API_URL=https://<your-api-domain>` and publish `apps/web/dist`.
6. Confirm the UI can log in with the reviewer token, inspect the sample job and resume an approved
   graph after restart. Approval is local-only; do not describe it as a marketplace submission.
7. Leave the service online through grading and monitor the host's health checks and logs. Avoid
   recording tokens or client message bodies.

## Railway service layout

1. Create a Railway project and connect the repository.
2. Add an API service using `infra/docker/api.Dockerfile`, root build context, and start command
   `uvicorn apps.api.main:app --host 0.0.0.0 --port $PORT`. Add a persistent volume mounted at
   `/app/data/processed`; set the variables above.
3. Add a worker service using the same API image and start command `python -m worker.scout`. Set
   `GIGBID_API_URL` to the internal API service URL and share a persistent filesystem only if the
   platform supports safe single-writer SQLite access. Otherwise disable the worker and run one
   local/manual scouting cycle.
4. Add a static web service or use `infra/docker/web.Dockerfile`; configure API CORS to the exact
   public UI origin. Keep the token out of static build variables.
5. Enable the API `/health` probe; test both normal and interrupted approval states after a redeploy.

Do not configure the Upwork adapter until its official OAuth flow and scopes are completed by the
account owner. The current live adapter accepts an OAuth access token supplied by environment but
does not implement the OAuth authorization/callback flow or live writes. The Docker Compose
`gigsim` service is our local deterministic simulator, not the instructor's service. Its
synthetic outcomes and Connects are not suitable as production or hidden-test results.

## Other services and manual steps

- **Database:** local SQLite is included. For public multi-user deployment, migrate proposal,
  checkpoint, idempotency, audit, and memory stores together to managed Postgres and validate
  transaction/checkpointer behavior. There is no migration script in this prototype.
- **Redis/worker queue:** not required by the local worker; the worker polls at least every 15
  minutes and keeps its seen IDs in SQLite. A production queue and separate tenant-safe scheduler
  are not wired.
- **Model provider:** the shipped open profile is deterministic local code and does not require an
  API key. No paid provider is configured, and no LLM inference costs were incurred in the measured
  smoke test.
- **GitHub MCP:** add a separately installed official GitHub MCP server with a narrowly scoped
  read-only token before using it. It is not configured in the provided starter tree.
- **Observability:** local trace IDs and audit events exist. LangSmith/Langfuse credentials are not
  configured. Enable a hosted trace exporter only after PII masking tests and retention policy are
  reviewed.
- **Reviewer login:** the current UI asks for a bearer token; this is a single shared reviewer
  credential, not multi-user authentication. Generate and share it privately after deployment.

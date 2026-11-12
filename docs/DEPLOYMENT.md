# Deployment and service setup guide

## Recommendation

The assignment prototype is deployed on Railway:

- **Web:** https://genuine-art-production.up.railway.app/
- **API health:** https://gig-bid-production.up.railway.app/health
- **Source:** https://github.com/FatikImran/gig-bid

The hosted app uses bundled synthetic examples, a shared API bearer token, and SQLite. It is not a
production multi-user service, is not connected to the instructor's GigSim or hidden data, and does
not submit to Upwork. Keep the reviewer token out of Git and provide it only in the private
Classroom submission comment.

## Railway service layout

The deployed services use the repository root as the build context:

1. **API:** Dockerfile path `infra/docker/api.Dockerfile`; start command
   `uvicorn apps.api.main:app --host 0.0.0.0 --port 8000`; persistent volume mounted at
   `/app/data/processed`; health path `/health`. Set `GIGBID_DB_PATH=/app/data/processed/gigbid.sqlite3`,
   a strong `GIGBID_API_TOKEN`, and `GIGBID_USE_KAGGLE_FEED=false` (the processed Kaggle seed is not
   committed).
2. **Web:** Dockerfile path `infra/docker/web.Dockerfile`; set `VITE_API_URL` to the public API URL
   as a build variable. `VITE_API_URL` is passed to Vite through the Dockerfile build argument.
   Generate the web domain on port `80`.
3. Set `GIGBID_CORS_ORIGINS` on the API to the exact web origin, with no trailing slash, then
   redeploy the API. Its public domain routes to port `8000`.
4. Keep the API at one replica while it uses SQLite. Do not put the bearer token in web build
   variables or commit it.

Railway's custom Start Command does not expand `$PORT` in the entered command: use the numeric
port (`8000` for this API) or leave the Dockerfile's default command. The current hosted instance
does not have the optional local simulator service configured; its UI is explicitly a no-external-
send demo.

To add the local simulator for a synthetic approval/reply demo, deploy `gigsim.app:app` as a
separate private service, use a distinct persistent volume, and configure the API's
`GIGSIM_BASE_URL` and matching `GIGSIM_API_TOKEN`. This is our deterministic simulator, not the
instructor's service and not a real marketplace.

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

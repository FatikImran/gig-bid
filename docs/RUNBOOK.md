# Runbook

## Local development

1. Install Python 3.11+ and Node.js 20+.
2. Copy `.env.example` to `.env`; replace `GIGBID_API_TOKEN` with a random local secret.
3. Install dependencies: `python -m pip install -e ".[dev]"` and `cd apps/web && npm ci`.
4. Optional Kaggle feed: place downloaded files in `data\raw\` and run
   `python -m evals.runners.prepare_kaggle_data`.
5. To use the local simulator, set a unique `GIGSIM_API_TOKEN` and
   `GIGSIM_BASE_URL=http://localhost:8010`, then run `uvicorn gigsim.app:app --reload --port 8010`.
6. Set `GIGBID_API_TOKEN`; set `GIGBID_USE_KAGGLE_FEED=true` if using the prepared feed. Start the
   API with `uvicorn apps.api.main:app --reload --port 8000`.
7. In another terminal, start the UI: `cd apps/web && npm run dev`.
8. Open `http://localhost:5173` and use the API token. Approvals write only to the local simulator
   when it is configured; simulator outcomes and Connects are fictional.

## Docker

Use the repository root as the working directory. Run `python -m evals.runners.prepare_kaggle_data`
if the Kaggle CSVs are present. Set `GIGBID_API_TOKEN` and `GIGSIM_API_TOKEN` in the shell or a
private `.env` file, then run `docker compose -f infra/docker-compose.yml up --build`. The UI is at
`http://localhost:4173` and the API health check is at `http://localhost:8000/health`. SQLite and
LangGraph checkpoints use `data\processed\`. Compose starts the local GigSim-style API on port 8010;
approval submits only to that simulator and decrements its fictional Connects balance. The worker
polls at least every 15 minutes (default one hour), analyzes unseen job IDs, and never sends. To stop: `docker compose -f
infra/docker-compose.yml down`; keep the volume for persistent checkpoints.

## Recovery and degraded mode

SQLite is opened in WAL mode. A proposal paused at the approval interrupt can be resumed after an API
restart using its persisted LangGraph thread ID. Approval uses an idempotency key and stores an
append-only audit event. If the checkpoint or DB is unavailable, the endpoint fails closed with
503/409; do not approve through a direct marketplace tool. The current worker logs API transport
errors and retries on its next polling interval. The UI displays API errors; no external action is
queued for later delivery.

## Configuration and rate limits

- `GIGBID_API_TOKEN`: required bearer token; replace the local default in development and set a
  unique secret in deployment.
- `GIGBID_DB_PATH`: SQLite database/checkpoint path; persist it across restarts.
- `GIGBID_CORS_ORIGINS`: comma-separated allowed browser origins.
- `GIGSIM_BASE_URL`: optional local simulator endpoint; only `localhost`, `127.0.0.1`, or the
  Docker Compose service name `gigsim` is accepted for simulator writes.
- `GIGSIM_API_TOKEN`: separate bearer credential for the local simulator.
- `GIGBID_USE_KAGGLE_FEED`: include the generated local seed in the inbox.
- `GIGBID_MARKETPLACE_MODE`: adapter selector scaffold; live Upwork submission remains disabled.
- `UPWORK_MCP_URL`, `UPWORK_ACCESS_TOKEN`: optional OAuth-managed live read connection. Do not put
  real credentials in `.env.example` or Git.
- `GIGBID_SCOUT_INTERVAL_SECONDS`: worker interval, clamped to at least 900 seconds.
- Local MCP marketplace tools allow at most 20 requests/minute. No scraping or browser automation
  is used.

## Deployment

Follow [DEPLOYMENT.md](./DEPLOYMENT.md). Public hosting, OAuth authorization, reviewer identity,
TLS/domain, and deployment secrets are manual actions. Do not deploy the local demo token or treat
SQLite single-user auth as production multi-tenant identity.

## Known gaps

The instructor's GigSim, policy update, hidden evaluation sets, Postgres/Redis, model provider,
Langfuse/LangSmith, OAuth callback service, and external reviewer account are absent. The local
GigSim-style simulator is not the instructor's service and does not model real client outcomes.
Compose is a local development package, not a public production deployment.

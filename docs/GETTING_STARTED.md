# Getting started

## Run locally

- Python 3.11+ and Node.js 20+ are required.
- Install Python dependencies with `python -m pip install -e ".[dev]"`.
- Install frontend dependencies with `cd apps/web && npm ci`.
- The starter sample runs without downloading anything. To use the Kaggle-derived local feed,
  download the two recommended CSVs into `data\raw\upwork-jobs.csv` and
  `data\raw\contracts.csv`, then run `python -m evals.runners.prepare_kaggle_data`.
- Set `GIGBID_API_TOKEN`, `GIGSIM_API_TOKEN`, and `GIGBID_USE_KAGGLE_FEED=true` in your shell so
  both services inherit them. Set `GIGSIM_BASE_URL=http://localhost:8010` for the GigBid API to
  enable local-simulator writes.
- Run the local simulator: `uvicorn gigsim.app:app --reload --port 8010`.
- Run `uvicorn apps.api.main:app --reload --port 8000`.
- In a second terminal run `cd apps/web && npm run dev`.
- Open `http://localhost:5173`, enter the same API bearer token, then review the safe sample job and
  the flagged unpaid/off-platform job. If the Kaggle feed is enabled, it also shows the prepared
  local postings and labeled synthetic safety cases.

The instructor's simulator and hidden evaluation sets are not present; `gigsim.app` is our own
local substitute with deterministic synthetic clients and outcomes. Explicitly approving a proposal
or message while the local simulator URL is configured writes only to that local simulator. It can
spend fictional Connects; it never contacts Upwork. The three personas and their portfolio records
are synthetic examples. See [DATA_CARD.md](./DATA_CARD.md) for sourcing and limitations.

## Reproduce checks and measurements

- `python -m pytest -q`
- `ruff check .`
- `python -m evals.runners.run_demo_eval`
- `python -m evals.runners.evaluate_gigsim`
- `python -m evals.runners.prepare_kaggle_data` (requires the downloaded Kaggle CSVs)
- `cd apps/web && npm run build`
- `docker compose -f infra/docker-compose.yml config`

The metrics JSON is written to `evals/results/demo_eval.json`. Do not replace unavailable outcome,
hidden-set, judge, or human-panel measurements with guessed values.

## MCP servers

Run each server over local stdio using:

- `python -m mcp_servers.portfolio.server`
- `python -m mcp_servers.marketplace.server`
- `python -m mcp_servers.workspace.server`

The MCP marketplace server still exposes its sample adapter. The FastAPI application approval
endpoints call the separately running local simulator only when `GIGSIM_BASE_URL` points to
localhost or the Docker `gigsim` service; no live Upwork write is implemented.

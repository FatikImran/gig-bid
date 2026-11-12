# Docker images and Compose

The API and worker use `api.Dockerfile`; the React UI is built by `web.Dockerfile` and served by
Nginx. Build contexts are the repository root.

From the repository root, start the local API, synthetic GigSim, web UI, and worker with:

```powershell
docker compose -f infra/docker-compose.yml up --build
```

The web image reads `VITE_API_URL` at build time. Compose defaults it to
`http://localhost:8000`; override `VITE_API_URL` when building for another API origin. The API
stores SQLite data under `/app/data/processed`; mount persistent storage there for deployments.

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from pathlib import Path

import httpx

LOG = logging.getLogger("gigbid.worker")
API_URL = os.getenv("GIGBID_API_URL", "http://localhost:8000")
TOKEN = os.getenv("GIGBID_API_TOKEN", "")
DB_PATH = Path(os.getenv("GIGBID_DB_PATH", "data/processed/gigbid.sqlite3"))
INTERVAL = max(900, int(os.getenv("GIGBID_SCOUT_INTERVAL_SECONDS", "3600")))


def _initialize_seen_jobs() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS worker_seen_jobs "
            "(job_id TEXT PRIMARY KEY, first_seen_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )


def _has_seen(job_id: str) -> bool:
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        return (
            conn.execute("SELECT 1 FROM worker_seen_jobs WHERE job_id=?", (job_id,)).fetchone()
            is not None
        )


def _mark_seen(job_id: str) -> None:
    with sqlite3.connect(DB_PATH, timeout=10) as conn:
        conn.execute("INSERT OR IGNORE INTO worker_seen_jobs (job_id) VALUES (?)", (job_id,))


async def scout_once() -> int:
    if not TOKEN:
        raise RuntimeError("GIGBID_API_TOKEN is required by the worker")
    _initialize_seen_jobs()
    processed = 0
    async with httpx.AsyncClient(
        base_url=API_URL,
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=httpx.Timeout(15),
    ) as client:
        response = await client.get("/api/jobs")
        response.raise_for_status()
        for job in response.json():
            job_id = job.get("job_id")
            if not isinstance(job_id, str) or not job_id:
                LOG.warning("Skipping a job with no valid ID")
                continue
            if _has_seen(job_id):
                continue
            analysis_response = await client.post(f"/api/jobs/{job_id}/analyze")
            analysis_response.raise_for_status()
            _mark_seen(job_id)
            processed += 1
            await asyncio.sleep(3.1)
    return processed


async def run_forever() -> None:
    while True:
        try:
            count = await scout_once()
            LOG.info("Scouting cycle complete; newly processed jobs: %d", count)
        except httpx.HTTPError as exc:
            LOG.error("Marketplace/API unavailable during scouting: %s", exc)
        await asyncio.sleep(INTERVAL)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    if os.getenv("GIGBID_SCOUT_ONCE", "").casefold() == "true":
        print(f"New jobs analyzed: {asyncio.run(scout_once())}")
    else:
        asyncio.run(run_forever())


if __name__ == "__main__":
    main()

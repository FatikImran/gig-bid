import csv

import httpx
import pytest
from fastapi.testclient import TestClient

from agent.marketplace_port import LocalGigSimRESTAdapter
from evals.runners.prepare_kaggle_data import build_seed
from gigsim.app import create_app


def _rows():
    return [
        {
            "title": f"Python data project {index}",
            "link": f"https://example.test/jobs/{index}",
            "description": (
                "Build a Python and SQL reporting dashboard. Contact me at "
                "client@example.com or 202-555-0198."
            ),
            "published_date": "2024-01-01",
            "is_hourly": "True",
            "hourly_low": "20",
            "hourly_high": "50",
            "budget": "",
            "country": "United States",
        }
        for index in range(2)
    ]


def test_seed_builder_redacts_contacts_and_labels_synthetic_scenarios():
    seed = build_seed(_rows(), limit=2, synthetic_scenarios=2)
    real_jobs = [job for job in seed["jobs"] if job["data_provenance"] == "kaggle_posting"]
    synthetic_jobs = [
        job for job in seed["jobs"] if job["data_provenance"] == "synthetic_scenario"
    ]
    assert len(real_jobs) == 2
    assert len(synthetic_jobs) == 2
    assert "client@example.com" not in real_jobs[0]["description"]
    assert "202-555-0198" not in real_jobs[0]["description"]
    assert "https://" not in real_jobs[0]["description"]
    assert real_jobs[0]["budget"]["type"] == "hourly"
    assert seed["clients"][real_jobs[0]["client_id"]]["hidden_preferences"]


def test_gigsim_requires_approval_and_spends_connects_once(tmp_path):
    seed = build_seed(_rows(), limit=2, synthetic_scenarios=0)
    app = create_app(
        db_path=tmp_path / "gigsim.sqlite3",
        seed_data=seed,
        rate_limit=50,
        fault_interval=0,
    )
    headers = {"Authorization": "Bearer local-gigsim-token"}
    job = seed["jobs"][0]
    client_id = job["client_id"]
    with TestClient(app) as client:
        assert client.get("/api/jobs", headers=headers).status_code == 200
        history = client.get(f"/api/clients/{client_id}/history", headers=headers).json()
        assert "hidden_preferences" not in history
        assert client.get("/api/connects", headers=headers).json()["balance"] == 500
        payload = {
            "job_id": job["job_id"],
            "client_id": client_id,
            "cover_letter": f"I have experience with {job['required_skills'][0]}.",
            "screening_answers": [],
            "evidence_ids": ["synthetic-evidence"],
            "amount": 30,
            "idempotency_key": "proposal-key-0001",
            "approved": False,
        }
        assert client.post("/api/proposals", headers=headers, json=payload).status_code == 403
        payload["approved"] = True
        first = client.post("/api/proposals", headers=headers, json=payload)
        assert first.status_code == 201
        replay = client.post("/api/proposals", headers=headers, json=payload)
        assert replay.status_code == 201
        assert replay.json() == first.json()
        assert first.json()["outcome_provenance"] == "synthetic_simulator"
        assert first.json()["outcome"] in {"ignored", "replied", "hired"}
        assert client.get("/api/connects", headers=headers).json()["balance"] == 492
        payload["amount"] = 31
        assert client.post("/api/proposals", headers=headers, json=payload).status_code == 409


def test_gigsim_auth_and_rate_limit(tmp_path):
    seed = build_seed(_rows(), limit=1, synthetic_scenarios=0)
    app = create_app(
        db_path=tmp_path / "rate.sqlite3",
        seed_data=seed,
        rate_limit=1,
        fault_interval=0,
    )
    with TestClient(app) as client:
        assert client.get("/api/jobs").status_code == 401
        headers = {"Authorization": "Bearer local-gigsim-token"}
        assert client.get("/api/jobs", headers=headers).status_code == 200
        limited = client.get("/api/connects", headers=headers)
        assert limited.status_code == 429
        assert limited.headers["Retry-After"] == "60"


def test_contract_summary_filters_invalid_rates(tmp_path):
    from evals.runners.prepare_kaggle_data import _contract_summary

    path = tmp_path / "contracts.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=["hourly_rate", "total_paid"])
        writer.writeheader()
        writer.writerows(
            [
                {"hourly_rate": "20", "total_paid": "100"},
                {"hourly_rate": "0", "total_paid": "0"},
                {"hourly_rate": "", "total_paid": "50"},
            ]
        )
    summary = _contract_summary(path)
    assert summary is not None
    assert summary["rows_scanned"] == 3
    assert summary["positive_hourly_rate_rows"] == 1
    assert summary["median_hourly_rate_usd"] == 20
    assert "not joined" in summary["use"]


def test_marketplace_adapter_rejects_non_local_simulator_endpoint():
    with pytest.raises(ValueError, match="local hostname"):
        LocalGigSimRESTAdapter("http://example.com:8010", "local-token")
    with pytest.raises(ValueError, match="HTTP"):
        LocalGigSimRESTAdapter("https://localhost:8010", "local-token")


@pytest.mark.asyncio
async def test_marketplace_adapter_exercises_simulator_rest_api(tmp_path):
    seed = build_seed(_rows(), limit=1, synthetic_scenarios=0)
    app = create_app(
        db_path=tmp_path / "adapter.sqlite3",
        seed_data=seed,
        rate_limit=50,
        fault_interval=0,
    )
    async with app.router.lifespan_context(app):
        adapter = LocalGigSimRESTAdapter(
            "http://localhost:8010",
            "local-gigsim-token",
            transport=httpx.ASGITransport(app=app),
        )
        job = seed["jobs"][0]
        client = job["client_id"]
        assert (await adapter.search_jobs("Python"))[0]["job_id"] == job["job_id"]
        assert "hidden_preferences" not in await adapter.get_client_history(client)
        assert (await adapter.get_connects_balance())["balance"] == 500
        payload = {
            "job_id": job["job_id"],
            "client_id": client,
            "cover_letter": "A proposal about Python.",
            "screening_answers": [],
            "evidence_ids": ["synthetic-evidence"],
            "amount": 30,
        }
        proposal = await adapter.submit_proposal(payload, "rest-adapter-proposal-1", True)
        replay = await adapter.submit_proposal(payload, "rest-adapter-proposal-1", True)
        assert replay == proposal
        assert proposal["outcome_provenance"] == "synthetic_simulator"
        message = await adapter.send_message(
            {
                "job_id": job["job_id"],
                "client_id": client,
                "message": "Thanks for your response.",
            },
            "rest-adapter-message-1",
            True,
        )
        assert message["outcome_provenance"] == "synthetic_simulator"
        assert await adapter.get_connects_balance() == {
            "balance": 492,
            "currency": "Connects",
            "source": "synthetic_simulator",
        }

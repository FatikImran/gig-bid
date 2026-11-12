from fastapi.testclient import TestClient

from agent.sample_data import jobs
from apps.api import main


def test_api_approval_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "gigbid.sqlite3")
    monkeypatch.delenv("GIGSIM_BASE_URL", raising=False)
    with TestClient(main.app) as client:
        headers = {"Authorization": "Bearer local-dev-token"}

        assert client.get("/api/jobs").status_code == 401
        jobs = client.get("/api/jobs", headers=headers)
        assert jobs.status_code == 200
        assert jobs.json()[0]["recommendation"] == "bid"
        assert jobs.json()[1]["recommendation"] == "skip"

        analysis = client.post("/api/jobs/sample-job-001/analyze", headers=headers)
        assert analysis.status_code == 201
        proposal_id = analysis.json()["id"]
        assert analysis.json()["status"] == "awaiting_review"

        bad_edit = client.put(
            f"/api/proposals/{proposal_id}",
            headers=headers,
            json={
                "cover_letter": "I guarantee you a 100% success rate.",
                "screening_answers": [],
            },
        )
        assert bad_edit.status_code == 422

        approval_headers = {**headers, "Idempotency-Key": "approve-test-0001"}
        approved = client.post(
            f"/api/proposals/{proposal_id}/approve",
            headers=approval_headers,
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        assert "no marketplace write" in approved.json()["external_submission"]

        replay = client.post(
            f"/api/proposals/{proposal_id}/approve",
            headers=approval_headers,
        )
        assert replay.status_code == 200
        assert replay.headers["Idempotent-Replay"] == "true"


def test_reject_requires_reason_and_records_status(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "gigbid.sqlite3")
    monkeypatch.delenv("GIGSIM_BASE_URL", raising=False)
    with TestClient(main.app) as client:
        headers = {"Authorization": "Bearer local-dev-token"}
        created = client.post("/api/jobs/sample-job-001/analyze", headers=headers).json()
        rejected = client.post(
            f"/api/proposals/{created['id']}/reject",
            headers=headers,
            json={"reason": "Not aligned with my current work."},
        )
        assert rejected.status_code == 200
        assert rejected.json()["status"] == "rejected"


def test_approval_graph_resumes_after_api_restart(tmp_path, monkeypatch):
    database = tmp_path / "crash-resume.sqlite3"
    monkeypatch.setattr(main, "DB_PATH", database)
    monkeypatch.delenv("GIGSIM_BASE_URL", raising=False)
    headers = {"Authorization": "Bearer local-dev-token"}
    with TestClient(main.app) as first_client:
        created = first_client.post(
            "/api/jobs/sample-job-001/analyze",
            headers=headers,
        ).json()
        proposal_id = created["id"]
    with TestClient(main.app) as restarted_client:
        result = restarted_client.post(
            f"/api/proposals/{proposal_id}/approve",
            headers={**headers, "Idempotency-Key": "crash-resume-key-01"},
        )
    assert result.status_code == 200
    assert result.json()["status"] == "approved"
    assert "no marketplace write" in result.json()["external_submission"]


def test_conversation_graph_stops_for_user_review(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "messages.sqlite3")
    monkeypatch.delenv("GIGSIM_BASE_URL", raising=False)
    with TestClient(main.app) as client:
        headers = {"Authorization": "Bearer local-dev-token"}
        draft = client.post(
            "/api/messages/draft",
            headers=headers,
            json={
                "job_id": "sample-job-001",
                "message": "Could we schedule an interview next week?",
            },
        )
        assert draft.status_code == 201
        assert draft.json()["status"] == "awaiting_review"
        assert draft.json()["intent"] == "interview_request"
        approved = client.post(
            f"/api/messages/{draft.json()['id']}/approve",
            headers={**headers, "Idempotency-Key": "message-approval-01"},
        )
        assert approved.status_code == 200
        assert "no message was sent" in approved.json()["external_send"]
        listed = client.get("/api/messages", headers=headers)
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == draft.json()["id"]
        assert client.get("/api/runs", headers=headers).json()
        analytics = client.get("/api/analytics", headers=headers).json()
        assert analytics["outcome_provenance"] == "synthetic_simulator"


def test_negotiation_message_uses_selected_persona_floor(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "negotiation-message.sqlite3")
    monkeypatch.delenv("GIGSIM_BASE_URL", raising=False)
    with TestClient(main.app) as client:
        response = client.post(
            "/api/messages/draft",
            headers={"Authorization": "Bearer local-dev-token"},
            json={
                "job_id": "sample-job-001",
                "message": "I can offer $250 for this project.",
                "persona_id": "sample-fullstack-developer",
            },
        )

    assert response.status_code == 201
    result = response.json()
    assert result["negotiation_decision"]["action"] == "counter"
    assert result["negotiation_decision"]["profile_floor"] == 300
    assert result["negotiation_decision"]["recommended_amount"] == 300


def test_message_rejection_resumes_conversation_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "message-reject.sqlite3")
    monkeypatch.delenv("GIGSIM_BASE_URL", raising=False)
    with TestClient(main.app) as client:
        headers = {"Authorization": "Bearer local-dev-token"}
        draft = client.post(
            "/api/messages/draft",
            headers=headers,
            json={"job_id": "sample-job-001", "message": "Could you clarify the timeline?"},
        ).json()
        rejected = client.post(
            f"/api/messages/{draft['id']}/reject",
            headers=headers,
            json={"reason": "I need more project context first."},
        )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


def test_approval_uses_local_simulator_port_after_graph_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "simulator-write.sqlite3")
    monkeypatch.setenv("GIGSIM_BASE_URL", "http://localhost:8010")
    monkeypatch.setenv("GIGBID_MARKETPLACE_MODE", "gigsim")
    calls = []

    class FakeSimulator:
        async def search_jobs(self):
            return jobs()

        async def get_job(self, job_id):
            return next(job for job in jobs() if job["job_id"] == job_id)

        async def submit_proposal(self, payload, idempotency_key, approved):
            calls.append((payload, idempotency_key, approved))
            return {
                "proposal_id": "sim-proposal-001",
                "outcome": "replied",
                "outcome_provenance": "synthetic_simulator",
            }

    monkeypatch.setattr(main, "create_marketplace_port", FakeSimulator)
    headers = {"Authorization": "Bearer local-dev-token"}
    with TestClient(main.app) as client:
        listing = client.get("/api/jobs", headers=headers)
        assert listing.status_code == 200
        assert len(listing.json()) >= 2
        created = client.post("/api/jobs/sample-job-001/analyze", headers=headers).json()
        result = client.post(
            f"/api/proposals/{created['id']}/approve",
            headers={**headers, "Idempotency-Key": "simulator-approval-1"},
        )
        replay = client.post(
            f"/api/proposals/{created['id']}/approve",
            headers={**headers, "Idempotency-Key": "simulator-approval-1"},
        )
    assert result.status_code == 200
    assert result.json()["simulator_result"]["outcome"] == "replied"
    assert result.json()["external_submission"].startswith("submitted to local GigSim")
    assert replay.headers["Idempotent-Replay"] == "true"
    assert len(calls) == 1
    assert calls[0][0]["client_id"].startswith("synthetic-client")
    assert calls[0][2] is True

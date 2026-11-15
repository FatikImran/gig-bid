import json

import pytest
from fastapi.testclient import TestClient

from agent.model_runtime import GroqInferenceError
from agent.nodes import writer
from agent.sample_data import jobs
from apps.api import main


def test_groq_rate_limit_is_visible_to_browser(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "rate-limit.sqlite3")
    monkeypatch.setenv("GIGBID_MARKETPLACE_MODE", "gigsim")
    monkeypatch.setenv("GIGBID_MODEL_PROFILE", "open")

    def rate_limit(*_args):
        raise GroqInferenceError(429, "30")

    monkeypatch.setattr(writer, "generate", rate_limit)
    headers = {"Authorization": "Bearer local-dev-token", "Origin": "http://localhost:5173"}
    with TestClient(main.app, headers=headers) as client:
        response = client.post("/api/jobs/sample-job-001/analyze")
        assert response.status_code == 503
        assert response.headers["access-control-allow-origin"] == headers["Origin"]
        assert response.json() == {"detail": "Groq inference failed with HTTP 429."}
        assert client.get("/api/proposals").json() == []


def test_live_listings_do_not_use_synthetic_portfolio_or_approval(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "live-browse.sqlite3")
    monkeypatch.setenv("GIGBID_MARKETPLACE_MODE", "upwork")

    class LiveJobs:
        async def search_jobs(self):
            return [{"job_id": "1234", "title": "Live job", "data_provenance": "upwork_live"}]

    monkeypatch.setattr(main, "create_marketplace_port", LiveJobs)
    with TestClient(main.app, headers={"Authorization": "Bearer local-dev-token"}) as client:
        listing = client.get("/api/jobs").json()[0]
        assert listing["recommendation"] == "watch"
        assert listing["fit_score"] is None
        assert client.post("/api/jobs/1234/analyze").status_code == 409
        assert (
            client.post(
                "/api/proposals/old-draft/approve", headers={"Idempotency-Key": "live-approval-01"}
            ).status_code
            == 404
        )


@pytest.mark.parametrize("rejected", [False, True])
def test_upwork_web_approval_returns_preview_and_replays_without_resending(
    tmp_path, monkeypatch, rejected
):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "preview.sqlite3")
    monkeypatch.setenv("GIGBID_MARKETPLACE_MODE", "upwork")
    portfolio = tmp_path / "owner.json"
    portfolio.write_text(
        json.dumps(
            [
                {
                    "evidence_id": "owner-example",
                    "freelancer_id": "local-owner",
                    "title": "Python workflow",
                    "summary": "Built a Python workflow that classifies support requests.",
                    "skills": ["Python"],
                    "outcome": "Local fixture",
                    "source": "Owner-provided résumé",
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "PORTFOLIO_PATH", portfolio)
    calls = []

    class LiveJobs:
        async def get_job(self, job_id):
            return {
                "job_id": job_id,
                "title": "Python support workflow",
                "description": "Classify requests",
                "required_skills": ["Python"],
                "budget": {"type": "hourly"},
                "applied": False,
                "data_provenance": "upwork_live",
                "upwork_reference": "1234",
                "connects_cost": 8,
            }

        async def create_proposal_draft(self, payload, idempotency_key, approved, dry_run):
            assert approved is True and dry_run is False
            calls.append(payload)
            if rejected:
                raise main.UpworkMarketplaceError("Upwork rejected this preview (EXAMPLE_CODE).")
            return {
                "preview_id": "local-test-preview",
                "preview": {"connects_cost": 8, "connects_balance": 20},
            }

    monkeypatch.setattr(main, "create_marketplace_port", LiveJobs)
    headers = {"Authorization": "Bearer local-dev-token"}
    with TestClient(main.app, headers=headers) as client:
        assert client.get("/api/portfolio").json()["evidence"][0]["evidence_id"] == "owner-example"
        response = client.post(
            "/api/jobs/1234/analyze",
            json={
                "evidence_id": "owner-example",
                "amount": 50,
                "unit": "hourly",
            },
        )
        assert response.status_code == 201
        result = response.json()
        assert result["status"] == "awaiting_review"
        assert calls == []

        approval = f"/api/proposals/{result['id']}/approve"
        approval_headers = {"Idempotency-Key": "upwork-approval-test"}
        first = client.post(approval, headers=approval_headers)
        if rejected:
            assert first.status_code == 502
            assert "EXAMPLE_CODE" in first.json()["detail"]
            assert client.get(f"/api/proposals/{result['id']}").json()["status"] == "preview_failed"
            assert client.post(approval, headers=approval_headers).status_code == 409
            assert len(calls) == 1
            return
        assert first.status_code == 200
        assert first.json()["status"] == "preview_ready"
        assert first.json()["upwork_preview"]["connects_cost"] == 8
        assert "local-test-preview" not in first.text
        assert (
            client.post(approval, headers=approval_headers).headers["Idempotent-Replay"] == "true"
        )
        assert (
            client.post(approval, headers={"Idempotency-Key": "different-key-test"}).status_code
            == 409
        )
        assert calls == [
            {
                "job_reference": "1234",
                "charged_amount": 50,
                "cover_letter": result["proposal"]["cover_letter"],
            }
        ]


def test_upwork_message_approval_only_releases_local_draft(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "live-reply.sqlite3")
    monkeypatch.setenv("GIGBID_MARKETPLACE_MODE", "upwork")

    def forbidden_marketplace():
        raise AssertionError("The draft handoff must not call Upwork or the simulator")

    monkeypatch.setattr(main, "create_marketplace_port", forbidden_marketplace)
    headers = {"Authorization": "Bearer local-dev-token"}
    with TestClient(main.app, headers=headers) as client:
        response = client.post(
            "/api/messages/draft", json={"message": "Can we discuss the budget?"}
        )
        assert response.status_code == 201
        draft = response.json()
        assert draft["status"] == "awaiting_review"
        assert draft["negotiation_decision"] is None
        result = client.post(
            f"/api/messages/{draft['id']}/approve", headers={"Idempotency-Key": "upwork-reply-test"}
        )
        assert result.status_code == 200
        assert result.json()["status"] == "ready_to_copy"
        saved = client.get("/api/messages").json()[0]
        assert saved["draft"] == draft["draft"]
        assert saved["external_send_enabled"] is False


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

        cover_letter = analysis.json()["proposal"]["cover_letter"]
        unsupported_answer = client.put(
            f"/api/proposals/{proposal_id}",
            headers=headers,
            json={"cover_letter": cover_letter, "screening_answers": ["I am a licensed attorney."]},
        )
        assert unsupported_answer.status_code == 422
        assert unsupported_answer.json()["detail"]["field"] == "screening_answers[0]"

        grounded_answer = cover_letter.split(". ", 1)[0] + "."
        safe_edit = client.put(
            f"/api/proposals/{proposal_id}",
            headers=headers,
            json={"cover_letter": cover_letter, "screening_answers": [grounded_answer]},
        )
        assert safe_edit.status_code == 200
        assert safe_edit.json()["analysis"]["claim_verification"][-1]["claim"] == grounded_answer

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


def test_approval_rechecks_legacy_screening_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "legacy-draft.sqlite3")
    monkeypatch.delenv("GIGSIM_BASE_URL", raising=False)
    headers = {"Authorization": "Bearer local-dev-token"}
    with TestClient(main.app) as client:
        created = client.post("/api/jobs/sample-job-001/analyze", headers=headers).json()
        proposal_path = f"/api/proposals/{created['id']}"
        with main.connection() as conn:
            row = conn.execute(
                "SELECT payload FROM proposals WHERE id=?", (created["id"],)
            ).fetchone()
            payload = json.loads(row["payload"])
            payload["proposal"]["screening_answers"] = ["I am a licensed attorney."]
            conn.execute(
                "UPDATE proposals SET payload=? WHERE id=?", (json.dumps(payload), created["id"])
            )

        result = client.post(
            f"{proposal_path}/approve", headers={**headers, "Idempotency-Key": "legacy-draft-0001"}
        )
        assert result.status_code == 422
        assert result.json()["detail"]["field"] == "screening_answers[0]"
        assert client.get(proposal_path, headers=headers).json()["status"] == "awaiting_review"


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

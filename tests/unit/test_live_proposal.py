from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from agent import live_proposal
from agent.upwork_marketplace import UpworkMarketplaceError, UpworkMCPAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["PREVIEW", "no"])
async def test_private_evidence_and_graph_approval_gate_provider_preview(monkeypatch, reply):
    evidence = live_proposal.ResumeEvidence(
        evidence_id="owner-demo",
        freelancer_id="local-owner",
        title="Python support workflow",
        summary="Built a Python workflow that classifies support requests.",
        skills=["Python"],
        outcome="Local example",
        source="Owner-provided résumé",
    )
    job = {
        "job_id": "1234",
        "title": "Build a Python support workflow",
        "description": "Classify support requests",
        "required_skills": ["Python"],
        "budget": {"type": "hourly"},
        "can_apply": True,
        "applied": False,
        "connects_cost": 8,
        "upwork_reference": "1234",
    }

    class Marketplace:
        get_job = AsyncMock(return_value=job)
        create_proposal_draft = AsyncMock(return_value={"preview_id": "example-only"})

    monkeypatch.setattr(live_proposal, "configured_upwork_marketplace", Marketplace)
    monkeypatch.setattr("builtins.input", lambda _: reply)
    await live_proposal.prepare_preview("1234", evidence, 50, "hourly")

    if reply == "PREVIEW":
        args, kwargs = Marketplace.create_proposal_draft.await_args
        assert args[0]["cover_letter"] == evidence.summary
        assert args[0]["charged_amount"] == 50
        assert kwargs["approved"] is True
        assert kwargs["dry_run"] is False
    else:
        Marketplace.create_proposal_draft.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("existing", [False, True])
async def test_upwork_preview_checks_prior_applications_and_uses_only_create(monkeypatch, existing):
    adapter = UpworkMCPAdapter(client=None)

    @asynccontextmanager
    async def account_session():
        yield None, "test-org"

    async def provider_call(session, tool, arguments):
        if tool == "manage_proposals":
            return {"preview_id": "example-only"}
        if arguments["action"] == "invitations":
            return {"invitations": []}
        if existing and arguments["params"]["status"] == "Pending":
            return {"proposals": [{"jobPosting": {"id": "1234"}}]}
        return {
            "data": {
                "freelancerProposalConnection": {
                    "edges": [],
                    "page_info": {"has_next_page": False},
                }
            }
        }

    call = AsyncMock(side_effect=provider_call)
    monkeypatch.setattr(adapter, "_account_session", account_session)
    monkeypatch.setattr(adapter, "_call", call)
    payload = {"job_reference": "1234", "cover_letter": "Example letter", "charged_amount": 50}

    if existing:
        with pytest.raises(UpworkMarketplaceError, match="already has a proposal"):
            await adapter.create_proposal_draft(
                payload, "example-key", approved=True, dry_run=False
            )
        assert all(args.args[1] != "manage_proposals" for args in call.await_args_list)
    else:
        result = await adapter.create_proposal_draft(
            payload, "example-key", approved=True, dry_run=False
        )
        assert result["preview_id"] == "example-only"
        assert len(call.await_args_list) == 8
        assert call.await_args.args[1:] == (
            "manage_proposals",
            {
                "action": "create",
                "org_uid": "test-org",
                "params": payload,
            },
        )

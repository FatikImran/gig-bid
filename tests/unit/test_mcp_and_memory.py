import pytest

from agent.memory.promotion_rules import should_promote_outcome, should_promote_style_edit
from agent.memory.store import add_memory, delete_memory, list_memory
from agent.nodes.compliance import check as compliance_check
from agent.observability import mask_pii
from mcp_servers.marketplace.server import ProposalInput, create_proposal_draft
from mcp_servers.portfolio.server import get_case_study, search_evidence
from mcp_servers.workspace.server import available_slots, create_tentative_hold


def test_portfolio_mcp_functions_validate_and_return_real_sample_data():
    results = search_evidence("Python classification", k=1)
    assert results[0]["evidence_id"] == "evidence-001"
    assert get_case_study("evidence-001")["type"] == "case_study"
    with pytest.raises(ValueError):
        search_evidence("", k=1)


def test_marketplace_write_requires_approval_and_dry_run(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    request = ProposalInput(
        job_id="sample-job-001",
        cover_letter="Evidence-grounded draft.",
        evidence_ids=["evidence-001"],
        amount=300,
        idempotency_key="test-key-001",
        approved=False,
        dry_run=True,
    )
    with pytest.raises(PermissionError):
        create_proposal_draft(request)
    preview = create_proposal_draft(request.model_copy(update={"approved": True}))
    assert preview["external_write"] is False
    assert preview["preview"]["connects_cost"] == 8


def test_workspace_requires_approval_and_aware_time():
    assert available_slots(days=7)
    with pytest.raises(PermissionError):
        create_tentative_hold("2026-11-13T10:00:00+00:00", "2026-11-13T10:30:00+00:00", False)


def test_memory_requires_explicit_promotion_and_tenant_scope(tmp_path, monkeypatch):
    from agent.memory import store

    monkeypatch.setattr(store, "DB_PATH", tmp_path / "memory.sqlite3")
    assert should_promote_style_edit(3, True)
    assert not should_promote_style_edit(2, True)
    assert should_promote_outcome("won", True, True)
    with pytest.raises(PermissionError):
        add_memory(
            "tenant-a",
            "style",
            "Avoid opening with passion.",
            "repeated_user_edit",
            explicitly_approved=False,
        )
    memory_id = add_memory(
        "tenant-a",
        "style",
        "Avoid generic openings.",
        "repeated_user_edit",
        explicitly_approved=True,
    )
    assert list_memory("tenant-a")[0]["id"] == memory_id
    assert list_memory("tenant-b") == []
    assert delete_memory("tenant-a", memory_id)


def test_compliance_and_logging_mask_contact_details():
    verdict = compliance_check(
        "You can email me at alex@example.com or call 202-555-0198.",
        ["evidence-001"],
    )
    assert verdict.allowed is False
    masked = mask_pii("Contact alex@example.com or 202-555-0198.")
    assert "alex@example.com" not in masked
    assert "202-555-0198" not in masked

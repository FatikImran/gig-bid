from langgraph.types import Command

from agent.graphs.bid_graph import build_bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.sample_data import jobs


def test_bid_graph_pauses_then_resumes_after_approval():
    graph = build_bid_graph()
    config = {"configurable": {"thread_id": "bid-graph-test"}}
    paused = graph.invoke({"job": jobs()[0]}, config)
    assert paused["__interrupt__"]
    approval_payload = paused["__interrupt__"][0].value
    assert approval_payload["kind"] == "proposal_approval"
    assert approval_payload["dry_run"]["external_write_enabled"] is False

    finished = graph.invoke(Command(resume={"approved": True}), config)
    assert finished["approval_status"] == "approved"
    assert "external submission is disabled" in finished["external_action"]


def test_conversation_graph_blocks_off_platform_scam():
    graph = build_conversation_graph()
    config = {"configurable": {"thread_id": "conversation-scam-test"}}
    result = graph.invoke(
        {"message": "Please continue on WhatsApp and pay a crypto fee."},
        config,
    )
    assert result["status"] == "blocked"
    assert not result.get("__interrupt__")


def test_conversation_graph_negotiation_uses_walkaway_subgraph_before_approval():
    graph = build_conversation_graph()
    config = {"configurable": {"thread_id": "conversation-negotiation-test"}}
    paused = graph.invoke(
        {
            "message": "I can offer $150 for the project.",
            "job": {
                "job_id": "negotiation-test",
                "budget": {"type": "fixed", "min": 50, "max": 100},
            },
            "profile": {
                "hourly_rate_usd": 25,
                "minimum_project_budget_usd": 200,
            },
        },
        config,
    )

    assert paused["negotiation_decision"]["action"] == "walk_away"
    assert paused["negotiation_decision"]["recommended_amount"] is None
    assert paused["__interrupt__"][0].value["kind"] == "message_approval"

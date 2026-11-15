"""Generate diagrams and sanitized graph traces from bundled synthetic fixtures."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command

from agent.graphs import bid_graph
from agent.graphs.conversation_graph import build_conversation_graph
from agent.handoffs import Critique
from agent.sample_data import load_json

DOCS = Path(__file__).resolve().parents[2] / "docs"


def capture(graph, value, config):
    events = []
    for update in graph.stream(value, config, stream_mode="updates"):
        for node, data in update.items():
            event = {"node": node}
            if isinstance(data, dict):
                if "decision" in data:
                    event["decision"] = data["decision"]["action"]
                if "critique" in data:
                    event["critic_approved"] = data["critique"]["approved"]
                    event["revision_count"] = data["revision_count"]
                if "approval_status" in data:
                    event["approval_status"] = data["approval_status"]
            events.append(event)
    return events


def crash_worker(path):
    config = {"configurable": {"thread_id": "synthetic-crash"}}
    with SqliteSaver.from_conn_string(path) as saver:
        graph = bid_graph.build_bid_graph(saver)
        events = capture(graph, {"job": load_json("jobs.json")[0]}, config)
        assert "approval" in graph.get_state(config).next
        print(json.dumps(events), flush=True)
        # Exit without running the checkpointer context manager's shutdown path.
        os._exit(17)


def main():
    diagrams = ["# LangGraph diagrams", "", "Generated from the compiled graphs."]
    for name, graph in (
        ("Bid graph", bid_graph.build_bid_graph()),
        ("Conversation graph", build_conversation_graph()),
    ):
        diagrams.extend(
            ["", f"## {name}", "", "```mermaid", graph.get_graph().draw_mermaid(), "```"]
        )
    (DOCS / "GRAPHS.md").write_text("\n".join(diagrams) + "\n", encoding="utf-8")

    paid, scam = load_json("jobs.json")[:2]
    approved = Command(resume={"approved": True})
    graph = bid_graph.build_bid_graph()
    scam_config = {"configurable": {"thread_id": "synthetic-scam"}}
    skipped = capture(graph, {"job": scam}, scam_config)
    assert any(event.get("decision") == "skip" for event in skipped)
    assert not any(event["node"] == "__interrupt__" for event in skipped)
    proposal_config = {"configurable": {"thread_id": "synthetic-proposal"}}
    proposal = capture(graph, {"job": paid}, proposal_config)
    assert "approval" in graph.get_state(proposal_config).next
    proposal += capture(graph, approved, proposal_config)
    assert any(event.get("approval_status") == "approved" for event in proposal)

    real_critic = bid_graph.critique

    def reject_first_review(draft, evidence, revision_count):
        if revision_count == 0:
            return Critique(approved=False, issues=["Injected test condition"], revision_count=0)
        return real_critic(draft, evidence, revision_count)

    with patch.object(bid_graph, "critique", reject_first_review):
        critic = capture(
            bid_graph.build_bid_graph(),
            {"job": paid},
            {"configurable": {"thread_id": "synthetic-critic"}},
        )
    assert [event["critic_approved"] for event in critic if "critic_approved" in event] == [
        False,
        True,
    ]

    with TemporaryDirectory() as directory:
        path = str(Path(directory) / "checkpoint.sqlite3")
        worker = subprocess.run(
            [sys.executable, "-m", "evals.runners.capture_graph_evidence", "--crash-worker", path],
            capture_output=True,
            text=True,
            check=False,
        )
        if worker.returncode != 17:
            raise RuntimeError(worker.stderr or f"Unexpected worker exit: {worker.returncode}")
        crash = json.loads(worker.stdout)
        crash.append({"event": "worker_exit", "exit_code": worker.returncode})
        with SqliteSaver.from_conn_string(path) as saver:
            graph = bid_graph.build_bid_graph(saver)
            config = {"configurable": {"thread_id": "synthetic-crash"}}
            assert "approval" in graph.get_state(config).next
            crash.append({"event": "checkpoint_reopened", "next": "approval"})
            crash += capture(graph, approved, config)
            assert graph.get_state(config).values["approval_status"] == "approved"

    scenarios = [
        ("Skipped scam", "Bundled unpaid trial fixture.", skipped),
        (
            "Approved proposal",
            "Bundled paid job, resumed after the human approval interrupt.",
            proposal,
        ),
        (
            "Critic loop",
            "A controlled fixture forces the first Critic rejection. The retry uses the normal Critic and follows the compiled graph.",
            critic,
        ),
        (
            "Crash and resume",
            "A subprocess exits abruptly at the approval checkpoint. The parent reopens SQLite and resumes. This trace covers graph recovery through approval.",
            crash,
        ),
    ]
    lines = [
        "# Synthetic LangGraph traces",
        "",
        "These local streams record graph node updates and approval states. Hosted tracing, MCP spans, and token and cost telemetry are separate work.",
    ]
    for name, description, events in scenarios:
        lines.extend(
            ["", f"## {name}", "", description, "", "```json", json.dumps(events, indent=2), "```"]
        )
    (DOCS / "GRAPH_TRACES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--crash-worker":
        crash_worker(sys.argv[2])
    else:
        main()

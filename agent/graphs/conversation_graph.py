from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agent.graphs.negotiation_graph import build_negotiation_graph
from agent.nodes.client_liaison import draft_reply

_negotiation_graph = build_negotiation_graph()


class ConversationState(TypedDict, total=False):
    message: str
    job: dict[str, Any]
    profile: dict[str, Any]
    intent: str
    draft: str
    status: str
    negotiation_decision: dict[str, Any]
    approval_status: str
    external_action: str


def _liaison(state: ConversationState) -> dict[str, Any]:
    result = draft_reply(state["message"])
    if result["intent"] == "negotiation":
        negotiation = _negotiation_graph.invoke(
            {
                "message": state["message"],
                "job": state["job"],
                "profile": state["profile"],
            }
        )["decision"]
        result["draft"] = negotiation["reply"]
        result["negotiation_decision"] = negotiation
    return result


def _route(state: ConversationState) -> str:
    return "approval" if state["status"] == "pending_review" else END


def _approval(state: ConversationState) -> dict[str, str]:
    decision = interrupt(
        {
            "kind": "message_approval",
            "intent": state["intent"],
            "draft": state["draft"],
            "external_send_enabled": False,
        }
    )
    if isinstance(decision, dict) and decision.get("approved") is True:
        return {"approval_status": "approved"}
    return {"approval_status": "rejected"}


def build_conversation_graph(checkpointer=None):
    graph = StateGraph(ConversationState)
    graph.add_node("client_liaison", _liaison)
    graph.add_node("approval", _approval)
    graph.add_node(
        "approved_locally",
        lambda _state: {"external_action": "approved_locally; external message send is disabled"},
    )
    graph.add_edge(START, "client_liaison")
    graph.add_conditional_edges("client_liaison", _route, {"approval": "approval", END: END})
    graph.add_conditional_edges(
        "approval",
        lambda state: "approved_locally" if state.get("approval_status") == "approved" else END,
        {"approved_locally": "approved_locally", END: END},
    )
    graph.add_edge("approved_locally", END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())

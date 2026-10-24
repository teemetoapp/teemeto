"""LangGraph state graph with Human-in-the-Loop interrupt."""

from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from packages.shared.orchestration.state import AgentWorkflowState


def retrieve_context_node(state: AgentWorkflowState) -> dict[str, Any]:
    """Retrieves relevant business knowledge chunks."""
    msg = state.get("user_message", "")
    # In production, calls PgVectorMemoryStore; for graph unit, produces structured context
    return {
        "context_chunks": [f"Retrieved knowledge for query: {msg}"],
        "status": "context_retrieved",
    }


def draft_response_node(state: AgentWorkflowState) -> dict[str, Any]:
    """Generates an initial draft response based on user input and retrieved context."""
    user_msg = state.get("user_message", "")
    draft = f"درود بر شما، در پاسخ به پیام '{user_msg}'، خوشحال می‌شویم کمکتان کنیم."
    return {
        "draft_response": draft,
        "status": "pending_approval",
    }


def human_approval_node(state: AgentWorkflowState) -> dict[str, Any]:
    """
    Halts graph execution using LangGraph interrupt.
    Awaits human supervisor decision via Command(resume=...).
    """
    # Trigger interrupt with payload for human supervisor
    human_decision = interrupt(
        {
            "action_id": state.get("action_id", ""),
            "tenant_id": state.get("tenant_id", ""),
            "conversation_id": state.get("conversation_id", ""),
            "draft_response": state.get("draft_response", ""),
        }
    )

    is_approved = bool(human_decision.get("approved", False))
    edited_text = human_decision.get("edited_text")

    if is_approved:
        final_text = edited_text if edited_text else state.get("draft_response", "")
        return {
            "status": "approved",
            "final_response": final_text,
        }
    else:
        return {
            "status": "rejected",
            "final_response": "",
        }


def send_response_node(state: AgentWorkflowState) -> dict[str, Any]:
    """Finalizes output and marks workflow completed."""
    if state.get("status") == "approved":
        return {"status": "completed"}
    return {"status": "aborted"}


def create_agent_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[AgentWorkflowState, Any, Any, Any]:
    """Builds and compiles the human-in-the-loop agent StateGraph."""
    builder = StateGraph(AgentWorkflowState)

    builder.add_node("retrieve_context", retrieve_context_node)
    builder.add_node("draft_response", draft_response_node)
    builder.add_node("human_approval", human_approval_node)
    builder.add_node("send_response", send_response_node)

    builder.add_edge(START, "retrieve_context")
    builder.add_edge("retrieve_context", "draft_response")
    builder.add_edge("draft_response", "human_approval")
    builder.add_edge("human_approval", "send_response")
    builder.add_edge("send_response", END)

    saver = checkpointer if checkpointer is not None else MemorySaver()
    return builder.compile(checkpointer=saver)

"""State definitions for LangGraph agent orchestration."""

from typing import TypedDict


class AgentWorkflowState(TypedDict):
    """Execution state tracked through the LangGraph supervisor workflow."""

    tenant_id: str
    conversation_id: str
    user_message: str
    context_chunks: list[str]
    draft_response: str
    status: str
    action_id: str
    final_response: str

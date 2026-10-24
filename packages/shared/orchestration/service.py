"""Orchestration service coordinating LangGraph execution and action queue persistence."""

from typing import Any, cast
from uuid import uuid4

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from packages.shared.orchestration.graph import create_agent_graph
from packages.shared.orchestration.state import AgentWorkflowState


class OrchestrationService:
    """Manages agent execution lifecycle, HitL queue persistence, and resumption."""

    def __init__(
        self,
        checkpointer: BaseCheckpointSaver[Any] | None = None,
        queue_table_name: str = "agent_action_queue",
    ) -> None:
        self.queue_table_name = queue_table_name
        self.graph: CompiledStateGraph[AgentWorkflowState, Any, Any, Any] = (
            create_agent_graph(checkpointer=checkpointer)
        )

    async def start_agent_workflow(
        self,
        tenant_id: str,
        conversation_id: str,
        user_message: str,
        session: AsyncSession,
    ) -> dict[str, Any]:
        """
        Launches the agent workflow for a message.
        Executes until the human_approval node halts at interrupt,
        then records the pending action in agent_action_queue.
        """
        action_id = str(uuid4())
        thread_config: RunnableConfig = {
            "configurable": {
                "thread_id": f"{tenant_id}:{conversation_id}",
            }
        }


        initial_state: AgentWorkflowState = {
            "tenant_id": tenant_id,
            "conversation_id": conversation_id,
            "user_message": user_message,
            "context_chunks": [],
            "draft_response": "",
            "status": "processing",
            "action_id": action_id,
            "final_response": "",
        }

        # Run graph until interrupt
        await self.graph.ainvoke(initial_state, thread_config)

        # Inspect current interrupted state
        snapshot = await self.graph.aget_state(thread_config)
        is_interrupted = bool(snapshot.tasks and snapshot.tasks[0].interrupts)

        if not is_interrupted:
            return {
                "action_id": action_id,
                "status": "completed",
                "final_response": snapshot.values.get("final_response", ""),
            }

        interrupt_data = cast(dict[str, Any], snapshot.tasks[0].interrupts[0].value)
        draft_text = str(interrupt_data.get("draft_response", ""))

        # Persist action item in agent_action_queue table
        stmt = text(f"""
            INSERT INTO {self.queue_table_name} (
                id, tenant_id, conversation_id, draft_response, status
            ) VALUES (
                :id, :tenant_id, :conversation_id, :draft_response, 'pending'
            )
            ON CONFLICT (id) DO UPDATE SET
                draft_response = EXCLUDED.draft_response,
                status = 'pending'
        """)

        await session.execute(
            stmt,
            {
                "id": action_id,
                "tenant_id": tenant_id,
                "conversation_id": conversation_id,
                "draft_response": draft_text,
            },
        )

        return {
            "action_id": action_id,
            "status": "pending_approval",
            "draft_response": draft_text,
            "thread_id": f"{tenant_id}:{conversation_id}",
        }

    async def resume_agent_workflow(
        self,
        tenant_id: str,
        conversation_id: str,
        action_id: str,
        approved: bool,
        edited_text: str | None,
        session: AsyncSession,
    ) -> dict[str, Any]:
        """
        Resumes an interrupted workflow with human supervisor input.
        Updates action queue record and completes graph execution.
        """
        thread_config: RunnableConfig = {
            "configurable": {
                "thread_id": f"{tenant_id}:{conversation_id}",
            }
        }

        # Update action queue status in database
        status_val = "approved" if approved else "rejected"
        stmt = text(f"""
            UPDATE {self.queue_table_name}
            SET status = :status,
                final_response = :final_response
            WHERE id = :id AND tenant_id = :tenant_id
        """)

        final_draft = edited_text if (approved and edited_text) else ""
        await session.execute(
            stmt,
            {
                "status": status_val,
                "final_response": final_draft,
                "id": action_id,
                "tenant_id": tenant_id,
            },
        )

        # Resume LangGraph execution
        resumed_raw = await self.graph.ainvoke(
            cast(Any, Command(resume={"approved": approved, "edited_text": edited_text})),
            thread_config,
        )
        resumed_state = cast(dict[str, Any], resumed_raw)

        return {
            "action_id": action_id,
            "status": resumed_state.get("status"),
            "final_response": resumed_state.get("final_response"),
        }

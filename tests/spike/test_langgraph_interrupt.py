"""
Spike test validating LangGraph Human-in-the-Loop (HitL) interrupt and resumption.
Acceptance test for Task 0.5.
"""

from collections.abc import AsyncGenerator

import pytest
from sqlalchemy import text

from packages.shared.db.session import admin_session, dispose_engines, tenant_session
from packages.shared.orchestration.service import OrchestrationService

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS test_agent_action_queue (
        id UUID PRIMARY KEY,
        tenant_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        draft_response TEXT NOT NULL,
        final_response TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TIMESTAMPTZ DEFAULT NOW()
    )
    """,
    "ALTER TABLE test_agent_action_queue ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE test_agent_action_queue FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS queue_tenant_policy ON test_agent_action_queue",
    """
    CREATE POLICY queue_tenant_policy ON test_agent_action_queue
        FOR ALL
        USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
        WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), ''))
    """,
    "GRANT ALL ON test_agent_action_queue TO teemeto_app",
]


@pytest.fixture(autouse=True)
async def setup_and_cleanup_queue_table() -> AsyncGenerator[None, None]:
    """Prepares the test action queue table and truncates between tests."""
    async with admin_session() as session:
        for stmt in DDL_STATEMENTS:
            await session.execute(text(stmt))
        await session.execute(text("TRUNCATE TABLE test_agent_action_queue;"))
    yield
    await dispose_engines()


@pytest.mark.asyncio
async def test_langgraph_interrupt_and_resume_with_edit() -> None:
    """
    Verifies that:
    1. Workflow generates draft and pauses before output step.
    2. Pending item is persisted to database action queue.
    3. Human supervisor approves with edited response.
    4. Workflow resumes and finishes with the edited text.
    """
    tenant_id = "tenant-hitl-1"
    conversation_id = "conv-101"
    user_msg = "سلام، آیا امکان ارسال فوری دارید؟"

    service = OrchestrationService(queue_table_name="test_agent_action_queue")

    # Step 1: Start workflow and expect interrupt
    async with tenant_session(tenant_id) as session:
        pause_info = await service.start_agent_workflow(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_message=user_msg,
            session=session,
        )

    action_id = pause_info["action_id"]
    assert pause_info["status"] == "pending_approval"
    assert "درود بر شما" in pause_info["draft_response"]

    # Verify record in database action queue
    async with tenant_session(tenant_id) as session:
        result = await session.execute(
            text("SELECT status, draft_response FROM test_agent_action_queue WHERE id = :id"),
            {"id": action_id},
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "pending"
        assert row[1] == pause_info["draft_response"]

    # Step 2: Human supervisor edits and approves the response
    edited_reply = "سلام! بله، ارسال فوری در تهران ظرف ۲ ساعت انجام می‌شود."

    async with tenant_session(tenant_id) as session:
        final_info = await service.resume_agent_workflow(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            action_id=action_id,
            approved=True,
            edited_text=edited_reply,
            session=session,
        )

    # Assert workflow completed with edited text
    assert final_info["status"] == "completed"
    assert final_info["final_response"] == edited_reply

    # Verify database action queue updated to approved
    async with tenant_session(tenant_id) as session:
        result = await session.execute(
            text("SELECT status, final_response FROM test_agent_action_queue WHERE id = :id"),
            {"id": action_id},
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "approved"
        assert row[1] == edited_reply


@pytest.mark.asyncio
async def test_langgraph_interrupt_and_resume_rejected() -> None:
    """Verifies that rejecting a draft halts the workflow and updates queue status."""
    tenant_id = "tenant-hitl-2"
    conversation_id = "conv-202"
    user_msg = "پیام غیرمرتبط یا نامناسب"

    service = OrchestrationService(queue_table_name="test_agent_action_queue")

    # Step 1: Start workflow
    async with tenant_session(tenant_id) as session:
        pause_info = await service.start_agent_workflow(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            user_message=user_msg,
            session=session,
        )

    action_id = pause_info["action_id"]

    # Step 2: Human supervisor rejects the action
    async with tenant_session(tenant_id) as session:
        final_info = await service.resume_agent_workflow(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            action_id=action_id,
            approved=False,
            edited_text=None,
            session=session,
        )

    # Assert workflow aborted
    assert final_info["status"] == "aborted"
    assert final_info["final_response"] == ""

    # Verify database record marked rejected
    async with tenant_session(tenant_id) as session:
        result = await session.execute(
            text("SELECT status FROM test_agent_action_queue WHERE id = :id"),
            {"id": action_id},
        )
        row = result.fetchone()
        assert row is not None
        assert row[0] == "rejected"

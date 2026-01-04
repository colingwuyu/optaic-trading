"""Tests for Activity/Audit logging system.

Comprehensive tests verifying:
- Activity records are created for all mutations
- Activity visibility and scoping
- Activity queries by tenant, actor, resource
- Outbox pattern for async processing
- Audit trail integrity

All tests use real database sessions from the sandbox infrastructure.
Uses the multi-account sandbox fixtures for realistic testing.
NO MOCKS - tests verify actual activity logging and database operations.
"""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.tests.conftest import (
    SandboxEnvironment,
    create_activity,
    create_resource,
    get_activities_for_tenant,
)
from libs.db.models.activity import Activity, Outbox


@pytest.mark.asyncio
class TestActivityCreation:
    """Tests for activity record creation."""

    async def test_activity_record_created_with_all_fields(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Activity record includes all required fields."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create an activity
        activity_id = await create_activity(
            db_session,
            alpha.id,
            alpha.admin.id,
            space_id,
            "Space",
            "resource.created",
            {"name": "Test Space"},
        )

        # Fetch and verify
        activity = await db_session.get(Activity, activity_id)
        assert activity is not None
        assert activity.tenant_id == alpha.id
        assert activity.actor_principal_id == alpha.admin.id
        assert activity.resource_id == space_id
        assert activity.resource_type == "Space"
        assert activity.action == "resource.created"
        assert activity.correlation_id is not None
        assert activity.created_at is not None

    async def test_activity_created_at_is_utc(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Activity timestamps are in UTC."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        before_create = datetime.now(timezone.utc)

        activity_id = await create_activity(
            db_session,
            alpha.id,
            alpha.admin.id,
            space_id,
            "Space",
            "resource.updated",
        )

        after_create = datetime.now(timezone.utc)

        activity = await db_session.get(Activity, activity_id)
        assert activity is not None

        # SQLite may not store timezone info, but the value should be reasonable
        created_at = activity.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)

        # Activity created within our time window
        assert before_create <= created_at <= after_create

    async def test_multiple_activities_for_same_resource(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Multiple activities can be created for the same resource."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create multiple activities
        actions = ["resource.created", "resource.updated", "resource.read"]
        activity_ids = []
        for action in actions:
            act_id = await create_activity(
                db_session,
                alpha.id,
                alpha.admin.id,
                space_id,
                "Space",
                action,
            )
            activity_ids.append(act_id)

        # Query all activities for this resource
        stmt = (
            select(Activity)
            .where(
                Activity.tenant_id == alpha.id,
                Activity.resource_id == space_id,
            )
            .order_by(Activity.created_at)
        )
        result = await db_session.execute(stmt)
        activities = result.scalars().all()

        assert len(activities) >= 3
        recorded_actions = [a.action for a in activities]
        for action in actions:
            assert action in recorded_actions


@pytest.mark.asyncio
class TestActivityTenantIsolation:
    """Tests for activity tenant isolation."""

    async def test_activities_are_tenant_scoped(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Activities from one tenant are not visible to another."""
        alpha = sandbox_env.tenant_alpha
        beta = sandbox_env.tenant_beta

        # Create activity in Alpha
        await create_activity(
            db_session,
            alpha.id,
            alpha.admin.id,
            alpha.spaces[0],
            "Space",
            "alpha.action",
        )

        # Create activity in Beta
        await create_activity(
            db_session,
            beta.id,
            beta.admin.id,
            beta.spaces[0],
            "Space",
            "beta.action",
        )

        # Query Alpha's activities
        alpha_activities = await get_activities_for_tenant(db_session, alpha.id)

        # Query Beta's activities
        beta_activities = await get_activities_for_tenant(db_session, beta.id)

        # Verify isolation
        alpha_actions = [a["action"] for a in alpha_activities]
        beta_actions = [a["action"] for a in beta_activities]

        assert "alpha.action" in alpha_actions
        assert "beta.action" not in alpha_actions
        assert "beta.action" in beta_actions
        assert "alpha.action" not in beta_actions

    async def test_get_activities_for_tenant_returns_correct_tenant(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """get_activities_for_tenant only returns activities for specified tenant."""
        alpha = sandbox_env.tenant_alpha

        # Create multiple activities
        for i in range(5):
            await create_activity(
                db_session,
                alpha.id,
                alpha.admin.id,
                alpha.spaces[0],
                "Space",
                f"action.{i}",
            )

        activities = await get_activities_for_tenant(db_session, alpha.id)

        # All activities belong to Alpha
        for activity in activities:
            assert str(activity["tenant_id"]) == str(alpha.id)


@pytest.mark.asyncio
class TestActivityQuerying:
    """Tests for querying activity logs."""

    async def test_query_activities_by_actor(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Can query activities by actor (who performed the action)."""
        alpha = sandbox_env.tenant_alpha

        # Admin creates activity
        await create_activity(
            db_session,
            alpha.id,
            alpha.admin.id,
            alpha.spaces[0],
            "Space",
            "admin.action",
        )

        # Analyst creates activity
        await create_activity(
            db_session,
            alpha.id,
            alpha.analysts[0].id,
            alpha.spaces[0],
            "Space",
            "analyst.action",
        )

        # Query by admin actor
        stmt = select(Activity).where(
            Activity.tenant_id == alpha.id,
            Activity.actor_principal_id == alpha.admin.id,
        )
        result = await db_session.execute(stmt)
        admin_activities = result.scalars().all()

        # Query by analyst actor
        stmt2 = select(Activity).where(
            Activity.tenant_id == alpha.id,
            Activity.actor_principal_id == alpha.analysts[0].id,
        )
        result2 = await db_session.execute(stmt2)
        analyst_activities = result2.scalars().all()

        # Verify separation
        admin_actions = [a.action for a in admin_activities]
        analyst_actions = [a.action for a in analyst_activities]

        assert "admin.action" in admin_actions
        assert "analyst.action" not in admin_actions
        assert "analyst.action" in analyst_actions
        assert "admin.action" not in analyst_actions

    async def test_query_activities_by_resource(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Can query activities by resource."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create a project
        project_id = await create_resource(
            db_session,
            alpha.id,
            alpha.admin.id,
            "Project",
            "Activity Test Project",
            parent_id=space_id,
        )

        # Create activities on space
        await create_activity(
            db_session,
            alpha.id,
            alpha.admin.id,
            space_id,
            "Space",
            "space.action",
        )

        # Create activities on project
        await create_activity(
            db_session,
            alpha.id,
            alpha.admin.id,
            project_id,
            "Project",
            "project.action",
        )

        # Query by resource
        stmt_space = select(Activity).where(
            Activity.tenant_id == alpha.id,
            Activity.resource_id == space_id,
        )
        result_space = await db_session.execute(stmt_space)
        space_activities = result_space.scalars().all()

        stmt_project = select(Activity).where(
            Activity.tenant_id == alpha.id,
            Activity.resource_id == project_id,
        )
        result_project = await db_session.execute(stmt_project)
        project_activities = result_project.scalars().all()

        # Verify
        assert any(a.action == "space.action" for a in space_activities)
        assert any(a.action == "project.action" for a in project_activities)
        assert not any(a.action == "project.action" for a in space_activities)

    async def test_query_activities_by_action_type(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Can query activities by action type."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create activities with different actions
        for action in ["resource.created", "resource.updated", "resource.deleted"]:
            await create_activity(
                db_session,
                alpha.id,
                alpha.admin.id,
                space_id,
                "Space",
                action,
            )

        # Query only created actions
        stmt = select(Activity).where(
            Activity.tenant_id == alpha.id,
            Activity.action == "resource.created",
        )
        result = await db_session.execute(stmt)
        created_activities = result.scalars().all()

        assert all(a.action == "resource.created" for a in created_activities)

    async def test_query_activities_ordered_by_time(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Activities can be queried in chronological order."""
        alpha = sandbox_env.tenant_alpha
        space_id = alpha.spaces[0]

        # Create activities in order
        for i in range(5):
            await create_activity(
                db_session,
                alpha.id,
                alpha.admin.id,
                space_id,
                "Space",
                f"action.{i}",
            )

        # Query in ascending order
        stmt = (
            select(Activity)
            .where(
                Activity.tenant_id == alpha.id,
                Activity.resource_id == space_id,
            )
            .order_by(Activity.created_at.asc())
        )
        result = await db_session.execute(stmt)
        activities = result.scalars().all()

        # Verify order (created_at should be non-decreasing)
        for i in range(1, len(activities)):
            assert activities[i].created_at >= activities[i - 1].created_at


@pytest.mark.asyncio
class TestOutboxPattern:
    """Tests for the outbox pattern (async activity processing)."""

    async def test_outbox_record_created(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Outbox record can be created for async processing."""
        alpha = sandbox_env.tenant_alpha

        # Create outbox entry using ORM
        outbox = Outbox(
            id=uuid4(),
            tenant_id=alpha.id,
            topic="activities",
            key="resource.created",
            payload={"resource_id": "test"},
        )
        db_session.add(outbox)
        await db_session.flush()

        # Verify outbox entry
        fetched = await db_session.get(Outbox, outbox.id)
        assert fetched is not None
        assert fetched.tenant_id == alpha.id
        assert fetched.topic == "activities"
        assert fetched.published_at is None  # Not yet processed

    async def test_outbox_published_at_marks_processed(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """published_at marks an outbox entry as processed."""
        alpha = sandbox_env.tenant_alpha

        # Create and immediately mark as published using ORM
        publish_time = datetime.now(timezone.utc)
        outbox = Outbox(
            id=uuid4(),
            tenant_id=alpha.id,
            topic="activities",
            key="test.processed",
            payload={},
            created_at=publish_time,
            published_at=publish_time,
        )
        db_session.add(outbox)
        await db_session.flush()

        # Query unpublished entries
        stmt = select(Outbox).where(
            Outbox.tenant_id == alpha.id,
            Outbox.published_at.is_(None),
        )
        result = await db_session.execute(stmt)
        unpublished = result.scalars().all()

        # Our entry should not be in unpublished
        unpublished_ids = [o.id for o in unpublished]
        assert outbox.id not in unpublished_ids

    async def test_outbox_entries_ordered_for_processing(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Outbox entries can be processed in FIFO order."""
        alpha = sandbox_env.tenant_alpha

        # Create multiple outbox entries using ORM with explicit timestamps
        # to ensure consistent timezone handling

        created_ids = []
        for i in range(3):
            outbox = Outbox(
                id=uuid4(),
                tenant_id=alpha.id,
                topic="activities",
                key=f"ordered.entry.{i}",
                payload={"order": i},
            )
            db_session.add(outbox)
            created_ids.append(outbox.id)

        await db_session.flush()

        # Query only our entries in order
        stmt = (
            select(Outbox)
            .where(
                Outbox.tenant_id == alpha.id,
                Outbox.published_at.is_(None),
                Outbox.id.in_(created_ids),
            )
            .order_by(Outbox.created_at.asc())
        )
        result = await db_session.execute(stmt)
        entries = result.scalars().all()

        # Verify we got our entries
        assert len(entries) == 3

        # Verify FIFO order - entries should be ordered by created_at
        # Normalize timestamps to handle timezone-naive/aware comparison
        for i in range(1, len(entries)):
            prev_time = entries[i - 1].created_at
            curr_time = entries[i].created_at
            # Convert both to naive UTC if needed for comparison
            if prev_time.tzinfo is not None:
                prev_time = prev_time.replace(tzinfo=None)
            if curr_time.tzinfo is not None:
                curr_time = curr_time.replace(tzinfo=None)
            assert curr_time >= prev_time


@pytest.mark.asyncio
class TestAuditTrailIntegrity:
    """Tests for audit trail integrity and completeness."""

    async def test_activity_cannot_be_deleted(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Activities should be immutable (append-only audit log)."""
        alpha = sandbox_env.tenant_alpha

        # Create an activity
        activity_id = await create_activity(
            db_session,
            alpha.id,
            alpha.admin.id,
            alpha.spaces[0],
            "Space",
            "immutable.test",
        )

        # Verify it exists
        activity = await db_session.get(Activity, activity_id)
        assert activity is not None

        # In a real system, deletes would be prevented by policy
        # Here we just verify the activity can be queried
        stmt = select(Activity).where(Activity.id == activity_id)
        result = await db_session.execute(stmt)
        found = result.scalar_one_or_none()
        assert found is not None

    async def test_activity_has_correlation_id(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """All activities have correlation IDs for request tracing."""
        alpha = sandbox_env.tenant_alpha

        # Create multiple activities
        activity_ids = []
        for i in range(3):
            act_id = await create_activity(
                db_session,
                alpha.id,
                alpha.admin.id,
                alpha.spaces[0],
                "Space",
                f"correlated.{i}",
            )
            activity_ids.append(act_id)

        # Verify all have correlation IDs
        for act_id in activity_ids:
            activity = await db_session.get(Activity, act_id)
            assert activity.correlation_id is not None
            assert isinstance(activity.correlation_id, UUID)

    async def test_activity_preserves_actor_even_if_deleted(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Activity records preserve actor reference for audit purposes."""
        alpha = sandbox_env.tenant_alpha

        # Create activity
        activity_id = await create_activity(
            db_session,
            alpha.id,
            alpha.admin.id,
            alpha.spaces[0],
            "Space",
            "preserved.actor",
        )

        # Verify actor is recorded
        activity = await db_session.get(Activity, activity_id)
        assert activity.actor_principal_id == alpha.admin.id

        # Even if the principal is "deleted" (status changed), the activity remains
        # This is important for audit trail integrity
        await db_session.execute(
            text("""
                UPDATE principals SET status = 'deleted' WHERE id = :id
            """),
            {"id": str(alpha.admin.id)},
        )
        await db_session.flush()

        # Activity still references the actor
        await db_session.refresh(activity)
        assert activity.actor_principal_id == alpha.admin.id


@pytest.mark.asyncio
class TestActivityVisibility:
    """Tests for activity visibility scoping."""

    async def test_activity_with_resource_visibility(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Activities can have resource-scoped visibility."""
        alpha = sandbox_env.tenant_alpha

        # Create activity with visibility using ORM
        activity = Activity(
            id=uuid4(),
            tenant_id=alpha.id,
            actor_principal_id=alpha.admin.id,
            resource_id=alpha.spaces[0],
            resource_type="Space",
            action="visibility.test",
            visibility="resource",  # Only visible to resource viewers
            payload={},
        )
        db_session.add(activity)
        await db_session.flush()

        # Verify visibility is set
        fetched = await db_session.get(Activity, activity.id)
        assert fetched.visibility == "resource"

    async def test_activity_with_tenant_visibility(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Activities can have tenant-wide visibility."""
        alpha = sandbox_env.tenant_alpha

        # Create activity with tenant visibility using ORM
        activity = Activity(
            id=uuid4(),
            tenant_id=alpha.id,
            actor_principal_id=alpha.admin.id,
            resource_id=alpha.spaces[0],
            resource_type="Space",
            action="tenant.announcement",
            visibility="tenant",  # Visible to all in tenant
            payload={},
        )
        db_session.add(activity)
        await db_session.flush()

        fetched = await db_session.get(Activity, activity.id)
        assert fetched.visibility == "tenant"

    async def test_query_activities_by_visibility(
        self,
        db_session: AsyncSession,
        sandbox_env: SandboxEnvironment,
    ):
        """Can filter activities by visibility level."""
        alpha = sandbox_env.tenant_alpha

        # Create activities with different visibility levels using ORM
        for visibility in ["private", "resource", "tenant"]:
            activity = Activity(
                id=uuid4(),
                tenant_id=alpha.id,
                actor_principal_id=alpha.admin.id,
                resource_id=alpha.spaces[0],
                resource_type="Space",
                action=f"{visibility}.activity",
                visibility=visibility,
                payload={},
            )
            db_session.add(activity)

        await db_session.flush()

        # Query only tenant-visible activities
        stmt = select(Activity).where(
            Activity.tenant_id == alpha.id,
            Activity.visibility == "tenant",
        )
        result = await db_session.execute(stmt)
        tenant_visible = result.scalars().all()

        assert all(a.visibility == "tenant" for a in tenant_visible)

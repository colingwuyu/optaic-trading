"""Lineage Observers for Pub/Sub Pattern.

Phase 2.8.3: Implements the observer pattern for lineage-based notifications.

When an upstream dataset completes:
1. Query downstream dependents from dataset_lineage table
2. Update their upstream_status to mark this upstream as "ready"
3. Check if all upstreams are now ready
4. Publish notification to Centrifugo for real-time UI updates
5. Optionally auto-trigger downstream runs if configured

This module bridges the activity system with the lineage system,
enabling reactive data pipelines.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Optional
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

from .lineage import LineageResolver

logger = logging.getLogger(__name__)


class LineageObserver:
    """Observes pipeline completion and notifies downstream dependents.

    This class is the core of the pub/sub pattern for lineage:
    - Listens to pipeline.run_completed events
    - Updates downstream instance's upstream_status
    - Determines which downstreams are now ready to run
    - Publishes real-time notifications

    Example usage in worker:
        observer = LineageObserver()
        ready_ids = await observer.on_upstream_completed(
            session,
            upstream_id=activity.resource_id,
            run_id=activity.payload["run_id"],
        )

        for downstream_id in ready_ids:
            await centrifugo.publish(f"datasets:{downstream_id}", {...})
    """

    def __init__(self) -> None:
        """Initialize the LineageObserver."""
        self._lineage_resolver = LineageResolver()

    async def on_upstream_completed(
        self,
        session: "AsyncSession",
        upstream_id: UUID,
        run_id: UUID,
        *,
        propagate: bool = True,
    ) -> list[UUID]:
        """Handle upstream pipeline completion event.

        This is called by the worker when a pipeline.run_completed activity
        is processed. It updates all downstream dependents and returns
        those that are now ready to run (all upstreams complete).

        Args:
            session: Database session
            upstream_id: The DatasetInstance that just completed
            run_id: The PipelineRun ID that completed
            propagate: If True, also mark downstream as "fresh" if appropriate

        Returns:
            List of downstream DatasetInstance IDs that are now fully ready
        """
        from sqlalchemy import select

        from libs.db.models.quant import DatasetInstance, DatasetLineage

        # 1. Get all direct downstream dependents
        stmt = select(DatasetLineage.downstream_resource_id).where(
            DatasetLineage.upstream_resource_id == upstream_id
        )
        result = await session.execute(stmt)
        downstream_ids = list(result.scalars().all())

        if not downstream_ids:
            logger.debug(f"No downstreams for upstream {upstream_id}")
            return []

        logger.info(
            f"Notifying {len(downstream_ids)} downstreams of upstream {upstream_id} completion"
        )

        # 2. Update each downstream's upstream_status
        ready_ids: list[UUID] = []

        for downstream_id in downstream_ids:
            instance = await session.get(DatasetInstance, downstream_id)
            if not instance:
                continue

            # Update upstream status
            all_ready = await self._lineage_resolver.update_upstream_status(
                session, downstream_id, upstream_id, "ready"
            )

            if all_ready:
                ready_ids.append(downstream_id)
                logger.info(f"Downstream {downstream_id} is now fully ready")

        await session.flush()
        return ready_ids

    async def on_upstream_failed(
        self,
        session: "AsyncSession",
        upstream_id: UUID,
        run_id: UUID,
        error: Optional[str] = None,
    ) -> list[UUID]:
        """Handle upstream pipeline failure event.

        Marks the upstream as "error" in all downstream dependents.

        Args:
            session: Database session
            upstream_id: The DatasetInstance that failed
            run_id: The PipelineRun ID that failed
            error: Optional error message

        Returns:
            List of affected downstream DatasetInstance IDs
        """
        from sqlalchemy import select

        from libs.db.models.quant import DatasetLineage

        # Get all direct downstream dependents
        stmt = select(DatasetLineage.downstream_resource_id).where(
            DatasetLineage.upstream_resource_id == upstream_id
        )
        result = await session.execute(stmt)
        downstream_ids = list(result.scalars().all())

        if not downstream_ids:
            return []

        logger.warning(
            f"Notifying {len(downstream_ids)} downstreams of upstream {upstream_id} failure"
        )

        # Update each downstream's upstream_status to error
        affected_ids: list[UUID] = []
        for downstream_id in downstream_ids:
            await self._lineage_resolver.update_upstream_status(
                session, downstream_id, upstream_id, "error"
            )
            affected_ids.append(downstream_id)

        await session.flush()
        return affected_ids

    async def on_upstream_started(
        self,
        session: "AsyncSession",
        upstream_id: UUID,
        run_id: UUID,
    ) -> list[UUID]:
        """Handle upstream pipeline started event.

        Marks the upstream as "running" in all downstream dependents.
        This allows UI to show that an upstream is currently refreshing.

        Args:
            session: Database session
            upstream_id: The DatasetInstance that started
            run_id: The PipelineRun ID that started

        Returns:
            List of affected downstream DatasetInstance IDs
        """
        from sqlalchemy import select

        from libs.db.models.quant import DatasetLineage

        # Get all direct downstream dependents
        stmt = select(DatasetLineage.downstream_resource_id).where(
            DatasetLineage.upstream_resource_id == upstream_id
        )
        result = await session.execute(stmt)
        downstream_ids = list(result.scalars().all())

        if not downstream_ids:
            return []

        # Update each downstream's upstream_status to running
        affected_ids: list[UUID] = []
        for downstream_id in downstream_ids:
            await self._lineage_resolver.update_upstream_status(
                session, downstream_id, upstream_id, "running"
            )
            affected_ids.append(downstream_id)

        await session.flush()
        return affected_ids

    async def get_ready_to_run(
        self,
        session: "AsyncSession",
        tenant_id: UUID,
    ) -> list[UUID]:
        """Get all datasets that are ready to run (all upstreams complete).

        Useful for finding datasets that can be refreshed in a batch.

        Args:
            session: Database session
            tenant_id: Tenant ID

        Returns:
            List of DatasetInstance IDs ready to run
        """
        from sqlalchemy import select

        from libs.db.models.quant import DatasetInstance

        # Get all datasets with upstream dependencies
        stmt = select(DatasetInstance).where(
            DatasetInstance.tenant_id == tenant_id,
            DatasetInstance.upstream_resource_ids.isnot(None),
        )
        result = await session.execute(stmt)
        instances = result.scalars().all()

        ready_ids: list[UUID] = []
        for instance in instances:
            upstream_ids = instance.upstream_resource_ids or []
            if not upstream_ids:
                continue

            # Check if all upstreams are ready
            upstream_status = instance.upstream_status or {}
            all_ready = all(
                upstream_status.get(str(uid)) == "ready" for uid in upstream_ids
            )

            if all_ready:
                ready_ids.append(instance.resource_id)

        return ready_ids


class CentrifugoNotifier:
    """Publishes lineage events to Centrifugo for real-time UI updates.

    Channels:
    - datasets:{id} - Per-dataset events (upstream_ready, upstream_failed)
    - lineage:{tenant_id} - Tenant-wide lineage events
    """

    def __init__(self, centrifugo_client: Any = None) -> None:
        """Initialize the notifier.

        Args:
            centrifugo_client: Optional Centrifugo client. If None, will be lazy loaded.
        """
        self._client = centrifugo_client

    async def _get_client(self) -> Any:
        """Lazy load the Centrifugo client."""
        if self._client is None:
            try:
                from libs.realtime import get_centrifugo_client

                self._client = await get_centrifugo_client()
            except ImportError:
                logger.warning("Centrifugo client not available")
                return None
        return self._client

    async def notify_upstream_ready(
        self,
        downstream_id: UUID,
        upstream_id: UUID,
        all_ready: bool,
    ) -> None:
        """Notify a downstream that an upstream is ready.

        Args:
            downstream_id: The downstream DatasetInstance ID
            upstream_id: The upstream DatasetInstance ID that completed
            all_ready: Whether all upstreams are now ready
        """
        client = await self._get_client()
        if not client:
            return

        try:
            await client.publish(
                channel=f"datasets:{downstream_id}",
                data={
                    "event": "upstream_ready",
                    "upstream_id": str(upstream_id),
                    "all_ready": all_ready,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to publish upstream_ready: {e}")

    async def notify_upstream_failed(
        self,
        downstream_id: UUID,
        upstream_id: UUID,
        error: Optional[str] = None,
    ) -> None:
        """Notify a downstream that an upstream failed.

        Args:
            downstream_id: The downstream DatasetInstance ID
            upstream_id: The upstream DatasetInstance ID that failed
            error: Optional error message
        """
        client = await self._get_client()
        if not client:
            return

        try:
            await client.publish(
                channel=f"datasets:{downstream_id}",
                data={
                    "event": "upstream_failed",
                    "upstream_id": str(upstream_id),
                    "error": error,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to publish upstream_failed: {e}")

    async def notify_lineage_change(
        self,
        tenant_id: UUID,
        resource_id: UUID,
        change_type: str,  # "created", "deleted", "updated"
    ) -> None:
        """Notify tenant-wide that lineage has changed.

        Args:
            tenant_id: Tenant ID
            resource_id: Resource that changed
            change_type: Type of change
        """
        client = await self._get_client()
        if not client:
            return

        try:
            await client.publish(
                channel=f"lineage:{tenant_id}",
                data={
                    "event": "lineage_change",
                    "resource_id": str(resource_id),
                    "change_type": change_type,
                },
            )
        except Exception as e:
            logger.warning(f"Failed to publish lineage_change: {e}")

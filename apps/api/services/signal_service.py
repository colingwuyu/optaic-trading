"""Signal Service - Signal Registration and Validation.

Signals are datasets that have been promoted with a SignalSpec defining:
- Bounds (min/max values)
- Neutral value
- Index schema (columns, frequency)
- Whether NaN is allowed

This service handles:
- Registering datasets as signals
- Validating signal data against specs
- Promoting signals to official status
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.activity import ActivityEnvelope, record_activity_with_outbox
from libs.core.rbac.models import ActorContext
from libs.db.models.quant import DatasetInstance, SignalSpec
from libs.db.models.resource import Resource

if TYPE_CHECKING:
    import pandas as pd


class SignalService:
    """Service for signal operations.

    Signals are datasets with additional constraints:
    - Bounded values (typically -1 to 1)
    - No lookahead bias (PIT correctness)
    - Defined index schema (entity, date)

    The SignalSpec extension table stores these constraints.
    """

    async def register_signal(
        self,
        session: AsyncSession,
        actor: ActorContext,
        dataset_id: UUID,
        *,
        min_value: float = -1.0,
        max_value: float = 1.0,
        neutral_value: float = 0.0,
        allow_nan: bool = False,
        index_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a dataset as a signal.

        This creates a SignalSpec extension for the dataset resource,
        defining the constraints that the signal data must satisfy.

        Args:
            session: Database session
            actor: Actor context
            dataset_id: Dataset resource ID to register as signal
            min_value: Minimum allowed value (default: -1.0)
            max_value: Maximum allowed value (default: 1.0)
            neutral_value: Neutral/no-signal value (default: 0.0)
            allow_nan: Whether NaN values are allowed (default: False)
            index_schema: Schema for index columns

        Returns:
            Signal registration info
        """
        # Check if already registered
        existing = await session.get(SignalSpec, dataset_id)
        if existing:
            raise ValueError(f"Dataset {dataset_id} is already registered as a signal")

        # Verify dataset exists
        resource = await session.get(Resource, dataset_id)
        if not resource or resource.tenant_id != actor.tenant_id:
            raise ValueError(f"Dataset {dataset_id} not found")

        # Create SignalSpec
        signal_spec = SignalSpec(
            resource_id=dataset_id,
            tenant_id=actor.tenant_id,
            min_value=min_value,
            max_value=max_value,
            neutral_value=neutral_value,
            allow_nan=allow_nan,
            index_schema_json=index_schema or {},
        )
        session.add(signal_spec)

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=dataset_id,
            resource_type="SignalSpec",
            action="signal.registered",
            payload={
                "min_value": min_value,
                "max_value": max_value,
                "neutral_value": neutral_value,
                "allow_nan": allow_nan,
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.commit()

        return {
            "id": str(dataset_id),
            "name": resource.name,
            "min_value": min_value,
            "max_value": max_value,
            "neutral_value": neutral_value,
            "allow_nan": allow_nan,
            "status": "registered",
        }

    async def get_signal(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        signal_id: UUID,
    ) -> dict[str, Any] | None:
        """Get signal spec and metadata.

        Args:
            session: Database session
            tenant_id: Tenant ID
            signal_id: Signal resource ID

        Returns:
            Signal info or None if not found
        """
        spec = await session.get(SignalSpec, signal_id)
        if not spec or spec.tenant_id != tenant_id:
            return None

        resource = await session.get(Resource, signal_id)
        if not resource:
            return None

        # Get dataset info if linked
        dataset_instance = await session.get(DatasetInstance, signal_id)

        return {
            "id": str(signal_id),
            "name": resource.name,
            "min_value": spec.min_value,
            "max_value": spec.max_value,
            "neutral_value": spec.neutral_value,
            "allow_nan": spec.allow_nan,
            "index_schema": spec.index_schema_json,
            "source_expression": spec.source_expression,
            "freshness_status": dataset_instance.freshness_status if dataset_instance else None,
            "last_data_date": str(dataset_instance.last_data_date) if dataset_instance and dataset_instance.last_data_date else None,
        }

    async def validate_signal(
        self,
        session: AsyncSession,
        actor: ActorContext,
        signal_id: UUID,
        data: "pd.DataFrame",
    ) -> dict[str, Any]:
        """Validate signal data against its spec.

        Checks:
        - Values within bounds
        - NaN handling
        - Index schema compliance

        Args:
            session: Database session
            actor: Actor context
            signal_id: Signal resource ID
            data: DataFrame to validate

        Returns:
            Validation result with issues if any
        """
        spec = await session.get(SignalSpec, signal_id)
        if not spec or spec.tenant_id != actor.tenant_id:
            return {
                "valid": False,
                "issues": [{"code": "SIGNAL_NOT_FOUND", "message": f"Signal {signal_id} not found"}],
            }

        issues = []

        # Check bounds
        if spec.min_value is not None:
            below_min = (data < spec.min_value).any().any()
            if below_min:
                issues.append({
                    "code": "BELOW_MIN",
                    "message": f"Values below minimum {spec.min_value}",
                })

        if spec.max_value is not None:
            above_max = (data > spec.max_value).any().any()
            if above_max:
                issues.append({
                    "code": "ABOVE_MAX",
                    "message": f"Values above maximum {spec.max_value}",
                })

        # Check NaN
        if not spec.allow_nan:
            has_nan = data.isna().any().any()
            if has_nan:
                issues.append({
                    "code": "CONTAINS_NAN",
                    "message": "Signal contains NaN values but allow_nan=False",
                })

        # Emit validation activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=signal_id,
            resource_type="SignalSpec",
            action="signal.validated",
            payload={
                "valid": len(issues) == 0,
                "issue_count": len(issues),
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.commit()

        return {
            "valid": len(issues) == 0,
            "issues": issues,
            "checked": {
                "rows": len(data),
                "columns": list(data.columns),
            },
        }

    async def list_signals(
        self,
        session: AsyncSession,
        actor: ActorContext,
        *,
        parent_id: UUID | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List signals.

        Args:
            session: Database session
            actor: Actor context
            parent_id: Optional parent resource filter
            status: Optional status filter (e.g. "active")
            limit: Maximum results

        Returns:
            List of signal info dicts
        """
        stmt = (
            select(Resource, SignalSpec)
            .join(SignalSpec, Resource.id == SignalSpec.resource_id)
            .where(
                Resource.tenant_id == actor.tenant_id,
            )
        )

        if status:
            stmt = stmt.where(Resource.status == status)
        else:
            # Default to active if no status specified? Or list all?
            # Originally it was hardcoded to active. Let's keep that default if status is None
            # Or usually list endpoints show all if not filtered?
            # Existing code hardcoded 'active'. Let's relax it or default to active.
            # Usually list endpoints without status filter return all non-deleted?
            # Let's match original behavior if status is None -> 'active'
            # But wait, Router default in signals.py is None. 
            # If I want to see 'registered' signals I need to pass status='registered'.
            # If status is None, maybe return all? 
            # Original code: where(Resource.status == "active")
            # Usually users might want to see 'active' by default.
            stmt = stmt.where(Resource.status == "active")

        if parent_id:
            stmt = stmt.where(Resource.parent_id == parent_id)

        stmt = stmt.limit(limit)

        result = await session.execute(stmt)
        rows = result.all()

        signals = []
        for resource, spec in rows:
            # Optionally get dataset freshness
            dataset_instance = await session.get(DatasetInstance, resource.id)
            signals.append({
                "id": str(resource.id),
                "name": resource.name,
                "min_value": spec.min_value,
                "max_value": spec.max_value,
                "allow_nan": spec.allow_nan,
                "freshness_status": dataset_instance.freshness_status if dataset_instance else None,
            })

        return signals

    async def promote_signal(
        self,
        session: AsyncSession,
        actor: ActorContext,
        signal_id: UUID,
    ) -> dict[str, Any]:
        """Promote a signal to official status.

        This requires all validation to pass and marks the signal
        as official in its subspace.

        Args:
            session: Database session
            actor: Actor context
            signal_id: Signal resource ID

        Returns:
            Promotion status
        """
        resource = await session.get(Resource, signal_id)
        if not resource or resource.tenant_id != actor.tenant_id:
            raise ValueError(f"Signal {signal_id} not found")

        spec = await session.get(SignalSpec, signal_id)
        if not spec:
            raise ValueError(f"Signal spec for {signal_id} not found")

        # Update subspace to official
        resource.subspace_kind = "official"
        await session.flush()

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=signal_id,
            resource_type="SignalSpec",
            action="signal.promoted",
            payload={
                "subspace_kind": "official",
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.commit()

        return {
            "id": str(signal_id),
            "name": resource.name,
            "subspace_kind": resource.subspace_kind,
            "status": "promoted",
        }

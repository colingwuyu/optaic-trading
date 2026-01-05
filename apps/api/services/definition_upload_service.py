"""Definition Upload Service - Main Orchestrator.

This service handles the complete upload workflow:
1. Receive ZIP file from API
2. Parse and validate via ExtensionLoader
3. Run tests via TestRunnerService (if test_suite_file specified)
4. Create Resource and Definition extension records
5. Create DefinitionUpload tracking record
6. Register plugin in FactoryRegistry (if tests pass/skipped)
7. Emit activity events

The uploaded definition can then be used to create Instances.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from libs.core.activity import (
    ActivityEnvelope,
    record_activity_with_outbox,
    tx_activity,
)
from libs.core.artifacts import get_artifact_manager
from libs.core.plugin_loader import register_plugin
from libs.core.rbac.models import ActorContext
from libs.db.models.definition_upload import DefinitionUpload
from libs.db.models.quant import (
    AccessorDefinition,
    OpDefinition,
    PipelineDefinition,
    StoreDefinition,
)
from libs.db.models.resource import Resource

from .extension_loader import (
    ExtensionLoader,
    LoadedPackage,
    ManifestValidationError,
    ZipValidationError,
    get_extension_loader,
)
from .test_runner_service import TestRunnerService, TestRunResult, get_test_runner

logger = structlog.get_logger(__name__)


# Definition type to extension model mapping
DEFINITION_EXTENSION_MAP = {
    "PipelineDef": PipelineDefinition,
    "StoreDef": StoreDefinition,
    "AccessorDef": AccessorDefinition,
    "OpDef": OpDefinition,
    # Add more as needed: MLModuleDef, PortfolioOptimizerDef
}


class DefinitionUploadError(Exception):
    """Base exception for definition upload errors."""

    pass


class DefinitionUploadService:
    """Orchestrates the complete definition upload workflow.

    Workflow:
    1. Parse ZIP and validate manifest via ExtensionLoader
    2. Run tests if test_suite_file specified
    3. Create Resource with artifact_ref
    4. Create Definition extension (e.g., PipelineDefinition)
    5. Create DefinitionUpload tracking record
    6. Register plugin in factory (if active)
    7. Emit activities

    Usage:
        service = DefinitionUploadService()
        result = await service.upload(
            session=db_session,
            actor=actor_context,
            zip_content=file_bytes,
            target_parent_id=project_id,  # Optional
        )
    """

    def __init__(
        self,
        extension_loader: ExtensionLoader | None = None,
        test_runner: TestRunnerService | None = None,
    ) -> None:
        """Initialize the service.

        Args:
            extension_loader: ExtensionLoader instance
            test_runner: TestRunnerService instance
        """
        self._extension_loader = extension_loader or get_extension_loader()
        self._test_runner = test_runner or get_test_runner()
        self._artifact_manager = get_artifact_manager()

    async def upload(
        self,
        session: AsyncSession,
        actor: ActorContext,
        zip_content: bytes,
        *,
        original_filename: str = "upload.zip",
        target_parent_id: UUID | None = None,
        skip_tests: bool = False,
    ) -> dict[str, Any]:
        """Upload a definition plugin.

        Args:
            session: Database session
            actor: Actor context
            zip_content: ZIP file content
            original_filename: Original filename
            target_parent_id: Parent resource ID (defaults to tenant root)
            skip_tests: Skip test execution

        Returns:
            Upload result with resource info

        Raises:
            DefinitionUploadError: If upload fails
            ManifestValidationError: If manifest invalid
            ZipValidationError: If ZIP invalid
        """
        # Emit start activity
        upload_id = uuid4()
        started_at = datetime.now(timezone.utc)

        logger.info(
            "definition_upload.starting",
            upload_id=str(upload_id),
            original_filename=original_filename,
            size_bytes=len(zip_content),
        )

        # Step 1: Parse and validate ZIP
        try:
            package = self._extension_loader.load_package(
                zip_content=zip_content,
                original_filename=original_filename,
            )
        except (ZipValidationError, ManifestValidationError) as e:
            # Emit failure activity
            await self._emit_upload_failed(session, actor, upload_id, str(e))
            raise

        logger.info(
            "definition_upload.package_loaded",
            artifact_ref=str(package.artifact_ref),
            definition_type=package.manifest.definition_type,
            class_name=package.manifest.class_name,
        )

        # Step 2: Run tests if test_suite_file specified
        test_result: TestRunResult | None = None
        evaluation_status = "skipped"

        if package.manifest.test_suite_file and not skip_tests:
            evaluation_status = "running"

            # Emit test started activity
            await self._emit_tests_started(session, actor, package, upload_id)

            test_result = await self._test_runner.run_tests(
                artifact_ref=package.artifact_ref,
                test_file=package.manifest.test_suite_file,
                module_file=package.manifest.module_file,
            )

            evaluation_status = "passed" if test_result.passed else "failed"

            # Emit test result activity
            await self._emit_tests_completed(
                session, actor, package, upload_id, test_result
            )

            # Commit test activities before creating resource
            # This ensures record_activity_with_outbox doesn't leave session in
            # a partial transaction state that would cause tx_activity to use
            # begin_nested() instead of begin()
            await session.commit()

        # Step 3: Determine resource status
        # active if tests pass or skipped, draft if tests fail
        resource_status = (
            "active" if evaluation_status in ("passed", "skipped") else "draft"
        )

        # Step 4: Create Resource, Extension, and DefinitionUpload
        resource_id = uuid4()

        async def domain_fn(sess: AsyncSession) -> Resource:
            # Resolve parent_id
            parent_id = target_parent_id
            if parent_id is None:
                # Use actor's default space/project
                parent_id = await self._get_default_parent(sess, actor)

            # Create Resource
            resource = Resource(
                id=resource_id,
                tenant_id=actor.tenant_id,
                type=package.manifest.definition_type,
                parent_id=parent_id,
                owner_principal_id=actor.id,
                name=package.manifest.name,
                artifact_ref=package.artifact_ref,
                space_kind="team",
                subspace_kind="staging",
                status=resource_status,
                metadata_json={
                    "version": package.manifest.version,
                    "category": package.manifest.category,
                    "description": package.manifest.description,
                },
            )
            sess.add(resource)
            await sess.flush()

            # Create Definition Extension
            await self._create_definition_extension(sess, actor, resource_id, package)

            # Create DefinitionUpload tracking record
            definition_upload = DefinitionUpload(
                id=upload_id,
                tenant_id=actor.tenant_id,
                resource_id=resource_id,
                original_filename=original_filename,
                manifest_version=package.manifest.version,
                upload_size_bytes=package.total_size_bytes,
                module_file=package.manifest.module_file,
                class_name=package.manifest.class_name,
                test_suite_file=package.manifest.test_suite_file,
                evaluation_status=evaluation_status,
                tests_total=test_result.tests_total if test_result else None,
                tests_passed=test_result.tests_passed if test_result else None,
                tests_failed=test_result.tests_failed if test_result else None,
                test_duration_ms=test_result.duration_ms if test_result else None,
                test_output=test_result.output if test_result else None,
                test_report_json=test_result.report_json if test_result else None,
                manifest_json=package.manifest.raw_json,
                uploaded_by=actor.id,
                uploaded_at=started_at,
                tests_started_at=test_result.started_at if test_result else None,
                tests_completed_at=test_result.completed_at if test_result else None,
            )
            sess.add(definition_upload)
            await sess.flush()

            return resource

        # Create with activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=resource_id,
            resource_type=package.manifest.definition_type,
            action="definition.upload_completed",
            payload={
                "name": package.manifest.name,
                "version": package.manifest.version,
                "definition_type": package.manifest.definition_type,
                "code_ref": package.manifest.class_name,
                "status": resource_status,
                "evaluation_status": evaluation_status,
                "artifact_ref": str(package.artifact_ref),
            },
        )
        resource, _ = await tx_activity(session, envelope, domain_fn)

        # Step 5: Register plugin in factory (if active)
        if resource_status == "active":
            try:
                register_plugin(
                    definition_type=package.manifest.definition_type,
                    artifact_ref=package.artifact_ref,
                    module_file=package.manifest.module_file,
                    class_name=package.manifest.class_name,
                )
                logger.info(
                    "definition_upload.plugin_registered",
                    code_ref=package.manifest.class_name,
                    definition_type=package.manifest.definition_type,
                )
            except Exception as e:
                # Log but don't fail - plugin can be loaded later
                logger.warning(
                    "definition_upload.plugin_registration_failed",
                    code_ref=package.manifest.class_name,
                    error=str(e),
                )

        logger.info(
            "definition_upload.completed",
            resource_id=str(resource_id),
            name=package.manifest.name,
            status=resource_status,
            evaluation_status=evaluation_status,
        )

        return {
            "id": str(resource_id),
            "name": package.manifest.name,
            "version": package.manifest.version,
            "definition_type": package.manifest.definition_type,
            "code_ref": package.manifest.class_name,
            "status": resource_status,
            "evaluation_status": evaluation_status,
            "artifact_ref": str(package.artifact_ref),
            "tests_total": test_result.tests_total if test_result else None,
            "tests_passed": test_result.tests_passed if test_result else None,
            "tests_failed": test_result.tests_failed if test_result else None,
            "issues": (
                [f.test_name + ": " + f.message for f in test_result.failures]
                if test_result and test_result.failures
                else []
            ),
        }

    async def deploy(
        self,
        session: AsyncSession,
        actor: ActorContext,
        definition_id: UUID,
    ) -> dict[str, Any]:
        """Deploy a draft definition.

        Changes status from draft to active and registers plugin.

        Args:
            session: Database session
            actor: Actor context
            definition_id: Definition resource ID

        Returns:
            Deployment result
        """
        resource = await session.get(Resource, definition_id)
        if not resource or resource.tenant_id != actor.tenant_id:
            raise DefinitionUploadError(f"Definition {definition_id} not found")

        if resource.status != "draft":
            raise DefinitionUploadError(
                f"Cannot deploy: status is '{resource.status}', expected 'draft'"
            )

        # Get upload record for module info
        stmt = select(DefinitionUpload).where(
            DefinitionUpload.resource_id == definition_id
        )
        result = await session.scalars(stmt)
        upload = result.first()

        if not upload:
            raise DefinitionUploadError(f"Upload record not found for {definition_id}")

        # Register plugin in factory
        try:
            register_plugin(
                definition_type=resource.type,
                artifact_ref=resource.artifact_ref,
                module_file=upload.module_file,
                class_name=upload.class_name,
            )
        except Exception as e:
            raise DefinitionUploadError(f"Failed to register plugin: {e}") from e

        # Update status
        resource.status = "active"
        await session.flush()

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=definition_id,
            resource_type=resource.type,
            action="definition.deployed",
            payload={
                "code_ref": upload.class_name,
                "artifact_ref": str(resource.artifact_ref),
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.commit()

        return {
            "id": str(definition_id),
            "name": resource.name,
            "code_ref": upload.class_name,
            "status": "active",
        }

    async def rerun_tests(
        self,
        session: AsyncSession,
        actor: ActorContext,
        definition_id: UUID,
    ) -> dict[str, Any]:
        """Re-run tests for a definition.

        Args:
            session: Database session
            actor: Actor context
            definition_id: Definition resource ID

        Returns:
            Test results
        """
        resource = await session.get(Resource, definition_id)
        if not resource or resource.tenant_id != actor.tenant_id:
            raise DefinitionUploadError(f"Definition {definition_id} not found")

        # Get upload record
        stmt = select(DefinitionUpload).where(
            DefinitionUpload.resource_id == definition_id
        )
        result = await session.scalars(stmt)
        upload = result.first()

        if not upload:
            raise DefinitionUploadError(f"Upload record not found for {definition_id}")

        if not upload.test_suite_file:
            raise DefinitionUploadError("No test suite configured")

        # Update status to running
        upload.evaluation_status = "running"
        upload.tests_started_at = datetime.now(timezone.utc)
        await session.flush()

        # Run tests
        test_result = await self._test_runner.run_tests(
            artifact_ref=resource.artifact_ref,
            test_file=upload.test_suite_file,
            module_file=upload.module_file,
        )

        # Update upload record
        upload.evaluation_status = "passed" if test_result.passed else "failed"
        upload.tests_total = test_result.tests_total
        upload.tests_passed = test_result.tests_passed
        upload.tests_failed = test_result.tests_failed
        upload.test_duration_ms = test_result.duration_ms
        upload.test_output = test_result.output
        upload.test_report_json = test_result.report_json
        upload.tests_completed_at = test_result.completed_at

        # Update resource status if tests pass
        if test_result.passed and resource.status == "draft":
            resource.status = "active"
            # Register plugin
            try:
                register_plugin(
                    definition_type=resource.type,
                    artifact_ref=resource.artifact_ref,
                    module_file=upload.module_file,
                    class_name=upload.class_name,
                )
            except Exception as e:
                logger.warning(
                    "definition_upload.rerun_plugin_registration_failed",
                    error=str(e),
                )

        await session.flush()

        # Emit activity
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=definition_id,
            resource_type=resource.type,
            action="definition.tests_rerun",
            payload={
                "evaluation_status": upload.evaluation_status,
                "tests_total": test_result.tests_total,
                "tests_passed": test_result.tests_passed,
                "tests_failed": test_result.tests_failed,
            },
        )
        await record_activity_with_outbox(session, envelope)
        await session.commit()

        return {
            "id": str(definition_id),
            "evaluation_status": upload.evaluation_status,
            "tests_total": test_result.tests_total,
            "tests_passed": test_result.tests_passed,
            "tests_failed": test_result.tests_failed,
            "duration_ms": test_result.duration_ms,
            "passed": test_result.passed,
            "failures": [
                {"test_name": f.test_name, "message": f.message}
                for f in test_result.failures
            ],
        }

    async def get_upload_details(
        self,
        session: AsyncSession,
        actor: ActorContext,
        definition_id: UUID,
    ) -> dict[str, Any] | None:
        """Get upload details for a definition.

        Args:
            session: Database session
            actor: Actor context
            definition_id: Definition resource ID

        Returns:
            Upload details or None
        """
        stmt = (
            select(DefinitionUpload, Resource)
            .join(Resource, DefinitionUpload.resource_id == Resource.id)
            .where(
                DefinitionUpload.resource_id == definition_id,
                Resource.tenant_id == actor.tenant_id,
            )
        )
        result = await session.execute(stmt)
        row = result.first()

        if not row:
            return None

        upload, resource = row

        return {
            "id": str(resource.id),
            "name": resource.name,
            "version": upload.manifest_version,
            "definition_type": resource.type,
            "code_ref": upload.class_name,
            "module_file": upload.module_file,
            "test_suite_file": upload.test_suite_file,
            "status": resource.status,
            "evaluation_status": upload.evaluation_status,
            "artifact_ref": str(resource.artifact_ref),
            "original_filename": upload.original_filename,
            "upload_size_bytes": upload.upload_size_bytes,
            "tests_total": upload.tests_total,
            "tests_passed": upload.tests_passed,
            "tests_failed": upload.tests_failed,
            "test_duration_ms": upload.test_duration_ms,
            "uploaded_by": str(upload.uploaded_by),
            "uploaded_at": upload.uploaded_at.isoformat(),
            "manifest": upload.manifest_json,
        }

    async def _create_definition_extension(
        self,
        session: AsyncSession,
        actor: ActorContext,
        resource_id: UUID,
        package: LoadedPackage,
    ) -> None:
        """Create the definition extension record.

        Args:
            session: Database session
            actor: Actor context
            resource_id: Resource ID
            package: Loaded package
        """
        manifest = package.manifest
        definition_type = manifest.definition_type
        extension_model = DEFINITION_EXTENSION_MAP.get(definition_type)

        if extension_model is None:
            logger.warning(
                "definition_upload.unknown_extension_type",
                definition_type=definition_type,
            )
            return

        # Build extension based on type
        if definition_type == "PipelineDef":
            extension = PipelineDefinition(
                resource_id=resource_id,
                tenant_id=actor.tenant_id,
                category=manifest.category or "custom",
                interface_spec=manifest.interface_spec,
                code_ref=manifest.class_name,
                input_schema=manifest.input_schema,
                output_schema=manifest.output_schema,
                parameters_schema=manifest.parameters_schema,
                compatibility_rules={},
                guardrail_contracts=manifest.guardrail_contracts,
                test_suite_ref=manifest.test_suite_file,
                evaluation_status="pending",
            )
        elif definition_type == "StoreDef":
            extension = StoreDefinition(
                resource_id=resource_id,
                tenant_id=actor.tenant_id,
                backend_type=manifest.category or "custom",
                interface_spec=manifest.interface_spec,
                code_ref=manifest.class_name,
                parameters_schema=manifest.parameters_schema,
                guardrail_contracts=manifest.guardrail_contracts,
            )
        elif definition_type == "AccessorDef":
            extension = AccessorDefinition(
                resource_id=resource_id,
                tenant_id=actor.tenant_id,
                accessor_type=manifest.category or "custom",
                interface_spec=manifest.interface_spec,
                code_ref=manifest.class_name,
                parameters_schema=manifest.parameters_schema,
                guardrail_contracts=manifest.guardrail_contracts,
            )
        elif definition_type == "OpDef":
            extension = OpDefinition(
                resource_id=resource_id,
                tenant_id=actor.tenant_id,
                category=manifest.category or "custom",
                signature=manifest.raw_json.get(
                    "signature", f"{manifest.class_name}()"
                ),
                interface_spec=manifest.interface_spec,
                code_ref=manifest.class_name,
                input_schema=manifest.input_schema,
                output_schema=manifest.output_schema,
                parameters_schema=manifest.parameters_schema,
            )
        else:
            # Unknown type - skip extension
            return

        session.add(extension)

    async def _get_default_parent(
        self,
        session: AsyncSession,
        actor: ActorContext,
    ) -> UUID:
        """Get default parent ID for uploads.

        Uses the tenant's first active Project or Space.

        Args:
            session: Database session
            actor: Actor context

        Returns:
            Parent resource ID
        """
        # Try to find an active Project
        stmt = (
            select(Resource)
            .where(
                Resource.tenant_id == actor.tenant_id,
                Resource.type == "Project",
                Resource.status == "active",
            )
            .limit(1)
        )
        result = await session.scalars(stmt)
        project = result.first()

        if project:
            return project.id

        # Fall back to Space
        stmt = (
            select(Resource)
            .where(
                Resource.tenant_id == actor.tenant_id,
                Resource.type == "Space",
                Resource.status == "active",
            )
            .limit(1)
        )
        result = await session.scalars(stmt)
        space = result.first()

        if space:
            return space.id

        raise DefinitionUploadError(
            "No default parent found. Create a Project or Space first."
        )

    async def _emit_upload_failed(
        self,
        session: AsyncSession,
        actor: ActorContext,
        upload_id: UUID,
        error: str,
    ) -> None:
        """Emit upload failed activity."""
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=upload_id,
            resource_type="DefinitionUpload",
            action="definition.upload_failed",
            payload={"error": error},
        )
        await record_activity_with_outbox(session, envelope)

    async def _emit_tests_started(
        self,
        session: AsyncSession,
        actor: ActorContext,
        package: LoadedPackage,
        upload_id: UUID,
    ) -> None:
        """Emit tests started activity."""
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=upload_id,
            resource_type="DefinitionUpload",
            action="definition.tests_started",
            payload={
                "name": package.manifest.name,
                "test_file": package.manifest.test_suite_file,
            },
        )
        await record_activity_with_outbox(session, envelope)

    async def _emit_tests_completed(
        self,
        session: AsyncSession,
        actor: ActorContext,
        package: LoadedPackage,
        upload_id: UUID,
        test_result: TestRunResult,
    ) -> None:
        """Emit tests completed activity."""
        action = (
            "definition.tests_passed"
            if test_result.passed
            else "definition.tests_failed"
        )
        envelope = ActivityEnvelope(
            tenant_id=actor.tenant_id,
            actor_principal_id=actor.id,
            resource_id=upload_id,
            resource_type="DefinitionUpload",
            action=action,
            payload={
                "name": package.manifest.name,
                "tests_total": test_result.tests_total,
                "tests_passed": test_result.tests_passed,
                "tests_failed": test_result.tests_failed,
                "duration_ms": test_result.duration_ms,
            },
        )
        await record_activity_with_outbox(session, envelope)


# Singleton instance
_default_service: DefinitionUploadService | None = None


def get_definition_upload_service() -> DefinitionUploadService:
    """Get the default definition upload service.

    Returns:
        DefinitionUploadService instance
    """
    global _default_service

    if _default_service is None:
        _default_service = DefinitionUploadService()

    return _default_service

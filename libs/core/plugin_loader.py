"""Plugin Loader for user-uploaded Definition artifacts.

Manages dynamic loading of plugin modules from artifact storage:
1. Adds artifact paths to sys.path
2. Imports module files dynamically
3. Registers classes in appropriate FactoryRegistry

Called at:
- Application startup (load all active plugins via load_all_plugins)
- After successful definition upload (load single plugin via register_plugin)

Integration:
- ArtifactManager: Files stored at {DATA_DIR}/artifacts/{artifact_ref}/
- FactoryRegistry: Classes registered via FACTORY.register(code_ref)(cls)
- startup.py: load_all_plugins() called in run_startup_hooks()
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

from libs.core.artifacts import get_artifact_path

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# Map definition types to their factory registries
# Imported lazily to avoid circular imports
_FACTORY_MAP: dict[str, Any] | None = None


def _get_factory_map() -> dict[str, Any]:
    """Lazy load factory map to avoid circular imports."""
    global _FACTORY_MAP
    if _FACTORY_MAP is None:
        from libs.data.registry import (
            ACCESSOR_FACTORY,
            OPS_FACTORY,
            PIPELINE_FACTORY,
            STORE_FACTORY,
        )

        _FACTORY_MAP = {
            "PipelineDef": PIPELINE_FACTORY,
            "StoreDef": STORE_FACTORY,
            "AccessorDef": ACCESSOR_FACTORY,
            "OpDef": OPS_FACTORY,
            # ML and Portfolio optimizers can be added when their factories exist
        }
    return _FACTORY_MAP


def load_plugin_module(artifact_ref: UUID, module_file: str) -> object:
    """Load a plugin module from artifact storage.

    Args:
        artifact_ref: UUID of the artifact folder
        module_file: Relative path to the module file (e.g., "pipeline.py")

    Returns:
        The loaded module object

    Raises:
        FileNotFoundError: If the module file doesn't exist
    """
    artifact_path = get_artifact_path(artifact_ref)
    module_path = artifact_path / module_file

    if not module_path.exists():
        raise FileNotFoundError(f"Module not found: {module_path}")

    # Add artifact path to sys.path for relative imports within the plugin
    artifact_str = str(artifact_path)
    if artifact_str not in sys.path:
        sys.path.insert(0, artifact_str)
        logger.debug(
            "plugin.path_added",
            artifact_ref=str(artifact_ref),
            path=artifact_str,
        )

    # Create a unique module name to avoid collisions
    module_stem = Path(module_file).stem
    module_name = f"optaic_plugins.{artifact_ref}.{module_stem}"

    # Dynamic import using importlib
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for: {module_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    logger.debug(
        "plugin.module_loaded",
        artifact_ref=str(artifact_ref),
        module_file=module_file,
        module_name=module_name,
    )

    return module


def register_plugin(
    definition_type: str,
    artifact_ref: UUID,
    module_file: str,
    class_name: str,
) -> str:
    """Load plugin module and register class in appropriate factory.

    This function:
    1. Loads the module from artifact storage
    2. Gets the class by name from the module
    3. Registers it in the appropriate FactoryRegistry

    Args:
        definition_type: Type of definition (PipelineDef, StoreDef, etc.)
        artifact_ref: UUID of the artifact folder
        module_file: Relative path to the module file
        class_name: Name of the class to register (becomes code_ref)

    Returns:
        The code_ref (factory key) that was registered

    Raises:
        FileNotFoundError: If module file doesn't exist
        AttributeError: If class not found in module
        ValueError: If definition type unknown
    """
    # Load the module
    module = load_plugin_module(artifact_ref, module_file)

    # Get the class from the module
    if not hasattr(module, class_name):
        available = [name for name in dir(module) if not name.startswith("_")]
        raise AttributeError(
            f"Class '{class_name}' not found in module. "
            f"Available: {', '.join(available[:10])}"
        )

    cls = getattr(module, class_name)

    # Get the appropriate factory
    factory_map = _get_factory_map()
    factory = factory_map.get(definition_type)
    if factory is None:
        raise ValueError(
            f"Unknown definition type: {definition_type}. "
            f"Supported: {', '.join(factory_map.keys())}"
        )

    # Check if already registered (avoid duplicates on restart)
    if factory.contains(class_name):
        logger.debug(
            "plugin.already_registered",
            definition_type=definition_type,
            code_ref=class_name,
        )
        return class_name

    # Register in factory
    factory.register(class_name)(cls)

    logger.info(
        "plugin.registered",
        definition_type=definition_type,
        code_ref=class_name,
        artifact_ref=str(artifact_ref),
    )

    return class_name


def unregister_plugin(definition_type: str, class_name: str) -> bool:
    """Unregister a plugin from its factory.

    Note: This doesn't remove the module from sys.modules or sys.path.
    Use with caution - mainly for testing purposes.

    Args:
        definition_type: Type of definition
        class_name: The code_ref to unregister

    Returns:
        True if unregistered, False if wasn't registered
    """
    factory_map = _get_factory_map()
    factory = factory_map.get(definition_type)
    if factory is None:
        return False

    if not factory.contains(class_name):
        return False

    # FactoryRegistry doesn't have a remove method, but we can access _constructors
    if hasattr(factory, "_constructors") and class_name in factory._constructors:
        del factory._constructors[class_name]
        logger.info(
            "plugin.unregistered",
            definition_type=definition_type,
            code_ref=class_name,
        )
        return True

    return False


async def load_all_plugins(session: AsyncSession) -> int:
    """Load all active uploaded plugins at application startup.

    This enables users to create Instances from uploaded Definitions.
    Called during run_startup_hooks() after seed_definitions().

    Queries:
    1. Resources with type in Definition types, status=active, artifact_ref not null
    2. Joins with DefinitionUpload to get module_file
    3. Joins with extension tables (PipelineDefinition, etc.) to get code_ref

    Args:
        session: Database session

    Returns:
        Number of plugins successfully loaded
    """
    from sqlalchemy import select

    from libs.db.models.resource import Resource

    # Definition types that can be uploaded plugins
    definition_types = ["PipelineDef", "StoreDef", "AccessorDef", "OpDef"]

    # Query active definitions with artifact_ref (indicates uploaded plugin)
    stmt = select(Resource).where(
        Resource.type.in_(definition_types),
        Resource.status == "active",
        Resource.artifact_ref.isnot(None),
    )
    result = await session.scalars(stmt)
    resources = result.all()

    if not resources:
        logger.debug("plugin.no_uploaded_plugins_found")
        return 0

    loaded_count = 0
    for resource in resources:
        try:
            # Get the extension record to find code_ref
            ext_record = await _get_definition_extension(
                session, resource.id, resource.type
            )
            if ext_record is None:
                logger.warning(
                    "plugin.extension_not_found",
                    resource_id=str(resource.id),
                    resource_type=resource.type,
                )
                continue

            code_ref = ext_record.code_ref
            if not code_ref:
                logger.warning(
                    "plugin.no_code_ref",
                    resource_id=str(resource.id),
                )
                continue

            # Get module_file from DefinitionUpload if available
            upload_record = await _get_upload_record(session, resource.id)
            if upload_record is None:
                # Built-in definitions don't have upload records
                logger.debug(
                    "plugin.no_upload_record",
                    resource_id=str(resource.id),
                    hint="Built-in definition, skipping",
                )
                continue

            module_file = upload_record.module_file
            if not module_file:
                logger.warning(
                    "plugin.no_module_file",
                    resource_id=str(resource.id),
                )
                continue

            # Register the plugin
            register_plugin(
                definition_type=resource.type,
                artifact_ref=resource.artifact_ref,
                module_file=module_file,
                class_name=code_ref,
            )
            loaded_count += 1

        except Exception as e:
            logger.warning(
                "plugin.load_failed",
                resource_id=str(resource.id),
                artifact_ref=str(resource.artifact_ref)
                if resource.artifact_ref
                else None,
                error=str(e),
            )

    logger.info("plugin.startup_load_complete", loaded_count=loaded_count)
    return loaded_count


async def _get_definition_extension(
    session: AsyncSession, resource_id: UUID, resource_type: str
) -> Any | None:
    """Get the extension table record for a definition resource."""
    from sqlalchemy import select

    from libs.db.models.quant import (
        AccessorDefinition,
        OpDefinition,
        PipelineDefinition,
        StoreDefinition,
    )

    type_to_model = {
        "PipelineDef": PipelineDefinition,
        "StoreDef": StoreDefinition,
        "AccessorDef": AccessorDefinition,
        "OpDef": OpDefinition,
    }

    model = type_to_model.get(resource_type)
    if model is None:
        return None

    stmt = select(model).where(model.resource_id == resource_id)
    result = await session.scalars(stmt)
    return result.first()


async def _get_upload_record(session: AsyncSession, resource_id: UUID) -> Any | None:
    """Get the DefinitionUpload record for a resource.

    Returns None if the record doesn't exist (e.g., built-in definitions).
    """
    try:
        from sqlalchemy import select

        from libs.db.models.definition_upload import DefinitionUpload

        stmt = select(DefinitionUpload).where(
            DefinitionUpload.resource_id == resource_id
        )
        result = await session.scalars(stmt)
        return result.first()
    except ImportError:
        # DefinitionUpload model doesn't exist yet
        return None

"""Data System Registry.

Central registry for Pipelines, Accessors, Stores, and Operators.
Adapted from optaic-v0/data/registry.py with Resource-aware patterns.

Key Differences from optaic-v0:
- No DATA_CATALOG registry (datasets are now Resources in the database)
- Factories still used for pluggable components (pipelines, stores, accessors, ops)
- Definition resources reference factory keys to instantiate components
"""

from __future__ import annotations

import pkgutil
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from importlib import import_module
from typing import Any, Generic, TypeVar

import structlog

T = TypeVar("T")
Constructor = Callable[..., T]
logger = structlog.get_logger(__name__)


class FactoryRegistry(Generic[T]):
    """Registry-driven object factory with auto-discovery support.

    Used for pluggable components that Definition resources reference:
    - PipelineDef.code_ref -> PIPELINE_FACTORY[code_ref]
    - StoreDef.code_ref -> STORE_FACTORY[code_ref]
    - AccessorDef.code_ref -> ACCESSOR_FACTORY[code_ref]
    - OpDef.code_ref -> OPS_FACTORY[code_ref]
    """

    def __init__(
        self,
        namespace: str,
        *,
        base_type: type[Any] | tuple[type[Any], ...] | None = None,
    ) -> None:
        self.namespace = namespace
        self.base_type = base_type
        self._constructors: dict[str, Constructor[T]] = {}
        self._auto_discovery: list[dict[str, Any]] | None = None

    def register(
        self,
        name: str | None = None,
        *,
        constructor: Constructor[T] | None = None,
    ) -> Callable[[Constructor[T]], Constructor[T]]:
        """Register constructor under name. Works as decorator or direct call."""

        def _decorator(target: Constructor[T]) -> Constructor[T]:
            key = name or target.__name__
            self._validate_constructor(target, key)
            self._constructors[key] = target
            return target

        if constructor is not None:
            return _decorator(constructor)
        return _decorator

    def _validate_constructor(self, constructor: Constructor[T], key: str) -> None:
        if self.base_type is None:
            return
        if isinstance(constructor, type):
            if not issubclass(constructor, self.base_type):
                raise TypeError(
                    f"Registered {self.namespace} '{key}' must inherit from {self.base_type}."
                )
        elif not callable(constructor):
            raise TypeError(f"Registered {self.namespace} '{key}' must be callable.")

    def keys(self) -> tuple[str, ...]:
        self._ensure_auto_discovery()
        return tuple(self._constructors)

    def contains(self, name: str) -> bool:
        self._ensure_auto_discovery()
        return name in self._constructors

    def get(self, name: str, default: T | None = None) -> T | None:
        self._ensure_auto_discovery()
        return self._constructors.get(name, default)

    def get_constructor(self, name: str) -> Constructor[T]:
        self._ensure_auto_discovery()
        try:
            return self._constructors[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._constructors)) or "<empty>"
            raise KeyError(
                f"Unknown {self.namespace} '{name}'. Available: {available}"
            ) from exc

    def build(self, name: str, **params: Any) -> T:
        """Build an instance from a registered constructor."""
        constructor = self.get_constructor(name)
        return constructor(**params)

    def build_from_config(self, cfg: Mapping[str, Any]) -> T:
        """Build from a config dict with 'name' and optional 'params'."""
        if "name" not in cfg:
            raise KeyError("Factory config requires a 'name' field.")
        params = cfg.get("params") or {}
        return self.build(cfg["name"], **params)

    def configure_auto_discovery(
        self,
        package: str,
        *,
        exclude: Iterable[str] | None = None,
        recursive: bool = True,
        append: bool = True,
    ) -> None:
        """Enable automatic module imports before registry usage."""
        entry = {
            "package": package,
            "exclude": set(exclude or ()),
            "recursive": recursive,
            "completed": False,
        }
        if append and self._auto_discovery:
            self._auto_discovery.append(entry)
        else:
            self._auto_discovery = [entry]

    def _ensure_auto_discovery(self) -> None:
        cfg_lst = self._auto_discovery
        if not cfg_lst:
            return
        for cfg in cfg_lst:
            if cfg["completed"]:
                continue
            try:
                self._import_package_modules(
                    cfg["package"],
                    cfg["exclude"],
                    cfg["recursive"],
                    visited=set(),
                )
            except Exception as e:
                logger.warning(
                    f"[{self.namespace}] Auto-discovery partial failure",
                    error=str(e),
                )
            cfg["completed"] = True

    def _import_package_modules(
        self,
        package_name: str,
        exclude: set[str],
        recursive: bool,
        *,
        visited: set[str],
    ) -> None:
        if package_name in visited:
            return
        visited.add(package_name)
        try:
            module = import_module(package_name)
        except ImportError as e:
            logger.warning(f"Skipping {package_name} due to import error: {e}")
            return

        package_path = getattr(module, "__path__", None)
        if package_path is None:
            return
        for module_info in pkgutil.iter_modules(package_path):
            if module_info.name.startswith("_"):
                continue
            full_name = f"{package_name}.{module_info.name}"
            if module_info.name in exclude or full_name in exclude:
                continue

            with suppress(ImportError):
                import_module(full_name)

            if recursive and module_info.ispkg:
                self._import_package_modules(
                    full_name, exclude, recursive, visited=visited
                )

    def __contains__(self, name: str) -> bool:
        return self.contains(name)

    def __len__(self) -> int:
        return len(self._constructors)

    def __iter__(self):
        self._ensure_auto_discovery()
        return iter(self._constructors)

    def __repr__(self) -> str:
        contents = ", ".join(sorted(self._constructors))
        return f"FactoryRegistry(namespace='{self.namespace}', keys=[{contents}])"


# =============================================================================
# Global Registries
# =============================================================================

# Pipeline implementations (FREDPipeline, SQLitePipeline, ExpressionPipeline, etc.)
PIPELINE_FACTORY: FactoryRegistry = FactoryRegistry("data pipeline")
PIPELINE_FACTORY.configure_auto_discovery("libs.data.pipelines")


def register_pipeline(name: str | None = None):
    """Decorator to register a pipeline class."""
    return PIPELINE_FACTORY.register(name)


# Store implementations (ParquetStore, SQLiteStore, VirtualStore, etc.)
STORE_FACTORY: FactoryRegistry = FactoryRegistry("data store")
STORE_FACTORY.configure_auto_discovery("libs.data.store")


def register_store(name: str | None = None):
    """Decorator to register a store class."""
    return STORE_FACTORY.register(name)


# Accessor implementations (SimpleAccessor, PITAccessor, etc.)
ACCESSOR_FACTORY: FactoryRegistry = FactoryRegistry("data accessor")
ACCESSOR_FACTORY.configure_auto_discovery("libs.data.access")


def register_accessor(name: str | None = None):
    """Decorator to register an accessor class."""
    return ACCESSOR_FACTORY.register(name)


# Operator implementations (REF, DELTA, MEAN, etc.)
OPS_FACTORY: FactoryRegistry = FactoryRegistry("operator")
OPS_FACTORY.configure_auto_discovery("libs.data.ops")


def register_op(name: str | None = None):
    """Decorator to register an operator class."""
    return OPS_FACTORY.register(name)

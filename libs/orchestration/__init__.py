"""Orchestration package for execution management.

This package provides:
- OrchestratorAdapter: Abstract interface for execution backends
- LocalOrchestrator: In-process DAG executor for testing/embedded use
- PrefectOrchestrator: Prefect server integration for production
- StatusStore: Execution metadata storage
- RunExecutionService: Central coordinator for run resources
- DependencyGraph: Build execution DAGs from resource dependencies
- FreshnessChecker: Calculate staleness status for resources
- LineageResolver: Resolve upstream/downstream dependencies
"""

from __future__ import annotations

from .adapter import OrchestratorAdapter, RunStatus, SubmitResult
from .dag import DependencyGraph, build_graph
from .freshness import DatasetStatus, FreshnessChecker, FreshnessReport, UpdateFrequency
from .lineage import LineageFreshnessReport, LineageResolver, UpstreamNotReadyError
from .local import LocalOrchestrator
from .prefect_adapter import PrefectOrchestrator
from .run_service import RunExecutionService
from .status_store import DatasetStatusRecord, StatusStore

__all__ = [
    "DatasetStatus",
    "DatasetStatusRecord",
    "DependencyGraph",
    "FreshnessChecker",
    "FreshnessReport",
    "LineageFreshnessReport",
    "LineageResolver",
    "LocalOrchestrator",
    "OrchestratorAdapter",
    "PrefectOrchestrator",
    "RunExecutionService",
    "RunStatus",
    "StatusStore",
    "SubmitResult",
    "UpdateFrequency",
    "UpstreamNotReadyError",
    "build_graph",
]

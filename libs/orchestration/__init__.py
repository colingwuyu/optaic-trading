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

from .adapter import DeploymentResult, OrchestratorAdapter, RunStatus, SubmitResult
from .dag import DependencyGraph, build_graph
from .freshness import DatasetStatus, FreshnessChecker, FreshnessReport, UpdateFrequency
from .lineage import (
    LineageDAG,
    LineageFreshnessReport,
    LineageResolver,
    UpstreamNotReadyError,
)
from .observers import CentrifugoNotifier, LineageObserver
from .local import LocalOrchestrator
from .prefect_adapter import PrefectOrchestrator
from .run_service import RunExecutionService
from .status_store import DatasetStatusRecord, StatusStore

__all__ = [
    "CentrifugoNotifier",
    "DatasetStatus",
    "DatasetStatusRecord",
    "DependencyGraph",
    "DeploymentResult",
    "FreshnessChecker",
    "FreshnessReport",
    "LineageDAG",
    "LineageFreshnessReport",
    "LineageObserver",
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

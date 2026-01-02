"""OptAIC Data Platform Core.

This package provides the data access layer for OptAIC, adapted from optaic-v0's
DataAPI to work with the Resource model and Activity-driven architecture.

Key Components:
- catalog: Dataset metadata types (BackendType, DatasetKind, etc.)
- registry: Pluggable factories for pipelines, stores, accessors, operators
- store: Data storage backends (parquet, sqlite, virtual)
- access: Data accessor implementations (simple, PIT)
- expression: Expression engine for operator evaluation
- ops: Operator definitions and registry

Architecture Note:
Unlike optaic-v0 which used name-based catalog lookups, this implementation
uses Resource IDs from the database. All operations flow through the service
layer which handles RBAC and activity emission.
"""

from libs.data.catalog import (
    BackendType as BackendType,
    DatasetKind as DatasetKind,
    DatasetStatus as DatasetStatus,
    UpdateFrequency as UpdateFrequency,
)

"""Resource type taxonomy and governance rules.

Resource Hierarchy:
    Scope Resources (composite containers):
        - Space: Top-level container (personal, team, system)
        - SubSpace: Partitions within a space (official, staging, custom)
        - Project: Container for related resources

    Individual Resources (under Projects):
        - Definition: Static templates/schemas (immutable once promoted)
        - Instance: Configured executions of definitions
        - Flow: Execution records of instances (runs)

Governance Rules by Resource Category:
    Flow Resources: View-only sharing, no copy/transfer/promote/branch/merge
    Scope Resources: Copy, transfer, promote (no branch/merge)
    Definition/Instance: All governance operations allowed

RBAC Inheritance:
    Space/SubSpace > Project > Individual Resource
    (more specific wins when conflicting)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import ClassVar


class ResourceCategory(str, Enum):
    """High-level resource categories for governance rules."""

    SCOPE = "scope"  # Space, SubSpace, Project
    DEFINITION = "definition"  # Static schemas/templates
    INSTANCE = "instance"  # Configured executions
    FLOW = "flow"  # Execution records (runs)


class GovernanceAction(str, Enum):
    """Available governance actions."""

    COPY = "copy"
    BRANCH = "branch"
    TRANSFER = "transfer"
    PROMOTE = "promote"
    MERGE = "merge"
    VIEW = "view"  # Always allowed if RBAC permits


@dataclass(frozen=True)
class ResourceTypeInfo:
    """Metadata about a resource type."""

    name: str
    category: ResourceCategory
    parent_type: str | None  # Required parent type
    allowed_actions: frozenset[GovernanceAction]
    description: str = ""


class ResourceTypes:
    """Registry of resource types and their governance rules.

    Resource types are organized in a hierarchy:
    - Scope resources: Space > SubSpace > Project
    - Under Project: Definition, Instance, Flow

    Governance rules are determined by category:
    - Flow: view-only (no governance actions)
    - Scope (Project): copy, transfer, promote
    - Definition/Instance: all actions (copy, branch, transfer, promote, merge)
    """

    # Scope resource types (containers)
    SPACE = "Space"
    SUBSPACE = "SubSpace"
    PROJECT = "Project"

    # Definition resource types (static templates)
    PIPELINE_DEF = "PipelineDef"
    STORE_DEF = "StoreDef"
    ACCESSOR_DEF = "AccessorDef"
    OP_DEF = "OpDef"
    ML_MODULE_DEF = "MLModuleDef"
    PORTFOLIO_OPTIMIZER_DEF = "PortfolioOptimizerDef"
    SIGNAL_DEF = "SignalDef"
    DATASET_DEF = "DatasetDef"
    STRATEGY_DEF = "StrategyDef"

    # Instance resource types (configured executions)
    PIPELINE_INSTANCE = "PipelineInstance"
    DATASET_INSTANCE = "DatasetInstance"
    SIGNAL_INSTANCE = "SignalInstance"
    EXPERIMENT_INSTANCE = "ExperimentInstance"
    MODEL_INSTANCE = "ModelInstance"
    PORTFOLIO_OPTIMIZER_INSTANCE = "PortfolioOptimizerInstance"
    BACKTEST_INSTANCE = "BacktestInstance"

    # Flow resource types (execution records)
    PIPELINE_RUN = "PipelineRun"
    EXPERIMENT_RUN = "ExperimentRun"
    BACKTEST_RUN = "BacktestRun"
    PORTFOLIO_OPTIMIZATION_RUN = "PortfolioOptimizationRun"
    TRAINING_RUN = "TrainingRun"
    INFERENCE_RUN = "InferenceRun"
    MONITORING_RUN = "MonitoringRun"

    # Chat and collaboration types (treated as flow-like, view-only)
    CHANNEL = "Channel"
    MESSAGE = "Message"
    THREAD = "Thread"

    # Allowed actions per category
    FLOW_ACTIONS: ClassVar[frozenset[GovernanceAction]] = frozenset(
        [GovernanceAction.VIEW]
    )
    SCOPE_ACTIONS: ClassVar[frozenset[GovernanceAction]] = frozenset(
        [
            GovernanceAction.VIEW,
            GovernanceAction.COPY,
            GovernanceAction.TRANSFER,
            GovernanceAction.PROMOTE,
        ]
    )
    INDIVIDUAL_ACTIONS: ClassVar[frozenset[GovernanceAction]] = frozenset(
        [
            GovernanceAction.VIEW,
            GovernanceAction.COPY,
            GovernanceAction.BRANCH,
            GovernanceAction.TRANSFER,
            GovernanceAction.PROMOTE,
            GovernanceAction.MERGE,
        ]
    )

    # Resource type registry
    _TYPES: ClassVar[dict[str, ResourceTypeInfo]] = {}

    @classmethod
    def _init_registry(cls) -> None:
        """Initialize the resource type registry."""
        if cls._TYPES:
            return

        # Scope resources
        cls._TYPES[cls.SPACE] = ResourceTypeInfo(
            name=cls.SPACE,
            category=ResourceCategory.SCOPE,
            parent_type=None,
            allowed_actions=frozenset([GovernanceAction.VIEW]),  # Spaces can't be moved
            description="Top-level container (personal, team, system)",
        )
        cls._TYPES[cls.SUBSPACE] = ResourceTypeInfo(
            name=cls.SUBSPACE,
            category=ResourceCategory.SCOPE,
            parent_type=cls.SPACE,
            allowed_actions=frozenset([GovernanceAction.VIEW]),  # SubSpaces are fixed
            description="Partition within a space (official, staging, custom)",
        )
        cls._TYPES[cls.PROJECT] = ResourceTypeInfo(
            name=cls.PROJECT,
            category=ResourceCategory.SCOPE,
            parent_type=cls.SUBSPACE,
            allowed_actions=cls.SCOPE_ACTIONS,
            description="Container for related resources",
        )

        # Definition resources (all under Project)
        definition_types = [
            (cls.PIPELINE_DEF, "Pipeline definition"),
            (cls.STORE_DEF, "Data store definition"),
            (cls.ACCESSOR_DEF, "Data accessor definition"),
            (cls.OP_DEF, "Operator definition"),
            (cls.ML_MODULE_DEF, "ML module definition"),
            (cls.PORTFOLIO_OPTIMIZER_DEF, "Portfolio optimizer definition"),
            (cls.SIGNAL_DEF, "Signal definition"),
            (cls.DATASET_DEF, "Dataset definition"),
            (cls.STRATEGY_DEF, "Strategy definition"),
        ]
        for name, desc in definition_types:
            cls._TYPES[name] = ResourceTypeInfo(
                name=name,
                category=ResourceCategory.DEFINITION,
                parent_type=cls.PROJECT,
                allowed_actions=cls.INDIVIDUAL_ACTIONS,
                description=desc,
            )

        # Instance resources (all under Project)
        instance_types = [
            (cls.PIPELINE_INSTANCE, "Configured pipeline execution"),
            (cls.DATASET_INSTANCE, "Configured dataset"),
            (cls.SIGNAL_INSTANCE, "Configured signal"),
            (cls.EXPERIMENT_INSTANCE, "Configured experiment"),
            (cls.MODEL_INSTANCE, "Configured ML model"),
            (cls.PORTFOLIO_OPTIMIZER_INSTANCE, "Configured portfolio optimizer"),
            (cls.BACKTEST_INSTANCE, "Configured backtest"),
        ]
        for name, desc in instance_types:
            cls._TYPES[name] = ResourceTypeInfo(
                name=name,
                category=ResourceCategory.INSTANCE,
                parent_type=cls.PROJECT,
                allowed_actions=cls.INDIVIDUAL_ACTIONS,
                description=desc,
            )

        # Flow resources (runs - under their Instance or Project)
        flow_types = [
            (cls.PIPELINE_RUN, "Pipeline execution record"),
            (cls.EXPERIMENT_RUN, "Experiment execution record"),
            (cls.BACKTEST_RUN, "Backtest execution record"),
            (cls.PORTFOLIO_OPTIMIZATION_RUN, "Portfolio optimization record"),
            (cls.TRAINING_RUN, "Model training record"),
            (cls.INFERENCE_RUN, "Inference execution record"),
            (cls.MONITORING_RUN, "Monitoring execution record"),
        ]
        for name, desc in flow_types:
            cls._TYPES[name] = ResourceTypeInfo(
                name=name,
                category=ResourceCategory.FLOW,
                parent_type=cls.PROJECT,  # Actually under Instance, but Project for placement
                allowed_actions=cls.FLOW_ACTIONS,
                description=desc,
            )

        # Chat resources (view-only)
        chat_types = [
            (cls.CHANNEL, "Communication channel"),
            (cls.MESSAGE, "Channel message"),
            (cls.THREAD, "Discussion thread"),
        ]
        for name, desc in chat_types:
            cls._TYPES[name] = ResourceTypeInfo(
                name=name,
                category=ResourceCategory.FLOW,
                parent_type=cls.PROJECT,
                allowed_actions=cls.FLOW_ACTIONS,
                description=desc,
            )

    @classmethod
    def get_info(cls, resource_type: str) -> ResourceTypeInfo | None:
        """Get type info for a resource type."""
        cls._init_registry()
        return cls._TYPES.get(resource_type)

    @classmethod
    def get_category(cls, resource_type: str) -> ResourceCategory | None:
        """Get the category for a resource type."""
        info = cls.get_info(resource_type)
        return info.category if info else None

    @classmethod
    def is_action_allowed(cls, resource_type: str, action: GovernanceAction) -> bool:
        """Check if an action is allowed for a resource type."""
        info = cls.get_info(resource_type)
        if not info:
            # Unknown types default to individual resource rules
            return action in cls.INDIVIDUAL_ACTIONS
        return action in info.allowed_actions

    @classmethod
    def is_flow_resource(cls, resource_type: str) -> bool:
        """Check if a resource type is a flow (run) resource."""
        return cls.get_category(resource_type) == ResourceCategory.FLOW

    @classmethod
    def is_scope_resource(cls, resource_type: str) -> bool:
        """Check if a resource type is a scope (container) resource."""
        return cls.get_category(resource_type) == ResourceCategory.SCOPE

    @classmethod
    def is_definition_resource(cls, resource_type: str) -> bool:
        """Check if a resource type is a definition resource."""
        return cls.get_category(resource_type) == ResourceCategory.DEFINITION

    @classmethod
    def is_instance_resource(cls, resource_type: str) -> bool:
        """Check if a resource type is an instance resource."""
        return cls.get_category(resource_type) == ResourceCategory.INSTANCE

    @classmethod
    def get_allowed_actions(cls, resource_type: str) -> frozenset[GovernanceAction]:
        """Get allowed actions for a resource type."""
        info = cls.get_info(resource_type)
        if not info:
            return cls.INDIVIDUAL_ACTIONS
        return info.allowed_actions

    @classmethod
    def validate_placement(
        cls,
        resource_type: str,
        parent_type: str | None,
    ) -> tuple[bool, str]:
        """Validate if a resource can be placed under a parent.

        Args:
            resource_type: Type of resource being placed
            parent_type: Type of parent resource

        Returns:
            (is_valid, error_message)
        """
        info = cls.get_info(resource_type)
        if not info:
            # Unknown types can go under Projects
            if parent_type == cls.PROJECT:
                return True, ""
            return (
                False,
                f"Unknown resource type '{resource_type}' must be under Project",
            )

        # Check required parent type
        if info.parent_type is None:
            # Top-level resources (Space) have no parent
            if parent_type is None:
                return True, ""
            return False, f"{resource_type} cannot have a parent"

        if parent_type == info.parent_type:
            return True, ""

        # Allow flexibility: Definition/Instance can also go under Instance
        if info.category in (ResourceCategory.DEFINITION, ResourceCategory.INSTANCE):
            if parent_type in (cls.PROJECT, cls.SUBSPACE):
                return True, ""

        return (
            False,
            f"{resource_type} must be under {info.parent_type}, not {parent_type}",
        )

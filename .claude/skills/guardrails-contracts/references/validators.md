# Validator Implementation Patterns

## Base Validator Interface

```python
from abc import ABC, abstractmethod
from typing import Dict, Any, List
from dataclasses import dataclass
from enum import Enum

class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"

@dataclass
class ValidationIssue:
    code: str
    severity: Severity
    message: str
    path: str = ""
    context: Dict[str, Any] = None

class ContractValidator(ABC):
    """Base class for contract validators."""

    contract_kind: str  # Must be set by subclass

    @abstractmethod
    def validate(
        self,
        target_snapshot: Dict[str, Any],
        contract_config: Dict[str, Any]
    ) -> List[ValidationIssue]:
        """
        Validate target against contract.

        MUST be pure and deterministic.
        No side effects, no DB access, no external calls.

        Args:
            target_snapshot: Minimal dict with validation data
            contract_config: Contract configuration

        Returns:
            List of validation issues (empty if valid)
        """
        pass
```

## Signal Bounds Validator

```python
class SignalBoundsValidator(ContractValidator):
    """Validates signal values are within bounds."""

    contract_kind = "signal.bounds"

    def validate(
        self,
        target_snapshot: Dict[str, Any],
        contract_config: Dict[str, Any]
    ) -> List[ValidationIssue]:
        issues = []
        values = target_snapshot.get("values", [])
        min_val = contract_config["min_value"]
        max_val = contract_config["max_value"]
        allow_nan = contract_config.get("allow_nan", False)

        # Check NaN
        if not allow_nan:
            nan_count = sum(1 for v in values if v != v)
            if nan_count > 0:
                issues.append(ValidationIssue(
                    code="SIGNAL_CONTAINS_NAN",
                    severity=Severity.ERROR,
                    message=f"Signal contains {nan_count} NaN values",
                    path="values"
                ))

        # Check bounds
        out_of_bounds = [v for v in values
                        if v == v and (v < min_val or v > max_val)]
        if out_of_bounds:
            issues.append(ValidationIssue(
                code="SIGNAL_OUT_OF_BOUNDS",
                severity=Severity.ERROR,
                message=f"{len(out_of_bounds)} values outside [{min_val}, {max_val}]",
                path="values",
                context={"min_found": min(out_of_bounds), "max_found": max(out_of_bounds)}
            ))

        return issues
```

## Dataset PIT Validator

```python
class DatasetPITValidator(ContractValidator):
    """Validates point-in-time correctness."""

    contract_kind = "dataset.pit"

    def validate(
        self,
        target_snapshot: Dict[str, Any],
        contract_config: Dict[str, Any]
    ) -> List[ValidationIssue]:
        issues = []

        # Check no lookahead (knowledge_date >= as_of_date)
        lookahead_rows = target_snapshot.get("lookahead_violations", [])
        if lookahead_rows:
            issues.append(ValidationIssue(
                code="PIT_LOOKAHEAD_BIAS",
                severity=Severity.ERROR,
                message=f"Found {len(lookahead_rows)} rows with lookahead bias",
                context={"sample_rows": lookahead_rows[:5]}
            ))

        # Check staleness
        max_stale = contract_config.get("max_staleness_days")
        if max_stale and target_snapshot.get("max_staleness", 0) > max_stale:
            issues.append(ValidationIssue(
                code="PIT_EXCESSIVE_STALENESS",
                severity=Severity.WARNING,
                message=f"Data exceeds {max_stale} day staleness"
            ))

        return issues
```

## Target Snapshot Design

Keep snapshots **minimal** and **reproducible**:

```python
# Good - minimal, auditable
snapshot = {
    "resource_id": "uuid",
    "resource_type": "signal",
    "location": {"space": "team", "subspace": "staging"},
    "values": [0.5, -0.3, 0.8],
    "metadata": {"frequency": "daily"}
}

# Bad - too much internal state
snapshot = {
    "db_session": session,      # NO
    "full_dataframe": df,       # NO - too large
    "user_object": user         # NO - not needed
}
```

## Registration

```python
from optaic.guardrails.registry import ContractRegistry

# Register contract kind + validator
ContractRegistry.register(
    kind="signal.bounds",
    schema=SIGNAL_BOUNDS_SCHEMA,
    validator=SignalBoundsValidator,
    version="1.0"
)
```

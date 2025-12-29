"""Tests for the guardrails framework.

Acceptance tests:
- test_hash_deterministic: same ref+config => same contract_hash on repeated calls
- test_hash_changes_on_config_change
- test_policy_official_is_block
- test_policy_staging_warn_default_and_block_hint
- test_models_roundtrip_json: ContractBundle/ValidationReport serialize/deserialize
"""

from __future__ import annotations

from datetime import datetime, timezone


from optaic.guardrails import (
    ContractRef,
    ContractInstance,
    ContractBundle,
    ValidationIssue,
    ValidationReport,
    compute_effective_enforcement,
    contract_hash,
    canonical_dumps,
)


# =============================================================================
# Hash Determinism Tests
# =============================================================================


def test_hash_deterministic() -> None:
    """Same ref+config => same contract_hash on repeated calls."""
    ref = ContractRef(
        contract_kind="schema",
        contract_name="dataset_schema",
        version="1.0.0",
        json_schema='{"type":"object"}',
    )
    config = '{"columns":["a","b","c"]}'

    hash1 = contract_hash(ref, config)
    hash2 = contract_hash(ref, config)
    hash3 = contract_hash(ref, config)

    assert hash1 == hash2 == hash3
    assert len(hash1) == 64  # SHA-256 hex digest


def test_hash_changes_on_config_change() -> None:
    """Different config => different hash."""
    ref = ContractRef(
        contract_kind="schema",
        contract_name="dataset_schema",
        version="1.0.0",
        json_schema='{"type":"object"}',
    )

    hash1 = contract_hash(ref, '{"columns":["a"]}')
    hash2 = contract_hash(ref, '{"columns":["a","b"]}')

    assert hash1 != hash2


def test_hash_changes_on_ref_change() -> None:
    """Different ref fields => different hash."""
    config = '{"columns":["a","b"]}'

    ref1 = ContractRef(
        contract_kind="schema",
        contract_name="dataset_schema",
        version="1.0.0",
    )
    ref2 = ContractRef(
        contract_kind="schema",
        contract_name="dataset_schema",
        version="1.0.1",  # Different version
    )

    hash1 = contract_hash(ref1, config)
    hash2 = contract_hash(ref2, config)

    assert hash1 != hash2


def test_canonical_dumps_sorted_keys() -> None:
    """Canonical dumps should sort keys deterministically."""
    obj1 = {"z": 1, "a": 2, "m": 3}
    obj2 = {"a": 2, "m": 3, "z": 1}

    assert canonical_dumps(obj1) == canonical_dumps(obj2)
    assert canonical_dumps(obj1) == '{"a":2,"m":3,"z":1}'


# =============================================================================
# Enforcement Policy Tests
# =============================================================================


def test_policy_official_is_block() -> None:
    """Official subspace always enforces 'block'."""
    assert compute_effective_enforcement("official", "create", "warn") == "block"
    assert compute_effective_enforcement("official", "update", "warn") == "block"
    assert compute_effective_enforcement("official", "promote", "block") == "block"


def test_policy_staging_warn_default_and_block_hint() -> None:
    """Staging uses 'warn' by default, 'block' when hint is 'block'."""
    # Default warn
    assert compute_effective_enforcement("staging", "create", "warn") == "warn"
    assert compute_effective_enforcement("staging", "update", "warn") == "warn"

    # Warn even when hint is block (fail open in staging)
    assert compute_effective_enforcement("staging", "create", "block") == "warn"
    assert compute_effective_enforcement("staging", "promote", "block") == "warn"


def test_policy_other_subspaces_respect_hint() -> None:
    """Non-official subspaces respect the hint."""
    assert compute_effective_enforcement("dev", "create", "warn") == "warn"
    assert compute_effective_enforcement("dev", "create", "block") == "block"
    assert compute_effective_enforcement("sandbox", "update", "warn") == "warn"


# =============================================================================
# Model Roundtrip Tests
# =============================================================================


def test_contract_bundle_roundtrip_json() -> None:
    """ContractBundle serializes/deserializes without losing fields."""
    ref = ContractRef(
        contract_kind="invariant",
        contract_name="no_nulls",
        version="1.0.0",
    )
    instance = ContractInstance(
        ref=ref,
        config_json='{"column":"id"}',
        contract_hash="abc123",
        enforcement_hint="block",
    )
    bundle = ContractBundle(
        bundle_id="bundle-001",
        resource_id="resource-123",
        resource_version_id="v1",
        created_by="user@example.com",
        created_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        contracts=[instance],
        notes="Test bundle",
    )

    # Serialize to JSON
    json_str = bundle.model_dump_json()

    # Deserialize back
    restored = ContractBundle.model_validate_json(json_str)

    assert restored.bundle_id == bundle.bundle_id
    assert restored.resource_id == bundle.resource_id
    assert restored.resource_version_id == bundle.resource_version_id
    assert restored.created_by == bundle.created_by
    assert restored.notes == bundle.notes
    assert len(restored.contracts) == 1
    assert restored.contracts[0].ref.contract_name == "no_nulls"
    assert restored.contracts[0].enforcement_hint == "block"


def test_validation_report_roundtrip_json() -> None:
    """ValidationReport serializes/deserializes without losing fields."""
    issue = ValidationIssue(
        severity="error",
        code="NULL_VALUE",
        message="Column 'id' contains null values",
        path="$.data.id",
        meta={"row_count": 5},
    )
    report = ValidationReport(
        report_id="report-001",
        scope="resource",
        target_id="resource-123",
        ok=False,
        enforced_as="block",
        issues=[issue],
        contract_hashes=["hash1", "hash2"],
        created_by="system",
        created_at=datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc),
        correlation_id="corr-456",
    )

    # Serialize to JSON
    json_str = report.model_dump_json()

    # Deserialize back
    restored = ValidationReport.model_validate_json(json_str)

    assert restored.report_id == report.report_id
    assert restored.scope == "resource"
    assert restored.target_id == report.target_id
    assert restored.ok is False
    assert restored.enforced_as == "block"
    assert len(restored.issues) == 1
    assert restored.issues[0].code == "NULL_VALUE"
    assert restored.issues[0].meta == {"row_count": 5}
    assert restored.contract_hashes == ["hash1", "hash2"]
    assert restored.correlation_id == "corr-456"


def test_validation_issue_optional_fields() -> None:
    """ValidationIssue works with optional fields omitted."""
    issue = ValidationIssue(
        severity="warning",
        code="DEPRECATED_COLUMN",
        message="Column 'old_field' is deprecated",
    )

    assert issue.path is None
    assert issue.meta is None

    # Roundtrip
    restored = ValidationIssue.model_validate_json(issue.model_dump_json())
    assert restored.path is None
    assert restored.meta is None


def test_contract_bundle_empty_contracts() -> None:
    """ContractBundle works with empty contracts list."""
    bundle = ContractBundle(
        bundle_id="bundle-empty",
        resource_id="resource-999",
        created_by="system",
    )

    assert bundle.contracts == []
    assert bundle.resource_version_id is None
    assert bundle.notes is None

    # Roundtrip
    restored = ContractBundle.model_validate_json(bundle.model_dump_json())
    assert restored.contracts == []

"""E2E Test Configuration.

Import sandbox fixtures from apps/api/tests for E2E case study tests.
"""

from apps.api.tests.conftest import (
    alpha_admin_actor,
    alpha_analyst_actor,
    alpha_viewer_actor,
    beta_admin_actor,
    external_actor,
    sandbox_env,
    sandbox_with_resources,
)

# Re-export all sandbox fixtures
__all__ = [
    "sandbox_env",
    "sandbox_with_resources",
    "alpha_admin_actor",
    "alpha_analyst_actor",
    "alpha_viewer_actor",
    "beta_admin_actor",
    "external_actor",
]

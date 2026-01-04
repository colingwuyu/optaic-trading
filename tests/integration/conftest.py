"""
Integration test fixtures.

All infrastructure fixtures (prefect_server, mlflow_server, centrifugo_server)
are provided by the root conftest.py. This file only provides additional
fixtures specific to integration testing.
"""

from __future__ import annotations

import pytest

# Mark all tests in this directory as integration tests
pytestmark = pytest.mark.integration

"""Test Runner Service - Pytest Subprocess Execution.

This service handles:
- Running pytest in isolated subprocess
- Configuring PYTHONPATH for artifact modules
- Parsing pytest JSON output
- Capturing stdout/stderr with truncation
- Returning structured test results

The service runs tests in a subprocess to:
1. Isolate plugin code from the main process
2. Provide clean environment for each test run
3. Capture all output safely
4. Handle timeouts and crashes gracefully
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog

from libs.core.artifacts import get_artifact_path

logger = structlog.get_logger(__name__)

# Maximum test execution time (5 minutes)
DEFAULT_TIMEOUT_SECONDS = 300

# Maximum output size to store (100 KB)
MAX_OUTPUT_SIZE = 100 * 1024

# pytest JSON report plugin
PYTEST_JSON_REPORT = "pytest-json-report"


@dataclass
class TestFailure:
    """Details about a single test failure."""

    test_name: str
    message: str
    longrepr: str | None = None
    duration_seconds: float = 0.0


@dataclass
class TestRunResult:
    """Result of a test run execution."""

    passed: bool
    tests_total: int
    tests_passed: int
    tests_failed: int
    tests_skipped: int
    duration_ms: int
    output: str
    failures: list[TestFailure] = field(default_factory=list)
    report_json: dict[str, Any] = field(default_factory=dict)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    error: str | None = None


class TestRunnerError(Exception):
    """Base exception for test runner errors."""

    pass


class TestTimeoutError(TestRunnerError):
    """Raised when test execution times out."""

    pass


class TestRunnerService:
    """Runs plugin test suites in isolated subprocess.

    Workflow:
    1. Configure environment with artifact path in PYTHONPATH
    2. Run pytest with JSON report output
    3. Parse results and capture output
    4. Return structured TestRunResult

    Usage:
        runner = TestRunnerService()
        result = await runner.run_tests(
            artifact_ref=uuid,
            test_file="test_pipeline.py",
            module_file="pipeline.py",  # Optional, for imports
        )
    """

    def __init__(
        self,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        max_output_size: int = MAX_OUTPUT_SIZE,
    ) -> None:
        """Initialize the test runner.

        Args:
            timeout_seconds: Maximum test execution time.
            max_output_size: Maximum output to capture.
        """
        self._timeout = timeout_seconds
        self._max_output = max_output_size

    async def run_tests(
        self,
        artifact_ref: UUID,
        test_file: str,
        module_file: str | None = None,
        *,
        extra_pytest_args: list[str] | None = None,
    ) -> TestRunResult:
        """Run tests for a plugin artifact.

        Args:
            artifact_ref: UUID of the artifact containing test files
            test_file: Test file to run (relative to artifact)
            module_file: Module file being tested (for PYTHONPATH)
            extra_pytest_args: Additional pytest arguments

        Returns:
            TestRunResult with execution details

        Raises:
            TestRunnerError: If execution fails unexpectedly
            TestTimeoutError: If tests exceed timeout
        """
        started_at = datetime.now(timezone.utc)

        artifact_path = get_artifact_path(artifact_ref)
        test_path = artifact_path / test_file

        if not test_path.exists():
            return TestRunResult(
                passed=False,
                tests_total=0,
                tests_passed=0,
                tests_failed=0,
                tests_skipped=0,
                duration_ms=0,
                output="",
                started_at=started_at,
                completed_at=datetime.now(timezone.utc),
                error=f"Test file not found: {test_file}",
            )

        logger.info(
            "test_runner.starting",
            artifact_ref=str(artifact_ref),
            test_file=test_file,
        )

        # Run in thread pool to not block event loop
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            self._run_pytest_subprocess,
            artifact_path,
            test_file,
            extra_pytest_args or [],
            started_at,
        )

        logger.info(
            "test_runner.completed",
            artifact_ref=str(artifact_ref),
            passed=result.passed,
            tests_total=result.tests_total,
            tests_failed=result.tests_failed,
            duration_ms=result.duration_ms,
        )

        return result

    def _run_pytest_subprocess(
        self,
        artifact_path: Path,
        test_file: str,
        extra_args: list[str],
        started_at: datetime,
    ) -> TestRunResult:
        """Execute pytest in subprocess.

        Args:
            artifact_path: Path to artifact directory
            test_file: Test file to run
            extra_args: Extra pytest arguments
            started_at: When test started

        Returns:
            TestRunResult
        """
        # Create temp file for JSON report
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".json",
            delete=False,
        ) as report_file:
            report_path = Path(report_file.name)

        try:
            # Build pytest command
            cmd = [
                sys.executable,
                "-m",
                "pytest",
                str(artifact_path / test_file),
                "-v",
                "--tb=short",
                "--json-report",  # Enable JSON report plugin
                f"--json-report-file={report_path}",
                *extra_args,
            ]

            # Configure environment
            env = os.environ.copy()

            # Add artifact path to PYTHONPATH
            python_path = env.get("PYTHONPATH", "")
            if python_path:
                env["PYTHONPATH"] = f"{artifact_path}{os.pathsep}{python_path}"
            else:
                env["PYTHONPATH"] = str(artifact_path)

            # Run pytest
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                    env=env,
                    cwd=str(artifact_path),
                )
            except subprocess.TimeoutExpired:
                completed_at = datetime.now(timezone.utc)
                duration_ms = int((completed_at - started_at).total_seconds() * 1000)
                return TestRunResult(
                    passed=False,
                    tests_total=0,
                    tests_passed=0,
                    tests_failed=0,
                    tests_skipped=0,
                    duration_ms=duration_ms,
                    output=f"Test execution timed out after {self._timeout} seconds",
                    started_at=started_at,
                    completed_at=completed_at,
                    error=f"Timeout after {self._timeout}s",
                )

            completed_at = datetime.now(timezone.utc)
            duration_ms = int((completed_at - started_at).total_seconds() * 1000)

            # Combine and truncate output
            output = f"=== STDOUT ===\n{proc.stdout}\n\n=== STDERR ===\n{proc.stderr}"
            if len(output) > self._max_output:
                output = output[: self._max_output] + "\n\n... (truncated)"

            # Parse JSON report
            report_json: dict[str, Any] = {}
            failures: list[TestFailure] = []

            if report_path.exists():
                try:
                    with open(report_path, "r") as f:
                        report_json = json.load(f)

                    # Extract test counts and failures
                    summary = report_json.get("summary", {})
                    tests_total = summary.get("total", 0)
                    tests_passed = summary.get("passed", 0)
                    tests_failed = summary.get("failed", 0)
                    tests_skipped = summary.get("skipped", 0)

                    # Extract failure details
                    for test in report_json.get("tests", []):
                        if test.get("outcome") == "failed":
                            call_info = test.get("call", {})
                            failures.append(
                                TestFailure(
                                    test_name=test.get("nodeid", "unknown"),
                                    message=call_info.get("crash", {}).get(
                                        "message", "Unknown failure"
                                    ),
                                    longrepr=call_info.get("longrepr"),
                                    duration_seconds=test.get("duration", 0.0),
                                )
                            )

                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning(
                        "test_runner.report_parse_failed",
                        error=str(e),
                    )
                    # Fall back to return code
                    tests_total = 1 if proc.returncode == 0 else 1
                    tests_passed = 1 if proc.returncode == 0 else 0
                    tests_failed = 0 if proc.returncode == 0 else 1
                    tests_skipped = 0
            else:
                # No report file - use return code
                logger.warning("test_runner.no_report_file")
                tests_total = 1
                tests_passed = 1 if proc.returncode == 0 else 0
                tests_failed = 0 if proc.returncode == 0 else 1
                tests_skipped = 0

            # Determine overall pass/fail
            # pytest exit codes: 0=pass, 1=fail, 2=interrupt, 3=internal, 4=usage, 5=no tests
            passed = proc.returncode == 0 or proc.returncode == 5  # No tests is ok

            return TestRunResult(
                passed=passed,
                tests_total=tests_total,
                tests_passed=tests_passed,
                tests_failed=tests_failed,
                tests_skipped=tests_skipped,
                duration_ms=duration_ms,
                output=output,
                failures=failures,
                report_json=report_json,
                started_at=started_at,
                completed_at=completed_at,
            )

        finally:
            # Clean up temp file
            if report_path.exists():
                try:
                    report_path.unlink()
                except OSError:
                    pass

    async def check_dependencies(self) -> dict[str, bool]:
        """Check if required dependencies are available.

        Returns:
            Dict with dependency names and availability status
        """
        result = {}

        # Check pytest
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "pytest",
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            result["pytest"] = proc.returncode == 0
        except Exception:
            result["pytest"] = False

        # Check pytest-json-report
        try:
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                "import pytest_jsonreport",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.wait()
            result["pytest-json-report"] = proc.returncode == 0
        except Exception:
            result["pytest-json-report"] = False

        return result


# Singleton instance
_default_runner: TestRunnerService | None = None


def get_test_runner() -> TestRunnerService:
    """Get the default test runner instance.

    Returns:
        TestRunnerService instance
    """
    global _default_runner

    if _default_runner is None:
        _default_runner = TestRunnerService()

    return _default_runner

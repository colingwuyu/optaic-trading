"""End-to-End Definition Upload Tests - Using Python SDK.

These tests verify the definition plugin upload system works correctly
end-to-end through the SDK -> API -> Service -> Database stack.

Test Scenarios:
1. Upload valid definition with passing tests → status=active
2. Upload definition with failing tests → status=draft
3. Upload without test suite → status=active, eval=skipped
4. Upload with invalid manifest → 422 error
5. Deploy draft definition → status=active
6. Re-run tests for a definition
7. List definitions with filters

CRITICAL PRINCIPLE: SDK-ONLY TESTING
=====================================
E2E tests must ONLY use the SDK. NO direct database access allowed.
NO MOCKS - All tests use real API endpoints via SDK.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from uuid import UUID, uuid4

import pytest
import pytest_asyncio

from libs.sdk_py import AsyncPlatformClient

# E2E tests connect to an external server
# Start the server with: python scripts/e2e_server.py
E2E_API_URL = os.environ.get("E2E_API_URL", "http://localhost:8082")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def create_plugin_zip(
    name: str,
    class_name: str,
    definition_type: str = "PipelineDef",
    *,
    version: str = "1.0.0",
    category: str = "custom",
    interface_spec: str = "libs.data.pipelines.base.BasePipeline",
    include_test_file: bool = False,
    test_should_pass: bool = True,
    extra_manifest_fields: dict | None = None,
    module_content: str | None = None,
) -> bytes:
    """Create a plugin ZIP file for testing.

    Args:
        name: Plugin name
        class_name: Class name to register
        definition_type: Type of definition
        version: Version string
        category: Category string
        interface_spec: Interface specification
        include_test_file: Whether to include a test file
        test_should_pass: Whether the test should pass
        extra_manifest_fields: Additional manifest fields
        module_content: Custom module content

    Returns:
        ZIP file content as bytes
    """
    buffer = io.BytesIO()

    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Create manifest.json
        manifest = {
            "name": name,
            "version": version,
            "definition_type": definition_type,
            "module_file": "plugin.py",
            "class_name": class_name,
            "interface_spec": interface_spec,
            "category": category,
            "description": f"Test plugin: {name}",
        }

        if include_test_file:
            manifest["test_suite_file"] = "test_plugin.py"

        if extra_manifest_fields:
            manifest.update(extra_manifest_fields)

        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        # Create module file
        if module_content:
            plugin_code = module_content
        else:
            plugin_code = f'''"""Test plugin module."""


class {class_name}:
    """Test plugin class."""

    def __init__(self, **kwargs):
        self.config = kwargs

    async def run(self, context=None):
        return {{"status": "success", "class": "{class_name}"}}
'''
        zf.writestr("plugin.py", plugin_code)

        # Create test file if requested
        if include_test_file:
            if test_should_pass:
                test_code = f'''"""Test suite for {name}."""

import pytest
from plugin import {class_name}


def test_plugin_init():
    """Test plugin initialization."""
    plugin = {class_name}(param1="value")
    assert plugin.config["param1"] == "value"


def test_plugin_has_run_method():
    """Test plugin has run method."""
    plugin = {class_name}()
    assert hasattr(plugin, "run")
'''
            else:
                test_code = f'''"""Test suite for {name} - failing tests."""

import pytest
from plugin import {class_name}


def test_plugin_init():
    """Test plugin initialization."""
    plugin = {class_name}(param1="value")
    assert plugin.config["param1"] == "value"


def test_this_should_fail():
    """This test will fail."""
    assert False, "Intentional failure for testing"
'''
            zf.writestr("test_plugin.py", test_code)

    return buffer.getvalue()


# =============================================================================
# FIXTURES
# =============================================================================


@pytest_asyncio.fixture(scope="function")
async def sdk_client():
    """Create an AsyncPlatformClient connected to E2E test server.

    NOTE: The E2E server must be running before tests execute.
    Start it with: python scripts/e2e_server.py
    """
    client = AsyncPlatformClient(base_url=E2E_API_URL)
    yield client
    await client.close()


@pytest_asyncio.fixture(scope="function")
async def upload_test_setup(sdk_client: AsyncPlatformClient):
    """Set up using bootstrap tenant/principal for upload testing.

    The E2E server bootstraps a system tenant on startup with:
    - tenant_id: 00000000-0000-0000-0000-000000000001
    - admin_id: 00000000-0000-0000-0000-000000000003
    - space_id: 00000000-0000-0000-0000-000000000002
    - project_id: 00000000-0000-0000-0000-000000000013
    """
    # Use bootstrap admin principal and tenant
    BOOTSTRAP_TENANT_ID = "00000000-0000-0000-0000-000000000001"
    BOOTSTRAP_ADMIN_ID = "00000000-0000-0000-0000-000000000003"
    BOOTSTRAP_SPACE_ID = "00000000-0000-0000-0000-000000000002"

    sdk_client.set_principal_id(BOOTSTRAP_ADMIN_ID)
    sdk_client.set_tenant_id(BOOTSTRAP_TENANT_ID)

    # Create a unique Project for each test to isolate data
    project = await sdk_client.resources.create(
        resource_type="Project",
        parent_id=BOOTSTRAP_SPACE_ID,
        name=f"Upload Test Project {uuid4()}",
    )

    return {
        "client": sdk_client,
        "tenant_id": UUID(BOOTSTRAP_TENANT_ID),
        "principal_id": UUID(BOOTSTRAP_ADMIN_ID),
        "root_resource_id": UUID(BOOTSTRAP_SPACE_ID),
        "space_id": UUID(BOOTSTRAP_SPACE_ID),
        "project_id": UUID(project["id"]),
    }


# =============================================================================
# BASIC UPLOAD TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_upload_valid_definition_without_tests(upload_test_setup):
    """Test uploading a valid definition without tests → status=active."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    # Create a plugin ZIP without tests
    zip_content = create_plugin_zip(
        name="TestPipeline",
        class_name="TestPipeline",
        definition_type="PipelineDef",
        include_test_file=False,
    )

    # Upload via SDK
    result = await client.definitions.upload_bytes(
        zip_content=zip_content,
        filename="test_pipeline.zip",
        target_parent_id=project_id,
    )

    # Verify result
    assert "id" in result
    assert result["name"] == "TestPipeline"
    assert result["definition_type"] == "PipelineDef"
    assert result["code_ref"] == "TestPipeline"
    assert result["status"] == "active"  # No tests = active
    assert result["evaluation_status"] == "skipped"  # No test file
    assert "artifact_ref" in result


@pytest.mark.asyncio
async def test_upload_valid_definition_with_passing_tests(upload_test_setup):
    """Test uploading a definition with passing tests → status=active."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    # Create a plugin ZIP with passing tests
    zip_content = create_plugin_zip(
        name="PassingTestPipeline",
        class_name="PassingTestPipeline",
        definition_type="PipelineDef",
        include_test_file=True,
        test_should_pass=True,
    )

    # Upload via SDK
    result = await client.definitions.upload_bytes(
        zip_content=zip_content,
        filename="passing_pipeline.zip",
        target_parent_id=project_id,
    )

    # Verify result
    assert result["name"] == "PassingTestPipeline"
    assert result["status"] == "active"
    assert result["evaluation_status"] == "passed"
    assert result["tests_total"] is not None
    assert result["tests_passed"] is not None
    assert result["tests_failed"] == 0


@pytest.mark.asyncio
async def test_upload_definition_with_failing_tests(upload_test_setup):
    """Test uploading a definition with failing tests → status=draft."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    # Create a plugin ZIP with failing tests
    zip_content = create_plugin_zip(
        name="FailingTestPipeline",
        class_name="FailingTestPipeline",
        definition_type="PipelineDef",
        include_test_file=True,
        test_should_pass=False,
    )

    # Upload via SDK
    result = await client.definitions.upload_bytes(
        zip_content=zip_content,
        filename="failing_pipeline.zip",
        target_parent_id=project_id,
    )

    # Verify result
    assert result["name"] == "FailingTestPipeline"
    assert result["status"] == "draft"  # Tests failed
    assert result["evaluation_status"] == "failed"
    assert result["tests_failed"] > 0
    assert len(result.get("issues", [])) > 0


@pytest.mark.asyncio
async def test_upload_skip_tests(upload_test_setup):
    """Test uploading with skip_tests=True skips test execution."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    # Create a plugin ZIP with failing tests but skip them
    zip_content = create_plugin_zip(
        name="SkipTestPipeline",
        class_name="SkipTestPipeline",
        definition_type="PipelineDef",
        include_test_file=True,
        test_should_pass=False,  # Would fail if run
    )

    # Upload with skip_tests
    result = await client.definitions.upload_bytes(
        zip_content=zip_content,
        filename="skip_test_pipeline.zip",
        target_parent_id=project_id,
        skip_tests=True,
    )

    # Verify tests were skipped
    assert result["status"] == "active"
    assert result["evaluation_status"] == "skipped"


# =============================================================================
# MANIFEST VALIDATION TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_upload_invalid_manifest_missing_fields(upload_test_setup):
    """Test uploading with invalid manifest missing required fields → 422."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    # Create ZIP with incomplete manifest
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        # Missing required fields: module_file, class_name, interface_spec
        manifest = {
            "name": "InvalidPlugin",
            "version": "1.0.0",
            "definition_type": "PipelineDef",
        }
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("plugin.py", "class Foo: pass")

    with pytest.raises(Exception) as exc_info:
        await client.definitions.upload_bytes(
            zip_content=buffer.getvalue(),
            filename="invalid.zip",
            target_parent_id=project_id,
        )

    assert "422" in str(exc_info.value) or "validation" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_upload_invalid_definition_type(upload_test_setup):
    """Test uploading with unsupported definition type → 422."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    # Create ZIP with invalid definition_type
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        manifest = {
            "name": "InvalidType",
            "version": "1.0.0",
            "definition_type": "InvalidDef",  # Not supported
            "module_file": "plugin.py",
            "class_name": "InvalidType",
            "interface_spec": "some.interface",
        }
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("plugin.py", "class InvalidType: pass")

    with pytest.raises(Exception) as exc_info:
        await client.definitions.upload_bytes(
            zip_content=buffer.getvalue(),
            filename="invalid_type.zip",
            target_parent_id=project_id,
        )

    assert "422" in str(exc_info.value) or "Unsupported" in str(exc_info.value)


@pytest.mark.asyncio
async def test_upload_no_manifest(upload_test_setup):
    """Test uploading ZIP without manifest.json → 422."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    # Create ZIP without manifest
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("plugin.py", "class NoManifest: pass")

    with pytest.raises(Exception) as exc_info:
        await client.definitions.upload_bytes(
            zip_content=buffer.getvalue(),
            filename="no_manifest.zip",
            target_parent_id=project_id,
        )

    assert "422" in str(exc_info.value) or "manifest" in str(exc_info.value).lower()


# =============================================================================
# DEPLOY AND RERUN TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_deploy_draft_definition(upload_test_setup):
    """Test deploying a draft definition → status=active."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    # Create a definition with failing tests (draft)
    zip_content = create_plugin_zip(
        name="DeployTestPipeline",
        class_name="DeployTestPipeline",
        definition_type="PipelineDef",
        include_test_file=True,
        test_should_pass=False,
    )

    # Upload (will be draft)
    upload_result = await client.definitions.upload_bytes(
        zip_content=zip_content,
        filename="deploy_test.zip",
        target_parent_id=project_id,
    )

    assert upload_result["status"] == "draft"
    definition_id = upload_result["id"]

    # Deploy the draft definition
    deploy_result = await client.definitions.deploy(definition_id)

    assert deploy_result["id"] == definition_id
    assert deploy_result["status"] == "active"
    assert deploy_result["code_ref"] == "DeployTestPipeline"


@pytest.mark.asyncio
async def test_rerun_tests_on_definition(upload_test_setup):
    """Test re-running tests on a definition."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    # Create a definition with passing tests
    zip_content = create_plugin_zip(
        name="RerunTestPipeline",
        class_name="RerunTestPipeline",
        definition_type="PipelineDef",
        include_test_file=True,
        test_should_pass=True,
    )

    # Upload
    upload_result = await client.definitions.upload_bytes(
        zip_content=zip_content,
        filename="rerun_test.zip",
        target_parent_id=project_id,
    )

    definition_id = upload_result["id"]

    # Rerun tests
    rerun_result = await client.definitions.rerun_tests(definition_id)

    assert rerun_result["id"] == definition_id
    assert rerun_result["evaluation_status"] == "passed"
    assert rerun_result["tests_total"] > 0
    assert rerun_result["passed"] is True


# =============================================================================
# GET AND LIST TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_get_definition_details(upload_test_setup):
    """Test getting detailed information about a definition."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    # Upload a definition
    zip_content = create_plugin_zip(
        name="DetailTestPipeline",
        class_name="DetailTestPipeline",
        definition_type="PipelineDef",
        include_test_file=True,
        test_should_pass=True,
    )

    upload_result = await client.definitions.upload_bytes(
        zip_content=zip_content,
        filename="detail_test.zip",
        target_parent_id=project_id,
    )

    definition_id = upload_result["id"]

    # Get details
    details = await client.definitions.get(definition_id)

    assert details["id"] == definition_id
    assert details["name"] == "DetailTestPipeline"
    assert details["version"] == "1.0.0"
    assert details["definition_type"] == "PipelineDef"
    assert details["code_ref"] == "DetailTestPipeline"
    assert details["module_file"] == "plugin.py"
    assert details["test_suite_file"] == "test_plugin.py"
    assert "manifest" in details
    assert details["manifest"]["name"] == "DetailTestPipeline"


@pytest.mark.asyncio
async def test_list_definitions(upload_test_setup):
    """Test listing definitions with filters."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    # Upload multiple definitions
    for i in range(3):
        zip_content = create_plugin_zip(
            name=f"ListTestPipeline{i}",
            class_name=f"ListTestPipeline{i}",
            definition_type="PipelineDef",
        )
        await client.definitions.upload_bytes(
            zip_content=zip_content,
            filename=f"list_test_{i}.zip",
            target_parent_id=project_id,
        )

    # List all definitions
    result = await client.definitions.list()

    assert "items" in result
    assert len(result["items"]) >= 3

    # Verify items have expected fields
    for item in result["items"]:
        assert "id" in item
        assert "name" in item
        assert "definition_type" in item


@pytest.mark.asyncio
async def test_list_definitions_with_filters(upload_test_setup):
    """Test listing definitions with type and status filters."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    # Upload PipelineDef
    pipeline_zip = create_plugin_zip(
        name="FilterPipeline",
        class_name="FilterPipeline",
        definition_type="PipelineDef",
    )
    await client.definitions.upload_bytes(
        zip_content=pipeline_zip,
        filename="filter_pipeline.zip",
        target_parent_id=project_id,
    )

    # Upload OpDef
    op_zip = create_plugin_zip(
        name="FilterOp",
        class_name="FilterOp",
        definition_type="OpDef",
        category="rolling",
        extra_manifest_fields={"signature": "FilterOp(x: Series) -> Series"},
    )
    await client.definitions.upload_bytes(
        zip_content=op_zip,
        filename="filter_op.zip",
        target_parent_id=project_id,
    )

    # List only PipelineDef
    result = await client.definitions.list(definition_type="PipelineDef")

    pipeline_names = [item["name"] for item in result["items"]]
    assert "FilterPipeline" in pipeline_names

    # List only active definitions
    result = await client.definitions.list(status="active")
    for item in result["items"]:
        assert item["status"] == "active"


# =============================================================================
# ALL DEFINITION TYPES TESTS
# =============================================================================


@pytest.mark.asyncio
async def test_upload_store_definition(upload_test_setup):
    """Test uploading a StoreDef."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    zip_content = create_plugin_zip(
        name="CustomStore",
        class_name="CustomStore",
        definition_type="StoreDef",
        category="parquet",
        interface_spec="libs.data.stores.base.BaseStore",
    )

    result = await client.definitions.upload_bytes(
        zip_content=zip_content,
        filename="custom_store.zip",
        target_parent_id=project_id,
    )

    assert result["name"] == "CustomStore"
    assert result["definition_type"] == "StoreDef"
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_upload_accessor_definition(upload_test_setup):
    """Test uploading an AccessorDef."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    zip_content = create_plugin_zip(
        name="CustomAccessor",
        class_name="CustomAccessor",
        definition_type="AccessorDef",
        category="pit",
        interface_spec="libs.data.accessors.base.BaseAccessor",
    )

    result = await client.definitions.upload_bytes(
        zip_content=zip_content,
        filename="custom_accessor.zip",
        target_parent_id=project_id,
    )

    assert result["name"] == "CustomAccessor"
    assert result["definition_type"] == "AccessorDef"
    assert result["status"] == "active"


@pytest.mark.asyncio
async def test_upload_op_definition(upload_test_setup):
    """Test uploading an OpDef."""
    client = upload_test_setup["client"]
    project_id = upload_test_setup["project_id"]

    zip_content = create_plugin_zip(
        name="CustomOp",
        class_name="CustomOp",
        definition_type="OpDef",
        category="rolling",
        interface_spec="libs.data.ops.base.BaseOp",
        extra_manifest_fields={
            "signature": "CUSTOMOP(x: Series, window: int) -> Series"
        },
    )

    result = await client.definitions.upload_bytes(
        zip_content=zip_content,
        filename="custom_op.zip",
        target_parent_id=project_id,
    )

    assert result["name"] == "CustomOp"
    assert result["definition_type"] == "OpDef"
    assert result["status"] == "active"

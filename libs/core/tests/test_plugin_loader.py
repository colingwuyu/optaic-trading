"""Tests for plugin_loader module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from libs.core.plugin_loader import (
    load_plugin_module,
    register_plugin,
    unregister_plugin,
    _get_factory_map,
)
from libs.core.artifacts import ArtifactManager


class TestLoadPluginModule:
    """Tests for load_plugin_module function."""

    @pytest.fixture
    def artifact_manager(self, tmp_path: Path) -> ArtifactManager:
        """Create an ArtifactManager with a temporary directory."""
        return ArtifactManager(data_dir=tmp_path)

    @pytest.fixture
    def sample_plugin(self, artifact_manager: ArtifactManager) -> tuple:
        """Create a sample plugin module in artifact storage."""
        artifact_ref = artifact_manager.create_artifact()

        # Create a simple plugin module
        plugin_code = b'''
"""Sample pipeline plugin for testing."""

class SampleTestPipeline:
    """A simple test pipeline."""

    def __init__(self, param1: str = "default"):
        self.param1 = param1

    def run(self):
        return {"result": self.param1}


PLUGIN_VERSION = "1.0.0"
'''
        artifact_manager.write_file(artifact_ref, "sample_pipeline.py", plugin_code)

        return artifact_ref, "sample_pipeline.py", "SampleTestPipeline"

    def test_load_module_success(
        self, sample_plugin: tuple, artifact_manager: ArtifactManager, monkeypatch
    ) -> None:
        """Test loading a valid plugin module."""
        artifact_ref, module_file, class_name = sample_plugin

        # Monkeypatch get_artifact_path to use our test directory
        from libs.core import plugin_loader

        monkeypatch.setattr(
            plugin_loader,
            "get_artifact_path",
            lambda ref, data_dir=None: artifact_manager.get_path(ref),
        )

        module = load_plugin_module(artifact_ref, module_file)

        assert hasattr(module, class_name)
        assert hasattr(module, "PLUGIN_VERSION")
        assert module.PLUGIN_VERSION == "1.0.0"

    def test_load_module_not_found(
        self, artifact_manager: ArtifactManager, monkeypatch
    ) -> None:
        """Test loading a non-existent module raises FileNotFoundError."""
        artifact_ref = artifact_manager.create_artifact()

        from libs.core import plugin_loader

        monkeypatch.setattr(
            plugin_loader,
            "get_artifact_path",
            lambda ref, data_dir=None: artifact_manager.get_path(ref),
        )

        with pytest.raises(FileNotFoundError, match="Module not found"):
            load_plugin_module(artifact_ref, "nonexistent.py")

    def test_load_module_adds_to_sys_path(
        self, sample_plugin: tuple, artifact_manager: ArtifactManager, monkeypatch
    ) -> None:
        """Test that loading a module adds artifact path to sys.path."""
        artifact_ref, module_file, _ = sample_plugin

        from libs.core import plugin_loader

        monkeypatch.setattr(
            plugin_loader,
            "get_artifact_path",
            lambda ref, data_dir=None: artifact_manager.get_path(ref),
        )

        artifact_path = str(artifact_manager.get_path(artifact_ref))

        # Remove from sys.path if already there
        if artifact_path in sys.path:
            sys.path.remove(artifact_path)

        load_plugin_module(artifact_ref, module_file)

        assert artifact_path in sys.path


class TestRegisterPlugin:
    """Tests for register_plugin function."""

    @pytest.fixture
    def artifact_manager(self, tmp_path: Path) -> ArtifactManager:
        """Create an ArtifactManager with a temporary directory."""
        return ArtifactManager(data_dir=tmp_path)

    @pytest.fixture
    def pipeline_plugin(self, artifact_manager: ArtifactManager) -> tuple:
        """Create a pipeline plugin module in artifact storage."""
        artifact_ref = artifact_manager.create_artifact()

        # Create a pipeline plugin
        plugin_code = b'''
"""Test pipeline plugin."""

class TestRegistryPipeline:
    """A pipeline for testing registration."""

    def __init__(self, **kwargs):
        self.config = kwargs

    async def run(self, context):
        return {"status": "success"}
'''
        artifact_manager.write_file(artifact_ref, "test_pipeline.py", plugin_code)

        return artifact_ref, "test_pipeline.py", "TestRegistryPipeline"

    def test_register_pipeline_success(
        self, pipeline_plugin: tuple, artifact_manager: ArtifactManager, monkeypatch
    ) -> None:
        """Test registering a pipeline plugin."""
        artifact_ref, module_file, class_name = pipeline_plugin

        from libs.core import plugin_loader

        monkeypatch.setattr(
            plugin_loader,
            "get_artifact_path",
            lambda ref, data_dir=None: artifact_manager.get_path(ref),
        )

        code_ref = register_plugin(
            definition_type="PipelineDef",
            artifact_ref=artifact_ref,
            module_file=module_file,
            class_name=class_name,
        )

        assert code_ref == class_name

        # Verify it's in the factory
        factory_map = _get_factory_map()
        factory = factory_map["PipelineDef"]
        assert factory.contains(class_name)

        # Cleanup
        unregister_plugin("PipelineDef", class_name)

    def test_register_class_not_found(
        self, pipeline_plugin: tuple, artifact_manager: ArtifactManager, monkeypatch
    ) -> None:
        """Test registering with a non-existent class name raises AttributeError."""
        artifact_ref, module_file, _ = pipeline_plugin

        from libs.core import plugin_loader

        monkeypatch.setattr(
            plugin_loader,
            "get_artifact_path",
            lambda ref, data_dir=None: artifact_manager.get_path(ref),
        )

        with pytest.raises(AttributeError, match="not found in module"):
            register_plugin(
                definition_type="PipelineDef",
                artifact_ref=artifact_ref,
                module_file=module_file,
                class_name="NonExistentClass",
            )

    def test_register_unknown_definition_type(
        self, pipeline_plugin: tuple, artifact_manager: ArtifactManager, monkeypatch
    ) -> None:
        """Test registering with unknown definition type raises ValueError."""
        artifact_ref, module_file, class_name = pipeline_plugin

        from libs.core import plugin_loader

        monkeypatch.setattr(
            plugin_loader,
            "get_artifact_path",
            lambda ref, data_dir=None: artifact_manager.get_path(ref),
        )

        with pytest.raises(ValueError, match="Unknown definition type"):
            register_plugin(
                definition_type="UnknownDef",
                artifact_ref=artifact_ref,
                module_file=module_file,
                class_name=class_name,
            )

    def test_register_idempotent(
        self, pipeline_plugin: tuple, artifact_manager: ArtifactManager, monkeypatch
    ) -> None:
        """Test that registering the same plugin twice is idempotent."""
        artifact_ref, module_file, class_name = pipeline_plugin

        from libs.core import plugin_loader

        monkeypatch.setattr(
            plugin_loader,
            "get_artifact_path",
            lambda ref, data_dir=None: artifact_manager.get_path(ref),
        )

        # Register twice
        code_ref1 = register_plugin(
            definition_type="PipelineDef",
            artifact_ref=artifact_ref,
            module_file=module_file,
            class_name=class_name,
        )
        code_ref2 = register_plugin(
            definition_type="PipelineDef",
            artifact_ref=artifact_ref,
            module_file=module_file,
            class_name=class_name,
        )

        assert code_ref1 == code_ref2 == class_name

        # Cleanup
        unregister_plugin("PipelineDef", class_name)


class TestUnregisterPlugin:
    """Tests for unregister_plugin function."""

    @pytest.fixture
    def artifact_manager(self, tmp_path: Path) -> ArtifactManager:
        """Create an ArtifactManager with a temporary directory."""
        return ArtifactManager(data_dir=tmp_path)

    @pytest.fixture
    def registered_plugin(
        self, artifact_manager: ArtifactManager, monkeypatch
    ) -> tuple:
        """Create and register a pipeline plugin."""
        artifact_ref = artifact_manager.create_artifact()

        plugin_code = b"""
class UnregisterTestPipeline:
    pass
"""
        artifact_manager.write_file(artifact_ref, "unregister_test.py", plugin_code)

        from libs.core import plugin_loader

        monkeypatch.setattr(
            plugin_loader,
            "get_artifact_path",
            lambda ref, data_dir=None: artifact_manager.get_path(ref),
        )

        register_plugin(
            definition_type="PipelineDef",
            artifact_ref=artifact_ref,
            module_file="unregister_test.py",
            class_name="UnregisterTestPipeline",
        )

        return "PipelineDef", "UnregisterTestPipeline"

    def test_unregister_success(self, registered_plugin: tuple) -> None:
        """Test unregistering a plugin."""
        definition_type, class_name = registered_plugin

        result = unregister_plugin(definition_type, class_name)

        assert result is True

        # Verify it's no longer in the factory
        factory_map = _get_factory_map()
        factory = factory_map[definition_type]
        assert not factory.contains(class_name)

    def test_unregister_not_found(self) -> None:
        """Test unregistering a non-existent plugin returns False."""
        result = unregister_plugin("PipelineDef", "NonExistentPlugin")

        assert result is False

    def test_unregister_unknown_type(self) -> None:
        """Test unregistering with unknown type returns False."""
        result = unregister_plugin("UnknownDef", "SomePlugin")

        assert result is False


class TestGetFactoryMap:
    """Tests for _get_factory_map function."""

    def test_returns_all_factories(self) -> None:
        """Test that factory map contains expected definition types."""
        factory_map = _get_factory_map()

        assert "PipelineDef" in factory_map
        assert "StoreDef" in factory_map
        assert "AccessorDef" in factory_map
        assert "OpDef" in factory_map

    def test_caches_result(self) -> None:
        """Test that factory map is cached (singleton)."""
        map1 = _get_factory_map()
        map2 = _get_factory_map()

        assert map1 is map2

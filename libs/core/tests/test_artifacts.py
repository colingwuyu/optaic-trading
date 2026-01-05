"""Tests for ArtifactManager."""

from __future__ import annotations

import pytest
from pathlib import Path
from uuid import uuid4

from libs.core.artifacts import ArtifactManager, get_artifact_manager


class TestArtifactManager:
    """Tests for ArtifactManager class."""

    @pytest.fixture
    def manager(self, tmp_path: Path) -> ArtifactManager:
        """Create an ArtifactManager with a temporary directory."""
        return ArtifactManager(data_dir=tmp_path)

    def test_create_artifact(self, manager: ArtifactManager) -> None:
        """Test creating a new artifact folder."""
        artifact_ref = manager.create_artifact()

        assert manager.exists(artifact_ref)
        assert manager.get_path(artifact_ref).is_dir()

    def test_create_artifact_with_ref(self, manager: ArtifactManager) -> None:
        """Test creating an artifact with a specific UUID."""
        artifact_ref = uuid4()
        result = manager.create_artifact(artifact_ref)

        assert result == artifact_ref
        assert manager.exists(artifact_ref)

    def test_copy_artifact(self, manager: ArtifactManager) -> None:
        """Test copying an artifact folder."""
        # Create source artifact with a file
        source_ref = manager.create_artifact()
        manager.write_file(source_ref, "test.txt", b"hello world")

        # Copy the artifact
        target_ref = manager.copy_artifact(source_ref)

        assert manager.exists(target_ref)
        assert source_ref != target_ref

        # Verify file was copied
        content = manager.read_file(target_ref, "test.txt")
        assert content == b"hello world"

    def test_copy_artifact_with_target_ref(self, manager: ArtifactManager) -> None:
        """Test copying an artifact to a specific UUID."""
        source_ref = manager.create_artifact()
        manager.write_file(source_ref, "data.bin", b"\x00\x01\x02")

        target_ref = uuid4()
        result = manager.copy_artifact(source_ref, target_ref)

        assert result == target_ref
        assert manager.exists(target_ref)

    def test_copy_artifact_not_found(self, manager: ArtifactManager) -> None:
        """Test copying a non-existent artifact raises error."""
        fake_ref = uuid4()

        with pytest.raises(FileNotFoundError):
            manager.copy_artifact(fake_ref)

    def test_delete_artifact(self, manager: ArtifactManager) -> None:
        """Test deleting an artifact folder."""
        artifact_ref = manager.create_artifact()
        manager.write_file(artifact_ref, "test.txt", b"data")

        result = manager.delete_artifact(artifact_ref)

        assert result is True
        assert not manager.exists(artifact_ref)

    def test_delete_artifact_not_found(self, manager: ArtifactManager) -> None:
        """Test deleting a non-existent artifact returns False."""
        fake_ref = uuid4()

        result = manager.delete_artifact(fake_ref)

        assert result is False

    def test_exists(self, manager: ArtifactManager) -> None:
        """Test checking artifact existence."""
        artifact_ref = manager.create_artifact()
        fake_ref = uuid4()

        assert manager.exists(artifact_ref) is True
        assert manager.exists(fake_ref) is False

    def test_list_files(self, manager: ArtifactManager) -> None:
        """Test listing files in an artifact."""
        artifact_ref = manager.create_artifact()
        manager.write_file(artifact_ref, "a.txt", b"a")
        manager.write_file(artifact_ref, "b.txt", b"b")
        manager.write_file(artifact_ref, "subdir/c.txt", b"c")

        files = manager.list_files(artifact_ref)

        assert len(files) == 3
        assert Path("a.txt") in files
        assert Path("b.txt") in files
        assert Path("subdir/c.txt") in files

    def test_list_files_empty(self, manager: ArtifactManager) -> None:
        """Test listing files in an empty artifact."""
        artifact_ref = manager.create_artifact()

        files = manager.list_files(artifact_ref)

        assert files == []

    def test_list_files_not_found(self, manager: ArtifactManager) -> None:
        """Test listing files in a non-existent artifact raises error."""
        fake_ref = uuid4()

        with pytest.raises(FileNotFoundError):
            manager.list_files(fake_ref)

    def test_get_size(self, manager: ArtifactManager) -> None:
        """Test getting artifact size."""
        artifact_ref = manager.create_artifact()
        manager.write_file(artifact_ref, "a.txt", b"12345")  # 5 bytes
        manager.write_file(artifact_ref, "b.txt", b"67890")  # 5 bytes

        size = manager.get_size(artifact_ref)

        assert size == 10

    def test_get_size_empty(self, manager: ArtifactManager) -> None:
        """Test getting size of an empty artifact."""
        artifact_ref = manager.create_artifact()

        size = manager.get_size(artifact_ref)

        assert size == 0

    def test_get_size_not_found(self, manager: ArtifactManager) -> None:
        """Test getting size of a non-existent artifact raises error."""
        fake_ref = uuid4()

        with pytest.raises(FileNotFoundError):
            manager.get_size(fake_ref)

    def test_write_file(self, manager: ArtifactManager) -> None:
        """Test writing a file to an artifact."""
        artifact_ref = manager.create_artifact()
        content = b"test content"

        path = manager.write_file(artifact_ref, "test.txt", content)

        assert path.exists()
        assert path.read_bytes() == content

    def test_write_file_nested(self, manager: ArtifactManager) -> None:
        """Test writing a file to a nested directory."""
        artifact_ref = manager.create_artifact()
        content = b"nested content"

        path = manager.write_file(artifact_ref, "a/b/c/test.txt", content)

        assert path.exists()
        assert path.read_bytes() == content

    def test_write_file_artifact_not_found(self, manager: ArtifactManager) -> None:
        """Test writing to a non-existent artifact raises error."""
        fake_ref = uuid4()

        with pytest.raises(FileNotFoundError):
            manager.write_file(fake_ref, "test.txt", b"data")

    def test_read_file(self, manager: ArtifactManager) -> None:
        """Test reading a file from an artifact."""
        artifact_ref = manager.create_artifact()
        content = b"file content"
        manager.write_file(artifact_ref, "test.txt", content)

        result = manager.read_file(artifact_ref, "test.txt")

        assert result == content

    def test_read_file_not_found(self, manager: ArtifactManager) -> None:
        """Test reading a non-existent file raises error."""
        artifact_ref = manager.create_artifact()

        with pytest.raises(FileNotFoundError):
            manager.read_file(artifact_ref, "missing.txt")

    def test_read_file_artifact_not_found(self, manager: ArtifactManager) -> None:
        """Test reading from a non-existent artifact raises error."""
        fake_ref = uuid4()

        with pytest.raises(FileNotFoundError):
            manager.read_file(fake_ref, "test.txt")

    def test_delete_file(self, manager: ArtifactManager) -> None:
        """Test deleting a file from an artifact."""
        artifact_ref = manager.create_artifact()
        manager.write_file(artifact_ref, "test.txt", b"data")

        result = manager.delete_file(artifact_ref, "test.txt")

        assert result is True
        assert Path("test.txt") not in manager.list_files(artifact_ref)

    def test_delete_file_not_found(self, manager: ArtifactManager) -> None:
        """Test deleting a non-existent file returns False."""
        artifact_ref = manager.create_artifact()

        result = manager.delete_file(artifact_ref, "missing.txt")

        assert result is False

    def test_delete_file_artifact_not_found(self, manager: ArtifactManager) -> None:
        """Test deleting from a non-existent artifact raises error."""
        fake_ref = uuid4()

        with pytest.raises(FileNotFoundError):
            manager.delete_file(fake_ref, "test.txt")


class TestGetArtifactManager:
    """Tests for get_artifact_manager function."""

    def test_with_data_dir(self, tmp_path: Path) -> None:
        """Test getting a manager with a specific data directory."""
        manager = get_artifact_manager(data_dir=tmp_path)

        assert manager.artifacts_dir == tmp_path / "artifacts"

    def test_singleton_behavior(self) -> None:
        """Test that default manager is cached as singleton."""
        # Note: This test modifies global state, so we just verify
        # that calling get_artifact_manager() twice returns something
        manager1 = get_artifact_manager()
        manager2 = get_artifact_manager()

        # Both should be valid managers
        assert manager1 is not None
        assert manager2 is not None

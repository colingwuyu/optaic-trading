"""Artifact Manager for file operations.

Manages file artifacts stored in {DATA_DIR}/artifacts/{artifact_ref}/.
Each artifact_ref is a UUID that uniquely identifies an artifact folder.

Governance operations and their artifact handling:
- Copy (reference): Same artifact_ref, no file copy
- Branch: New artifact_ref with copied files
- Transfer: Same artifact_ref (ownership change only)
- Promote: New artifact_ref with copied files
- Merge: Branch artifact replaces ancestor artifact
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import UUID, uuid4

import structlog

from optaic.paths import resolve_data_dir

logger = structlog.get_logger(__name__)


def get_artifacts_dir(data_dir: Path | None = None) -> Path:
    """Get the base artifacts directory.

    Args:
        data_dir: Optional override for data directory

    Returns:
        Path to artifacts directory ({DATA_DIR}/artifacts/)
    """
    base = data_dir or resolve_data_dir()
    return base / "artifacts"


def get_artifact_path(artifact_ref: UUID, data_dir: Path | None = None) -> Path:
    """Get the path to a specific artifact folder.

    Args:
        artifact_ref: UUID of the artifact
        data_dir: Optional override for data directory

    Returns:
        Path to artifact folder ({DATA_DIR}/artifacts/{artifact_ref}/)
    """
    return get_artifacts_dir(data_dir) / str(artifact_ref)


class ArtifactManager:
    """Manages file artifacts for resources.

    Artifacts are stored in {DATA_DIR}/artifacts/{artifact_ref}/ where
    artifact_ref is a UUID stored on the Resource model.

    This class provides operations for:
    - Creating new artifacts
    - Copying artifacts (for branch/promote operations)
    - Deleting artifacts
    - Listing artifact contents
    """

    def __init__(self, data_dir: Path | None = None) -> None:
        """Initialize the artifact manager.

        Args:
            data_dir: Optional override for data directory.
                     If not provided, uses resolve_data_dir().
        """
        self._data_dir = data_dir or resolve_data_dir()
        self._artifacts_dir = self._data_dir / "artifacts"

    @property
    def artifacts_dir(self) -> Path:
        """Get the base artifacts directory."""
        return self._artifacts_dir

    def create_artifact(self, artifact_ref: UUID | None = None) -> UUID:
        """Create a new empty artifact folder.

        Args:
            artifact_ref: Optional UUID for the artifact. If not provided,
                         a new UUID will be generated.

        Returns:
            UUID of the created artifact
        """
        if artifact_ref is None:
            artifact_ref = uuid4()

        artifact_path = self._artifacts_dir / str(artifact_ref)
        artifact_path.mkdir(parents=True, exist_ok=True)

        logger.info(
            "artifact.created",
            artifact_ref=str(artifact_ref),
            path=str(artifact_path),
        )

        return artifact_ref

    def copy_artifact(
        self,
        source_ref: UUID,
        target_ref: UUID | None = None,
    ) -> UUID:
        """Copy an artifact folder to a new location.

        Used for branch and promote operations where files need to be copied.

        Args:
            source_ref: UUID of the source artifact
            target_ref: Optional UUID for the target. If not provided,
                       a new UUID will be generated.

        Returns:
            UUID of the new artifact

        Raises:
            FileNotFoundError: If source artifact doesn't exist
        """
        if target_ref is None:
            target_ref = uuid4()

        source_path = self._artifacts_dir / str(source_ref)
        target_path = self._artifacts_dir / str(target_ref)

        if not source_path.exists():
            raise FileNotFoundError(f"Source artifact not found: {source_ref}")

        # Ensure parent directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Copy entire directory tree
        shutil.copytree(source_path, target_path, dirs_exist_ok=True)

        logger.info(
            "artifact.copied",
            source_ref=str(source_ref),
            target_ref=str(target_ref),
        )

        return target_ref

    def delete_artifact(self, artifact_ref: UUID) -> bool:
        """Delete an artifact folder.

        Args:
            artifact_ref: UUID of the artifact to delete

        Returns:
            True if artifact was deleted, False if it didn't exist
        """
        artifact_path = self._artifacts_dir / str(artifact_ref)

        if not artifact_path.exists():
            return False

        shutil.rmtree(artifact_path)

        logger.info(
            "artifact.deleted",
            artifact_ref=str(artifact_ref),
        )

        return True

    def exists(self, artifact_ref: UUID) -> bool:
        """Check if an artifact exists.

        Args:
            artifact_ref: UUID of the artifact

        Returns:
            True if artifact folder exists
        """
        artifact_path = self._artifacts_dir / str(artifact_ref)
        return artifact_path.exists()

    def get_path(self, artifact_ref: UUID) -> Path:
        """Get the path to an artifact folder.

        Args:
            artifact_ref: UUID of the artifact

        Returns:
            Path to the artifact folder

        Note:
            This does not check if the artifact exists.
            Use exists() to verify first if needed.
        """
        return self._artifacts_dir / str(artifact_ref)

    def list_files(self, artifact_ref: UUID) -> list[Path]:
        """List all files in an artifact folder.

        Args:
            artifact_ref: UUID of the artifact

        Returns:
            List of file paths relative to the artifact folder

        Raises:
            FileNotFoundError: If artifact doesn't exist
        """
        artifact_path = self._artifacts_dir / str(artifact_ref)

        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact not found: {artifact_ref}")

        files = []
        for root, _, filenames in os.walk(artifact_path):
            root_path = Path(root)
            for filename in filenames:
                file_path = root_path / filename
                files.append(file_path.relative_to(artifact_path))

        return sorted(files)

    def get_size(self, artifact_ref: UUID) -> int:
        """Get the total size of an artifact in bytes.

        Args:
            artifact_ref: UUID of the artifact

        Returns:
            Total size in bytes

        Raises:
            FileNotFoundError: If artifact doesn't exist
        """
        artifact_path = self._artifacts_dir / str(artifact_ref)

        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact not found: {artifact_ref}")

        total_size = 0
        for root, _, filenames in os.walk(artifact_path):
            root_path = Path(root)
            for filename in filenames:
                file_path = root_path / filename
                total_size += file_path.stat().st_size

        return total_size

    def write_file(
        self,
        artifact_ref: UUID,
        relative_path: str | Path,
        content: bytes,
    ) -> Path:
        """Write a file to an artifact folder.

        Args:
            artifact_ref: UUID of the artifact
            relative_path: Path relative to artifact folder
            content: File content as bytes

        Returns:
            Full path to the written file

        Raises:
            FileNotFoundError: If artifact doesn't exist
        """
        artifact_path = self._artifacts_dir / str(artifact_ref)

        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact not found: {artifact_ref}")

        file_path = artifact_path / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_bytes(content)

        logger.debug(
            "artifact.file_written",
            artifact_ref=str(artifact_ref),
            relative_path=str(relative_path),
            size=len(content),
        )

        return file_path

    def read_file(self, artifact_ref: UUID, relative_path: str | Path) -> bytes:
        """Read a file from an artifact folder.

        Args:
            artifact_ref: UUID of the artifact
            relative_path: Path relative to artifact folder

        Returns:
            File content as bytes

        Raises:
            FileNotFoundError: If artifact or file doesn't exist
        """
        artifact_path = self._artifacts_dir / str(artifact_ref)

        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact not found: {artifact_ref}")

        file_path = artifact_path / relative_path

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {relative_path}")

        return file_path.read_bytes()

    def delete_file(self, artifact_ref: UUID, relative_path: str | Path) -> bool:
        """Delete a file from an artifact folder.

        Args:
            artifact_ref: UUID of the artifact
            relative_path: Path relative to artifact folder

        Returns:
            True if file was deleted, False if it didn't exist

        Raises:
            FileNotFoundError: If artifact doesn't exist
        """
        artifact_path = self._artifacts_dir / str(artifact_ref)

        if not artifact_path.exists():
            raise FileNotFoundError(f"Artifact not found: {artifact_ref}")

        file_path = artifact_path / relative_path

        if not file_path.exists():
            return False

        file_path.unlink()

        logger.debug(
            "artifact.file_deleted",
            artifact_ref=str(artifact_ref),
            relative_path=str(relative_path),
        )

        return True


# Singleton instance for convenience
_default_manager: ArtifactManager | None = None


def get_artifact_manager(data_dir: Path | None = None) -> ArtifactManager:
    """Get the default artifact manager instance.

    Args:
        data_dir: Optional data directory override.
                 If provided, creates a new manager with that directory.
                 If not provided, returns the cached default manager.

    Returns:
        ArtifactManager instance
    """
    global _default_manager

    if data_dir is not None:
        return ArtifactManager(data_dir)

    if _default_manager is None:
        _default_manager = ArtifactManager()

    return _default_manager

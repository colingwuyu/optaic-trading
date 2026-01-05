"""Extension Loader - ZIP Parsing and Manifest Validation.

This service handles:
- Parsing uploaded ZIP archives containing Definition plugins
- Validating manifest.json schema and required fields
- Extracting files to artifact storage via ArtifactManager
- Returning LoadedPackage with module info for plugin registration

Manifest Schema (manifest.json):
{
  "name": "CustomPipeline",
  "version": "1.0.0",
  "definition_type": "PipelineDef",
  "module_file": "pipeline.py",
  "class_name": "CustomPipeline",
  "test_suite_file": "test_pipeline.py",  // optional
  "interface_spec": "libs.data.pipelines.base.BasePipeline",
  "category": "expression",
  "description": "Pipeline description",
  "input_schema": {...},  // optional
  "output_schema": {...},  // optional
  "parameters_schema": {...},  // optional
  "guardrail_contracts": [{...}],  // optional
  "dependencies": ["numpy>=1.20.0"]  // optional
}
"""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog

from libs.core.artifacts import ArtifactManager, get_artifact_manager

logger = structlog.get_logger(__name__)

# Supported definition types for upload
SUPPORTED_DEFINITION_TYPES = frozenset(
    {
        "PipelineDef",
        "StoreDef",
        "AccessorDef",
        "OpDef",
        "MLModuleDef",
        "PortfolioOptimizerDef",
    }
)

# Required fields in manifest.json
REQUIRED_MANIFEST_FIELDS = frozenset(
    {
        "name",
        "version",
        "definition_type",
        "module_file",
        "class_name",
        "interface_spec",
    }
)

# Maximum allowed ZIP file size (50 MB)
MAX_ZIP_SIZE_BYTES = 50 * 1024 * 1024

# Maximum number of files allowed in ZIP
MAX_FILES_IN_ZIP = 100

# Forbidden file extensions (security)
FORBIDDEN_EXTENSIONS = frozenset(
    {
        ".exe",
        ".dll",
        ".so",
        ".dylib",
        ".bat",
        ".cmd",
        ".sh",
        ".ps1",
        ".pyd",
        ".pyc",
        ".pyo",
    }
)


@dataclass
class ManifestData:
    """Parsed manifest.json contents."""

    name: str
    version: str
    definition_type: str
    module_file: str
    class_name: str
    interface_spec: str
    test_suite_file: str | None = None
    category: str | None = None
    description: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    parameters_schema: dict[str, Any] = field(default_factory=dict)
    guardrail_contracts: list[dict[str, Any]] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    raw_json: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ManifestData:
        """Create ManifestData from parsed JSON dict."""
        return cls(
            name=data["name"],
            version=data["version"],
            definition_type=data["definition_type"],
            module_file=data["module_file"],
            class_name=data["class_name"],
            interface_spec=data["interface_spec"],
            test_suite_file=data.get("test_suite_file"),
            category=data.get("category"),
            description=data.get("description"),
            input_schema=data.get("input_schema", {}),
            output_schema=data.get("output_schema", {}),
            parameters_schema=data.get("parameters_schema", {}),
            guardrail_contracts=data.get("guardrail_contracts", []),
            dependencies=data.get("dependencies", []),
            raw_json=data,
        )


@dataclass
class LoadedPackage:
    """Result of loading a plugin package."""

    artifact_ref: UUID
    manifest: ManifestData
    module_path: Path
    test_path: Path | None
    total_size_bytes: int
    file_count: int


class ExtensionLoaderError(Exception):
    """Base exception for extension loader errors."""

    pass


class ManifestValidationError(ExtensionLoaderError):
    """Raised when manifest.json validation fails."""

    def __init__(self, message: str, issues: list[str] | None = None):
        super().__init__(message)
        self.issues = issues or []


class ZipValidationError(ExtensionLoaderError):
    """Raised when ZIP file validation fails."""

    pass


class ExtensionLoader:
    """Loads and validates uploaded Definition plugin packages.

    Workflow:
    1. Validate ZIP archive (size, file count, extensions)
    2. Extract and parse manifest.json
    3. Validate manifest schema
    4. Verify referenced files exist in ZIP
    5. Extract files to artifact storage
    6. Return LoadedPackage with module info

    Usage:
        loader = ExtensionLoader()
        package = await loader.load_package(
            zip_content=upload.file.read(),
            artifact_ref=uuid4(),  # Optional - generates if not provided
        )
    """

    def __init__(
        self,
        artifact_manager: ArtifactManager | None = None,
        max_zip_size: int = MAX_ZIP_SIZE_BYTES,
        max_files: int = MAX_FILES_IN_ZIP,
    ) -> None:
        """Initialize the extension loader.

        Args:
            artifact_manager: ArtifactManager instance. Uses default if not provided.
            max_zip_size: Maximum allowed ZIP file size in bytes.
            max_files: Maximum number of files allowed in ZIP.
        """
        self._artifact_manager = artifact_manager or get_artifact_manager()
        self._max_zip_size = max_zip_size
        self._max_files = max_files

    def load_package(
        self,
        zip_content: bytes,
        artifact_ref: UUID | None = None,
        original_filename: str = "upload.zip",
    ) -> LoadedPackage:
        """Load and extract a plugin package from ZIP content.

        Args:
            zip_content: Raw ZIP file bytes
            artifact_ref: Optional artifact UUID. Generated if not provided.
            original_filename: Original filename for logging

        Returns:
            LoadedPackage with extracted info

        Raises:
            ZipValidationError: If ZIP validation fails
            ManifestValidationError: If manifest validation fails
        """
        logger.info(
            "extension_loader.loading",
            original_filename=original_filename,
            size_bytes=len(zip_content),
        )

        # Step 1: Validate ZIP size
        if len(zip_content) > self._max_zip_size:
            raise ZipValidationError(
                f"ZIP file too large: {len(zip_content)} bytes "
                f"(max: {self._max_zip_size} bytes)"
            )

        # Step 2: Open and validate ZIP structure
        try:
            zip_buffer = io.BytesIO(zip_content)
            with zipfile.ZipFile(zip_buffer, "r") as zf:
                return self._process_zip(zf, artifact_ref, original_filename)
        except zipfile.BadZipFile as e:
            raise ZipValidationError(f"Invalid ZIP file: {e}") from e

    def _process_zip(
        self,
        zf: zipfile.ZipFile,
        artifact_ref: UUID | None,
        original_filename: str,
    ) -> LoadedPackage:
        """Process an opened ZIP file.

        Args:
            zf: Open ZipFile object
            artifact_ref: Optional artifact UUID
            original_filename: Original filename

        Returns:
            LoadedPackage
        """
        # Validate file count
        file_list = zf.namelist()
        if len(file_list) > self._max_files:
            raise ZipValidationError(
                f"Too many files in ZIP: {len(file_list)} (max: {self._max_files})"
            )

        # Check for forbidden extensions
        issues = []
        for file_path in file_list:
            ext = Path(file_path).suffix.lower()
            if ext in FORBIDDEN_EXTENSIONS:
                issues.append(f"Forbidden file type: {file_path}")

        if issues:
            raise ZipValidationError(
                f"ZIP contains forbidden files: {', '.join(issues)}"
            )

        # Find and parse manifest.json
        manifest_path = self._find_manifest(file_list)
        if manifest_path is None:
            raise ManifestValidationError(
                "manifest.json not found in ZIP root or single subdirectory"
            )

        try:
            manifest_bytes = zf.read(manifest_path)
            manifest_dict = json.loads(manifest_bytes.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise ManifestValidationError(f"Invalid JSON in manifest.json: {e}") from e

        # Validate manifest
        manifest = self._validate_manifest(manifest_dict, file_list, manifest_path)

        # Determine base path (root or subdirectory)
        base_path = Path(manifest_path).parent

        # Create artifact and extract files
        artifact_ref = self._artifact_manager.create_artifact(artifact_ref)
        artifact_path = self._artifact_manager.get_path(artifact_ref)

        total_size = 0
        file_count = 0

        for file_info in zf.infolist():
            if file_info.is_dir():
                continue

            # Get path relative to base (manifest location)
            full_path = Path(file_info.filename)

            # Handle base_path being "." (root level) vs subdirectory
            if base_path == Path("."):
                # All files at root are included
                relative_path = full_path
            else:
                # Only include files under the base path (subdirectory)
                try:
                    if not full_path.is_relative_to(base_path):
                        continue
                    relative_path = full_path.relative_to(base_path)
                except ValueError:
                    continue

            # Skip manifest.json itself from extraction (we've already parsed it)
            if str(relative_path) == "manifest.json":
                continue

            # Extract file
            content = zf.read(file_info.filename)
            self._artifact_manager.write_file(artifact_ref, str(relative_path), content)

            total_size += len(content)
            file_count += 1

        # Build result
        module_path = artifact_path / manifest.module_file
        test_path = (
            artifact_path / manifest.test_suite_file
            if manifest.test_suite_file
            else None
        )

        logger.info(
            "extension_loader.loaded",
            artifact_ref=str(artifact_ref),
            name=manifest.name,
            definition_type=manifest.definition_type,
            file_count=file_count,
            total_size=total_size,
        )

        return LoadedPackage(
            artifact_ref=artifact_ref,
            manifest=manifest,
            module_path=module_path,
            test_path=test_path,
            total_size_bytes=total_size,
            file_count=file_count,
        )

    def _find_manifest(self, file_list: list[str]) -> str | None:
        """Find manifest.json in the ZIP file list.

        Looks for manifest.json in:
        1. Root of ZIP
        2. Single top-level subdirectory (e.g., custom_pipeline/manifest.json)

        Args:
            file_list: List of file paths in ZIP

        Returns:
            Path to manifest.json or None if not found
        """
        # Check root
        if "manifest.json" in file_list:
            return "manifest.json"

        # Check for single top-level directory
        top_level_dirs = set()
        for path in file_list:
            parts = Path(path).parts
            if len(parts) > 1:
                top_level_dirs.add(parts[0])

        if len(top_level_dirs) == 1:
            subdir = top_level_dirs.pop()
            manifest_in_subdir = f"{subdir}/manifest.json"
            if manifest_in_subdir in file_list:
                return manifest_in_subdir

        return None

    def _validate_manifest(
        self,
        data: dict[str, Any],
        file_list: list[str],
        manifest_path: str,
    ) -> ManifestData:
        """Validate manifest.json content.

        Args:
            data: Parsed manifest JSON
            file_list: List of files in ZIP
            manifest_path: Path to manifest.json (for relative file resolution)

        Returns:
            Validated ManifestData

        Raises:
            ManifestValidationError: If validation fails
        """
        issues: list[str] = []

        # Check required fields
        for req_field in REQUIRED_MANIFEST_FIELDS:
            if req_field not in data:
                issues.append(f"Missing required field: {req_field}")
            elif not data[req_field]:
                issues.append(f"Empty required field: {req_field}")

        if issues:
            raise ManifestValidationError(
                f"Manifest validation failed: {len(issues)} issues",
                issues=issues,
            )

        # Validate definition_type
        definition_type = data["definition_type"]
        if definition_type not in SUPPORTED_DEFINITION_TYPES:
            issues.append(
                f"Unsupported definition_type: {definition_type}. "
                f"Supported: {', '.join(sorted(SUPPORTED_DEFINITION_TYPES))}"
            )

        # Determine base path for file validation
        base_path = Path(manifest_path).parent

        # Validate module_file exists
        module_file = data["module_file"]
        if base_path == Path("."):
            expected_module_path = module_file
        else:
            expected_module_path = f"{base_path}/{module_file}"

        if expected_module_path not in file_list:
            issues.append(f"Module file not found in ZIP: {module_file}")

        # Validate test_suite_file exists (if specified)
        test_suite_file = data.get("test_suite_file")
        if test_suite_file:
            if base_path == Path("."):
                expected_test_path = test_suite_file
            else:
                expected_test_path = f"{base_path}/{test_suite_file}"

            if expected_test_path not in file_list:
                issues.append(f"Test suite file not found in ZIP: {test_suite_file}")

        # Validate class_name format (Python identifier)
        class_name = data["class_name"]
        if not class_name.isidentifier():
            issues.append(
                f"Invalid class_name (not a valid Python identifier): {class_name}"
            )

        # Validate version format (semantic versioning-like)
        version = data["version"]
        if not self._is_valid_version(version):
            issues.append(f"Invalid version format: {version}")

        if issues:
            raise ManifestValidationError(
                f"Manifest validation failed: {len(issues)} issues",
                issues=issues,
            )

        return ManifestData.from_dict(data)

    def _is_valid_version(self, version: str) -> bool:
        """Check if version string is valid (loose semver).

        Accepts formats like: 1.0.0, 1.0, 0.1.0-alpha, 2.0.0+build.123

        Args:
            version: Version string

        Returns:
            True if valid
        """
        if not version:
            return False

        # Basic check: starts with digit and contains at least one dot
        parts = version.split(".")
        if len(parts) < 2:
            return False

        # First part should be numeric (or numeric with prefix/suffix)
        try:
            int(parts[0])
            return True
        except ValueError:
            return False


# Singleton instance for convenience
_default_loader: ExtensionLoader | None = None


def get_extension_loader() -> ExtensionLoader:
    """Get the default extension loader instance.

    Returns:
        ExtensionLoader instance
    """
    global _default_loader

    if _default_loader is None:
        _default_loader = ExtensionLoader()

    return _default_loader

"""Config Store Implementation.

Reads configuration data from YAML files.
Ported from optaic-v0/data/store/config.py.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from libs.data.registry import register_store
from libs.data.store.base import BaseStore

if TYPE_CHECKING:
    import pandas as pd


@register_store("ConfigStore")
class ConfigStore(BaseStore):
    """Config store for reading YAML configuration files.

    Used for static configuration data like contract specs,
    universe definitions, and other reference data.

    Config Options:
    - file_path: Path to YAML file (absolute or relative)
    - config_file: Alternative to file_path
    - key: Optional key to extract from YAML structure

    Returns:
    - dict or list depending on YAML structure
    """

    def _resolve_path(self) -> Path | None:
        """Resolve the config file path."""
        # Try file_path first (can be absolute)
        file_path = self.config.get("file_path")
        if file_path:
            path = Path(file_path)
            if path.is_absolute() and path.exists():
                return path
            # Try relative to data_dir
            rel_path = self.data_dir / path
            if rel_path.exists():
                return rel_path
            if path.is_absolute():
                return path

        # Fall back to config_file
        file_name = self.config.get("config_file")
        if not file_name:
            return None

        # Try relative to config_dir first
        config_dir = self.config.get("config_dir") or self.data_dir / "config"
        path = Path(config_dir) / file_name
        if path.exists():
            return path

        # Try relative to data_dir
        path = self.data_dir / file_name
        if path.exists():
            return path

        # Try absolute path
        abs_path = Path(file_name)
        if abs_path.exists():
            return abs_path

        return None

    def read(
        self,
        start_date: date | None = None,
        end_date: date | None = None,
        columns: list[str] | None = None,
        **kwargs: Any,
    ) -> "pd.DataFrame | dict | list | None":
        """Read configuration from YAML file.

        Args:
            start_date: Not used for config files
            end_date: Not used for config files
            columns: Not used for config files
            **kwargs: Additional arguments

        Returns:
            Dict, list, or DataFrame depending on config structure
        """
        import yaml

        path = self._resolve_path()
        if path is None or not path.exists():
            return None

        with open(path) as f:
            data = yaml.safe_load(f)

        # Extract key if specified
        key = self.config.get("key")
        if key and isinstance(data, dict):
            data = data.get(key)

        return data

    def write(
        self,
        data: "pd.DataFrame | dict | list",
        mode: str = "overwrite",
        **kwargs: Any,
    ) -> int:
        """Write is not supported for config store."""
        raise NotImplementedError("ConfigStore is read-only. Cannot write to config files.")

    def exists(self) -> bool:
        """Check if config file exists."""
        path = self._resolve_path()
        return path is not None and path.exists()

    def get_columns(self) -> list[str]:
        """Get keys if config is a dict."""
        data = self.read()
        if isinstance(data, dict):
            return list(data.keys())
        return []

    def get_row_count(self) -> int:
        """Get item count."""
        data = self.read()
        if isinstance(data, (dict, list)):
            return len(data)
        return 0 if data is None else 1

    def get_storage_path(self) -> Path | None:
        """Get the config file path."""
        return self._resolve_path()

    def delete(self) -> None:
        """Delete is not supported for config store."""
        raise NotImplementedError("ConfigStore is read-only. Cannot delete config files.")

    def clear(self) -> None:
        """Clear is not supported for config store."""
        raise NotImplementedError("ConfigStore is read-only. Cannot clear config files.")

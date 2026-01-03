from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal
import os
import tomllib

from optaic.paths import default_data_dir

_DATA_DIR_ENV = "OPTAIC_DATA_DIR"


@dataclass
class PrefectConfig:
    """Configuration for Prefect orchestration engine."""

    enabled: bool = False
    bind_host: str = "127.0.0.1"  # localhost only by default (secure)
    port: int = 4200
    api_url: str = ""  # if set, use remote mode
    home_dir: Path | None = None  # defaults to DATA_DIR/engines/prefect/home
    work_pool: str = "optaic-process"
    worker_limit: int = 4

    @property
    def mode(self) -> Literal["disabled", "local", "remote"]:
        """Determine mode based on enabled flag and api_url."""
        if not self.enabled:
            return "disabled"
        if self.api_url:
            return "remote"
        return "local"

    @property
    def is_local_mode(self) -> bool:
        """True if we need to start a local Prefect server."""
        return self.enabled and not self.api_url

    @property
    def effective_api_url(self) -> str:
        """Return the API URL (computed for local, provided for remote)."""
        if self.api_url:
            return self.api_url
        return f"http://{self.bind_host}:{self.port}/api"

    def get_security_warnings(self) -> list[str]:
        """Return list of security warnings for this configuration."""
        warnings: list[str] = []
        if self.enabled and self.bind_host in ("0.0.0.0", "::"):
            warnings.append(
                "SECURITY WARNING: Prefect is bound to all interfaces "
                f"({self.bind_host}). This exposes the server to the network. "
                "Use 127.0.0.1 for localhost-only access."
            )
        return warnings


@dataclass
class MlflowConfig:
    """Configuration for MLflow tracking/registry engine."""

    enabled: bool = False
    bind_host: str = "127.0.0.1"  # localhost only by default (secure)
    port: int = 5000
    tracking_uri: str = ""  # if set, use remote mode
    backend_store_uri: str = ""  # defaults to sqlite in DATA_DIR/engines/mlflow/backend
    artifacts_mode: Literal["direct", "proxied"] = "direct"
    default_artifact_root: Path | None = (
        None  # defaults to DATA_DIR/engines/mlflow/artifacts
    )

    @property
    def mode(self) -> Literal["disabled", "local", "remote"]:
        """Determine mode based on enabled flag and tracking_uri."""
        if not self.enabled:
            return "disabled"
        if self.tracking_uri:
            return "remote"
        return "local"

    @property
    def is_local_mode(self) -> bool:
        """True if we need to start a local MLflow server."""
        return self.enabled and not self.tracking_uri

    @property
    def effective_tracking_uri(self) -> str:
        """Return the tracking URI (computed for local, provided for remote)."""
        if self.tracking_uri:
            return self.tracking_uri
        return f"http://{self.bind_host}:{self.port}"

    def get_security_warnings(self) -> list[str]:
        """Return list of security warnings for this configuration."""
        warnings: list[str] = []
        if self.enabled and self.bind_host in ("0.0.0.0", "::"):
            warnings.append(
                "SECURITY WARNING: MLflow is bound to all interfaces "
                f"({self.bind_host}). This exposes the server to the network. "
                "Use 127.0.0.1 for localhost-only access."
            )
        return warnings


@dataclass
class RuntimeConfig:
    data_dir: Path
    prefect: PrefectConfig
    mlflow: MlflowConfig
    config_path: Path | None = None

    def as_dict(self, *, redact: bool = False) -> dict[str, object]:
        payload = {
            "data_dir": str(self.data_dir),
            "prefect": {
                "enabled": self.prefect.enabled,
                "mode": self.prefect.mode,
                "bind_host": self.prefect.bind_host,
                "port": self.prefect.port,
                "api_url": self.prefect.api_url,
                "effective_api_url": self.prefect.effective_api_url,
                "home_dir": str(self.prefect.home_dir) if self.prefect.home_dir else "",
                "work_pool": self.prefect.work_pool,
                "worker_limit": self.prefect.worker_limit,
            },
            "mlflow": {
                "enabled": self.mlflow.enabled,
                "mode": self.mlflow.mode,
                "bind_host": self.mlflow.bind_host,
                "port": self.mlflow.port,
                "tracking_uri": self.mlflow.tracking_uri,
                "effective_tracking_uri": self.mlflow.effective_tracking_uri,
                "backend_store_uri": self.mlflow.backend_store_uri,
                "artifacts_mode": self.mlflow.artifacts_mode,
                "default_artifact_root": (
                    str(self.mlflow.default_artifact_root)
                    if self.mlflow.default_artifact_root
                    else ""
                ),
            },
        }
        if redact:
            _redact_payload(payload)
        return payload

    def get_security_warnings(self) -> list[str]:
        """Collect all security warnings from engine configs."""
        warnings: list[str] = []
        warnings.extend(self.prefect.get_security_warnings())
        warnings.extend(self.mlflow.get_security_warnings())
        return warnings


def load_runtime_config(*, data_dir: Path | None = None) -> RuntimeConfig:
    config_path = _resolve_config_path()
    config_payload = _load_toml(config_path)

    file_data_dir = config_payload.get("data_dir")
    env_data_dir = os.environ.get(_DATA_DIR_ENV)
    resolved_data_dir = _resolve_data_dir(
        cli_value=data_dir,
        env_value=env_data_dir,
        file_value=file_data_dir,
        base_path=config_path.parent if config_path else Path.cwd(),
    )

    if config_path is None:
        candidate = resolved_data_dir / "optaic.toml"
        if candidate.exists():
            config_path = candidate
            config_payload = _load_toml(candidate)
            if data_dir is None and env_data_dir is None:
                file_value = config_payload.get("data_dir")
                if file_value:
                    resolved_data_dir = _resolve_data_dir(
                        cli_value=None,
                        env_value=None,
                        file_value=file_value,
                        base_path=candidate.parent,
                    )

    prefect_payload = _section(config_payload, "prefect")
    mlflow_payload = _section(config_payload, "mlflow")

    prefect_home_raw = prefect_payload.get("home_dir")
    if isinstance(prefect_home_raw, str):
        prefect_home_raw = _resolve_placeholders(prefect_home_raw, resolved_data_dir)
    prefect = PrefectConfig(
        enabled=_coerce_bool(prefect_payload.get("enabled"), default=False),
        bind_host=str(prefect_payload.get("bind_host") or "127.0.0.1"),
        port=_coerce_int(prefect_payload.get("port"), default=4200),
        api_url=str(prefect_payload.get("api_url") or ""),
        home_dir=_coerce_path(
            prefect_home_raw,
            resolved_data_dir / "engines" / "prefect" / "home",
            base_path=config_path.parent if config_path else Path.cwd(),
        ),
        work_pool=str(prefect_payload.get("work_pool") or "optaic-process"),
        worker_limit=_coerce_int(prefect_payload.get("worker_limit"), default=4),
    )

    mlflow_artifact_raw = mlflow_payload.get("default_artifact_root")
    if isinstance(mlflow_artifact_raw, str):
        mlflow_artifact_raw = _resolve_placeholders(
            mlflow_artifact_raw,
            resolved_data_dir,
        )
    mlflow = MlflowConfig(
        enabled=_coerce_bool(mlflow_payload.get("enabled"), default=False),
        bind_host=str(mlflow_payload.get("bind_host") or "127.0.0.1"),
        port=_coerce_int(mlflow_payload.get("port"), default=5000),
        tracking_uri=str(mlflow_payload.get("tracking_uri") or ""),
        backend_store_uri=str(mlflow_payload.get("backend_store_uri") or ""),
        artifacts_mode=_normalize_artifacts_mode(mlflow_payload.get("artifacts_mode")),
        default_artifact_root=_coerce_path(
            mlflow_artifact_raw,
            resolved_data_dir / "engines" / "mlflow" / "artifacts",
            base_path=config_path.parent if config_path else Path.cwd(),
        ),
    )

    _apply_env_overrides(prefect, mlflow)

    if prefect.home_dir is None:
        prefect.home_dir = resolved_data_dir / "engines" / "prefect" / "home"
    if not mlflow.backend_store_uri:
        backend_path = (
            resolved_data_dir / "engines" / "mlflow" / "backend" / "mlflow.db"
        )
        mlflow.backend_store_uri = _sqlite_uri_for(backend_path)
    if mlflow.default_artifact_root is None:
        mlflow.default_artifact_root = (
            resolved_data_dir / "engines" / "mlflow" / "artifacts"
        )

    prefect.api_url = _resolve_placeholders(prefect.api_url, resolved_data_dir)
    mlflow.tracking_uri = _resolve_placeholders(mlflow.tracking_uri, resolved_data_dir)
    mlflow.backend_store_uri = _resolve_placeholders(
        mlflow.backend_store_uri, resolved_data_dir
    )

    return RuntimeConfig(
        data_dir=resolved_data_dir,
        prefect=prefect,
        mlflow=mlflow,
        config_path=config_path,
    )


def _resolve_config_path() -> Path | None:
    env_override = os.environ.get("OPTAIC_CONFIG_PATH")
    if env_override:
        candidate = Path(env_override).expanduser()
        if candidate.exists():
            return candidate
    cwd_path = Path.cwd() / "optaic.toml"
    if cwd_path.exists():
        return cwd_path
    return None


def _load_toml(path: Path | None) -> dict[str, object]:
    if path is None or not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _section(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    if isinstance(value, dict):
        return value
    return {}


def _resolve_data_dir(
    *,
    cli_value: Path | None,
    env_value: str | None,
    file_value: object,
    base_path: Path,
) -> Path:
    if cli_value is not None:
        return Path(cli_value).expanduser()
    if env_value:
        return Path(env_value).expanduser()
    if isinstance(file_value, str) and file_value.strip():
        candidate = Path(file_value).expanduser()
        if not candidate.is_absolute():
            candidate = (base_path / candidate).resolve()
        return candidate
    return default_data_dir()


def _apply_env_overrides(prefect: PrefectConfig, mlflow: MlflowConfig) -> None:
    prefect.enabled = _env_bool("OPTAIC_PREFECT_ENABLED", prefect.enabled)
    prefect.bind_host = _env_str("OPTAIC_PREFECT_BIND_HOST", prefect.bind_host)
    prefect.port = _env_int("OPTAIC_PREFECT_PORT", prefect.port)
    prefect.api_url = _env_str("OPTAIC_PREFECT_API_URL", prefect.api_url)
    prefect.api_url = _env_str("PREFECT_API_URL", prefect.api_url)
    prefect.home_dir = _env_path("OPTAIC_PREFECT_HOME_DIR", prefect.home_dir)
    prefect.home_dir = _env_path("PREFECT_HOME", prefect.home_dir)
    prefect.work_pool = _env_str("OPTAIC_PREFECT_WORK_POOL", prefect.work_pool)
    prefect.worker_limit = _env_int(
        "OPTAIC_PREFECT_WORKER_LIMIT",
        prefect.worker_limit,
    )

    mlflow.enabled = _env_bool("OPTAIC_MLFLOW_ENABLED", mlflow.enabled)
    mlflow.bind_host = _env_str("OPTAIC_MLFLOW_BIND_HOST", mlflow.bind_host)
    mlflow.port = _env_int("OPTAIC_MLFLOW_PORT", mlflow.port)
    mlflow.tracking_uri = _env_str(
        "OPTAIC_MLFLOW_TRACKING_URI",
        mlflow.tracking_uri,
    )
    mlflow.tracking_uri = _env_str("MLFLOW_TRACKING_URI", mlflow.tracking_uri)
    mlflow.backend_store_uri = _env_str(
        "OPTAIC_MLFLOW_BACKEND_STORE_URI",
        mlflow.backend_store_uri,
    )
    mlflow.artifacts_mode = _normalize_artifacts_mode(
        _env_str("OPTAIC_MLFLOW_ARTIFACTS_MODE", mlflow.artifacts_mode)
    )
    mlflow.default_artifact_root = _env_path(
        "OPTAIC_MLFLOW_DEFAULT_ARTIFACT_ROOT",
        mlflow.default_artifact_root,
    )


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    if value is None:
        return default
    return value


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def _env_path(name: str, default: Path | None) -> Path | None:
    value = os.environ.get(name)
    if value is None:
        return default
    return Path(value).expanduser()


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return default


def _coerce_int(value: object, *, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _coerce_path(
    value: object,
    fallback: Path,
    *,
    base_path: Path,
) -> Path:
    if isinstance(value, str) and value.strip():
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = (base_path / candidate).resolve()
        return candidate
    return fallback


def _normalize_artifacts_mode(value: object) -> Literal["direct", "proxied"]:
    if isinstance(value, str) and value.lower() == "proxied":
        return "proxied"
    return "direct"


def _resolve_placeholders(value: str, data_dir: Path) -> str:
    if not value:
        return value
    resolved = value.replace("<DATA_DIR>", data_dir.as_posix())
    resolved = resolved.replace("${DATA_DIR}", data_dir.as_posix())
    return resolved


def _sqlite_uri_for(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def _redact_payload(payload: dict[str, object]) -> None:
    sensitive_keys = {"secret", "token", "password", "key"}
    for section_value in payload.values():
        if not isinstance(section_value, dict):
            continue
        for key, value in list(section_value.items()):
            lowered = key.lower()
            if any(part in lowered for part in sensitive_keys):
                section_value[key] = "*****"
            elif isinstance(value, str) and "@" in value and "://" in value:
                section_value[key] = _redact_uri(value)


def _redact_uri(value: str) -> str:
    try:
        from urllib.parse import urlsplit, urlunsplit
    except Exception:
        return value
    parts = urlsplit(value)
    if not parts.username and not parts.password:
        return value
    netloc = parts.hostname or ""
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))

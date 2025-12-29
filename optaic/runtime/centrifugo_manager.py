from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tarfile
import tempfile
import time
import urllib.request
import zipfile

from optaic.runtime.infra_manifest import (
    get_asset,
    get_default_version,
    load_manifest,
)

DEFAULT_CENTRIFUGO_VERSION = "6.1.0"


@dataclass(frozen=True)
class CentrifugoConfig:
    data_dir: Path
    port: int
    api_key: str
    token_secret: str
    allowed_origins: list[str]
    redis_url: str | None = None
    host: str = "127.0.0.1"

    @property
    def http_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def config_path(self) -> Path:
        return self.data_dir / "centrifugo" / "config.json"


class CentrifugoManager:
    def __init__(
        self,
        config: CentrifugoConfig,
        version: str,
        binary_path: Path | None = None,
    ) -> None:
        self.config = config
        self.version = version
        self.process: subprocess.Popen | None = None
        self.binary_path = binary_path or ensure_centrifugo_binary(
            version,
            config.data_dir,
        )

    def start(
        self,
        *,
        stdout: int | None = None,
        stderr: int | None = None,
        wait: bool = True,
    ) -> subprocess.Popen:
        config_path = write_centrifugo_config(self.config)
        cmd = [str(self.binary_path), "--config", str(config_path)]
        self.process = subprocess.Popen(
            cmd,
            cwd=str(self.config.data_dir),
            env=_centrifugo_env(),
            stdout=stdout,
            stderr=stderr,
            text=stdout is not None or stderr is not None,
        )
        if wait:
            wait_until_ready(self.config.http_url)
        return self.process

    def stop(self) -> None:
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()


def ensure_centrifugo_binary(version: str, data_dir: Path) -> Path:
    override = os.environ.get("OPTAIC_CENTRIFUGO_PATH")
    exe_name = "centrifugo.exe" if os.name == "nt" else "centrifugo"

    if override:
        override_path = Path(override).expanduser()
        if override_path.is_dir():
            override_path = override_path / exe_name
        if not override_path.exists():
            raise FileNotFoundError(
                f"OPTAIC_CENTRIFUGO_PATH not found: {override_path}"
            )
        return override_path

    bin_dir = data_dir / "bin" / "centrifugo" / version
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / exe_name
    if target.exists():
        return target

    legacy = data_dir / "bin" / f"centrifugo-{version}{'.exe' if os.name == 'nt' else ''}"
    if legacy.exists():
        shutil.copy2(legacy, target)
        return target

    manifest = load_manifest()
    desired_version = get_default_version(manifest, "centrifugo")
    if version != desired_version:
        raise RuntimeError(
            f"Centrifugo version {version} not in manifest (expected {desired_version})."
        )
    asset_key = _platform_key()
    asset = get_asset(manifest, "centrifugo", asset_key)
    asset_name = Path(asset["url"]).name
    archive_ext = _archive_ext(asset_name)
    downloads_dir = data_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    archive_path = downloads_dir / asset_name
    if not archive_path.exists():
        _download(asset["url"], archive_path)
    _verify_checksum(asset["sha256"], archive_path)

    _extract_binary(archive_path, archive_ext, exe_name, target)
    if os.name != "nt":
        target.chmod(target.stat().st_mode | 0o111)
    return target


def write_centrifugo_config(config: CentrifugoConfig) -> Path:
    config_path = config.config_path
    config_path.parent.mkdir(parents=True, exist_ok=True)
    engine: dict[str, object] = {"type": "memory"}
    if config.redis_url:
        engine = {"type": "redis", "redis_address": config.redis_url}
    payload = {
        "http_server": {"address": config.host, "port": config.port},
        "engine": engine,
        "http_api": {"key": config.api_key, "handler_prefix": "/api", "disabled": False},
        "client": {
            "allowed_origins": config.allowed_origins,
            "token": {"hmac_secret_key": config.token_secret},
            "subscription_token": {
                "enabled": True,
                "hmac_secret_key": config.token_secret,
            },
        },
        "health": {"enabled": True, "handler_prefix": "/health"},
        "admin": {"enabled": False},
    }
    config_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return config_path


def wait_until_ready(http_url: str, timeout_seconds: float = 20.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    health_url = f"{http_url.rstrip('/')}/health"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(health_url, timeout=2) as response:
                if response.status == 200:
                    return
            time.sleep(0.5)
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("Centrifugo did not become ready in time.")


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest.with_suffix(dest.suffix + ".tmp")
    request = urllib.request.Request(url, headers={"User-Agent": "optaic"})
    with urllib.request.urlopen(request) as response, open(temp_path, "wb") as handle:
        shutil.copyfileobj(response, handle)
    temp_path.replace(dest)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_checksum(expected: str, archive_path: Path) -> None:
    actual = _sha256(archive_path)
    if actual.lower() != expected.lower():
        raise RuntimeError(
            f"Centrifugo checksum mismatch: {actual} != {expected}"
        )


def _extract_binary(
    archive_path: Path,
    archive_ext: str,
    exe_name: str,
    target_path: Path,
) -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        if archive_ext == "zip":
            with zipfile.ZipFile(archive_path) as archive:
                member = _find_member(archive.namelist(), exe_name)
                if member is None:
                    raise FileNotFoundError("Centrifugo binary not found in zip.")
                archive.extract(member, temp_dir)
                source = Path(temp_dir) / member
        else:
            with tarfile.open(archive_path, "r:gz") as archive:
                member = _find_member(
                    [item.name for item in archive.getmembers()],
                    exe_name,
                )
                if member is None:
                    raise FileNotFoundError("Centrifugo binary not found in tar.")
                archive.extract(member, temp_dir)
                source = Path(temp_dir) / member

        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target_path))


def _find_member(members: list[str], exe_name: str) -> str | None:
    for name in members:
        if name.endswith(exe_name):
            return name
    return None


def _archive_ext(asset_name: str) -> str:
    if asset_name.endswith(".zip"):
        return "zip"
    if asset_name.endswith(".tar.gz"):
        return "tar.gz"
    raise RuntimeError(f"Unsupported archive format: {asset_name}")


def _platform_key() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system.startswith("win"):
        os_name = "windows"
    elif system == "darwin":
        os_name = "darwin"
    elif system == "linux":
        os_name = "linux"
    else:
        raise RuntimeError(f"Unsupported platform: {platform.system()}")

    if machine in {"x86_64", "amd64"}:
        arch = "amd64"
    elif machine in {"aarch64", "arm64"}:
        arch = "arm64"
    else:
        raise RuntimeError(f"Unsupported architecture: {platform.machine()}")

    return f"{os_name}_{arch}"


def _centrifugo_env() -> dict[str, str]:
    env = os.environ.copy()
    for key in list(env):
        if key.startswith("CENTRIFUGO_"):
            env.pop(key, None)
    return env

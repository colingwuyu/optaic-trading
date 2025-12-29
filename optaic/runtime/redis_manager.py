from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
import zipfile
from typing import Literal

from optaic.paths import resolve_data_dir
from optaic.runtime.infra_manifest import get_asset, get_default_version, load_manifest

RedisMode = Literal["disabled", "external", "embedded"]

DEFAULT_REDIS_VERSION = "8.4.0"
DEFAULT_REDIS_FLAVOR = "msys2"

_REDIS_PROCESS: subprocess.Popen | None = None
_REDIS_CLI_PATH: Path | None = None
_REDIS_URL: str | None = None


def resolve_redis_mode(
    with_redis: bool,
    redis_url: str | None,
    is_windows: bool,
) -> RedisMode:
    if not with_redis:
        return "disabled"
    if redis_url:
        return "external"
    if is_windows:
        return "embedded"
    raise RuntimeError(
        "Redis requested on non-Windows without --redis-url or OPTAIC_REDIS_URL."
    )


def start_redis(
    with_redis: bool,
    redis_url: str | None,
    bind: str,
    port: int,
    version: str,
    flavor: str,
    *,
    stdout: int | None = None,
    stderr: int | None = None,
) -> str | None:
    global _REDIS_PROCESS, _REDIS_CLI_PATH, _REDIS_URL

    if _REDIS_PROCESS and _REDIS_PROCESS.poll() is None:
        return _REDIS_URL

    mode = resolve_redis_mode(with_redis, redis_url, os.name == "nt")
    if mode == "disabled":
        _REDIS_URL = None
        return None
    if mode == "external":
        if not redis_url:
            raise RuntimeError("Redis URL is required for external Redis.")
        return redis_url

    data_dir = resolve_data_dir()
    if _is_port_open(bind, port):
        _REDIS_URL = _default_redis_url(bind, port)
        return _REDIS_URL

    server_path, cli_path = ensure_redis_binary(version, flavor, data_dir)
    conf_path = write_redis_conf(data_dir, bind, port)
    conf_arg = _redis_conf_arg(data_dir, conf_path)
    process = subprocess.Popen(
        [str(server_path), conf_arg],
        cwd=str(data_dir),
        stdout=stdout,
        stderr=stderr,
        text=stdout is not None or stderr is not None,
    )
    _wait_for_port(bind, port, timeout_seconds=10)
    _REDIS_PROCESS = process
    _REDIS_CLI_PATH = cli_path
    _REDIS_URL = _default_redis_url(bind, port)
    return _REDIS_URL


def stop_redis(timeout_seconds: float = 5) -> None:
    global _REDIS_PROCESS, _REDIS_CLI_PATH, _REDIS_URL
    if _REDIS_PROCESS is None:
        return

    host, port = _redis_host_port(_REDIS_URL or "")
    if _REDIS_CLI_PATH and _REDIS_CLI_PATH.exists():
        try:
            subprocess.run(
                [
                    str(_REDIS_CLI_PATH),
                    "-h",
                    host,
                    "-p",
                    str(port),
                    "shutdown",
                    "nosave",
                ],
                check=False,
                timeout=timeout_seconds,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

    try:
        _REDIS_PROCESS.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _REDIS_PROCESS.terminate()
        try:
            _REDIS_PROCESS.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _REDIS_PROCESS.kill()

    _REDIS_PROCESS = None
    _REDIS_CLI_PATH = None
    _REDIS_URL = None
    _REDIS_URL = None


def redis_process() -> subprocess.Popen | None:
    return _REDIS_PROCESS


def ensure_redis_binary(
    version: str,
    flavor: str,
    data_dir: Path,
) -> tuple[Path, Path]:
    if os.name != "nt":
        raise RuntimeError("Redis auto-download is only supported on Windows.")

    manifest = load_manifest()
    desired_version = get_default_version(manifest, "redis_windows")
    if version != desired_version:
        raise RuntimeError(
            f"Redis version {version} not in manifest (expected {desired_version})."
        )
    asset_key = f"windows_amd64_{flavor}"
    asset = get_asset(manifest, "redis_windows", asset_key)
    asset_name = Path(asset["url"]).name
    expected_sha = asset["sha256"]
    downloads_dir = data_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    archive_path = downloads_dir / asset_name
    if not archive_path.exists():
        _download(asset["url"], archive_path)
    if not verify_sha256(archive_path, expected_sha):
        raise RuntimeError(f"Redis checksum mismatch for {asset_name}")

    target_dir = data_dir / "bin" / "redis" / version
    server_path = _find_binary(target_dir, "redis-server.exe")
    cli_path = _find_binary(target_dir, "redis-cli.exe")
    if server_path and cli_path:
        return server_path, cli_path

    _extract_archive(archive_path, target_dir)
    server_path = _find_binary(target_dir, "redis-server.exe")
    cli_path = _find_binary(target_dir, "redis-cli.exe")
    if not server_path or not cli_path:
        raise FileNotFoundError("Redis binaries not found after extraction.")
    return server_path, cli_path


def write_redis_conf(data_dir: Path, bind: str, port: int) -> Path:
    redis_dir = data_dir / "redis"
    data_path = redis_dir / "data"
    redis_dir.mkdir(parents=True, exist_ok=True)
    data_path.mkdir(parents=True, exist_ok=True)

    conf_path = redis_dir / "redis.conf"
    conf_lines = [
        f"bind {bind}",
        f"port {port}",
        f"dir {data_path}",
        f"logfile {redis_dir / 'redis.log'}",
        'save ""',
        "appendonly no",
    ]
    conf_path.write_text("\n".join(conf_lines) + "\n", encoding="utf-8")
    return conf_path


def check_redis(redis_url: str, timeout_seconds: float = 2.0) -> tuple[str, str | None]:
    try:
        import redis
    except Exception as exc:
        return f"error: redis import failed ({exc})", None

    try:
        client = redis.from_url(
            redis_url,
            socket_timeout=timeout_seconds,
            socket_connect_timeout=timeout_seconds,
            decode_responses=True,
        )
        client.ping()
        info = client.info(section="server")
        version = info.get("redis_version") if isinstance(info, dict) else None
        return "ok", version
    except Exception as exc:
        return f"error: {exc}", None


def verify_sha256(path: Path, expected_hex: str) -> bool:
    actual = sha256_digest(path)
    return actual.lower() == expected_hex.lower()


def sha256_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()




def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest.with_suffix(dest.suffix + ".tmp")
    request = urllib.request.Request(url, headers={"User-Agent": "optaic"})
    with urllib.request.urlopen(request) as response, open(temp_path, "wb") as handle:
        shutil.copyfileobj(response, handle)
    temp_path.replace(dest)


def _extract_archive(archive_path: Path, target_dir: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        with tempfile.TemporaryDirectory() as temp_dir:
            archive.extractall(temp_dir)
            root = _archive_root(Path(temp_dir))
            target_dir.mkdir(parents=True, exist_ok=True)
            shutil.copytree(root, target_dir, dirs_exist_ok=True)


def _archive_root(temp_dir: Path) -> Path:
    entries = list(temp_dir.iterdir())
    if len(entries) == 1 and entries[0].is_dir():
        return entries[0]
    return temp_dir


def _find_binary(root: Path, name: str) -> Path | None:
    if not root.exists():
        return None
    for candidate in root.rglob(name):
        if candidate.is_file():
            return candidate
    return None


def _redis_conf_arg(data_dir: Path, conf_path: Path) -> str:
    try:
        return conf_path.relative_to(data_dir).as_posix()
    except ValueError:
        return str(conf_path)


def _default_redis_url(bind: str, port: int) -> str:
    return f"redis://{bind}:{port}/0"


def _redis_host_port(redis_url: str) -> tuple[str, int]:
    parsed = urllib.parse.urlparse(redis_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 6379
    return host, port


def _is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _wait_for_port(host: str, port: int, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if _is_port_open(host, port):
            return
        time.sleep(0.25)
    raise RuntimeError("Redis did not start in time.")

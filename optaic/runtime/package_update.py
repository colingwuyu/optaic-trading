from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request

from packaging.version import Version

from optaic.version import get_version

PYPI_BASE_URL = "https://pypi.org/pypi"


def check_pypi_latest(
    package_name: str = "optaic",
    *,
    current_version: str | None = None,
    timeout_seconds: float = 5.0,
) -> dict[str, object]:
    current = current_version or get_version()
    payload = _fetch_json(f"{PYPI_BASE_URL}/{package_name}/json", timeout_seconds)
    info = payload.get("info") or {}
    latest = info.get("version")
    if not latest:
        raise RuntimeError("Unable to determine latest version from PyPI.")
    has_update = _is_newer_version(latest, current)
    return {
        "package": package_name,
        "current_version": current,
        "latest_version": latest,
        "has_update": has_update,
        "source": "pypi",
        "checked_at": _utc_now(),
    }


def list_available_versions(index_url: str, package_name: str) -> list[Version]:
    if not index_url:
        raise ValueError("index_url is required")
    normalized = _normalize_package_name(package_name)
    project_url = _simple_project_url(index_url, normalized)
    html = _fetch_text(project_url, timeout_seconds=5.0)
    versions: set[Version] = set()
    for href in _extract_links(html):
        filename = _link_filename(href)
        version = _extract_version_from_filename(filename, normalized)
        if not version:
            continue
        try:
            versions.add(Version(version))
        except Exception:
            continue
    return sorted(versions)


def download_wheel_from_index(
    index_url: str,
    package_name: str,
    version: str,
    dest_dir: Path,
) -> Path:
    normalized = _normalize_package_name(package_name)
    project_url = _simple_project_url(index_url, normalized)
    html = _fetch_text(project_url, timeout_seconds=10.0)
    links = _extract_links(html)
    candidates = _filter_wheels_for_version(links, normalized, version)
    if not candidates:
        raise RuntimeError(f"No wheel found for {package_name} {version}.")
    best = _select_best_wheel(candidates)
    url = urllib.parse.urljoin(project_url, best["href"])
    filename = best["filename"]
    sha256 = best.get("sha256")

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename
    if dest_path.exists() and sha256 and _verify_sha256(dest_path, sha256):
        return dest_path

    _download(url, dest_path)
    if sha256:
        if not _verify_sha256(dest_path, sha256):
            raise RuntimeError(f"Wheel checksum mismatch for {filename}.")
    else:
        print("Wheel hash not provided by index; skipping verification.")
    return dest_path


def download_wheel(
    version: str,
    dest_dir: Path,
    *,
    package_name: str = "optaic",
    timeout_seconds: float = 10.0,
) -> Path:
    payload = _fetch_json(
        f"{PYPI_BASE_URL}/{package_name}/{version}/json",
        timeout_seconds,
    )
    urls = payload.get("urls") or []
    wheel = _select_wheel(urls)
    if not wheel:
        raise RuntimeError(f"No wheel found for {package_name} {version}.")
    url = wheel["url"]
    filename = wheel["filename"]
    sha256 = (wheel.get("digests") or {}).get("sha256")

    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / filename
    if dest_path.exists() and sha256 and _verify_sha256(dest_path, sha256):
        return dest_path

    _download(url, dest_path)
    if sha256 and not _verify_sha256(dest_path, sha256):
        raise RuntimeError(f"Wheel checksum mismatch for {filename}.")
    return dest_path


def write_package_update_state(data_dir: Path, result: dict[str, object]) -> Path:
    state_path = data_dir / "state" / "package_updates.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(result)
    payload["saved_at"] = _utc_now()
    state_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return state_path


def prepare_upgrade_job(
    data_dir: Path,
    *,
    package_name: str,
    version: str,
    wheel_path: Path,
    index_url: str | None = None,
    extra_index_url: str | None = None,
    trusted_host: str | None = None,
) -> Path:
    job_path = data_dir / "state" / "package_upgrade_job.json"
    job_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "package": package_name,
        "version": version,
        "wheel_path": str(wheel_path),
        "index_url": index_url,
        "extra_index_url": extra_index_url,
        "trusted_host": trusted_host,
        "status": "pending",
        "created_at": _utc_now(),
    }
    job_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return job_path


def _select_wheel(urls: list[dict[str, object]]) -> dict[str, object] | None:
    wheels = [item for item in urls if item.get("packagetype") == "bdist_wheel"]
    if not wheels:
        return None
    for item in wheels:
        filename = str(item.get("filename", ""))
        if filename.endswith("py3-none-any.whl"):
            return item
    for item in wheels:
        python_version = str(item.get("python_version", "")).lower()
        if python_version in {"py3", "py2.py3"}:
            return item
    return wheels[0]


def _fetch_json(url: str, timeout_seconds: float) -> dict[str, object]:
    request = urllib.request.Request(url, headers={"User-Agent": "optaic"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise RuntimeError(f"PyPI request failed: {response.status}")
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _fetch_text(url: str, *, timeout_seconds: float) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "optaic"})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        if response.status != 200:
            raise RuntimeError(f"Index request failed: {response.status}")
        return response.read().decode("utf-8")


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp_path = dest.with_suffix(dest.suffix + ".tmp")
    request = urllib.request.Request(url, headers={"User-Agent": "optaic"})
    with urllib.request.urlopen(request) as response, open(temp_path, "wb") as handle:
        handle.write(response.read())
    temp_path.replace(dest)


def _verify_sha256(path: Path, expected: str) -> bool:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == expected.lower()


def _is_newer_version(latest: str, current: str) -> bool:
    try:
        return Version(latest) > Version(current)
    except Exception:
        return _fallback_compare(latest, current)


def _fallback_compare(latest: str, current: str) -> bool:
    return _normalize_version(latest) > _normalize_version(current)


def _normalize_version(version: str) -> tuple[int, ...]:
    parts = re.split(r"[.+-]", version)
    normalized: list[int] = []
    for part in parts:
        if part.isdigit():
            normalized.append(int(part))
        else:
            normalized.append(0)
    return tuple(normalized)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_package_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _simple_project_url(index_url: str, package_name: str) -> str:
    base = index_url.rstrip("/")
    if not base.endswith("/simple"):
        base = f"{base}/simple"
    return f"{base}/{package_name}/"


def _extract_links(html: str) -> list[str]:
    links = re.findall(r'href=[\'"]?([^\'" >]+)', html, flags=re.IGNORECASE)
    return [link.strip() for link in links if link.strip()]


def _link_filename(href: str) -> str:
    parsed = urllib.parse.urlparse(href)
    return Path(parsed.path).name


def _extract_version_from_filename(filename: str, normalized_name: str) -> str | None:
    prefixes = {normalized_name, normalized_name.replace("-", "_")}
    for prefix in prefixes:
        if filename.startswith(f"{prefix}-"):
            remainder = filename[len(prefix) + 1 :]
            version = remainder.split("-")[0]
            return _strip_archive_suffix(version)
    return None


def _filter_wheels_for_version(
    links: list[str],
    normalized_name: str,
    version: str,
) -> list[dict[str, str]]:
    wheels: list[dict[str, str]] = []
    for href in links:
        filename = _link_filename(href)
        if not filename.endswith(".whl"):
            continue
        file_version = _extract_version_from_filename(filename, normalized_name)
        if file_version != version:
            continue
        sha256 = None
        if "#sha256=" in href:
            sha256 = href.split("#sha256=", 1)[1]
        wheels.append({"href": href, "filename": filename, "sha256": sha256 or ""})
    return wheels


def _select_best_wheel(candidates: list[dict[str, str]]) -> dict[str, str]:
    for item in candidates:
        if item["filename"].endswith("py3-none-any.whl"):
            return item
    return candidates[0]


def _strip_archive_suffix(version: str) -> str:
    for suffix in (".tar.gz", ".zip", ".whl"):
        if version.endswith(suffix):
            return version[: -len(suffix)]
    return version

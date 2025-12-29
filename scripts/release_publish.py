from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tomllib
import urllib.request


def _read_project_name() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data["project"]["name"]


def _read_project_version() -> str:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    return data["project"]["version"]


def _normalize_name(name: str) -> str:
    return name.replace("-", "_")


def _run(cmd: list[str]) -> None:
    print(f"+ {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


def main() -> None:
    repo_url = os.environ.get("OPTAIC_PYPI_REPO_URL")
    username = os.environ.get("OPTAIC_PYPI_USERNAME")
    password = os.environ.get("OPTAIC_PYPI_PASSWORD")
    if not repo_url or not username or not password:
        raise SystemExit(
            "Set OPTAIC_PYPI_REPO_URL, OPTAIC_PYPI_USERNAME, OPTAIC_PYPI_PASSWORD"
        )

    package_name = os.environ.get("OPTAIC_PACKAGE_NAME") or _read_project_name()
    version = _read_project_version()
    dist_name = _normalize_name(package_name)
    dist_dir = Path(__file__).resolve().parents[1] / "dist"
    wheels = sorted(dist_dir.glob(f"{dist_name}-*.whl"))
    sdists = sorted(dist_dir.glob(f"{dist_name}-*.tar.gz"))
    artifacts = wheels + sdists
    if not artifacts:
        raise SystemExit("No artifacts found in dist/. Run release_build.py first.")

    cmd = [
        sys.executable,
        "-m",
        "twine",
        "upload",
        "--repository-url",
        repo_url,
        "-u",
        username,
        "-p",
        password,
    ] + [str(path) for path in artifacts]
    _run(cmd)

    simple_url = f"{repo_url.rstrip('/')}/simple/{dist_name.replace('_', '-')}/"
    with urllib.request.urlopen(simple_url, timeout=5) as response:
        html = response.read().decode("utf-8")
    if not html:
        raise SystemExit("Upload verification failed: empty index response.")
    if version not in html:
        raise SystemExit(
            f"Upload verification failed: version {version} not found in index."
        )
    print(f"Verified upload at {simple_url}")


if __name__ == "__main__":
    main()

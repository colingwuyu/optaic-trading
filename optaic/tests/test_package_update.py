from __future__ import annotations

import hashlib
from pathlib import Path

from optaic.runtime import package_update as pu


def test_check_pypi_latest_compares_versions(monkeypatch) -> None:
    def _fake_fetch(_url: str, _timeout: float) -> dict[str, object]:
        return {"info": {"version": "1.2.0"}}

    monkeypatch.setattr(pu, "_fetch_json", _fake_fetch)
    result = pu.check_pypi_latest(
        package_name="optaic",
        current_version="1.0.0",
    )
    assert result["has_update"] is True
    assert result["latest_version"] == "1.2.0"


def test_download_wheel_uses_cached_file(tmp_path: Path, monkeypatch) -> None:
    content = b"wheel"
    sha256 = hashlib.sha256(content).hexdigest()
    dest = tmp_path / "optaic-1.2.0-py3-none-any.whl"
    dest.write_bytes(content)

    def _fake_fetch(_url: str, _timeout: float) -> dict[str, object]:
        return {
            "urls": [
                {
                    "packagetype": "bdist_wheel",
                    "filename": dest.name,
                    "url": "https://example.com/wheel.whl",
                    "digests": {"sha256": sha256},
                    "python_version": "py3",
                }
            ]
        }

    def _fail_download(_url: str, _dest: Path) -> None:
        raise AssertionError("download should not be called")

    monkeypatch.setattr(pu, "_fetch_json", _fake_fetch)
    monkeypatch.setattr(pu, "_download", _fail_download)

    resolved = pu.download_wheel("1.2.0", tmp_path, package_name="optaic")
    assert resolved == dest


def test_write_package_update_state(tmp_path: Path) -> None:
    result = {
        "package": "optaic",
        "current_version": "1.0.0",
        "latest_version": "1.1.0",
        "has_update": True,
        "checked_at": "2025-01-01T00:00:00Z",
    }
    path = pu.write_package_update_state(tmp_path, result)
    content = path.read_text(encoding="utf-8")
    assert "package_updates.json" in str(path)
    assert '"latest_version": "1.1.0"' in content


def test_list_available_versions_parses_simple_index(monkeypatch) -> None:
    html = """
    <html>
      <body>
        <a href="optaic-1.0.0-py3-none-any.whl">optaic-1.0.0-py3-none-any.whl</a>
        <a href="optaic-1.1.0.tar.gz">optaic-1.1.0.tar.gz</a>
      </body>
    </html>
    """
    monkeypatch.setattr(pu, "_fetch_text", lambda *_args, **_kwargs: html)
    versions = pu.list_available_versions("http://localhost:8080/simple", "optaic")
    assert str(versions[-1]) == "1.1.0"


def test_download_wheel_from_index_uses_hash(tmp_path: Path, monkeypatch) -> None:
    sha256 = hashlib.sha256(b"test").hexdigest()
    html = """
    <a href="optaic-2.0.0-py3-none-any.whl#sha256={sha}">
      optaic-2.0.0-py3-none-any.whl
    </a>
    """
    html = html.format(sha=sha256)
    monkeypatch.setattr(pu, "_fetch_text", lambda *_args, **_kwargs: html)

    def _fake_download(_url: str, dest: Path) -> None:
        dest.write_bytes(b"test")

    monkeypatch.setattr(pu, "_download", _fake_download)
    dest = pu.download_wheel_from_index(
        "http://localhost:8080/simple",
        "optaic",
        "2.0.0",
        tmp_path,
    )
    assert dest.name.endswith(".whl")

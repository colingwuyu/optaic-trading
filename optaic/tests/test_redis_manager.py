from __future__ import annotations

import hashlib
import json

import pytest

from optaic.runtime.centrifugo_manager import CentrifugoConfig, write_centrifugo_config
from optaic.runtime import redis_manager
from optaic.runtime.redis_manager import resolve_redis_mode, verify_sha256, write_redis_conf


def test_sha256_verification(tmp_path) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("hello", encoding="utf-8")
    expected = hashlib.sha256(b"hello").hexdigest()
    assert verify_sha256(sample, expected)
    assert not verify_sha256(sample, "0" * 64)


def test_write_redis_conf(tmp_path) -> None:
    conf_path = write_redis_conf(tmp_path, "127.0.0.1", 6380)
    content = conf_path.read_text(encoding="utf-8")
    assert "bind 127.0.0.1" in content
    assert "port 6380" in content
    assert 'save ""' in content
    assert "appendonly no" in content


def test_resolve_redis_mode() -> None:
    assert resolve_redis_mode(False, None, True) == "disabled"
    assert resolve_redis_mode(True, "redis://localhost:6379/0", False) == "external"
    assert resolve_redis_mode(True, None, True) == "embedded"
    with pytest.raises(RuntimeError):
        resolve_redis_mode(True, None, False)


def test_centrifugo_memory_engine(tmp_path) -> None:
    config = CentrifugoConfig(
        data_dir=tmp_path,
        port=8001,
        api_key="dev-api-key",
        token_secret="dev-secret",
        allowed_origins=["http://localhost:8080"],
        redis_url=None,
    )
    config_path = write_centrifugo_config(config)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    assert payload["engine"]["type"] == "memory"


def test_start_redis_external_no_download(monkeypatch) -> None:
    monkeypatch.setattr(redis_manager, "_REDIS_PROCESS", None)
    monkeypatch.setattr(redis_manager, "_REDIS_URL", None)

    def _fail_download(*_args, **_kwargs) -> None:
        raise AssertionError("download should not be called")

    monkeypatch.setattr(redis_manager, "_download", _fail_download)
    url = "redis://127.0.0.1:6379/0"
    resolved = redis_manager.start_redis(
        True,
        url,
        "127.0.0.1",
        6379,
        "8.4.0",
        "msys2",
    )
    assert resolved == url

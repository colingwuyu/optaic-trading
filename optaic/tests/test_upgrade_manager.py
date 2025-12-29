from __future__ import annotations

from pathlib import Path
import json

import pytest

from optaic.runtime import upgrade_manager as um


def _manifest() -> dict[str, object]:
    return {
        "schema": 1,
        "tools": {
            "centrifugo": {
                "default_version": "1.2.3",
                "assets": {
                    "windows_amd64": {
                        "url": "https://example.com/centrifugo.zip",
                        "sha256": "abc123",
                    }
                },
            },
            "redis_windows": {
                "default_version": "8.4.0",
                "assets": {
                    "windows_amd64_msys2": {
                        "url": "https://example.com/redis.zip",
                        "sha256": "def456",
                    }
                },
            },
        },
    }


def _installed_state() -> dict[str, object]:
    return {"schema": 1, "tools": {}, "db": {}}


def test_plan_upgrades_default_no_redis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    desired = _manifest()
    installed = _installed_state()
    actions = um.plan_upgrades(
        desired,
        installed,
        "windows_amd64",
        with_redis=False,
        redis_url=None,
        redis_flavor="msys2",
        centrifugo_override=None,
    )
    assert any(action.tool == "centrifugo" for action in actions)
    assert not any(action.tool == "redis" for action in actions)

    centrifugo_bin = tmp_path / "bin" / "centrifugo" / "1.2.3" / "centrifugo.exe"
    centrifugo_bin.parent.mkdir(parents=True, exist_ok=True)
    centrifugo_bin.write_text("bin", encoding="utf-8")
    monkeypatch.setattr(um, "ensure_centrifugo_binary", lambda *_: centrifugo_bin)
    monkeypatch.setattr(
        um,
        "ensure_redis_binary",
        lambda *_: (_ for _ in ()).throw(AssertionError("redis not expected")),
    )

    updated = um.apply_upgrades(
        actions,
        tmp_path,
        installed,
        desired,
        with_redis=False,
        redis_url=None,
        redis_flavor="msys2",
        centrifugo_override=None,
    )
    assert updated["tools"]["redis"]["enabled"] is False


def test_apply_upgrades_external_redis(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    desired = _manifest()
    installed = _installed_state()
    redis_url = "redis://127.0.0.1:6380/0"
    actions = um.plan_upgrades(
        desired,
        installed,
        "windows_amd64",
        with_redis=True,
        redis_url=redis_url,
        redis_flavor="msys2",
        centrifugo_override=None,
    )
    assert not any(action.tool == "redis" for action in actions)

    centrifugo_bin = tmp_path / "bin" / "centrifugo" / "1.2.3" / "centrifugo.exe"
    centrifugo_bin.parent.mkdir(parents=True, exist_ok=True)
    centrifugo_bin.write_text("bin", encoding="utf-8")
    monkeypatch.setattr(um, "ensure_centrifugo_binary", lambda *_: centrifugo_bin)
    monkeypatch.setattr(
        um,
        "ensure_redis_binary",
        lambda *_: (_ for _ in ()).throw(AssertionError("redis not expected")),
    )

    updated = um.apply_upgrades(
        actions,
        tmp_path,
        installed,
        desired,
        with_redis=True,
        redis_url=redis_url,
        redis_flavor="msys2",
        centrifugo_override=None,
    )
    redis_state = updated["tools"]["redis"]
    assert redis_state["mode"] == "external"
    assert redis_state["url"] == redis_url


def test_plan_upgrades_windows_embedded_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    desired = _manifest()
    installed = _installed_state()
    monkeypatch.setattr(um.os, "name", "nt")
    actions = um.plan_upgrades(
        desired,
        installed,
        "windows_amd64",
        with_redis=True,
        redis_url=None,
        redis_flavor="msys2",
        centrifugo_override=None,
    )
    assert any(action.tool == "redis" for action in actions)


def test_lock_prevents_concurrent(tmp_path: Path) -> None:
    lock = um.acquire_lock(tmp_path)
    try:
        with pytest.raises(RuntimeError):
            um.acquire_lock(tmp_path)
    finally:
        lock.release()


def test_log_upgrade(tmp_path: Path) -> None:
    um.log_upgrade(
        tmp_path,
        action="rollback",
        outcome="success",
        tool="centrifugo",
        before_version="1.2.4",
        after_version="1.2.3",
    )
    log_path = tmp_path / "state" / "upgrade.log"
    content = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 1
    payload = json.loads(content[0])
    assert payload["action"] == "rollback"
    assert payload["outcome"] == "success"
    assert payload["tool"] == "centrifugo"
    assert payload["before_version"] == "1.2.4"
    assert payload["after_version"] == "1.2.3"


def test_upgrade_status_roundtrip(tmp_path: Path) -> None:
    status = um.read_upgrade_status(tmp_path)
    assert status["status"] == "idle"

    running = um.set_upgrade_status(tmp_path, "running")
    assert running["status"] == "running"
    assert running["started_at"] is not None
    assert running["finished_at"] is None

    done = um.set_upgrade_status(tmp_path, "done")
    assert done["status"] == "done"
    assert done["finished_at"] is not None

    failed = um.set_upgrade_status(tmp_path, "failed", error="boom")
    assert failed["status"] == "failed"
    assert failed["last_error"] == "boom"
